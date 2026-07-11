from __future__ import annotations

import io
import logging
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from pathlib import Path

import chess
import chess.pgn

from cope.core.models import (
    ColorSlot,
    GameAssignment,
    TimeControl,
    WorkerGameAssignment,
    IncrementTimeControl,
    MoveNodesTimeControl,
    MoveTimeControl,
    MovesToGoTimeControl,
)
from cope.db import (
    GameAssignmentRecord,
    GameRecord,
    MoveRecord,
    OpeningPositionRecord,
    TournamentRecord,
    WorkerRecord,
    assign_game_to_worker,
    connect_database,
    finish_game_assignment,
    finish_game,
    get_engine,
    get_engine_name,
    get_game,
    get_game_assignment,
    get_opening_position,
    get_tournament,
    initialize_database,
    list_games,
    list_moves,
    list_tournaments,
    mark_game_assignment_live,
    mark_game_live,
    record_move,
    set_tournament_current_round_at_least,
    set_tournament_status,
)

from .scheduler import TournamentPreparation, advance_tournament, prepare_scheduled_tournaments
from .commands import process_pending_runner_commands
from .events import (
    publish_clock_sync,
    publish_engine_info,
    publish_game_move,
    publish_tournament_event,
    set_runner_wake_handler,
    start_event_publisher,
)
from cope.tournament.engine_instance import (
    EngineInstance,
    EngineCommandTransport,
    EngineSearchInfo,
)
from cope.tournament.game_runner import GameRunner
from cope.tournament.game_state import GameState
from cope.tournament.time_control import RuntimeTimeControl, TimeControlCategory
from cope.tournament.tournament import Game


TERMINAL_GAME_STATUSES = {"finished", "abandoned"}
DEFAULT_WORKER_MAX_PLIES = 160
DEFAULT_MAX_MOVES_DECISIVE_CP = 800
LOG = logging.getLogger("cope.runner")


@dataclass(frozen=True, slots=True)
class RunnerReport:
    prepared: tuple[TournamentPreparation, ...]
    tournaments_finished: int
    commands_applied: int = 0
    commands_failed: int = 0
    rating_commits_applied: int = 0
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RunnerServiceConfig:
    db_path: str | Path
    poll_interval_s: float = 2.0


def run_tournament_service(config: RunnerServiceConfig) -> None:
    initialize_database(config.db_path)
    LOG.info(
        "service started db=%s wake_mode=stream",
        config.db_path,
    )
    wake = threading.Event()
    set_runner_wake_handler(lambda _event: wake.set())
    start_event_publisher()

    while True:
        wake.clear()
        connection: sqlite3.Connection | None = None
        try:
            connection = connect_database(config.db_path)
            report = run_tournament_matches(connection)
            print_runner_report(report)
        except Exception:
            LOG.exception("cycle failed")
        finally:
            if connection is not None:
                connection.close()

        wake.wait(timeout=max(config.poll_interval_s, 0.1))


def run_tournament_matches(
    connection: sqlite3.Connection,
) -> RunnerReport:
    prepared = prepare_scheduled_tournaments(connection)
    tournaments_finished = finish_completed_tournaments(connection)
    command_report = process_pending_runner_commands(connection)
    connection.commit()
    for result in prepared:
        if result.skipped_reason is None:
            publish_tournament_event(result.tournament_id)
    if tournaments_finished:
        for tournament in list_tournaments(connection):
            if tournament.status == "finished":
                publish_tournament_event(tournament.id)
    for result in command_report.rating_commits:
        publish_tournament_event(result.tournament_id)

    return RunnerReport(
        prepared=prepared,
        tournaments_finished=tournaments_finished,
        commands_applied=command_report.applied,
        commands_failed=command_report.failed,
        rating_commits_applied=len(command_report.rating_commits),
        errors=command_report.errors,
    )


def finish_completed_tournaments(connection: sqlite3.Connection) -> int:
    tournaments_finished = 0
    for tournament in list_tournaments(connection):
        if tournament.status != "running":
            continue

        if _finish_tournament_if_complete(connection, tournament):
            tournaments_finished += 1

    return tournaments_finished


