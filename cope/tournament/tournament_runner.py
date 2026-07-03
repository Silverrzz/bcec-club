import chess

from .game_state import GameState
from .game_runner import GameRunner

from .tournament import Game, Tournament


class TournamentRunner():
    def __init__(self, tournament: Tournament, clock_probe_interval: float = 0.001):
        self._tournament = tournament
        self._clock_probe_interval = clock_probe_interval
        self._current_game_index = 0
        self._create_games()

    def get_tournament(self) -> Tournament:
        return self._tournament

    def set_tournament(self, tournament: Tournament):
        self._tournament = tournament
        self._current_game_index = 0
        self._create_games()

    def get_current_game_index(self) -> int:
        return self._current_game_index

    def get_current_game(self) -> Game | None:
        if self.is_finished():
            return None

        return self._tournament.get_games()[self._current_game_index]

    def get_completed_games(self) -> tuple[Game, ...]:
        return tuple(
            game
            for game in self._tournament.get_games()
            if game.state.is_finished()
        )

    def get_remaining_games(self) -> tuple[Game, ...]:
        return tuple(
            game
            for game in self._tournament.get_games()
            if not game.state.is_finished()
        )

    def is_finished(self) -> bool:
        return self._current_game_index >= len(self._tournament.get_games())

    def run(self):
        while not self.is_finished():
            self.run_next_game()

    def run_next_game(self) -> Game | None:
        game = self.get_current_game()

        if game is None:
            return None

        game_runner = GameRunner(game, clock_probe_interval=self._clock_probe_interval)
        game_runner.run()
        self._current_game_index += 1
        return game

    def _create_games(self):
        self._tournament.clear_games()
        self._current_game_index = 0

        game_id = 1
        engines = self._tournament.get_engines()

        for white_index in range(len(engines)):
            for black_index in range(white_index + 1, len(engines)):
                white = engines[white_index]
                black = engines[black_index]

                self._tournament.add_game(self._create_game(game_id, white, black))
                game_id += 1

                self._tournament.add_game(self._create_game(game_id, black, white))
                game_id += 1

    def _create_game(self, id, white, black) -> Game:
        time_control = self._tournament.get_time_control()

        return Game(
            id=id,
            white=white,
            black=black,
            state=GameState(board=chess.Board()),
            white_tm=time_control.create_manager(),
            black_tm=time_control.create_manager(),
        )
