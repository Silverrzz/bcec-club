from engine_instance import EngineInstance
from game_state import GameState
from time_control import TimeManager

class Match():
    def __init__(self, id: int, white: EngineInstance, black: EngineInstance, game_state: GameState, white_tm: TimeManager, black_tm: TimeManager):
        self._id = id
        self._white = white
        self._black = black
        self._game_state = game_state
        self._white_tm = white_tm
        self._black_tm = black_tm

    def get_id(self) -> int:
        return self._id

    def set_id(self, id: int):
        self._id = id

    def get_white(self) -> EngineInstance:
        return self._white

    def set_white(self, white: EngineInstance):
        self._white = white

    def get_black(self) -> EngineInstance:
        return self._black

    def set_black(self, black: EngineInstance):
        self._black = black

    def get_game_state(self) -> GameState:
        return self._game_state

    def set_game_state(self, game_state: GameState):
        self._game_state = game_state

    def get_white_tm(self) -> TimeManager:
        return self._white_tm

    def set_white_tm(self, white_tm: TimeManager):
        self._white_tm = white_tm

    def get_black_tm(self) -> TimeManager:
        return self._black_tm

    def set_black_tm(self, black_tm: TimeManager):
        self._black_tm = black_tm