def print_runner_report(report: RunnerReport) -> None:
    for result in report.prepared:
        if result.skipped_reason is None:
            LOG.info(
                "prepared tournament id=%s name=%s games=%s",
                result.tournament_id,
                result.tournament_name,
                result.created_games,
            )
        else:
            LOG.warning(
                "skipped tournament id=%s name=%s reason=%s",
                result.tournament_id,
                result.tournament_name,
                result.skipped_reason,
            )

    for error in report.errors:
        LOG.error("runner error: %s", error)

    if report.tournaments_finished:
        LOG.info("finished tournaments count=%s", report.tournaments_finished)
    if report.commands_applied:
        LOG.info(
            "applied runner commands count=%s rating_commits=%s",
            report.commands_applied,
            report.rating_commits_applied,
        )
    if report.commands_failed:
        LOG.warning("failed runner commands count=%s", report.commands_failed)


def next_worker_assignment(
    connection: sqlite3.Connection,
    worker: WorkerRecord,
) -> WorkerGameAssignment | None:
    for tournament in list_tournaments(connection):
        if tournament.status != "running":
            continue

        game = _next_playable_game(list_games(connection, tournament.id))
        if game is None:
            continue

        set_tournament_current_round_at_least(connection, tournament.id, game.round)
        assignment_record = assign_game_to_worker(
            connection,
            game_id=game.id,
            assignment_key=secrets.token_urlsafe(24),
            worker_id=worker.id,
        )
        opening = get_opening_position(connection, game.opening_id)
        LOG.info(
            "claimed game worker_id=%s assignment_id=%s game_id=%s tournament=%s round=%s",
            worker.id,
            assignment_record.id,
            game.id,
            tournament.name,
            game.round,
        )
        return _worker_assignment_payload(connection, tournament, game, assignment_record, opening)

    return None


def mark_worker_assignment_live(
    connection: sqlite3.Connection,
    assignment_id: int,
) -> None:
    assignment = get_game_assignment(connection, assignment_id)
    if assignment is None:
        raise RuntimeError(f"unknown assignment {assignment_id}")
    if assignment.status not in {"assigned", "acked", "live"}:
        raise RuntimeError(
            f"assignment {assignment_id} is no longer active ({assignment.status})"
        )
    mark_game_assignment_live(connection, assignment.id)
    mark_game_live(connection, assignment.game_id)


def run_worker_assignment_game(
    connection: sqlite3.Connection,
    assignment: WorkerGameAssignment,
    transport: EngineCommandTransport,
) -> None:
    assignment_record = _validated_assignment_record(connection, assignment)
    game_record = _validated_game(connection, assignment.assignment.game_id)
    tournament = _validated_tournament(connection, game_record.tournament_id)
    opening = get_opening_position(connection, game_record.opening_id)
    board = _starting_board(opening)
    _apply_recorded_moves(board, list_moves(connection, game_record.id))
    LOG.info(
        "starting game assignment_id=%s game_id=%s tournament=%s round=%s opening=%s",
        assignment.assignment.assignment_id,
        game_record.id,
        tournament.name,
        game_record.round,
        None if opening is None else opening.name,
    )

    runtime_time_control = _runtime_time_control(tournament.config.time_control)
    white = EngineInstance(
        game_record.white_engine_id,
        transport,
        options=_engine_options(assignment, game_record.white_engine_id),
    )
    black = EngineInstance(
        game_record.black_engine_id,
        transport,
        options=_engine_options(assignment, game_record.black_engine_id),
    )
    game = Game(
        id=game_record.id,
        white=white,
        black=black,
        state=GameState(board=board),
        white_tm=runtime_time_control.create_manager(),
        black_tm=runtime_time_control.create_manager(),
    )
    live_reporter = _LiveGameReporter(tournament.id, game_record.id, game, white, black)
    white.set_info_listener(live_reporter.publish_white_engine_info)
    black.set_info_listener(live_reporter.publish_black_engine_info)
    runner = GameRunner(game, on_clock_sync=live_reporter.publish_clock_sync)

    mark_worker_assignment_live(connection, assignment.assignment.assignment_id)
    _validated_assignment_record(connection, assignment)
    connection.commit()
    publish_tournament_event(tournament.id)

    while not game.state.is_finished() and board.ply() < assignment.max_plies:
        _validated_assignment_record(connection, assignment)
        side_to_move = board.turn
        board_before_move = board.copy()
        move = runner.run_next_move()
        if move is None:
            break
        _validated_assignment_record(connection, assignment)

        engine = white if side_to_move == chess.WHITE else black
        search = engine.get_last_search_result()
        clock = game.white_tm if side_to_move == chess.WHITE else game.black_tm
        clock_after_ms = _clock_time_ms(clock)
        record_move(
            connection,
            game_id=game_record.id,
            ply=board.ply(),
            uci=move.uci(),
            san=board_before_move.san(move),
            eval_cp=None if search is None else search.eval_cp,
            eval_mate=None if search is None else search.eval_mate,
            depth=None if search is None else search.depth,
            nodes=None if search is None else search.nodes,
            nps=None if search is None else search.nps,
            pv=None if search is None else search.pv,
            info_line=None if search is None else search.info_line,
            time_ms=0 if search is None else search.time_ms,
            clock_after_ms=clock_after_ms if clock_after_ms is not None else 0,
        )
        connection.commit()
        publish_game_move(tournament.id, game_record.id, board.ply())
        if board.ply() <= 10 or board.ply() % 10 == 0:
            LOG.info(
                "recorded move game_id=%s ply=%s move=%s",
                game_record.id,
                board.ply(),
                move.uci(),
            )

    _validated_assignment_record(connection, assignment)
    moves = list_moves(connection, game_record.id)
    if not game.state.is_finished():
        result, termination = _max_moves_result(tournament, moves)
    else:
        result = game.state.get_result()
        termination = game.state.get_details() or "unknown"

    pgn = _build_pgn(connection, tournament, game_record, opening, moves, result, termination)
    finish_game(
        connection,
        game_record.id,
        result=result,
        termination=termination,
        pgn=pgn,
    )
    finish_game_assignment(connection, assignment_record.id)
    _finish_tournament_if_complete(connection, tournament)
    connection.commit()
    LOG.info(
        "finished game assignment_id=%s game_id=%s result=%s termination=%s plies=%s",
        assignment.assignment.assignment_id,
        game_record.id,
        result,
        termination,
        len(moves),
    )
    publish_tournament_event(tournament.id)


