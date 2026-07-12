from __future__ import annotations

import asyncio
import contextlib
import logging
import secrets
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError
from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol, serve

from cope.core.models import (
    AssignmentComplete,
    AssignmentFailed,
    AssignmentReady,
    EngineCommand,
    EngineCommandResult,
    EngineInfo,
    PROTOCOL_VERSION,
    WorkerPoolEnrollmentHello,
    WorkerPoolSlotCredential,
    WorkerPoolSlotHello,
    WorkerPoolWelcome,
    WorkerResources,
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
    DEFAULT_DB_PATH,
    WorkerRecord,
    connect_database,
    disconnect_worker,
    fail_game_assignment,
    acknowledge_game_assignment,
    get_game,
    get_worker,
    get_worker_by_session_id,
    get_worker_by_pool_slot_token,
    get_worker_by_token,
    get_worker_pool_by_token,
    enroll_worker_pool,
    list_workers,
    record_worker_failure,
    set_service_endpoint,
    touch_workers_seen,
    touch_service_heartbeat,
    update_worker_status,
    upsert_worker_connection,
    worker_token_is_valid,
)
from cope.network import DEFAULT_WORKER_PATH, default_worker_host, default_worker_port
from cope.runner.local import (
    next_worker_assignment,
    run_worker_assignment_game,
)
from cope.runner.events import (
    publish_tournament_event,
    publish_workers_changed,
    set_runner_wake_handler,
    start_event_publisher,
)


LOG = logging.getLogger("cope.worker_server")
WORKER_CONNECTION_REPLACED_CLOSE_CODE = 4001
ASSIGNABLE_WORKER_STATUSES = {"connected", "downloading", "ready", "busy"}
ENGINE_FAILURE_BACKOFF_S = 60.0


class AssignmentPreparationFailed(RuntimeError):
    def __init__(self, failure: AssignmentFailed):
        self.failure = failure
        super().__init__(
            f"{failure.engine_name} {failure.stage} failed: {failure.error}"
        )


@dataclass(frozen=True)
class WorkerServerConfig:
    host: str = field(default_factory=default_worker_host)
    port: int = field(default_factory=default_worker_port)
    db_path: str | Path = DEFAULT_DB_PATH
    expected_app_commit: str | None = None
    heartbeat_interval_ms: int = 5000
    assignment_poll_interval_s: float = 10.0
    presence_flush_interval_s: float = 15.0
    game_thread_count: int = 2048


async def run_worker_server(config: WorkerServerConfig) -> None:
    try:
        threading.stack_size(1024 * 1024)
    except (RuntimeError, ValueError):
        LOG.warning("could not reduce game thread stack size")
    loop = asyncio.get_running_loop()
    loop.set_default_executor(
        ThreadPoolExecutor(
            max_workers=max(config.game_thread_count, 1),
            thread_name_prefix="cope-game",
        )
    )
    server = WorkerHandshakeServer(config)
    server.install_stream_wake_handler()
    start_event_publisher()
    orphaned_tournaments = server.reset_orphaned_worker_connections()
    if orphaned_tournaments:
        publish_workers_changed("worker.reset")
    for tournament_id in orphaned_tournaments:
        publish_tournament_event(tournament_id)
    heartbeat_interval_s = max(config.heartbeat_interval_ms / 1000, 0.5)
    ping_timeout_s = max(heartbeat_interval_s * 3, 15.0)
    await server.start_background_tasks()
    try:
        async with serve(
            server.handle_connection,
            config.host,
            config.port,
            ping_interval=heartbeat_interval_s,
            ping_timeout=ping_timeout_s,
            close_timeout=1,
            max_queue=32,
        ):
            _register_worker_endpoint(config)
            LOG.info(
                "listening for workers bind=%s:%s path=%s db=postgresql",
                config.host,
                config.port,
                DEFAULT_WORKER_PATH,
            )
            await asyncio.Future()
    finally:
        await server.stop_background_tasks()


def _register_worker_endpoint(config: WorkerServerConfig) -> None:
    connection = connect_database(config.db_path)
    try:
        set_service_endpoint(
            connection,
            service="worker-server",
            host=config.host,
            port=config.port,
            path=DEFAULT_WORKER_PATH,
        )
        connection.commit()
    finally:
        connection.close()


class WorkerConnectionInactive(RuntimeError):
    pass


