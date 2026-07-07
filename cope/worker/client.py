from __future__ import annotations

import asyncio
import logging
import os
import platform
from dataclasses import dataclass

from websockets.client import connect
from websockets.exceptions import ConnectionClosed

from cope.core.models import (
    AssignmentComplete,
    BenchInfo,
    EngineCommand,
    EngineCommandResult,
    EngineInfo,
    HardwareInfo,
    WorkerGameAssignment,
    WorkerSessionHello,
    WorkerTokenHello,
    WorkerWelcome,
)
from cope.core.protocol import (
    ProtocolValidationError,
    decode_envelope,
    decode_message,
    encode_message,
    make_message,
)

from .uci_engine import UciEngineProcess


LOG = logging.getLogger("cope.worker")


@dataclass(frozen=True)
class WorkerClientConfig:
    server_url: str
    app_commit: str
    token: str | None = None
    session_id: str | None = None
    label_hint: str = ""


async def run_worker_client(config: WorkerClientConfig) -> None:
    hello = _build_hello(config)
    message = make_message(
        "hello",
        hello,
    )

    LOG.info(
        "connecting to runner url=%s app_commit=%s",
        config.server_url,
        config.app_commit,
    )
    try:
        async with connect(config.server_url) as websocket:
            await websocket.send(encode_message(message))
            welcome = decode_message(await websocket.recv(), "welcome", WorkerWelcome)
            LOG.info(
                "accepted by runner worker_id=%s session=%s",
                welcome.worker_id,
                welcome.session_id,
            )
            while True:
                envelope = decode_envelope(await websocket.recv())
                if envelope.type != "assignment":
                    raise ProtocolValidationError(f"unexpected runner message: {envelope.type}")
                assignment = WorkerGameAssignment.model_validate(envelope.data)
                await _serve_assignment(websocket, assignment)
    except ConnectionClosed as error:
        _log_connection_closed(error)


def _build_hello(config: WorkerClientConfig) -> WorkerTokenHello | WorkerSessionHello:
    if (config.token is None) == (config.session_id is None):
        raise ValueError("worker client needs exactly one of token or session_id")

    hw = _detect_hardware()

    if config.token is not None:
        return WorkerTokenHello(
            token=config.token,
            label_hint=config.label_hint,
            hw=hw,
            app_commit=config.app_commit,
        )

    return WorkerSessionHello(
        session_id=config.session_id or "",
        hw=hw,
        app_commit=config.app_commit,
    )


async def _serve_assignment(websocket, assignment: WorkerGameAssignment) -> None:
    engines = {
        engine_id: UciEngineProcess(engine)
        for engine_id, engine in assignment.engines.items()
    }
    engine_names = ", ".join(engine.name for engine in assignment.engines.values())
    LOG.info(
        "assignment received assignment_id=%s game_id=%s tournament=%s round=%s engines=%s",
        assignment.assignment.assignment_id,
        assignment.assignment.game_id,
        assignment.tournament_name,
        assignment.round,
        engine_names,
    )
    try:
        commands_handled = 0
        while True:
            envelope = decode_envelope(await websocket.recv())
            if envelope.type == "assignment_complete":
                complete = AssignmentComplete.model_validate(envelope.data)
                _validate_assignment_message(complete, assignment, "assignment_complete")
                LOG.info(
                    "assignment complete assignment_id=%s game_id=%s commands=%s",
                    assignment.assignment.assignment_id,
                    assignment.assignment.game_id,
                    commands_handled,
                )
                return

            if envelope.type != "engine_command":
                raise ProtocolValidationError(f"unexpected runner message: {envelope.type}")

            command = EngineCommand.model_validate(envelope.data)
            _validate_assignment_message(command, assignment, "engine_command")

            engine = engines.get(command.engine_id)
            if engine is None:
                raise ProtocolValidationError(f"assignment missing engine {command.engine_id}")

            loop = asyncio.get_running_loop()

            def publish_info(line: str) -> None:
                info = EngineInfo(
                    **command.model_dump(exclude={"command"}),
                    lines=[line],
                )
                future = asyncio.run_coroutine_threadsafe(
                    _send_message(websocket, "engine_info", info),
                    loop,
                )
                future.result()

            line_callback = publish_info if command.command.startswith("go") else None
            result_lines = await asyncio.to_thread(
                engine.handle_command,
                command.command,
                line_callback,
            )

            result = EngineCommandResult(
                **command.model_dump(exclude={"command"}),
                lines=result_lines,
            )
            commands_handled += 1
            await _send_message(websocket, "engine_command_result", result)
    finally:
        for engine in engines.values():
            engine.close()
        LOG.info(
            "assignment engines closed assignment_id=%s game_id=%s",
            assignment.assignment.assignment_id,
            assignment.assignment.game_id,
        )


def _validate_assignment_message(
    message: AssignmentComplete | EngineCommand,
    assignment: WorkerGameAssignment,
    label: str,
) -> None:
    if not message.matches_assignment(assignment.assignment):
        raise ProtocolValidationError(f"{label} assignment mismatch")


async def _send_message(websocket, message_type: str, data) -> None:
    await websocket.send(encode_message(make_message(message_type, data)))


def _detect_hardware() -> HardwareInfo:
    logical_cores = os.cpu_count() or 1
    physical_cores = logical_cores
    ram_gb = 1

    try:
        import psutil

        physical_cores = psutil.cpu_count(logical=False) or logical_cores
        logical_cores = psutil.cpu_count(logical=True) or logical_cores
        ram_gb = max(1, round(psutil.virtual_memory().total / (1024**3)))
    except ImportError:
        pass

    hw = HardwareInfo(
        cpu_model=platform.processor() or platform.machine() or "unknown",
        physical_cores=physical_cores,
        logical_cores=logical_cores,
        ram_gb=ram_gb,
        gpu=None,
        os=f"{platform.system()} {platform.release()}".strip(),
        python=platform.python_version(),
        bench=BenchInfo(),
    )
    LOG.info(
        "detected hardware cpu=%s cores=%s ram=%s os=%s",
        hw.cpu_model,
        f"{hw.physical_cores}P/{hw.logical_cores}T",
        f"{hw.ram_gb}GB",
        hw.os,
    )
    return hw


def _log_connection_closed(error: ConnectionClosed) -> None:
    reason = error.reason or str(error) or error.__class__.__name__
    if error.code == 1000:
        LOG.info("runner connection closed code=%s reason=%s", error.code, reason)
        return

    LOG.warning("runner connection lost code=%s reason=%s", error.code, reason)
