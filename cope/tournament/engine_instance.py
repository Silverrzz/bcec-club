from concurrent.futures import Future, ThreadPoolExecutor
import shlex
import subprocess
import threading
import time
import select
import os
from collections.abc import Sequence

import chess

from .uci import position_command, setoption_command

class EngineInstance():
    def __init__(self, id, host, options: dict[str, str | int | bool] | None = None):
        self._name = id
        self._host = host
        self._options = dict(options or {})
        self._process: subprocess.Popen[str] | None = None
        self._stdout_buffer = ""
        self._io_lock = threading.Lock()
        self._started = False
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
        self._ensure_engine_started()
        for name, value in self._options.items():
            self._send_uci_command(setoption_command(name, value))

        self._send_uci_command("ucinewgame")
        self._send_uci_command("isready")
        self._read_until_token("readyok")

    def get_move(self, board: chess.Board, go_command_arg: str) -> chess.Move:
        self._ensure_engine_started()
        self._send_uci_command(position_command(board))
        self._send_uci_command(go_command_arg)

        while True:
            line = self._read_line(timeout=None)
            if line.startswith("bestmove"):
                parts = line.split()
                if len(parts) < 2 or parts[1] == "(none)":
                    raise RuntimeError(f"{self._name} returned invalid bestmove: {line}")
                try:
                    return chess.Move.from_uci(parts[1])
                except ValueError as exc:
                    raise RuntimeError(f"{self._name} returned malformed bestmove: {line}") from exc

    def start_search(self, board: chess.Board, go_command_arg: str = "go"):
        if self.is_searching():
            raise RuntimeError(f"{self._name} is already searching")

        self._search_future = self._search_executor.submit(self.get_move, board.copy(), go_command_arg)

    def _send_uci_command(self, command: str):
        process = self._ensure_process()
        if process.stdin is None:
            raise RuntimeError(f"{self._name} engine stdin is not available")
        try:
            process.stdin.write(command + "\n")
            process.stdin.flush()
        except BrokenPipeError as exc:
            raise RuntimeError(f"{self._name} engine pipe broke while sending {command!r}") from exc

    def _ensure_engine_started(self):
        with self._io_lock:
            process = self._ensure_process()
            if self._started:
                return
            self._send_raw("uci")
            self._read_until_token("uciok")
            self._send_raw("isready")
            self._read_until_token("readyok")
            self._started = True

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        if self._process is not None:
            raise RuntimeError(f"{self._name} engine exited with code {self._process.returncode}")

        cmd = self._host if isinstance(self._host, Sequence) and not isinstance(self._host, str) else shlex.split(str(self._host))
        if not cmd:
            raise RuntimeError(f"{self._name} has no engine command configured")
        try:
            self._process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise RuntimeError(f"{self._name} failed to start engine command: {cmd}") from exc
        self._started = False
        return self._process

    def _send_raw(self, command: str):
        self._send_uci_command(command)

    def _read_line(self, timeout: float | None = 10.0) -> str:
        process = self._ensure_process()
        if process.stdout is None:
            raise RuntimeError(f"{self._name} engine stdout is not available")
        if "\n" in self._stdout_buffer:
            line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
            return line.strip()
        if process.poll() is not None:
            raise RuntimeError(f"{self._name} engine exited with code {process.returncode}")
        if timeout is not None:
            fd = process.stdout.fileno()
            ready, _, _ = select.select([fd], [], [], timeout)
            if not ready:
                raise RuntimeError(f"{self._name} timed out waiting for engine output")
        fd = process.stdout.fileno()
        chunk = os.read(fd, 4096)
        if not chunk:
            raise RuntimeError(f"{self._name} engine exited unexpectedly while waiting for output")
        self._stdout_buffer += chunk.decode(errors="replace")
        if "\n" not in self._stdout_buffer:
            return self._read_line(timeout)
        line, self._stdout_buffer = self._stdout_buffer.split("\n", 1)
        return line.strip()

    def _read_until_token(self, token: str):
        deadline = time.monotonic() + 10.0
        while True:
            if time.monotonic() > deadline:
                raise RuntimeError(f"{self._name} timed out waiting for {token}")
            line = self._read_line()
            if line == token:
                return

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

        try:
            self._send_uci_command("stop")
        except Exception:
            pass
        self._search_future.cancel()
        self._terminate_process()
        self._search_executor.shutdown(wait=False, cancel_futures=True)
        self._search_executor = ThreadPoolExecutor(max_workers=1)
        self._search_future = None

    def _terminate_process(self):
        process = self._process
        self._process = None
        self._started = False
        if process is None:
            return
        try:
            if process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except Exception:
                    try:
                        process.kill()
                        process.wait(timeout=2)
                    except Exception:
                        pass
        finally:
            try:
                if process.stdin is not None:
                    process.stdin.close()
                if process.stdout is not None:
                    process.stdout.close()
                if process.stderr is not None:
                    process.stderr.close()
            except Exception:
                pass

    def close(self):
        process = self._process
        self._search_future = None
        self._search_executor.shutdown(wait=False, cancel_futures=True)
        if process is None:
            return
        self._process = process
        try:
            if process.poll() is None and process.stdin is not None:
                try:
                    process.stdin.write("quit\n")
                    process.stdin.flush()
                    process.wait(timeout=2)
                except Exception:
                    pass
        finally:
            self._terminate_process()

    def quit(self):
        self.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