class _LiveGameReporter:
    def __init__(
        self,
        tournament_id: int,
        game_id: int,
        game: Game,
        white: EngineInstance,
        black: EngineInstance,
    ):
        self._tournament_id = tournament_id
        self._game_id = game_id
        self._game = game
        self._white = white
        self._black = black

    def publish_white_engine_info(self, line: str, info: EngineSearchInfo) -> None:
        self._publish_engine_info("white", self._white, line, info)

    def publish_black_engine_info(self, line: str, info: EngineSearchInfo) -> None:
        self._publish_engine_info("black", self._black, line, info)

    def publish_clock_sync(
        self,
        side_to_move: chess.Color,
        running: bool,
        active_remaining_ms: int | None,
    ) -> None:
        side = "white" if side_to_move == chess.WHITE else "black"
        publish_clock_sync(
            self._tournament_id,
            {
                "tournament_id": self._tournament_id,
                "game_id": self._game_id,
                "active_side": side,
                "running": running,
                "clocks_ms": _live_clock_payload(self._game, side, active_remaining_ms),
            },
        )

    def _publish_engine_info(
        self,
        side: str,
        engine: EngineInstance,
        line: str,
        info: EngineSearchInfo,
    ) -> None:
        engine_data = _live_engine_data(info)
        root_fen = self._game.state.get_board().fen()
        engine_data["root_fen"] = root_fen
        engine_data["info"] = line
        publish_engine_info(
            self._tournament_id,
            {
                "tournament_id": self._tournament_id,
                "game_id": self._game_id,
                "engine_id": engine.get_name(),
                "side": side,
                "raw": line,
                "root_fen": root_fen,
                "engine_data": engine_data,
            },
        )


def _live_clock_payload(
    game: Game,
    active_side: str,
    active_remaining_ms: int | None,
) -> dict[str, int | None]:
    white_ms = _clock_time_ms(game.white_tm)
    black_ms = _clock_time_ms(game.black_tm)
    if active_side == "white":
        white_ms = active_remaining_ms if white_ms is not None else None
    else:
        black_ms = active_remaining_ms if black_ms is not None else None
    return {
        "white": white_ms,
        "black": black_ms,
    }


def _clock_time_ms(clock) -> int | None:
    remaining_time = clock.get_remaining_time()
    if remaining_time is not None:
        return remaining_time
    return clock.get_remaining_move_time()


def _live_engine_data(info: EngineSearchInfo | None) -> dict[str, str]:
    if info is None:
        return {
            "depth": "-",
            "nps": "-",
            "nodes": "-",
            "eval": "-",
            "pv": "not recorded",
        }

    nps = info.nps
    if nps is None and info.nodes is not None and info.time_ms > 0:
        nps = int(info.nodes / (info.time_ms / 1000))

    return {
        "depth": str(info.depth) if info.depth is not None else "-",
        "nps": f"{nps:,}" if nps is not None else "-",
        "nodes": f"{info.nodes:,}" if info.nodes is not None else "-",
        "eval": _live_eval_label(info),
        "pv": info.pv or "not recorded",
    }


