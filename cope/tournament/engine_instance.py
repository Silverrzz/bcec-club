from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
import shlex
import subprocess
import threading
import time
import select
import os
from collections.abc import Callable, Sequence
from typing import Protocol, runtime_checkable

import chess

from cope.core.stream import clamp_uci_info_line

from .uci import position_command, setoption_command


@dataclass(frozen=True, slots=True)
class EngineSearchResult:
    bestmove: chess.Move
    eval_cp: int | None = None
    eval_mate: int | None = None
    depth: int | None = None
    nodes: int | None = None
    nps: int | None = None
    time_ms: int = 0
    pv: str | None = None
    info_line: str | None = None


@dataclass(frozen=True, slots=True)
class EngineSearchInfo:
    eval_cp: int | None = None
    eval_mate: int | None = None
    depth: int | None = None
    nodes: int | None = None
    nps: int | None = None
    time_ms: int = 0
    pv: str | None = None


@runtime_checkable
class EngineCommandTransport(Protocol):
    def execute_engine_command(
        self,
        engine_id: int,
        command: str,
        info_handler: Callable[[str], None] | None = None,
    ) -> list[str]:
        ...


class EngineInstance:
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
        self._last_search_result: EngineSearchResult | None = None
        self._current_search_info: EngineSearchInfo | None = None
        self._info_listener: Callable[[str, EngineSearchInfo], None] | None = None

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

    def set_info_listener(
        self,
        listener: Callable[[str, EngineSearchInfo], None] | None,
    ) -> None:
        self._info_listener = listener

    def start_new_game(self):
        if self._is_remote():
            self._ensure_engine_started()
            for name, value in self._options.items():
                self._send_remote_command(setoption_command(name, value))
            self._send_remote_command("ucinewgame")
            self._read_remote_until_token("isready", "readyok")
            return

        self._ensure_engine_started()
        for name, value in self._options.items():
            self._send_uci_command(setoption_command(name, value))

        self._send_uci_command("ucinewgame")
        self._send_uci_command("isready")
        self._read_until_token("readyok")

    def get_move(self, board: chess.Board, go_command_arg: str) -> chess.Move:
        return self.get_search_result(board, go_command_arg).bestmove

    def get_search_result(self, board: chess.Board, go_command_arg: str) -> EngineSearchResult:
        self._ensure_engine_started()
        self._current_search_info = None

        if self._is_remote():
            lines: list[str] = []
            lines.extend(self._send_remote_command(position_command(board)))
            lines.extend(self._send_remote_command(go_command_arg, self._record_info_line))
            result = _parse_search_result(lines, board, self._name)
            self._last_search_result = result
            return result

        self._send_uci_command(position_command(board))
        self._send_uci_command(go_command_arg)

        lines: list[str] = []
        while True:
            line = self._read_line(timeout=None)
            lines.append(line)
            self._record_info_line(line)
            if line.startswith("bestmove"):
                result = _parse_search_result(lines, board, self._name)
                self._last_search_result = result
                return result

    def start_search(self, board: chess.Board, go_command_arg: str = "go"):
        if self.is_searching():
            raise RuntimeError(f"{self._name} is already searching")

        self._search_future = self._search_executor.submit(
            self.get_search_result,
            board.copy(),
            go_command_arg,
        )

    def get_last_search_result(self) -> EngineSearchResult | None:
        return self._last_search_result

    def get_current_search_info(self) -> EngineSearchInfo | None:
        return self._current_search_info

    def _is_remote(self) -> bool:
        return isinstance(self._host, EngineCommandTransport)

    def _send_remote_command(
        self,
        command: str,
        info_handler: Callable[[str], None] | None = None,
    ) -> list[str]:
        return self._host.execute_engine_command(int(self._name), command, info_handler)

    def _record_info_line(self, line: str) -> None:
        line = clamp_uci_info_line(line)
        info = _parse_info_line(line, self._current_search_info)
        if info is not None:
            self._current_search_info = info
            if self._info_listener is not None:
                self._info_listener(line, info)

    def _read_remote_until_token(self, command: str, token: str):
        lines = self._send_remote_command(command)
        if token not in lines:
            raise RuntimeError(f"{self._name} timed out waiting for {token}")

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
        if self._is_remote():
            if self._started:
                return
            self._send_remote_command("uci")
            self._read_remote_until_token("isready", "readyok")
            self._started = True
            return

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
        result = search_future.result()
        self._last_search_result = result
        return result.bestmove

    def stop_search(self):
        if self._search_future is None:
            return

        if self._is_remote():
            try:
                self._send_remote_command("stop")
            except Exception:
                pass
            self._search_future.cancel()
            self._search_executor.shutdown(wait=False, cancel_futures=True)
            self._search_executor = ThreadPoolExecutor(max_workers=1)
            self._search_future = None
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
        if self._is_remote():
            try:
                if self._started:
                    self._send_remote_command("quit")
            finally:
                self._started = False
            return

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


