from __future__ import annotations

import time
import unittest

from cope.tournament.engine_instance import EngineInstance, _parse_search_result
from cope.tournament.game_runner import GameRunner
from cope.tournament.game_state import GameState
from cope.tournament.time_control import RuntimeTimeControl, TimeControlCategory, TimeOutError
from cope.tournament.tournament import Game

import chess


class WorkerClockAccountingTests(unittest.TestCase):
    def test_game_does_not_charge_remote_round_trip_latency(self) -> None:
        class SlowTransport:
            def execute_engine_command(self, engine_id, command, info_handler=None):
                if command == "uci":
                    return ["uciok"]
                if command == "isready":
                    return ["readyok"]
                if command.startswith("go"):
                    time.sleep(0.03)
                    return [
                        "info string cope-worker-command-elapsed-ms 2",
                        "bestmove e2e4",
                    ]
                return []

        time_control = RuntimeTimeControl(
            TimeControlCategory.INCREMENT,
            initial_time=10,
            increment=0,
        )
        transport = SlowTransport()
        white = EngineInstance(1, transport)
        black = EngineInstance(2, transport)
        self.addCleanup(white.close)
        self.addCleanup(black.close)
        game = Game(
            id=1,
            white=white,
            black=black,
            state=GameState(board=chess.Board()),
            white_tm=time_control.create_manager(),
            black_tm=time_control.create_manager(),
        )

        move = GameRunner(game).run_next_move()

        self.assertEqual(move, chess.Move.from_uci("e2e4"))
        self.assertEqual(game.white_tm.get_remaining_time(), 8)

    def test_search_result_reads_worker_elapsed_marker(self) -> None:
        result = _parse_search_result(
            [
                "info depth 10 score cp 12 time 8",
                "info string cope-worker-command-elapsed-ms 11",
                "bestmove e2e4",
            ],
            chess.Board(),
            "test",
        )
        self.assertEqual(result.command_elapsed_ms, 11)
        self.assertEqual(result.time_ms, 8)

    def test_worker_elapsed_time_replaces_runner_wall_time(self) -> None:
        manager = RuntimeTimeControl(
            TimeControlCategory.INCREMENT,
            initial_time=50,
            increment=0,
        ).create_manager()
        manager.start_clock()
        time.sleep(0.06)
        manager.stop_clock(elapsed_time_ms=10)
        self.assertEqual(manager.get_remaining_time(), 40)

    def test_worker_elapsed_time_still_enforces_timeout(self) -> None:
        manager = RuntimeTimeControl(
            TimeControlCategory.INCREMENT,
            initial_time=10,
            increment=0,
        ).create_manager()
        manager.start_clock()
        with self.assertRaises(TimeOutError):
            manager.stop_clock(elapsed_time_ms=11)


if __name__ == "__main__":
    unittest.main()
