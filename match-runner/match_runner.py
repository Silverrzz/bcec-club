import chess
import time

from engine_instance import EngineInstance
from game_state import GameState
from match import Match
from time_control import TimeManager, TimeOutError


class MatchRunner():
    def __init__(self, match: Match, clock_probe_interval: float = 0.001):
        self._match = match
        self._clock_probe_interval = clock_probe_interval

    def get_match(self) -> Match:
        return self._match

    def set_match(self, match: Match):
        self._match = match

    def run(self):
        while not self._get_game_state().is_finished():
            self.run_next_move()

    def run_next_move(self):
        if self._get_game_state().is_finished():
            return None

        board = self._get_board()
        side_to_move = board.turn
        engine = self.get_engine_to_move()
        clock = self.get_clock_to_move()
        move = None

        engine.start_search(board)
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
                    return None

        if move is None:
            self._get_game_state().record_engine_error(side_to_move, RuntimeError("Engine returned no move"))
            return None

        if not self.push_legal_move(move, side_to_move):
            return None

        self._get_game_state().update_from_board()
        return move

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