def _live_eval_label(info: EngineSearchInfo) -> str:
    if info.eval_mate is not None:
        return f"#{info.eval_mate}"
    if info.eval_cp is not None:
        return f"{info.eval_cp / 100:+.2f}"
    return "-"


def _worker_assignment_payload(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
    game: GameRecord,
    assignment: GameAssignmentRecord,
    opening: OpeningPositionRecord | None,
) -> WorkerGameAssignment:
    return WorkerGameAssignment(
        assignment=GameAssignment(
            assignment_id=assignment.id,
            assignment_key=assignment.assignment_key,
            game_id=game.id,
            slots={
                ColorSlot.WHITE: game.white_engine_id,
                ColorSlot.BLACK: game.black_engine_id,
            },
            time_control=tournament.config.time_control,
        ),
        tournament_name=tournament.name,
        round=game.round,
        initial_fen=_starting_board(opening).fen(),
        opening_name=None if opening is None else opening.name,
        max_plies=_max_plies(tournament),
        engines=_assignment_engines(connection, game),
    )


def _assignment_engines(
    connection: sqlite3.Connection,
    game: GameRecord,
):
    engines = {}
    for engine_id in {game.white_engine_id, game.black_engine_id}:
        engine = get_engine(connection, engine_id)
        if engine is None:
            raise RuntimeError(f"unknown engine {engine_id}")
        engines[engine_id] = engine
    return engines


def _engine_options(
    assignment: WorkerGameAssignment,
    engine_id: int,
) -> dict[str, str | int | bool]:
    spec = assignment.engines.get(engine_id)
    if spec is None:
        raise RuntimeError(f"assignment missing engine {engine_id}")

    options = dict(spec.uci_options)
    options.update(assignment.assignment.uci_options_overrides.get(engine_id, {}))
    return options


def _runtime_time_control(time_control: TimeControl) -> RuntimeTimeControl:
    if isinstance(time_control, IncrementTimeControl):
        return RuntimeTimeControl(
            TimeControlCategory.INCREMENT,
            initial_time=time_control.initial_ms,
            increment=time_control.increment_ms,
        )
    if isinstance(time_control, MoveTimeControl):
        return RuntimeTimeControl(
            TimeControlCategory.MOVETIME,
            move_time=time_control.move_time_ms,
        )
    if isinstance(time_control, MovesToGoTimeControl):
        return RuntimeTimeControl(
            TimeControlCategory.MOVESTOGO,
            initial_time=time_control.initial_ms,
            moves_to_go=time_control.moves_to_go,
        )
    if isinstance(time_control, MoveNodesTimeControl):
        return RuntimeTimeControl(
            TimeControlCategory.MOVENODES,
            nodes=time_control.nodes,
        )
    raise RuntimeError(f"unsupported time control: {time_control}")


def _validated_game(connection: sqlite3.Connection, game_id: int) -> GameRecord:
    game = get_game(connection, game_id)
    if game is None:
        raise RuntimeError(f"unknown game {game_id}")
    if game.status in TERMINAL_GAME_STATUSES:
        raise RuntimeError(f"game {game_id} is already {game.status}")
    return game


def _validated_assignment_record(
    connection: sqlite3.Connection,
    assignment: WorkerGameAssignment,
) -> GameAssignmentRecord:
    payload = assignment.assignment
    assignment_record = get_game_assignment(connection, payload.assignment_id)
    if assignment_record is None:
        raise RuntimeError(f"unknown assignment {payload.assignment_id}")
    if assignment_record.assignment_key != payload.assignment_key:
        raise RuntimeError(f"stale assignment {payload.assignment_id}")
    if assignment_record.game_id != payload.game_id:
        raise RuntimeError(f"assignment {payload.assignment_id} game mismatch")
    if assignment_record.status not in {"assigned", "acked", "live"}:
        raise RuntimeError(
            f"assignment {payload.assignment_id} is no longer active "
            f"({assignment_record.status})"
        )
    return assignment_record


def _validated_tournament(
    connection: sqlite3.Connection,
    tournament_id: int,
) -> TournamentRecord:
    tournament = get_tournament(connection, tournament_id)
    if tournament is None:
        raise RuntimeError(f"unknown tournament {tournament_id}")
    return tournament


