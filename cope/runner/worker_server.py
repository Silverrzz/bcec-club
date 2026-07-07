from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import threading
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError
from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol, serve

from cope.core.models import (
    AssignmentComplete,
    EngineCommand,
    EngineCommandResult,
    EngineInfo,
    PROTOCOL_VERSION,
    WorkerSessionHello,
    WorkerTokenHello,
    WorkerWelcome,
)
from cope.core.protocol import (
    ProtocolError,
    ProtocolValidationError,
    decode_envelope,
    decode_message,
    encode_message,
    make_message,
)
from cope.db import (
    WorkerRecord,
    connect_database,
    disconnect_worker,
    fail_game_assignment,
    get_game,
    get_worker,
    get_worker_by_session_id,
    get_worker_by_token,
    initialize_database,
    list_workers,
    touch_worker_seen,
    update_worker_status,
    upsert_worker_connection,
    worker_token_is_valid,
)
from cope.network import DEFAULT_WORKER_PATH, default_worker_host, default_worker_port
from cope.runner.local import (
    next_worker_assignment,
    run_worker_assignment_game,
    run_tournament_matches,
)
from cope.runner.events import (
    publish_tournament_event,
    publish_workers_changed,
    set_runner_wake_handler,
    start_event_publisher,
)


LOG = logging.getLogger("cope.worker_server")
WORKER_CONNECTION_REPLACED_CLOSE_CODE = 4001
ASSIGNABLE_WORKER_STATUSES = {"connected", "building", "ready", "busy"}


@dataclass(frozen=True)
class WorkerServerConfig:
    host: str = field(default_factory=default_worker_host)
    port: int = field(default_factory=default_worker_port)
    db_path: str | Path = "cope.db"
    expected_app_commit: str | None = None
    heartbeat_interval_ms: int = 5000
    assignment_poll_interval_s: float = 1.0


async def run_worker_server(config: WorkerServerConfig) -> None:
    server = WorkerHandshakeServer(config)
    server.install_stream_wake_handler()
    start_event_publisher()
    orphaned_tournaments = server.reset_orphaned_worker_connections()
    if orphaned_tournaments:
        publish_workers_changed("worker.reset")
    for tournament_id in orphaned_tournaments:
        publish_tournament_event(tournament_id)
    heartbeat_interval_s = max(config.heartbeat_interval_ms / 1000, 0.5)
    async with serve(
        server.handle_connection,
        config.host,
        config.port,
        ping_interval=heartbeat_interval_s,
        ping_timeout=heartbeat_interval_s,
        close_timeout=1,
    ):
        LOG.info(
            "listening for workers bind=%s:%s path=%s db=%s",
            config.host,
            config.port,
            DEFAULT_WORKER_PATH,
            config.db_path,
        )
        await asyncio.Future()


class WorkerConnectionInactive(RuntimeError):
    pass