class WorkerHandshakeServer:
    def __init__(self, config: WorkerServerConfig):
        self._config = config
        self._work_available = asyncio.Condition()
        self._work_generation = 0
        self._wake_pending = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._assignment_lock = asyncio.Lock()
        self._empty_claim_generation: dict[tuple, int] = {}
        self._connections: dict[
            int, tuple[str, WebSocketServerProtocol]
        ] = {}
        self._worker_capabilities: dict[int, tuple] = {}
        self._background_tasks: list[asyncio.Task] = []

    async def start_background_tasks(self) -> None:
        self._background_tasks = [
            asyncio.create_task(self._fallback_wake_loop(), name="worker-fallback-wake"),
            asyncio.create_task(self._presence_flush_loop(), name="worker-presence-flush"),
        ]

    async def stop_background_tasks(self) -> None:
        for task in self._background_tasks:
            task.cancel()
        for task in self._background_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._background_tasks.clear()
        await self._flush_worker_presence()

    async def _fallback_wake_loop(self) -> None:
        interval = max(self._config.assignment_poll_interval_s, 1.0)
        while True:
            await asyncio.sleep(interval)
            await self._wake_workers()

    async def _presence_flush_loop(self) -> None:
        interval = max(self._config.presence_flush_interval_s, 1.0)
        while True:
            await asyncio.sleep(interval)
            try:
                await self._flush_worker_presence()
            except Exception:
                LOG.exception("worker presence batch failed")

    async def _flush_worker_presence(self) -> None:
        sessions = [
            (worker_id, session_id)
            for worker_id, (session_id, _websocket) in self._connections.items()
        ]
        connection = connect_database(self._config.db_path)
        try:
            current = touch_workers_seen(connection, sessions) if sessions else set()
            touch_service_heartbeat(
                connection,
                "worker-server",
                self._config.expected_app_commit or "dev",
            )
            connection.commit()
        finally:
            connection.close()

        stale = [item for item in sessions if item[0] not in current]
        for worker_id, session_id in stale:
            live = self._connections.get(worker_id)
            if live is None or live[0] != session_id:
                continue
            with contextlib.suppress(ConnectionClosed):
                await live[1].close(
                    code=WORKER_CONNECTION_REPLACED_CLOSE_CODE,
                    reason="worker session is no longer current",
                )

    def install_stream_wake_handler(self) -> None:
        self._loop = asyncio.get_running_loop()

        def wake_from_stream(_event) -> None:
            loop = self._loop
            if loop is None:
                return
            asyncio.run_coroutine_threadsafe(self._wake_workers(), loop)

        set_runner_wake_handler(wake_from_stream)

    def reset_orphaned_worker_connections(self) -> tuple[int, ...]:
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
                WorkerTokenHello
                | WorkerSessionHello
                | WorkerPoolSlotHello
                | WorkerPoolEnrollmentHello,
            )
            self._validate_app_commit(hello)
            if isinstance(hello, WorkerPoolEnrollmentHello):
                welcome = self._enroll_worker_pool(hello)
                await _send_message(websocket, "pool_welcome", welcome)
                publish_workers_changed(
                    "worker.pool_enrolled",
                    {"pool_id": welcome.pool_id, "slot_count": len(welcome.slots)},
                )
                await websocket.close(code=1000, reason="worker pool enrolled")
                return
            authenticated_worker = self._authenticate_worker(hello)
            session_id = _new_session_id()
            label = _worker_label(authenticated_worker, hello)
            worker = self._record_connection(authenticated_worker, label, session_id, hello)

            welcome = WorkerWelcome(
                worker_id=worker.id,
                session_id=session_id,
                heartbeat_interval_ms=self._config.heartbeat_interval_ms,
                resources=worker.resources,
            )
            await _send_message(websocket, "welcome", welcome)
            self._connections[worker.id] = (worker.session_id or "", websocket)
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
                live = self._connections.get(worker.id)
                if live is not None and live[0] == worker.session_id:
                    self._connections.pop(worker.id, None)
                    self._worker_capabilities.pop(worker.id, None)
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
        worker_status = "connected"
        try:
            while True:
                if websocket.closed:
                    return

                try:
                    assignment = await self._claim_next_assignment(
                        worker,
                        wake_generation,
                    )
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
                    if worker_status != "ready":
                        if not self._record_worker_status(
                            worker.id,
                            "ready",
                            session_id=worker.session_id,
                        ):
                            raise WorkerConnectionInactive(
                                "worker session is no longer current"
                            )
                        worker_status = "ready"
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
                    "downloading",
                    session_id=worker.session_id,
                ):
                    self._fail_assignment(
                        assignment,
                        RuntimeError("worker session is no longer current"),
                    )
                    raise WorkerConnectionInactive("worker session is no longer current")
                worker_status = "downloading"

                payload = assignment.assignment
                LOG.info(
                    "dispatching assignment worker_id=%s assignment_id=%s game_id=%s tournament=%s round=%s",
                    worker.id,
                    payload.assignment_id,
                    payload.game_id,
                    assignment.tournament_name,
                    assignment.round,
                )
                transport = WorkerEngineTransport(
                    websocket,
                    assignment,
                    failure_handler=lambda failure: self._record_runtime_failure(
                        worker,
                        assignment,
                        failure,
                    ),
                )
                try:
                    await _send_message(websocket, "assignment", assignment)
                    ready = await self._receive_assignment_ready(websocket, assignment)
                    self._acknowledge_assignment(ready)
                    if not self._record_worker_status(
                        worker.id,
                        "busy",
                        session_id=worker.session_id,
                    ):
                        raise WorkerConnectionInactive("worker session is no longer current")
                    worker_status = "busy"
                    await asyncio.to_thread(
                        self._run_assignment_game,
                        assignment,
                        transport,
                    )
                except AssignmentPreparationFailed as error:
                    self._fail_preparation_assignment(worker, assignment, error.failure)
                    LOG.error(
                        "assignment preparation failed worker_id=%s machine_id=%s "
                        "assignment_id=%s game_id=%s engine_id=%s engine=%s stage=%s error=%s",
                        worker.id,
                        worker.machine_id,
                        payload.assignment_id,
                        payload.game_id,
                        error.failure.engine_id,
                        error.failure.engine_name,
                        error.failure.stage,
                        error.failure.error,
                    )
                    await self._wake_workers()
                    await asyncio.sleep(ENGINE_FAILURE_BACKOFF_S)
                    continue
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
            if not closed.done():
                closed.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await closed

    async def _wake_workers(self) -> None:
        if self._wake_pending:
            return
        self._wake_pending = True
        try:
            await asyncio.sleep(0.05)
            async with self._work_available:
                self._work_generation += 1
                self._empty_claim_generation.clear()
                self._work_available.notify_all()
        finally:
            self._wake_pending = False

    async def _wait_for_work(self, wake_generation: int) -> int:
        async with self._work_available:
            await self._work_available.wait_for(
                lambda: self._work_generation != wake_generation
            )
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

    def _validate_app_commit(
        self,
        hello: WorkerTokenHello
        | WorkerSessionHello
        | WorkerPoolSlotHello
        | WorkerPoolEnrollmentHello,
    ) -> None:
        expected = self._config.expected_app_commit
        if expected is not None and hello.app_commit != expected:
            raise ProtocolValidationError(
                f"app_commit mismatch: expected {expected}, got {hello.app_commit}"
            )

    def _enroll_worker_pool(
        self,
        hello: WorkerPoolEnrollmentHello,
    ) -> WorkerPoolWelcome:
        connection = connect_database(self._config.db_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            pool = get_worker_pool_by_token(connection, hello.enrollment_token)
            if pool is None:
                raise ProtocolValidationError("invalid or expired worker pool enrollment token")
            try:
                credentials = enroll_worker_pool(
                    connection,
                    pool=pool,
                    machine_id=hello.machine_id,
                    hw=hello.hw,
                    app_commit=hello.app_commit,
                    protocol_version=PROTOCOL_VERSION,
                )
            except ValueError as error:
                raise ProtocolValidationError(str(error)) from error
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return WorkerPoolWelcome(
            pool_id=pool.id,
            label=pool.label,
            machine_id=hello.machine_id,
            slots=[
                WorkerPoolSlotCredential(
                    worker_id=credential.worker_id,
                    label=credential.label,
                    slot_token=credential.token,
                    resources=WorkerResources(
                        threads=pool.assigned_threads,
                        hash_mb=pool.assigned_hash_mb,
                    ),
                )
                for credential in credentials
            ],
        )

    def _authenticate_worker(
        self,
        hello: WorkerTokenHello | WorkerSessionHello | WorkerPoolSlotHello,
    ) -> WorkerRecord:
        connection = connect_database(self._config.db_path)
        try:
            if isinstance(hello, WorkerTokenHello):
                worker = get_worker_by_token(connection, hello.token)
                if worker is None or not worker_token_is_valid(worker):
                    raise ProtocolValidationError("invalid or expired worker token")
                return worker

            if isinstance(hello, WorkerPoolSlotHello):
                worker = get_worker_by_pool_slot_token(connection, hello.slot_token)
                if worker is None or worker.status == "revoked":
                    raise ProtocolValidationError("invalid worker pool slot credential")
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
        hello: WorkerTokenHello | WorkerSessionHello | WorkerPoolSlotHello,
    ) -> WorkerRecord:
        connection = connect_database(self._config.db_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._validate_worker_resources(connection, worker, hello)
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
                machine_id=hello.machine_id,
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

    def _validate_worker_resources(
        self,
        connection,
        worker: WorkerRecord,
        hello: WorkerTokenHello | WorkerSessionHello | WorkerPoolSlotHello,
    ) -> None:
        if hello.resources != worker.resources:
            raise ProtocolValidationError(
                "worker resource arguments do not match its registered reservation: "
                f"expected {worker.assigned_threads} threads and "
                f"{worker.assigned_hash_mb}MB hash"
            )

        expected_hardware = hello.hw.model_dump_json()
        machine = connection.execute(
            """
            SELECT
              COALESCE(SUM(assigned_threads), 0) AS reserved_threads,
              COALESCE(SUM(assigned_hash_mb), 0) AS reserved_hash_mb,
              COALESCE(BOOL_AND(hw IS NULL OR hw = ?), TRUE) AS hardware_matches
            FROM workers
            WHERE id != ?
              AND machine_id = ?
              AND status != 'revoked'
              AND (pool_id IS NOT NULL OR status IN ('connected', 'downloading', 'ready', 'busy'))
            """,
            (expected_hardware, worker.id, hello.machine_id),
        ).fetchone()
        if machine is not None and not machine["hardware_matches"]:
            raise ProtocolValidationError(
                "connected workers with the same machine id reported different hardware"
            )

        reserved_threads = hello.resources.threads + int(machine["reserved_threads"] or 0)
        if reserved_threads > hello.hw.physical_cores:
            raise ProtocolValidationError(
                f"machine resource oversubscription: workers reserve {reserved_threads} threads "
                f"but only {hello.hw.physical_cores} physical cores are available"
            )

        reserved_hash_mb = hello.resources.hash_mb + int(machine["reserved_hash_mb"] or 0)
        if reserved_hash_mb > hello.hw.total_ram_mb:
            raise ProtocolValidationError(
                f"machine resource oversubscription: workers reserve {reserved_hash_mb}MB hash "
                f"but only {hello.hw.total_ram_mb}MB RAM is available"
            )

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

    async def _claim_next_assignment(
        self,
        worker: WorkerRecord,
        wake_generation: int,
    ):
        capability = self._worker_capabilities.get(
            worker.id,
            _worker_capability_key(worker),
        )
        if self._empty_claim_generation.get(capability) == wake_generation:
            return None
        async with self._assignment_lock:
            if self._empty_claim_generation.get(capability) == wake_generation:
                return None
            assignment = self._claim_next_assignment_from_database(worker)
            if assignment is None:
                self._empty_claim_generation[capability] = wake_generation
            return assignment

    def _claim_next_assignment_from_database(self, worker: WorkerRecord):
        connection = connect_database(self._config.db_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            live_worker = self._validate_assignable_worker(connection, worker)
            assignment = next_worker_assignment(connection, live_worker)
            if assignment is not None:
                connection.commit()
                game = get_game(connection, assignment.assignment.game_id)
                if game is not None:
                    publish_tournament_event(game.tournament_id)
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

    async def _receive_assignment_ready(
        self,
        websocket: WebSocketServerProtocol,
        assignment,
    ) -> AssignmentReady:
        raw_message = await websocket.recv()
        envelope = decode_envelope(raw_message)
        if envelope.type == "assignment_failed":
            failure = AssignmentFailed.model_validate(envelope.data)
            if not failure.matches_assignment(assignment.assignment):
                raise ProtocolValidationError("assignment failure mismatch")
            if failure.engine_id not in assignment.engines:
                raise ProtocolValidationError("assignment failure references unknown engine")
            expected_name = assignment.engines[failure.engine_id].name
            if failure.engine_name != expected_name:
                raise ProtocolValidationError("assignment failure engine name mismatch")
            raise AssignmentPreparationFailed(failure)
        if envelope.type != "assignment_ready":
            raise ProtocolValidationError(
                f"expected assignment_ready, got {envelope.type}"
            )
        ready = AssignmentReady.model_validate(envelope.data)
        if not ready.matches_assignment(assignment.assignment):
            raise ProtocolValidationError("assignment_ready assignment mismatch")
        expected = set(assignment.engines)
        if set(ready.prepared_engine_ids) != expected:
            raise ProtocolValidationError(
                "assignment_ready must include every assigned engine"
            )
        return ready

    def _acknowledge_assignment(self, ready: AssignmentReady) -> None:
        connection = connect_database(self._config.db_path)
        try:
            acknowledge_game_assignment(
                connection,
                ready.assignment_id,
                ready.assignment_key,
            )
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
                assignment.assignment.assignment_key,
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

    def _fail_preparation_assignment(
        self,
        worker: WorkerRecord,
        assignment,
        failure: AssignmentFailed,
    ) -> None:
        connection = connect_database(self._config.db_path)
        try:
            fail_game_assignment(
                connection,
                assignment.assignment.assignment_id,
                assignment.assignment.assignment_key,
                str(AssignmentPreparationFailed(failure)),
            )
            record_worker_failure(
                connection,
                worker=worker,
                assignment_id=assignment.assignment.assignment_id,
                game_id=assignment.assignment.game_id,
                engine_id=failure.engine_id,
                engine_name=failure.engine_name,
                stage=failure.stage,
                error=failure.error,
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
            "worker.engine_failure",
            {
                "worker_id": worker.id,
                "machine_id": worker.machine_id,
                "assignment_id": assignment.assignment.assignment_id,
                "game_id": assignment.assignment.game_id,
                "engine_id": failure.engine_id,
                "stage": failure.stage,
            },
        )

    def _record_runtime_failure(
        self,
        worker: WorkerRecord,
        assignment,
        failure: AssignmentFailed,
    ) -> None:
        connection = connect_database(self._config.db_path)
        try:
            record_worker_failure(
                connection,
                worker=worker,
                assignment_id=assignment.assignment.assignment_id,
                game_id=assignment.assignment.game_id,
                engine_id=failure.engine_id,
                engine_name=failure.engine_name,
                stage=failure.stage,
                error=failure.error,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        publish_workers_changed(
            "worker.engine_failure",
            {
                "worker_id": worker.id,
                "machine_id": worker.machine_id,
                "assignment_id": assignment.assignment.assignment_id,
                "game_id": assignment.assignment.game_id,
                "engine_id": failure.engine_id,
                "stage": failure.stage,
            },
        )


def _worker_capability_key(worker: WorkerRecord) -> tuple:
    hardware = worker.hw.model_dump_json() if worker.hw is not None else ""
    return (
        worker.assigned_threads,
        worker.assigned_hash_mb,
        hardware,
    )


class WorkerEngineTransport:
    def __init__(
        self,
        websocket: WebSocketServerProtocol,
        assignment,
        *,
        failure_handler: Callable[[AssignmentFailed], None],
    ):
        self._websocket = websocket
        self._assignment = assignment
        self._loop = asyncio.get_running_loop()
        self._command_lock = asyncio.Lock()
        self._closed = threading.Event()
        self._pending: set[Future] = set()
        self._pending_lock = threading.Lock()
        self._failure_handler = failure_handler
        self._failure_reported = False

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

            if envelope.type == "assignment_failed":
                failure = _validate_worker_payload(AssignmentFailed, envelope.data)
                if not failure.matches_assignment(assignment):
                    raise ProtocolValidationError("engine failure assignment mismatch")
                if failure.engine_id != engine_id:
                    raise ProtocolValidationError("engine failure engine mismatch")
                if not self._failure_reported:
                    self._failure_reported = True
                    self._failure_handler(failure)
                raise RuntimeError(
                    f"{failure.engine_name} {failure.stage} failed: {failure.error}"
                )

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


def _hello_label(
    hello: WorkerTokenHello | WorkerSessionHello | WorkerPoolSlotHello,
) -> str:
    if isinstance(hello, WorkerTokenHello):
        return hello.label_hint or "token worker"

    if isinstance(hello, WorkerPoolSlotHello):
        return "pool worker"
    return "session worker"


def _worker_label(
    worker: WorkerRecord,
    hello: WorkerTokenHello | WorkerSessionHello | WorkerPoolSlotHello,
) -> str:
    if worker.label:
        return worker.label

    return _hello_label(hello)


def _close_reason(error: Exception) -> str:
    reason = str(error)
    if len(reason) <= 120:
        return reason

    return f"{reason[:117]}..."