def _next_playable_game(games: tuple[GameRecord, ...]) -> GameRecord | None:
    return next((game for game in games if game.status == "pending"), None)


def _finish_tournament_if_complete(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> bool:
    current = get_tournament(connection, tournament.id)
    if current is None or current.status != "running":
        return False

    games = list_games(connection, current.id)
    if not games:
        return False
    all_terminal = all(game.status in TERMINAL_GAME_STATUSES for game in games)
    if all_terminal and any(game.status == "abandoned" for game in games):
        set_tournament_status(connection, current.id, "aborted")
        return False

    advance = advance_tournament(connection, current)
    games = list_games(connection, current.id)
    if not advance.complete or any(game.status not in TERMINAL_GAME_STATUSES for game in games):
        return False

    set_tournament_status(connection, current.id, "finished")
    return True


def _starting_board(opening: OpeningPositionRecord | None) -> chess.Board:
    if opening is None or opening.fen == "startpos":
        return chess.Board()
    return chess.Board(opening.fen)


def _apply_recorded_moves(
    board: chess.Board,
    moves: tuple[MoveRecord, ...],
) -> None:
    for move_record in moves:
        move = chess.Move.from_uci(move_record.uci)
        if move not in board.legal_moves:
            raise RuntimeError(f"recorded move {move_record.uci} is illegal at ply {move_record.ply}")
        board.push(move)


def _max_plies(tournament: TournamentRecord) -> int:
    max_moves = tournament.config.adjudication.max_moves
    if max_moves is not None:
        return max_moves * 2
    return DEFAULT_WORKER_MAX_PLIES


def _max_moves_result(
    tournament: TournamentRecord,
    moves: tuple[MoveRecord, ...],
) -> tuple[str, str]:
    score = _latest_white_relative_score(moves)
    if score is None:
        return "1/2-1/2", "max moves"

    mate, cp = score
    if mate is not None:
        if mate > 0:
            return "1-0", "max moves: white has forced mate"
        if mate < 0:
            return "0-1", "max moves: black has forced mate"
        return "1/2-1/2", "max moves"

    if cp is None:
        return "1/2-1/2", "max moves"

    threshold = _max_moves_decisive_cp(tournament)
    if cp >= threshold:
        return "1-0", f"max moves: white winning by evaluation ({cp / 100:+.2f})"
    if cp <= -threshold:
        return "0-1", f"max moves: black winning by evaluation ({cp / 100:+.2f})"
    return "1/2-1/2", f"max moves: evaluation within decisive threshold ({cp / 100:+.2f})"


def _latest_white_relative_score(
    moves: tuple[MoveRecord, ...],
) -> tuple[int | None, int | None] | None:
    for move in reversed(moves):
        mover_sign = 1 if move.ply % 2 == 1 else -1
        if move.eval_mate is not None:
            return mover_sign * move.eval_mate, None
        if move.eval_cp is not None:
            return None, mover_sign * move.eval_cp
    return None


def _max_moves_decisive_cp(tournament: TournamentRecord) -> int:
    resign_rule = tournament.config.adjudication.resign
    if resign_rule is not None:
        return resign_rule.min_abs_cp
    return DEFAULT_MAX_MOVES_DECISIVE_CP


def _build_pgn(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
    game: GameRecord,
    opening: OpeningPositionRecord | None,
    moves: tuple[MoveRecord, ...],
    result: str,
    termination: str,
) -> str:
    board = _starting_board(opening)
    pgn_game = chess.pgn.Game()
    if board.fen() != chess.STARTING_FEN:
        pgn_game.setup(board)

    pgn_game.headers["Event"] = tournament.name
    pgn_game.headers["Round"] = str(game.round)
    pgn_game.headers["White"] = get_engine_name(connection, game.white_engine_id)
    pgn_game.headers["Black"] = get_engine_name(connection, game.black_engine_id)
    pgn_game.headers["Result"] = result
    pgn_game.headers["Termination"] = termination
    if opening is not None and opening.name:
        pgn_game.headers["Opening"] = opening.name

    node = pgn_game
    for move_record in moves:
        move = chess.Move.from_uci(move_record.uci)
        if move not in board.legal_moves:
            break
        node = node.add_variation(move)
        board.push(move)

    output = io.StringIO()
    exporter = chess.pgn.StringExporter(headers=True, variations=False, comments=False)
    print(pgn_game.accept(exporter), file=output)
    return output.getvalue().strip()