class WorkerHandshakeServer:
    def __init__(self, config: WorkerServerConfig):
        self._config = config
        self._work_available = asyncio.Condition()
        self._work_generation = 0
        self._loop: asyncio.AbstractEventLoop | None = None

    def install_stream_wake_handler(self) -> None:
        self._loop = asyncio.get_running_loop()

        def wake_from_stream(_event) -> None:
            loop = self._loop
            if loop is None:
                return
            asyncio.run_coroutine_threadsafe(self._wake_workers(), loop)

        set_runner_wake_handler(wake_from_stream)

    def reset_orphaned_worker_connections(self) -> tuple[int, ...]:
        initialize_database(self._config.db_path)
        connection = connect_database(self._config.db_path)
        try:
            tournament_ids: set[int] = set()
            for worker in list_workers(connection):
                if worker.status not in ASSIGNABLE_WORKER_STATUSES:
                    continue
                tournament_ids.update(
                    disconnect_worker(
                        connection,
                        worker.id,
                        reason="worker server restarted",
                    )
                )
            connection.commit()
            return tuple(sorted(tournament_ids))
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    async def handle_connection(
        self,
        websocket: WebSocketServerProtocol,
        path: str | None = None,
    ) -> None:
        worker: WorkerRecord | None = None
        try:
            if path is not None and path != DEFAULT_WORKER_PATH:
                await websocket.close(code=4004, reason="unknown websocket path")
                return

            raw_message = await websocket.recv()
            hello = decode_message(
                raw_message,
                "hello",
                WorkerTokenHello | WorkerSessionHello,
            )
            self._validate_app_commit(hello)
            authenticated_worker = self._authenticate_worker(hello)
            session_id = _new_session_id()
            label = _worker_label(authenticated_worker, hello)
            worker = self._record_connection(authenticated_worker, label, session_id, hello)

            welcome = WorkerWelcome(
                worker_id=worker.id,
                session_id=session_id,
                heartbeat_interval_ms=self._config.heartbeat_interval_ms,
            )
            await _send_message(websocket, "welcome", welcome)
            LOG.info("worker accepted worker_id=%s label=%s", worker.id, label)
            publish_workers_changed("worker.connected", {"worker_id": worker.id})
            await self._wake_workers()
            await self._serve_worker(websocket, worker)
        except ProtocolError as error:
            LOG.warning("closing connection reason=%s", error)
            await websocket.close(code=error.close_code, reason=_close_reason(error))
        except ConnectionClosed:
            LOG.info("worker connection closed")
            return
        finally:
            if worker is not None:
                try:
                    tournament_ids = self._record_worker_disconnected(worker)
                    for tournament_id in tournament_ids:
                        publish_tournament_event(tournament_id)
                    await self._wake_workers()
                except Exception:
                    LOG.exception("worker disconnect cleanup failed worker_id=%s", worker.id)

    async def _serve_worker(
        self,
        websocket: WebSocketServerProtocol,
        worker: WorkerRecord,
    ) -> None:
        wake_generation = self._work_generation
        closed = asyncio.create_task(websocket.wait_closed())
        heartbeat = asyncio.create_task(self._maintain_worker_heartbeat(worker, closed))
        try:
            while True:
                if websocket.closed:
                    return

                try:
                    assignment = self._claim_next_assignment(worker)
                except WorkerConnectionInactive as error:
                    LOG.info(
                        "worker session inactive worker_id=%s reason=%s",
                        worker.id,
                        error,
                    )
                    await websocket.close(
                        code=WORKER_CONNECTION_REPLACED_CLOSE_CODE,
                        reason=_close_reason(error),
                    )
                    return

                if assignment is None:
                    if not self._record_worker_status(
                        worker.id,
                        "ready",
                        session_id=worker.session_id,
                    ):
                        raise WorkerConnectionInactive("worker session is no longer current")
                    next_generation = await self._wait_for_work_or_disconnect(
                        wake_generation,
                        closed,
                    )
                    if next_generation is None:
                        return
                    wake_generation = next_generation
                    continue

                if not self._record_worker_status(
                    worker.id,
                    "busy",
                    session_id=worker.session_id,
                ):
                    self._fail_assignment(
                        assignment,
                        RuntimeError("worker session is no longer current"),
                    )
                    raise WorkerConnectionInactive("worker session is no longer current")

                payload = assignment.assignment
                LOG.info(
                    "dispatching assignment worker_id=%s assignment_id=%s game_id=%s tournament=%s round=%s",
                    worker.id,
                    payload.assignment_id,
                    payload.game_id,
                    assignment.tournament_name,
                    assignment.round,
                )
                transport = WorkerEngineTransport(websocket, assignment)
                try:
                    await _send_message(websocket, "assignment", assignment)
                    await asyncio.to_thread(
                        self._run_assignment_game,
                        assignment,
                        transport,
                    )
                except asyncio.CancelledError:
                    try:
                        self._fail_assignment(assignment, RuntimeError("runner shutting down"))
                    except Exception:
                        LOG.exception(
                            "assignment cleanup failed worker_id=%s assignment_id=%s game_id=%s",
                            worker.id,
                            payload.assignment_id,
                            payload.game_id,
                        )
                    raise
                except Exception as error:
                    self._fail_assignment(assignment, error)
                    LOG.exception(
                        "assignment failed worker_id=%s assignment_id=%s game_id=%s",
                        worker.id,
                        payload.assignment_id,
                        payload.game_id,
                    )
                    if websocket.closed:
                        raise
                    await _send_message(
                        websocket,
                        "assignment_complete",
                        AssignmentComplete(**payload.message_fields()),
                    )
                    LOG.info(
                        "assignment failed complete sent worker_id=%s assignment_id=%s game_id=%s",
                        worker.id,
                        payload.assignment_id,
                        payload.game_id,
                    )
                    await self._wake_workers()
                    continue
                finally:
                    transport.close()
                await _send_message(
                    websocket,
                    "assignment_complete",
                    AssignmentComplete(**payload.message_fields()),
                )
                LOG.info(
                    "assignment complete worker_id=%s assignment_id=%s game_id=%s",
                    worker.id,
                    payload.assignment_id,
                    payload.game_id,
                )
                await self._wake_workers()
        except WorkerConnectionInactive as error:
            LOG.info(
                "worker session inactive worker_id=%s reason=%s",
                worker.id,
                error,
            )
            with contextlib.suppress(ConnectionClosed):
                await websocket.close(
                    code=WORKER_CONNECTION_REPLACED_CLOSE_CODE,
                    reason=_close_reason(error),
                )
        finally:
            if not heartbeat.done():
                heartbeat.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await heartbeat
            if not closed.done():
                closed.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await closed

    async def _wake_workers(self) -> None:
        async with self._work_available:
            self._work_generation += 1
            self._work_available.notify_all()

    async def _wait_for_work(self, wake_generation: int) -> int:
        timeout_s = max(self._config.assignment_poll_interval_s, 0.1)
        try:
            async with self._work_available:
                await asyncio.wait_for(
                    self._work_available.wait_for(
                        lambda: self._work_generation != wake_generation
                    ),
                    timeout=timeout_s,
                )
                return self._work_generation
        except TimeoutError:
            return self._work_generation

    async def _wait_for_work_or_disconnect(
        self,
        wake_generation: int,
        closed: asyncio.Task,
    ) -> int | None:
        work = asyncio.create_task(self._wait_for_work(wake_generation))
        done, pending = await asyncio.wait(
            {work, closed},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if closed in done:
            for task in pending:
                task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await work
            return None
        return work.result()

    async def _maintain_worker_heartbeat(
        self,
        worker: WorkerRecord,
        closed: asyncio.Task,
    ) -> None:
        interval_s = max(self._config.heartbeat_interval_ms / 1000, 0.5)
        while not closed.done():
            try:
                await asyncio.wait_for(asyncio.shield(closed), timeout=interval_s)
            except TimeoutError:
                try:
                    if not self._touch_worker_seen(worker):
                        return
                except Exception:
                    LOG.exception("worker heartbeat update failed worker_id=%s", worker.id)
                    return

    def _touch_worker_seen(self, worker: WorkerRecord) -> bool:
        connection = connect_database(self._config.db_path)
        try:
            updated = touch_worker_seen(
                connection,
                worker.id,
                session_id=worker.session_id,
            )
            connection.commit()
            return updated
        finally:
            connection.close()

    def _validate_app_commit(self, hello: WorkerTokenHello | WorkerSessionHello) -> None:
        expected = self._config.expected_app_commit
        if expected is not None and hello.app_commit != expected:
            raise ProtocolValidationError(
                f"app_commit mismatch: expected {expected}, got {hello.app_commit}"
            )

    def _authenticate_worker(
        self,
        hello: WorkerTokenHello | WorkerSessionHello,
    ) -> WorkerRecord:
        initialize_database(self._config.db_path)
        connection = connect_database(self._config.db_path)
        try:
            if isinstance(hello, WorkerTokenHello):
                worker = get_worker_by_token(connection, hello.token)
                if worker is None or not worker_token_is_valid(worker):
                    raise ProtocolValidationError("invalid or expired worker token")
                return worker

            worker = get_worker_by_session_id(connection, hello.session_id)
            if worker is None or worker.status == "revoked":
                raise ProtocolValidationError("invalid worker session")
            return worker
        finally:
            connection.close()

    def _record_connection(
        self,
        worker: WorkerRecord,
        label: str,
        session_id: str,
        hello: WorkerTokenHello | WorkerSessionHello,
    ) -> WorkerRecord:
        connection = connect_database(self._config.db_path)
        try:
            tournament_ids = disconnect_worker(
                connection,
                worker.id,
                reason="worker session replaced",
            )
            upsert_worker_connection(
                connection,
                worker_id=worker.id,
                label=label,
                session_id=session_id,
                app_commit=hello.app_commit,
                protocol_version=PROTOCOL_VERSION,
                hw=hello.hw,
            )
            current = get_worker(connection, worker.id)
            if current is None or current.status == "revoked" or current.session_id != session_id:
                raise ProtocolValidationError("worker registration was revoked")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        for tournament_id in tournament_ids:
            publish_tournament_event(tournament_id)
        return current

    def _connected_worker(self, worker_id: int) -> WorkerRecord:
        connection = connect_database(self._config.db_path)
        try:
            worker = get_worker(connection, worker_id)
            if worker is None:
                raise RuntimeError(f"worker {worker_id} disappeared after connection")
            return worker
        finally:
            connection.close()

    def _record_worker_status(
        self,
        worker_id: int,
        status: str,
        *,
        session_id: str | None = None,
    ) -> bool:
        connection = connect_database(self._config.db_path)
        try:
            updated = update_worker_status(
                connection,
                worker_id,
                status,
                session_id=session_id,
            )
            connection.commit()
            if updated:
                publish_workers_changed("worker.status", {"worker_id": worker_id, "status": status})
            return updated
        finally:
            connection.close()

    def _record_worker_disconnected(self, worker: WorkerRecord) -> tuple[int, ...]:
        connection = connect_database(self._config.db_path)
        try:
            tournament_ids = disconnect_worker(
                connection,
                worker.id,
                session_id=worker.session_id,
                reason="worker connection lost",
            )
            connection.commit()
            publish_workers_changed("worker.disconnected", {"worker_id": worker.id})
            return tournament_ids
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _claim_next_assignment(self, worker: WorkerRecord):
        initialize_database(self._config.db_path)
        connection = connect_database(self._config.db_path)
        try:
            live_worker = self._validate_assignable_worker(connection, worker)
            run_tournament_matches(connection)
            live_worker = self._validate_assignable_worker(connection, live_worker)
            assignment = next_worker_assignment(connection, live_worker)
            if assignment is not None:
                connection.commit()
            return assignment
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _validate_assignable_worker(
        self,
        connection,
        worker: WorkerRecord,
    ) -> WorkerRecord:
        live_worker = get_worker(connection, worker.id)
        if live_worker is None:
            raise WorkerConnectionInactive("worker record was deleted")
        if live_worker.status == "revoked":
            raise WorkerConnectionInactive("worker was revoked")
        if live_worker.session_id != worker.session_id:
            raise WorkerConnectionInactive("worker session was replaced")
        if live_worker.status not in ASSIGNABLE_WORKER_STATUSES:
            raise WorkerConnectionInactive(f"worker is {live_worker.status}")
        return live_worker

    def _run_assignment_game(self, assignment, transport) -> None:
        connection = connect_database(self._config.db_path)
        try:
            run_worker_assignment_game(connection, assignment, transport)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _fail_assignment(self, assignment, error: Exception) -> None:
        connection = connect_database(self._config.db_path)
        try:
            fail_game_assignment(
                connection,
                assignment.assignment.assignment_id,
                str(error) or error.__class__.__name__,
            )
            game = get_game(connection, assignment.assignment.game_id)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        if game is not None:
            publish_tournament_event(game.tournament_id)
        publish_workers_changed(
            "assignment.failed",
            {"assignment_id": assignment.assignment.assignment_id},
        )


class WorkerEngineTransport:
    def __init__(self, websocket: WebSocketServerProtocol, assignment):
        self._websocket = websocket
        self._assignment = assignment
        self._loop = asyncio.get_running_loop()
        self._command_lock = asyncio.Lock()
        self._closed = threading.Event()
        self._pending: set[Future] = set()
        self._pending_lock = threading.Lock()

    def close(self) -> None:
        self._closed.set()
        with self._pending_lock:
            pending = tuple(self._pending)
        for future in pending:
            future.cancel()

    def execute_engine_command(
        self,
        engine_id: int,
        command: str,
        info_handler: Callable[[str], None] | None = None,
    ) -> list[str]:
        with self._pending_lock:
            if self._closed.is_set():
                raise RuntimeError("worker transport closed")
            future = asyncio.run_coroutine_threadsafe(
                self._execute_engine_command(engine_id, command, info_handler),
                self._loop,
            )
            self._pending.add(future)
        try:
            return future.result()
        finally:
            with self._pending_lock:
                self._pending.discard(future)

    async def _execute_engine_command(
        self,
        engine_id: int,
        command: str,
        info_handler: Callable[[str], None] | None,
    ) -> list[str]:
        async with self._command_lock:
            return await self._execute_engine_command_locked(engine_id, command, info_handler)

    async def _execute_engine_command_locked(
        self,
        engine_id: int,
        command: str,
        info_handler: Callable[[str], None] | None,
    ) -> list[str]:
        assignment = self._assignment.assignment
        await _send_message(
            self._websocket,
            "engine_command",
            EngineCommand(
                **assignment.message_fields(),
                engine_id=engine_id,
                command=command,
            ),
        )

        while True:
            raw_message = await self._websocket.recv()
            envelope = decode_envelope(raw_message)
            if envelope.type == "engine_info":
                info = _validate_worker_payload(EngineInfo, envelope.data)
                self._validate_engine_reply(info, engine_id)
                if info_handler is not None:
                    for line in info.lines:
                        try:
                            info_handler(line)
                        except Exception:
                            LOG.exception(
                                "engine info handler failed assignment_id=%s game_id=%s engine_id=%s",
                                assignment.assignment_id,
                                assignment.game_id,
                                engine_id,
                            )
                continue

            if envelope.type != "engine_command_result":
                raise ProtocolValidationError(f"unexpected worker message: {envelope.type}")

            result = _validate_worker_payload(EngineCommandResult, envelope.data)
            self._validate_engine_reply(result, engine_id)
            return result.lines

    def _validate_engine_reply(
        self,
        result: EngineCommandResult | EngineInfo,
        engine_id: int,
    ) -> None:
        if not result.matches_assignment(self._assignment.assignment) or result.engine_id != engine_id:
            assignment = self._assignment.assignment
            raise ProtocolValidationError(
                "engine reply mismatch: "
                f"expected assignment_id={assignment.assignment_id} "
                f"game_id={assignment.game_id} engine_id={engine_id}, "
                f"got assignment_id={result.assignment_id} "
                f"game_id={result.game_id} engine_id={result.engine_id}"
            )


def _new_session_id() -> str:
    return secrets.token_urlsafe(32)


async def _send_message(
    websocket: WebSocketServerProtocol,
    message_type: str,
    data,
) -> None:
    await websocket.send(encode_message(make_message(message_type, data)))


def _validate_worker_payload(model_type, data):
    try:
        return model_type.model_validate(data)
    except ValidationError as error:
        raise ProtocolValidationError(str(error)) from error


def _hello_label(hello: WorkerTokenHello | WorkerSessionHello) -> str:
    if isinstance(hello, WorkerTokenHello):
        return hello.label_hint or "token worker"

    return "session worker"


def _worker_label(
    worker: WorkerRecord,
    hello: WorkerTokenHello | WorkerSessionHello,
) -> str:
    if worker.label:
        return worker.label

    return _hello_label(hello)


def _close_reason(error: Exception) -> str:
    reason = str(error)
    if len(reason) <= 120:
        return reason

    return f"{reason[:117]}..."
