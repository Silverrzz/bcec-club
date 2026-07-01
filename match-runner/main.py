

import chess

from engine_instance import EngineInstance
from time_control import TimeControl, TimeControlCategory
from game_state import GameState
from match import Match
from match_runner import MatchRunner

if __name__ == "__main__":

    white_engine = EngineInstance("sable", "1.2.3.4")
    black_engine = EngineInstance("lacrima", "5.6.7.8")

    time_control = TimeControl(
        category=TimeControlCategory.INCREMENT,
        initial_time=500,
        increment=50
    )

    match = Match(
        id=1,
        white=white_engine,
        black=black_engine,
        game_state=GameState(board=chess.Board()),
        white_tm=time_control.get_manager_object(),
        black_tm=time_control.get_manager_object()
    )

    runner = MatchRunner(match)

    while not match.get_game_state().is_finished():
        move = runner.run_next_move()
        if move is not None:
            print(move)

    print(match.get_game_state().get_summary())
