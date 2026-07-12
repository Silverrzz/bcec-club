from __future__ import annotations

import hashlib
import logging
import os
import queue
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from cope.core.models import EngineSpec
from cope.core.stream import clamp_uci_info_line


LOG = logging.getLogger("cope.worker.engine")


class UciEngineProcess:
    def __init__(self, spec: EngineSpec, *, worker_id: int):
        self._spec = spec
        self._source_dir = _engine_source_dir(spec, worker_id)
        self._binary_path = self._source_dir / spec.binary_path
        self._process: subprocess.Popen[str] | None = None
        self._stdout: queue.Queue[str | None] = queue.Queue()
        self._stdout_thread: threading.Thread | None = None
        self._io_lock = threading.Lock()
        self._built = False
        LOG.info(
            "engine wrapper created engine_id=%s engine=%s source_dir=%s binary=%s",
            self._spec.engine_id,
            self._spec.name,
            self._source_dir,
            self._binary_path,
        )

    def prepare(self) -> None:
        """Install and build this engine without starting a UCI game process."""
        with self._io_lock:
            self._ensure_built()

    def handle_command(
        self,
        command: str,
        line_callback: Callable[[str], None] | None = None,
    ) -> list[str]:
        with self._io_lock:
            LOG.info(
                "engine command handling engine_id=%s engine=%s command=%s",
                self._spec.engine_id,
                self._spec.name,
                command,
            )
            if command == "quit":
                LOG.info(
                    "engine quit command received engine_id=%s engine=%s",
                    self._spec.engine_id,
                    self._spec.name,
                )
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
            LOG.info(
                "engine close skipped engine_id=%s engine=%s reason=not_started",
                self._spec.engine_id,
                self._spec.name,
            )
            return
        LOG.info(
            "engine closing engine_id=%s engine=%s pid=%s",
            self._spec.engine_id,
            self._spec.name,
            process.pid,
        )
        try:
            if process.poll() is None and process.stdin is not None:
                try:
                    LOG.info(
                        "engine stdin sending shutdown engine_id=%s engine=%s pid=%s line=%s",
                        self._spec.engine_id,
                        self._spec.name,
                        process.pid,
                        "quit",
                    )
                    process.stdin.write("quit\n")
                    process.stdin.flush()
                    process.wait(timeout=2)
                except Exception:
                    LOG.exception(
                        "engine graceful shutdown failed engine_id=%s engine=%s pid=%s",
                        self._spec.engine_id,
                        self._spec.name,
                        process.pid,
                    )
                    pass
            if process.poll() is None:
                LOG.warning(
                    "engine terminating engine_id=%s engine=%s pid=%s",
                    self._spec.engine_id,
                    self._spec.name,
                    process.pid,
                )
                process.terminate()
                process.wait(timeout=2)
        except Exception:
            if process.poll() is None:
                try:
                    LOG.warning(
                        "engine killing engine_id=%s engine=%s pid=%s",
                        self._spec.engine_id,
                        self._spec.name,
                        process.pid,
                    )
                    process.kill()
                    process.wait(timeout=2)
                except Exception:
                    LOG.exception(
                        "engine kill failed engine_id=%s engine=%s pid=%s",
                        self._spec.engine_id,
                        self._spec.name,
                        process.pid,
                    )
                    pass
        finally:
            for stream in (process.stdin, process.stdout):
                try:
                    if stream is not None:
                        stream.close()
                except Exception:
                    LOG.exception(
                        "engine stream close failed engine_id=%s engine=%s pid=%s",
                        self._spec.engine_id,
                        self._spec.name,
                        process.pid,
                    )
                    pass
            LOG.info(
                "engine closed engine_id=%s engine=%s pid=%s return_code=%s",
                self._spec.engine_id,
                self._spec.name,
                process.pid,
                process.poll(),
            )

    def _send(self, command: str) -> None:
        process = self._ensure_process()
        if process.stdin is None:
            raise RuntimeError(f"{self._spec.name} stdin is not available")
        try:
            LOG.debug(
                "engine stdin engine_id=%s engine=%s pid=%s line=%s",
                self._spec.engine_id,
                self._spec.name,
                process.pid,
                command,
            )
            process.stdin.write(command + "\n")
            process.stdin.flush()
        except BrokenPipeError as exc:
            raise RuntimeError(f"{self._spec.name} pipe broke while sending {command!r}") from exc

    def _ensure_process(self) -> subprocess.Popen[str]:
        if self._process is not None and self._process.poll() is None:
            LOG.debug(
                "engine process ready engine_id=%s engine=%s pid=%s",
                self._spec.engine_id,
                self._spec.name,
                self._process.pid,
            )
            return self._process
        if self._process is not None:
            LOG.error(
                "engine process exited engine_id=%s engine=%s return_code=%s",
                self._spec.engine_id,
                self._spec.name,
                self._process.returncode,
            )
            raise RuntimeError(
                f"{self._spec.name} exited with code {self._process.returncode}"
            )

        self._ensure_built()
        if not self._binary_path.exists():
            raise RuntimeError(f"{self._spec.name} binary does not exist: {self._binary_path}")

        try:
            LOG.info(
                "engine starting engine_id=%s engine=%s binary=%s cwd=%s",
                self._spec.engine_id,
                self._spec.name,
                self._binary_path,
                self._source_dir,
            )
            self._process = subprocess.Popen(
                [str(self._binary_path.resolve())],
                cwd=self._source_dir,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise RuntimeError(f"{self._spec.name} failed to start {self._binary_path}") from exc

        LOG.info(
            "engine started engine_id=%s engine=%s pid=%s",
            self._spec.engine_id,
            self._spec.name,
            self._process.pid,
        )
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
            LOG.info(
                "engine build already prepared engine_id=%s engine=%s binary=%s",
                self._spec.engine_id,
                self._spec.name,
                self._binary_path,
            )
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
            LOG.info(
                "engine build cache hit engine_id=%s engine=%s source_dir=%s commit=%s",
                self._spec.engine_id,
                self._spec.name,
                self._source_dir,
                self._spec.commit,
            )
            return

        LOG.info(
            "engine build preparing engine_id=%s engine=%s source_dir=%s commit=%s",
            self._spec.engine_id,
            self._spec.name,
            self._source_dir,
            self._spec.commit,
        )
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
        LOG.info(
            "engine build ready engine_id=%s engine=%s binary=%s",
            self._spec.engine_id,
            self._spec.name,
            self._binary_path,
        )

    def _read_stdout(self, process: subprocess.Popen[str]) -> None:
        LOG.info(
            "engine stdout reader started engine_id=%s engine=%s pid=%s",
            self._spec.engine_id,
            self._spec.name,
            process.pid,
        )
        if process.stdout is None:
            self._stdout.put(None)
            LOG.warning(
                "engine stdout unavailable engine_id=%s engine=%s pid=%s",
                self._spec.engine_id,
                self._spec.name,
                process.pid,
            )
            return
        try:
            for line in process.stdout:
                line = clamp_uci_info_line(line.rstrip("\r\n"))
                LOG.debug(
                    "engine stdout engine_id=%s engine=%s pid=%s line=%s",
                    self._spec.engine_id,
                    self._spec.name,
                    process.pid,
                    line,
                )
                self._stdout.put(line)
        finally:
            self._stdout.put(None)
            LOG.info(
                "engine stdout reader stopped engine_id=%s engine=%s pid=%s return_code=%s",
                self._spec.engine_id,
                self._spec.name,
                process.pid,
                process.poll(),
            )

    def _read_until(
        self,
        predicate,
        line_callback: Callable[[str], None] | None = None,
    ) -> list[str]:
        LOG.debug(
            "engine output wait started engine_id=%s engine=%s",
            self._spec.engine_id,
            self._spec.name,
        )
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
                LOG.debug(
                    "engine output wait finished engine_id=%s engine=%s lines=%s terminal_line=%s",
                    self._spec.engine_id,
                    self._spec.name,
                    len(lines),
                    line,
                )
                return lines

    def _drain_available(self) -> list[str]:
        lines: list[str] = []
        while True:
            try:
                line = self._stdout.get_nowait()
            except queue.Empty:
                LOG.debug(
                    "engine output drained engine_id=%s engine=%s lines=%s%s",
                    self._spec.engine_id,
                    self._spec.name,
                    len(lines),
                    _line_sample(lines),
                )
                return lines
            if line is None:
                process = self._process
                code = None if process is None else process.poll()
                raise RuntimeError(f"{self._spec.name} exited: {code}")
            lines.append(line)


def _engine_source_dir(spec: EngineSpec, worker_id: int) -> Path:
    configured_cache_root = os.environ.get("COPE_WORKER_ENGINE_DIR")
    if configured_cache_root:
        cache_root = Path(configured_cache_root)
    else:
        cache_root = Path(".cope-worker/workers") / str(worker_id) / "engines"
    source_key = hashlib.blake2s(
        f"{spec.git_url}\0{spec.branch}".encode("utf-8"),
        digest_size=8,
    ).hexdigest()
    safe_name = "".join(char if char.isalnum() else "-" for char in spec.name.lower()).strip("-")
    return cache_root / f"{spec.engine_id}-{safe_name or 'engine'}-{source_key}"


def _build_key(spec: EngineSpec) -> str:
    digest = hashlib.blake2s(digest_size=16)
    for value in (
        spec.git_url,
        spec.branch,
        spec.commit,
        spec.build_cmd,
        spec.binary_path,
        *spec.required_dependencies,
    ):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _run_checked(command, *, cwd: Path | None, shell: bool = False) -> None:
    LOG.info(
        "worker command started cwd=%s shell=%s command=%s",
        cwd,
        shell,
        _format_command(command),
    )
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

    output = (completed.stdout or "").strip()
    if output:
        LOG.debug(
            "worker command output cwd=%s command=%s output=%s",
            cwd,
            _format_command(command),
            output,
        )
    LOG.info(
        "worker command finished cwd=%s exit_code=%s command=%s",
        cwd,
        completed.returncode,
        _format_command(command),
    )
    if completed.returncode != 0:
        if len(output) > 2000:
            output = output[-2000:]
        raise RuntimeError(
            f"command failed with exit code {completed.returncode}: {command}\n{output}"
        )


def _format_command(command) -> str:
    if isinstance(command, str):
        return command
    return " ".join(str(part) for part in command)


def _line_sample(lines: list[str]) -> str:
    if not lines:
        return ""
    line = lines[-1]
    if len(line) > 200:
        line = f"{line[:197]}..."
    return f" last_line={line!r}"
