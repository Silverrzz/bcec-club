import chess
import time

from .engine_instance import EngineInstance
from .game_state import GameState
from .match import Match
from .time_control import TimeControlCategory
from .uci import go_command
from .time_control import TimeManager, TimeOutError


class MatchRunner():
    def __init__(self, match: Match, clock_probe_interval: float = 0.001):
        self._match = match
        self._clock_probe_interval = clock_probe_interval
        self._game_started = False

    def get_match(self) -> Match:
        return self._match

    def set_match(self, match: Match):
        self._match = match
        self._game_started = False

    def run(self):
        while not self._get_game_state().is_finished():
            self.run_next_move()

    def run_next_move(self):
        if self._get_game_state().is_finished():
            return None

        self._start_game()

        board = self._get_board()
        side_to_move = board.turn
        engine = self.get_engine_to_move()
        clock = self.get_clock_to_move()
        move = None

        engine.start_search(board, self._build_go_command(clock))
        clock.start_clock()

        try:
            while engine.is_searching():
                clock.probe_clock()
                time.sleep(self._clock_probe_interval)

            move = engine.get_search_move()
        except TimeOutError:
            engine.stop_search()
            clock.stop_clock_after_timeout()
            self._get_game_state().record_timeout(side_to_move)
            return None
        except Exception as error:
            engine.stop_search()
            clock.stop_clock_after_timeout()
            self._get_game_state().record_engine_error(side_to_move, error)
            return None
        finally:
            if not self._get_game_state().is_finished():
                try:
                    clock.stop_clock()
                except TimeOutError:
                    self._get_game_state().record_timeout(side_to_move)

        if self._get_game_state().is_finished():
            return None

        if move is None:
            self._get_game_state().record_engine_error(side_to_move, RuntimeError("Engine returned no move"))
            return None

        if not self.push_legal_move(move, side_to_move):
            return None

        self._get_game_state().update_from_board()
        return move

    def _start_game(self):
        if self._game_started:
            return

        self._match.get_white().start_new_game()
        self._match.get_black().start_new_game()
        self._game_started = True

    def _build_go_command(self, clock: TimeManager) -> str:
        white_clock = self._match.get_white_tm()
        black_clock = self._match.get_black_tm()
        args: dict[str, int | None] = {
            "wtime": white_clock.get_remaining_time(),
            "btime": black_clock.get_remaining_time(),
            "winc": None,
            "binc": None,
            "movetime": None,
            "movestogo": clock.get_moves_to_go(),
            "nodes": clock.get_nodes(),
        }

        tc = clock.get_time_control()
        if tc.get_category() is TimeControlCategory.INCREMENT:
            args["winc"] = white_clock.get_time_control().get_increment()
            args["binc"] = black_clock.get_time_control().get_increment()
        elif tc.get_category() is TimeControlCategory.MOVETIME:
            args["movetime"] = clock.get_remaining_move_time()

        return go_command(**args)

    def _get_game_state(self) -> GameState:
        return self._match.get_game_state()

    def _get_board(self) -> chess.Board:
        return self._get_game_state().get_board()

    def get_engine_to_move(self) -> EngineInstance:
        if self._get_board().turn == chess.WHITE:
            return self._match.get_white()

        return self._match.get_black()

    def get_clock_to_move(self) -> TimeManager:
        if self._get_board().turn == chess.WHITE:
            return self._match.get_white_tm()

        return self._match.get_black_tm()

    def push_legal_move(self, move: chess.Move, side_to_move: chess.Color) -> bool:
        board = self._get_board()

        if move not in board.legal_moves:
            self._get_game_state().record_illegal_move(side_to_move, move)
            return False

        board.push(move)
        return True
