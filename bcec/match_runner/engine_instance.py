from concurrent.futures import Future, ThreadPoolExecutor

import chess

from .uci import position_command, setoption_command

class EngineInstance():
    def __init__(self, id, host, options: dict[str, str | int | bool] | None = None):
        self._name = id
        self._host = host
        self._options = dict(options or {})
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

    def get_options(self) -> dict[str, str | int | bool]:
        return dict(self._options)

    def set_options(self, options: dict[str, str | int | bool]):
        self._options = dict(options)

    def start_new_game(self):
        for name, value in self._options.items():
            self._send_uci_command(setoption_command(name, value))

        self._send_uci_command("ucinewgame")

    def get_move(self, board: chess.Board, go_command_arg: str) -> chess.Move:
        self._send_uci_command(position_command(board))
        self._send_uci_command(go_command_arg)

        return next(iter(board.legal_moves))

    def start_search(self, board: chess.Board, go_command_arg: str = "go"):
        if self.is_searching():
            raise RuntimeError(f"{self._name} is already searching")

        self._search_future = self._search_executor.submit(self.get_move, board.copy(), go_command_arg)

    def _send_uci_command(self, command: str):
        pass

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
        self._search_executor.shutdown(wait=False, cancel_futures=True)
        self._search_executor = ThreadPoolExecutor(max_workers=1)
        self._search_future = None
