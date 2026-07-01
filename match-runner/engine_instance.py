from concurrent.futures import Future, ThreadPoolExecutor

import chess
import random
import time

class EngineInstance():
    def __init__(self, id, host):
        self._name = id
        self._host = host
        self._search_executor = ThreadPoolExecutor(max_workers=1)
        self._search_future: Future | None = None

    def get_name(self):
        return self._name

    def set_name(self, name):
        self._name = name

    def get_host(self):
        return self._host

    def set_host(self, host):
        self._host = host

    def get_move(self, board: chess.Board) -> chess.Move:
        while random.random() < 0.5:
            time.sleep(0.1)
        return next(iter(board.legal_moves))

    def start_search(self, board: chess.Board):
        if self.is_searching():
            raise RuntimeError(f"{self._name} is already searching")

        self._search_future = self._search_executor.submit(self.get_move, board.copy())

    def is_searching(self) -> bool:
        return self._search_future is not None and not self._search_future.done()

    def get_search_move(self) -> chess.Move:
        if self._search_future is None:
            raise RuntimeError(f"{self._name} has no active search")

        search_future = self._search_future
        self._search_future = None
        return search_future.result()

    def stop_search(self):
        if self._search_future is None:
            return

        self._search_future.cancel()
