from __future__ import annotations

import io
import logging
import secrets
import sqlite3
import time
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
    TournamentRecord,
    WorkerRecord,
    assign_game_to_worker,
    connect_database,
    finish_game_assignment,
    finish_game,
    get_engine,
    get_game,
    get_game_assignment,
    get_tournament,
    initialize_database,
    list_games,
    list_moves,
    list_tournaments,
    mark_game_assignment_live,
    mark_game_live,
    record_move,
    set_tournament_status,
)

from .scheduler import TournamentPreparation, prepare_scheduled_tournaments
from .events import publish_tournament_event
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
LOG = logging.getLogger("cope.runner")


@dataclass(frozen=True, slots=True)
class RunnerReport:
    prepared: tuple[TournamentPreparation, ...]
    tournaments_finished: int
    errors: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RunnerServiceConfig:
    db_path: str | Path
    poll_interval_s: float = 2.0


@dataclass(frozen=True, slots=True)
class OpeningPosition:
    name: str
    fen: str


def run_tournament_service(config: RunnerServiceConfig) -> None:
    initialize_database(config.db_path)
    LOG.info(
        "service started db=%s poll_interval_s=%s",
        config.db_path,
        config.poll_interval_s,
    )

    while True:
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

        time.sleep(config.poll_interval_s)


def run_tournament_matches(
    connection: sqlite3.Connection,
) -> RunnerReport:
    prepared = prepare_scheduled_tournaments(connection)
    tournaments_finished = finish_completed_tournaments(connection)
    connection.commit()
    for result in prepared:
        if result.skipped_reason is None:
            publish_tournament_event(result.tournament_id)
    if tournaments_finished:
        for tournament in list_tournaments(connection):
            if tournament.status == "finished":
                publish_tournament_event(tournament.id)

    return RunnerReport(
        prepared=prepared,
        tournaments_finished=tournaments_finished,
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


def _set_current_round(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
    round_number: int,
) -> None:
    if tournament.current_round >= round_number:
        return
    connection.execute(
        """
        UPDATE tournaments
        SET current_round = ?
        WHERE id = ? AND current_round < ?
        """,
        (round_number, tournament.id, round_number),
    )


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

        _set_current_round(connection, tournament, game.round)
        assignment_record = assign_game_to_worker(
            connection,
            game_id=game.id,
            assignment_key=secrets.token_urlsafe(24),
            hardware_mode=tournament.config.hardware_mode.value,
            worker_id=worker.id,
        )
        opening = _opening_position(connection, game.opening_id)
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
    opening = _opening_position(connection, game_record.opening_id)
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
    runner = GameRunner(game, on_tick=live_reporter.publish)

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
            time_ms=0 if search is None else search.time_ms,
            clock_after_ms=clock.get_remaining_time() or clock.get_remaining_move_time() or 0,
        )
        connection.commit()
        publish_tournament_event(tournament.id, {"clear": True})
        if board.ply() <= 10 or board.ply() % 10 == 0:
            LOG.info(
                "recorded move game_id=%s ply=%s move=%s",
                game_record.id,
                board.ply(),
                move.uci(),
            )
        publish_tournament_event(tournament.id)

    _validated_assignment_record(connection, assignment)
    if not game.state.is_finished():
        result = "1/2-1/2"
        termination = "max moves"
    else:
        result = game.state.get_result()
        termination = game.state.get_details() or "unknown"

    moves = list_moves(connection, game_record.id)
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
        interval_s: float = 0.25,
    ):
        self._tournament_id = tournament_id
        self._game_id = game_id
        self._game = game
        self._white = white
        self._black = black
        self._interval_s = interval_s
        self._last_publish = 0.0

    def publish(self, side_to_move: chess.Color, active_remaining_ms: int | None) -> None:
        now = time.monotonic()
        if now - self._last_publish < self._interval_s:
            return
        self._last_publish = now

        side = "white" if side_to_move == chess.WHITE else "black"
        engine = self._white if side_to_move == chess.WHITE else self._black
        publish_tournament_event(
            self._tournament_id,
            {
                "game_id": self._game_id,
                "active_side": side,
                "clocks": _live_clock_payload(self._game, side, active_remaining_ms),
                "engine_data": {
                    side: _live_engine_data(engine.get_current_search_info()),
                },
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
    return clock.get_remaining_time() or clock.get_remaining_move_time()


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
    opening: OpeningPosition | None,
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
    if game.status == "finished":
        raise RuntimeError(f"game {game_id} is already finished")
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
    if any(game.status not in TERMINAL_GAME_STATUSES for game in games):
        return False
    if any(game.status == "abandoned" for game in games):
        set_tournament_status(connection, current.id, "aborted")
        return False

    set_tournament_status(connection, current.id, "finished")
    return True


def _opening_position(
    connection: sqlite3.Connection,
    opening_id: int | None,
) -> OpeningPosition | None:
    if opening_id is None:
        return None

    row = connection.execute(
        "SELECT name, fen FROM openings WHERE id = ?",
        (opening_id,),
    ).fetchone()
    if row is None:
        return None
    return OpeningPosition(name=row["name"] or "Opening", fen=row["fen"])


def _starting_board(opening: OpeningPosition | None) -> chess.Board:
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


def _build_pgn(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
    game: GameRecord,
    opening: OpeningPosition | None,
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
    pgn_game.headers["White"] = _engine_name(connection, game.white_engine_id)
    pgn_game.headers["Black"] = _engine_name(connection, game.black_engine_id)
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


def _engine_name(connection: sqlite3.Connection, engine_id: int) -> str:
    row = connection.execute("SELECT name FROM engines WHERE id = ?", (engine_id,)).fetchone()
    if row is None:
        return f"Engine {engine_id}"
    return row["name"]
