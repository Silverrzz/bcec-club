from dataclasses import dataclass

from .engine_instance import EngineInstance
from .game_state import GameState
from .time_control import TimeControl
from .time_control import TimeManager


@dataclass(slots=True)
class Game:
    id: int
    white: EngineInstance
    black: EngineInstance
    state: GameState
    white_tm: TimeManager
    black_tm: TimeManager


class Tournament():
    def __init__(
        self,
        id: int,
        name: str,
        engines: list[EngineInstance],
        time_control: TimeControl,
    ):
        self._id = id
        self._name = name
        self._engines = engines
        self._time_control = time_control
        self._games: list[Game] = []

    def get_id(self) -> int:
        return self._id

    def set_id(self, id: int):
        self._id = id

    def get_name(self) -> str:
        return self._name

    def set_name(self, name: str):
        self._name = name

    def get_engines(self) -> list[EngineInstance]:
        return self._engines

    def set_engines(self, engines: list[EngineInstance]):
        self._engines = engines

    def get_time_control(self) -> TimeControl:
        return self._time_control

    def set_time_control(self, time_control: TimeControl):
        self._time_control = time_control

    def get_games(self) -> tuple[Game, ...]:
        return tuple(self._games)

    def add_game(self, game: Game):
        self._games.append(game)

    def clear_games(self):
        self._games.clear()
