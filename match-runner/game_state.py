import chess
from enum import Enum


class GameTermination(Enum):
    CHECKMATE = "checkmate"
    STALEMATE = "stalemate"
    INSUFFICIENT_MATERIAL = "insufficient material"
    SEVENTYFIVE_MOVES = "seventy-five moves"
    FIVEFOLD_REPETITION = "fivefold repetition"
    FIFTY_MOVES = "fifty moves"
    THREEFOLD_REPETITION = "threefold repetition"
    TIMEOUT = "timeout"
    ILLEGAL_MOVE = "illegal move"
    ENGINE_ERROR = "engine error"
    VARIANT_END = "variant end"
    UNKNOWN = "unknown"


class GameState():
    def __init__(self, board: chess.Board):
        self._board = board
        self._result = "*"
        self._winner = None
        self._termination = None
        self._details = ""
        self.update_from_board()

    def get_board(self) -> chess.Board:
        return self._board

    def set_board(self, board: chess.Board):
        self._board = board

    def get_result(self) -> str:
        return self._result

    def get_winner(self) -> chess.Color | None:
        return self._winner

    def get_termination(self) -> GameTermination | None:
        return self._termination

    def get_details(self) -> str:
        return self._details

    def is_finished(self) -> bool:
        return self._result != "*"

    def update_from_board(self):
        outcome = self._board.outcome(claim_draw=True)

        if outcome is None:
            return

        self._result = outcome.result()
        self._winner = outcome.winner
        self._termination = self._get_board_termination(outcome.termination)
        self._details = self._termination.value

    def record_timeout(self, loser: chess.Color):
        winner = not loser
        self._set_decisive_result(winner, GameTermination.TIMEOUT)

    def record_illegal_move(self, loser: chess.Color, move: chess.Move):
        winner = not loser
        self._set_decisive_result(winner, GameTermination.ILLEGAL_MOVE, str(move))

    def record_engine_error(self, loser: chess.Color, error: Exception):
        winner = not loser
        self._set_decisive_result(winner, GameTermination.ENGINE_ERROR, str(error))

    def get_summary(self) -> str:
        if not self.is_finished():
            return "Game in progress"

        if self._details:
            return f"{self._result} by {self._details}"

        return self._result

    def _set_decisive_result(self, winner: chess.Color, termination: GameTermination, details: str = ""):
        self._winner = winner
        self._termination = termination
        self._result = "1-0" if winner == chess.WHITE else "0-1"
        self._details = termination.value

        if details:
            self._details = f"{self._details}: {details}"

    def _get_board_termination(self, termination: chess.Termination) -> GameTermination:
        termination_map = {
            chess.Termination.CHECKMATE: GameTermination.CHECKMATE,
            chess.Termination.STALEMATE: GameTermination.STALEMATE,
            chess.Termination.INSUFFICIENT_MATERIAL: GameTermination.INSUFFICIENT_MATERIAL,
            chess.Termination.SEVENTYFIVE_MOVES: GameTermination.SEVENTYFIVE_MOVES,
            chess.Termination.FIVEFOLD_REPETITION: GameTermination.FIVEFOLD_REPETITION,
            chess.Termination.FIFTY_MOVES: GameTermination.FIFTY_MOVES,
            chess.Termination.THREEFOLD_REPETITION: GameTermination.THREEFOLD_REPETITION,
            chess.Termination.VARIANT_WIN: GameTermination.VARIANT_END,
            chess.Termination.VARIANT_LOSS: GameTermination.VARIANT_END,
            chess.Termination.VARIANT_DRAW: GameTermination.VARIANT_END,
        }

        return termination_map.get(termination, GameTermination.UNKNOWN)
