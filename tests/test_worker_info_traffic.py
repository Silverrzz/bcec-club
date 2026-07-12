from __future__ import annotations

import asyncio
import unittest

from cope.core.models import EngineCommand
from cope.core.protocol import decode_envelope
from cope.worker.client import _EngineInfoPublisher, _compact_search_result_lines


class _SlowWebSocket:
    def __init__(self, delay: float = 0.01) -> None:
        self.delay = delay
        self.messages: list[str] = []

    async def send(self, message: str) -> None:
        await asyncio.sleep(self.delay)
        self.messages.append(message)


class EngineInfoTrafficTests(unittest.IsolatedAsyncioTestCase):
    def command(self) -> EngineCommand:
        return EngineCommand(
            assignment_id=1,
            assignment_key="a" * 16,
            game_id=2,
            engine_id=3,
            command="go wtime 1000 btime 1000",
        )

    async def test_publisher_coalesces_updates_without_blocking_producer(self) -> None:
        websocket = _SlowWebSocket()
        loop = asyncio.get_running_loop()
        publisher = _EngineInfoPublisher(websocket, self.command(), loop)

        await asyncio.to_thread(
            lambda: [publisher.publish(f"info depth {depth}") for depth in range(100)]
        )
        await asyncio.sleep(0.3)
        await publisher.finish()

        self.assertLessEqual(len(websocket.messages), 2)
        envelope = decode_envelope(websocket.messages[-1])
        self.assertEqual(envelope.type, "engine_info")
        self.assertEqual(envelope.data["lines"], ["info depth 99"])

    def test_search_result_keeps_only_latest_info_and_bestmove(self) -> None:
        self.assertEqual(
            _compact_search_result_lines(
                [
                    "info depth 1 score cp 5",
                    "info depth 2 score cp 8",
                    "bestmove e2e4 ponder e7e5",
                ],
                17,
            ),
            [
                "info depth 2 score cp 8",
                "info string cope-worker-command-elapsed-ms 17",
                "bestmove e2e4 ponder e7e5",
            ],
        )


if __name__ == "__main__":
    unittest.main()
