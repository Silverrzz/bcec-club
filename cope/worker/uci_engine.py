from __future__ import annotations

import hashlib
import logging
import os
import queue
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from urllib.parse import urljoin, urlsplit, urlunsplit
from contextlib import contextmanager
from collections.abc import Callable
from pathlib import Path
from typing import Iterator

from cope.core.models import EngineSpec
from cope.core.stream import clamp_uci_info_line


LOG = logging.getLogger("cope.worker.engine")
_ARTIFACT_FAILURE_COOLDOWN_S = 60.0
_ARTIFACT_LOCKS: dict[Path, threading.Lock] = {}
_ARTIFACT_LOCKS_GUARD = threading.Lock()


class EnginePreparationError(RuntimeError):
    def __init__(self, spec: EngineSpec, stage: str, detail: str):
        self.engine_id = spec.engine_id
        self.engine_name = spec.name
        self.stage = stage
        self.detail = detail.strip() or "unknown engine preparation error"
        super().__init__(f"{spec.name} {stage} failed: {self.detail}")


class UciEngineProcess:
    def __init__(self, spec: EngineSpec, *, server_url: str, credential: str):
        self._spec = spec
        self._source_dir = _engine_source_dir(spec)
        self._binary_path = self._source_dir / "engine"
        self._download_url = _absolute_download_url(server_url, spec.binary_url)
        self._credential = credential
        self._process: subprocess.Popen[str] | None = None
        self._stdout: queue.Queue[str | None] = queue.Queue()
        self._stdout_thread: threading.Thread | None = None
        self._io_lock = threading.Lock()
        self._prepared = False
        LOG.info(
            "engine wrapper created engine_id=%s engine=%s source_dir=%s binary=%s",
            self._spec.engine_id,
            self._spec.name,
            self._source_dir,
            self._binary_path,
        )

    @property
    def process_started(self) -> bool:
        return self._process is not None

    def prepare(self) -> None:
        """Download and verify this version without starting a UCI process."""
        with self._io_lock:
            try:
                self._ensure_artifact()
            except EnginePreparationError:
                raise
            except Exception as exc:
                raise EnginePreparationError(self._spec, "cache", str(exc)) from exc

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

        self._ensure_artifact()
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

    def _ensure_artifact(self) -> None:
        if self._prepared and self._binary_path.exists():
            LOG.info(
                "engine artifact already prepared engine_id=%s engine=%s binary=%s",
                self._spec.engine_id,
                self._spec.name,
                self._binary_path,
            )
            return

        artifact_key = self._spec.binary_sha256
        cache_root = self._source_dir.parent
        cache_name = self._source_dir.name
        lock_path = cache_root / ".locks" / f"{cache_name}.lock"
        failure_path = cache_root / ".failures" / f"{cache_name}.txt"

        LOG.info(
            "engine download waiting for machine cache engine_id=%s engine=%s cache=%s",
            self._spec.engine_id,
            self._spec.name,
            self._source_dir,
        )
        with _exclusive_artifact_lock(lock_path):
            if _artifact_is_ready(
                self._source_dir, self._binary_path, artifact_key, self._spec.binary_size
            ):
                self._prepared = True
                LOG.info(
                    "engine machine cache hit engine_id=%s engine=%s source_dir=%s sha256=%s",
                    self._spec.engine_id,
                    self._spec.name,
                    self._source_dir,
                    self._spec.binary_sha256,
                )
                return

            cached_failure = _recent_artifact_failure(failure_path)
            if cached_failure is not None:
                stage, detail = cached_failure
                raise EnginePreparationError(
                    self._spec,
                    stage,
                    "a recent machine-wide download attempt failed; retry is temporarily "
                    f"suppressed:\n{detail}",
                )

            LOG.info(
                "engine machine download starting engine_id=%s engine=%s cache=%s sha256=%s",
                self._spec.engine_id,
                self._spec.name,
                self._source_dir,
                self._spec.binary_sha256,
            )
            # The name is deterministic because the artifact lock guarantees one
            # writer. A process killed mid-download leaves a directory that the
            # next attempt can identify and remove.
            temporary = cache_root / ".tmp" / cache_name
            stage = "cache"
            try:
                if self._source_dir.exists():
                    shutil.rmtree(self._source_dir)
                if temporary.exists():
                    shutil.rmtree(temporary)
                temporary.parent.mkdir(parents=True, exist_ok=True)

                temporary.mkdir(parents=True)
                stage = "download"
                temporary_binary = temporary / "engine"
                _download_binary(
                    self._download_url,
                    temporary_binary,
                    credential=self._credential,
                    expected_size=self._spec.binary_size,
                )
                stage = "verify"
                digest = _sha256_file(temporary_binary)
                if digest != self._spec.binary_sha256:
                    raise RuntimeError(f"SHA-256 mismatch: expected {self._spec.binary_sha256}, got {digest}")
                if temporary_binary.stat().st_size != self._spec.binary_size:
                    raise RuntimeError("downloaded binary size does not match the registered artifact")
                temporary_binary.chmod(0o700)
                (temporary / ".cope-artifact").write_text(artifact_key, encoding="utf-8")
                os.replace(temporary, self._source_dir)
                if failure_path.exists():
                    failure_path.unlink()
            except Exception as exc:
                error = EnginePreparationError(self._spec, stage, str(exc))
                _record_artifact_failure(failure_path, error.stage, error.detail)
                raise error from exc
            finally:
                if temporary.exists():
                    try:
                        shutil.rmtree(temporary)
                    except OSError:
                        LOG.exception("could not remove temporary engine download %s", temporary)

            self._prepared = True
            LOG.info(
                "engine machine artifact ready engine_id=%s engine=%s binary=%s",
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


def _engine_source_dir(spec: EngineSpec) -> Path:
    configured_cache_root = os.environ.get("COPE_WORKER_ENGINE_DIR")
    if configured_cache_root:
        cache_root = Path(configured_cache_root).expanduser().resolve()
    else:
        cache_root = (_effective_home_dir() / ".cope-worker" / "engines").resolve()
    return cache_root / f"sha256-{spec.binary_sha256}"


def _effective_home_dir() -> Path:
    if os.name == "posix":
        import pwd

        return Path(pwd.getpwuid(os.geteuid()).pw_dir)
    return Path.home()


def _artifact_is_ready(
    source_dir: Path,
    binary_path: Path,
    artifact_key: str,
    expected_size: int,
) -> bool:
    marker = source_dir / ".cope-artifact"
    try:
        return (
            source_dir.is_dir()
            and binary_path.is_file()
            and binary_path.stat().st_size == expected_size
            and marker.read_text(encoding="utf-8") == artifact_key
            and _sha256_file(binary_path) == artifact_key
        )
    except (OSError, UnicodeError):
        return False


def _recent_artifact_failure(path: Path) -> tuple[str, str] | None:
    try:
        age = time.time() - path.stat().st_mtime
        if age >= _ARTIFACT_FAILURE_COOLDOWN_S:
            path.unlink(missing_ok=True)
            return None
        stage, separator, detail = path.read_text(encoding="utf-8").partition("\n")
        return (stage, detail.strip()) if separator else ("cache", stage.strip())
    except (FileNotFoundError, OSError, UnicodeError):
        return None


def _record_artifact_failure(path: Path, stage: str, detail: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{stage}\n{detail[-8000:]}\n", encoding="utf-8")
    except OSError:
        # Preserve the actual download/verification exception, especially when the
        # reason the failure cannot be recorded is a full filesystem.
        LOG.exception("could not record engine artifact failure in %s", path)


@contextmanager
def _exclusive_artifact_lock(path: Path) -> Iterator[None]:
    """Serialize one artifact download across pool threads and Linux processes."""
    with _ARTIFACT_LOCKS_GUARD:
        thread_lock = _ARTIFACT_LOCKS.setdefault(path, threading.Lock())

    with thread_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a+b") as lock_file:
            if os.name == "posix":
                import fcntl

                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if os.name == "posix":
                    import fcntl

                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _absolute_download_url(server_url: str, path: str) -> str:
    if path.startswith(("https://", "http://")):
        return path
    parsed = urlsplit(server_url)
    scheme = "https" if parsed.scheme in {"wss", "https"} else "http"
    origin = urlunsplit((scheme, parsed.netloc, "/", "", ""))
    return urljoin(origin, path.lstrip("/"))


def _download_binary(
    url: str,
    destination: Path,
    *,
    credential: str,
    expected_size: int,
) -> None:
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {credential}", "Accept": "application/octet-stream"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response, destination.open("xb") as output:
            declared = response.headers.get("Content-Length")
            if declared and int(declared) != expected_size:
                raise RuntimeError("server reported an unexpected binary size")
            received = 0
            while True:
                chunk = response.read(min(1024 * 1024, expected_size - received + 1))
                if not chunk:
                    break
                received += len(chunk)
                if received > expected_size:
                    raise RuntimeError("server sent more binary data than registered")
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"binary server returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"could not reach binary server: {exc.reason}") from exc


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
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
        if len(output) > 8000:
            output = output[-8000:]
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
