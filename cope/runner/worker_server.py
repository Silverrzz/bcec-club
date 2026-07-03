from __future__ import annotations

import asyncio
from dataclasses import dataclass

from websockets.exceptions import ConnectionClosed
from websockets.server import WebSocketServerProtocol, serve

from cope.core.models import WorkerSessionHello, WorkerTokenHello, WorkerWelcome
from cope.core.protocol import (
    ProtocolError,
    ProtocolValidationError,
    decode_message,
    encode_message,
    make_message,
)


@dataclass(frozen=True)
class WorkerServerConfig:
    host: str = "127.0.0.1"
    port: int = 8702
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
        self._next_worker_id = 1

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

            worker_id = self._next_worker_id
            self._next_worker_id += 1
            session_id = _session_id_for(worker_id)

            welcome = WorkerWelcome(
                worker_id=worker_id,
                session_id=session_id,
                heartbeat_interval_ms=self._config.heartbeat_interval_ms,
            )
            response = make_message(
                "welcome",
                welcome,
            )
            await websocket.send(encode_message(response))
            print(f"worker {worker_id} accepted: {_hello_label(hello)}")
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


def _text_payload(payload: str | bytes | bytearray) -> str | bytes | bytearray:
    if isinstance(payload, (str, bytes, bytearray)):
        return payload

    raise ProtocolValidationError("websocket payload must be text or bytes")


def _session_id_for(worker_id: int) -> str:
    return f"dev-session-{worker_id}"


def _hello_label(hello: WorkerTokenHello | WorkerSessionHello) -> str:
    if isinstance(hello, WorkerTokenHello):
        return hello.label_hint or "token worker"

    return "session worker"


def _close_reason(error: Exception) -> str:
    reason = str(error)
    if len(reason) <= 120:
        return reason

    return f"{reason[:117]}..."