def _parse_search_result(
    lines: list[str],
    board: chess.Board,
    engine_name: str,
) -> EngineSearchResult:
    bestmove: chess.Move | None = None
    search_info = EngineSearchInfo()
    info_line: str | None = None

    for line in lines:
        info = _parse_info_line(line, search_info)
        if info is not None:
            search_info = info
            info_line = clamp_uci_info_line(line)
            continue

        parts = line.split()
        if parts and parts[0] == "bestmove" and len(parts) >= 2:
            if parts[1] == "(none)":
                raise RuntimeError(f"{engine_name} returned invalid bestmove: {line}")
            try:
                bestmove = chess.Move.from_uci(parts[1])
            except ValueError as exc:
                raise RuntimeError(f"{engine_name} returned malformed bestmove: {line}") from exc

    if bestmove is None:
        raise RuntimeError(f"{engine_name} did not return bestmove")
    if bestmove not in board.legal_moves:
        raise RuntimeError(f"{engine_name} returned illegal bestmove: {bestmove.uci()}")

    return EngineSearchResult(
        bestmove=bestmove,
        eval_cp=search_info.eval_cp,
        eval_mate=search_info.eval_mate,
        depth=search_info.depth,
        nodes=search_info.nodes,
        nps=search_info.nps,
        time_ms=search_info.time_ms,
        pv=search_info.pv,
        info_line=info_line,
    )


def _parse_info_line(line: str, previous: EngineSearchInfo | None) -> EngineSearchInfo | None:
    parts = line.split()
    if not parts or parts[0] != "info":
        return None
    if len(parts) >= 2 and parts[1] == "string":
        return None

    previous = previous or EngineSearchInfo()
    eval_cp = previous.eval_cp
    eval_mate = previous.eval_mate
    depth = _int_after(parts, "depth", previous.depth)
    nodes = _int_after(parts, "nodes", previous.nodes)
    nps = _int_after(parts, "nps", previous.nps)
    time_ms = _int_after(parts, "time", previous.time_ms) or 0
    pv = previous.pv

    if "score" in parts:
        score_index = parts.index("score")
        if score_index + 2 < len(parts) and parts[score_index + 1] == "cp":
            score_cp = _int_at(parts, score_index + 2)
            if score_cp is not None:
                eval_cp = score_cp
                eval_mate = None
        elif score_index + 2 < len(parts) and parts[score_index + 1] == "mate":
            score_mate = _int_at(parts, score_index + 2)
            if score_mate is not None:
                eval_mate = score_mate
                eval_cp = None

    if "pv" in parts:
        pv_index = parts.index("pv")
        if pv_index + 1 < len(parts):
            pv = " ".join(parts[pv_index + 1 :])

    return EngineSearchInfo(
        eval_cp=eval_cp,
        eval_mate=eval_mate,
        depth=depth,
        nodes=nodes,
        nps=nps,
        time_ms=time_ms,
        pv=pv,
    )


def _int_after(parts: list[str], key: str, default: int | None) -> int | None:
    if key not in parts:
        return default
    index = parts.index(key)
    value = _int_at(parts, index + 1)
    if value is None:
        return default
    return value


def _int_at(parts: list[str], index: int) -> int | None:
    if index >= len(parts):
        return None
    try:
        return int(parts[index])
    except ValueError:
        return None
