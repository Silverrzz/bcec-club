from __future__ import annotations

import hashlib
import os
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from cope.core.models import EngineSpec


class UciEngineProcess:
    def __init__(self, spec: EngineSpec):
        self._spec = spec
        self._source_dir = _engine_source_dir(spec)
        self._binary_path = self._source_dir / spec.binary_path
        self._process: subprocess.Popen[str] | None = None
        self._stdout: queue.Queue[str | None] = queue.Queue()
        self._stdout_thread: threading.Thread | None = None
        self._io_lock = threading.Lock()
        self._built = False

    def handle_command(
        self,
        command: str,
        line_callback: Callable[[str], None] | None = None,
    ) -> list[str]:
        with self._io_lock:
            if command == "quit":
                self.close()
                return []

            self._send(command)
            if command == "uci":
                return self._read_until(lambda line: line == "uciok")
            if command == "isready":
                return self._read_until(lambda line: line == "readyok")
            if command.startswith("go"):
                return self._read_until(
                    lambda line: line.startswith("bestmove"),
                    line_callback=line_callback,
                )
            if command == "stop":
                return self._drain_available()

            return self._drain_available()

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.poll() is None and process.stdin is not None:
                try:
                    process.stdin.write("quit\n")
                    process.stdin.flush()
                    process.wait(timeout=2)
                except Exception:
                    pass
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=2)
        except Exception:
            if process.poll() is None:
                try:
                    process.kill()
                    process.wait(timeout=2)
                except Exception:
                    pass
        finally:
            for stream in (process.stdin, process.stdout):
                try:
                    if stream is not None:
                        stream.close()
                except Exception:
                    pass

    def _send(self, command: str) -> None:
        process = self._ensure_process()
        if process.stdin is None:
            raise RuntimeError(f"{self._spec.name} stdin is not available")
        try:
            process.stdin.write(command + "\n")
            process.stdin.flush()
        except BrokenPipeError as exc:
            raise RuntimeError(f"{self._spec.name} pipe broke while sending {command!r}") from exc

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            return self._process
        if self._process is not None:
            raise RuntimeError(
                f"{self._spec.name} exited with code {self._process.returncode}"
            )

        self._ensure_built()
        if not self._binary_path.exists():
            raise RuntimeError(f"{self._spec.name} binary does not exist: {self._binary_path}")

        try:
            self._process = subprocess.Popen(
                [str(self._binary_path)],
                cwd=self._source_dir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise RuntimeError(f"{self._spec.name} failed to start {self._binary_path}") from exc

        self._stdout = queue.Queue()
        self._stdout_thread = threading.Thread(
            target=self._read_stdout,
            args=(self._process,),
            daemon=True,
        )
        self._stdout_thread.start()
        return self._process

    def _ensure_built(self) -> None:
        if self._built and self._binary_path.exists():
            return

        marker = self._source_dir / ".cope-build"
        build_key = _build_key(self._spec)
        if (
            self._source_dir.exists()
            and marker.exists()
            and marker.read_text(encoding="utf-8") == build_key
            and self._binary_path.exists()
        ):
            self._built = True
            return

        self._source_dir.parent.mkdir(parents=True, exist_ok=True)
        if not self._source_dir.exists():
            command = ["git", "clone"]
            if self._spec.branch:
                command.extend(["--branch", self._spec.branch])
            command.extend([self._spec.git_url, str(self._source_dir)])
            _run_checked(command, cwd=None)

        if self._spec.branch:
            fetch_command = ["git", "fetch", "--tags", "origin", self._spec.branch]
        else:
            fetch_command = ["git", "fetch", "--all", "--tags"]
        _run_checked(fetch_command, cwd=self._source_dir)
        _run_checked(["git", "checkout", "--force", "--detach", self._spec.commit], cwd=self._source_dir)

        _run_checked(self._spec.build_cmd, cwd=self._source_dir, shell=True)
        if not self._binary_path.exists():
            raise RuntimeError(
                f"{self._spec.name} build completed but binary was not found: {self._binary_path}"
            )
        marker.write_text(build_key, encoding="utf-8")
        self._built = True

    def _read_stdout(self, process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            self._stdout.put(None)
            return
        try:
            for line in process.stdout:
                self._stdout.put(line.rstrip("\r\n"))
        finally:
            self._stdout.put(None)

    def _read_until(
        self,
        predicate,
        line_callback: Callable[[str], None] | None = None,
    ) -> list[str]:
        deadline = time.monotonic() + 60.0
        lines: list[str] = []
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RuntimeError(f"{self._spec.name} timed out waiting for UCI output")
            try:
                line = self._stdout.get(timeout=remaining)
            except queue.Empty as exc:
                raise RuntimeError(f"{self._spec.name} timed out waiting for UCI output") from exc
            if line is None:
                process = self._process
                code = None if process is None else process.poll()
                raise RuntimeError(f"{self._spec.name} exited while waiting for UCI output: {code}")
            lines.append(line)
            if line_callback is not None and line.startswith("info"):
                line_callback(line)
            if predicate(line):
                return lines

    def _drain_available(self) -> list[str]:
        lines: list[str] = []
        while True:
            try:
                line = self._stdout.get_nowait()
            except queue.Empty:
                return lines
            if line is None:
                process = self._process
                code = None if process is None else process.poll()
                raise RuntimeError(f"{self._spec.name} exited: {code}")
            lines.append(line)


def _engine_source_dir(spec: EngineSpec) -> Path:
    cache_root = Path(os.environ.get("COPE_WORKER_ENGINE_DIR", ".cope-worker/engines"))
    source_key = hashlib.blake2s(
        f"{spec.git_url}\0{spec.branch}".encode("utf-8"),
        digest_size=8,
    ).hexdigest()
    safe_name = "".join(char if char.isalnum() else "-" for char in spec.name.lower()).strip("-")
    return cache_root / f"{spec.engine_id}-{safe_name or 'engine'}-{source_key}"


def _build_key(spec: EngineSpec) -> str:
    digest = hashlib.blake2s(digest_size=16)
    for value in (spec.git_url, spec.branch, spec.commit, spec.build_cmd, spec.binary_path):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _run_checked(command, *, cwd: Path | None, shell: bool = False) -> None:
    try:
        completed = subprocess.run(
            command,
            cwd=None if cwd is None else str(cwd),
            shell=shell,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"failed to run command: {command}") from exc

    if completed.returncode != 0:
        output = (completed.stdout or "").strip()
        if len(output) > 2000:
            output = output[-2000:]
        raise RuntimeError(
            f"command failed with exit code {completed.returncode}: {command}\n{output}"
        )
