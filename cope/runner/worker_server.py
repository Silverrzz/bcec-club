from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass
from pathlib import Path

from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol, serve

from cope.core.models import PROTOCOL_VERSION, WorkerSessionHello, WorkerTokenHello, WorkerWelcome
from cope.core.protocol import (
    ProtocolError,
    ProtocolValidationError,
    decode_message,
    encode_message,
    make_message,
)
from cope.db import (
    WorkerRecord,
    connect_database,
    get_worker_by_session_id,
    get_worker_by_token,
    initialize_database,
    upsert_worker_connection,
    worker_token_is_valid,
)


@dataclass(frozen=True)
class WorkerServerConfig:
    host: str = "127.0.0.1"
    port: int = 8702
    db_path: str | Path = "cope.db"
    expected_app_commit: str | None = None
    heartbeat_interval_ms: int = 5000


async def run_worker_server(config: WorkerServerConfig) -> None:
    server = WorkerHandshakeServer(config)
    async with serve(server.handle_connection, config.host, config.port):
        print(f"worker server listening on ws://{config.host}:{config.port}/worker")
        await asyncio.Future()


class WorkerHandshakeServer:
    def __init__(self, config: WorkerServerConfig):
        self._config = config

    async def handle_connection(
        self,
        websocket: WebSocketServerProtocol,
        path: str | None = None,
    ) -> None:
        try:
            if path is not None and path != "/worker":
                await websocket.close(code=4004, reason="unknown websocket path")
                return

            raw_message = await websocket.recv()
            hello = decode_message(
                _text_payload(raw_message),
                "hello",
                WorkerTokenHello | WorkerSessionHello,
            )
            self._validate_app_commit(hello)
            worker = self._authenticate_worker(hello)
            session_id = _new_session_id()
            label = _worker_label(worker, hello)
            self._record_connection(worker, label, session_id, hello)

            welcome = WorkerWelcome(
                worker_id=worker.id,
                session_id=session_id,
                heartbeat_interval_ms=self._config.heartbeat_interval_ms,
            )
            response = make_message(
                "welcome",
                welcome,
            )
            await websocket.send(encode_message(response))
            print(f"worker {worker.id} accepted: {label}")
            await websocket.wait_closed()
        except ProtocolError as error:
            await websocket.close(code=error.close_code, reason=_close_reason(error))
        except ConnectionClosed:
            return

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
    ) -> None:
        connection = connect_database(self._config.db_path)
        try:
            upsert_worker_connection(
                connection,
                worker_id=worker.id,
                label=label,
                session_id=session_id,
                app_commit=hello.app_commit,
                protocol_version=PROTOCOL_VERSION,
                hw=hello.hw,
            )
            connection.commit()
        finally:
            connection.close()


def _text_payload(payload: str | bytes | bytearray) -> str | bytes | bytearray:
    if isinstance(payload, (str, bytes, bytearray)):
        return payload

    raise ProtocolValidationError("websocket payload must be text or bytes")


def _new_session_id() -> str:
    return secrets.token_urlsafe(32)


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
