from __future__ import annotations

import asyncio
import logging
import os
import platform
from dataclasses import dataclass
from typing import Any

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
    encode_message,
    make_message,
)
from cope.core.stream import clamp_uci_info_line

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
    LOG.info(
        "connecting to runner url=%s app_commit=%s",
        config.server_url,
        config.app_commit,
    )
    try:
        async with connect(config.server_url) as websocket:
            await _send_message(websocket, "hello", _build_hello(config))
            welcome = await _recv_message(websocket, "welcome", WorkerWelcome)
            LOG.info(
                "accepted by runner worker_id=%s session=%s",
                welcome.worker_id,
                _redact_secret(welcome.session_id),
            )
            while True:
                envelope = await _recv_envelope(websocket)
                if envelope.type != "assignment":
                    raise ProtocolValidationError(f"unexpected runner message: {envelope.type}")
                assignment = WorkerGameAssignment.model_validate(envelope.data)
                await _serve_assignment(websocket, assignment)
    except ConnectionClosed as error:
        _log_connection_closed(error)
    except Exception:
        LOG.exception("worker client failed")
        raise


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
            envelope = await _recv_envelope(websocket)
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
            LOG.info(
                "engine command received assignment_id=%s game_id=%s engine_id=%s command=%s",
                command.assignment_id,
                command.game_id,
                command.engine_id,
                command.command,
            )

            engine = engines.get(command.engine_id)
            if engine is None:
                raise ProtocolValidationError(f"assignment missing engine {command.engine_id}")

            loop = asyncio.get_running_loop()

            def publish_info(line: str) -> None:
                line = clamp_uci_info_line(line)
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
            LOG.info(
                "engine command completed assignment_id=%s game_id=%s engine_id=%s command=%s lines=%s%s",
                command.assignment_id,
                command.game_id,
                command.engine_id,
                command.command,
                len(result_lines),
                _line_sample(result_lines),
            )
            await _send_message(websocket, "engine_command_result", result)
    except Exception:
        LOG.exception(
            "assignment failed assignment_id=%s game_id=%s",
            assignment.assignment.assignment_id,
            assignment.assignment.game_id,
        )
        raise
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
    log = LOG.debug if message_type == "engine_info" else LOG.info
    log(
        "sending runner message type=%s %s",
        message_type,
        _message_log_context(message_type, data),
    )
    await websocket.send(encode_message(make_message(message_type, data)))


async def _recv_envelope(websocket):
    raw_message = await websocket.recv()
    envelope = decode_envelope(raw_message)
    log = LOG.debug if envelope.type == "engine_command" else LOG.info
    log(
        "received runner message type=%s %s",
        envelope.type,
        _message_log_context(envelope.type, envelope.data),
    )
    return envelope


async def _recv_message(websocket, message_type: str, data_type):
    envelope = await _recv_envelope(websocket)
    if envelope.type != message_type:
        raise ProtocolValidationError(
            f"expected {message_type} message, got {envelope.type}"
        )
    return data_type.model_validate(envelope.data)


def _message_log_context(message_type: str, data: Any) -> str:
    payload = _model_data(data)
    if message_type == "hello":
        auth = "token" if payload.get("token") else "session"
        hw = payload.get("hw") or {}
        return (
            f"auth={auth} app_commit={payload.get('app_commit')} "
            f"label_hint={payload.get('label_hint', '')!r} "
            f"active_assignments={len(payload.get('active_assignment_ids') or [])} "
            f"cpu={hw.get('cpu_model')} cores={hw.get('physical_cores')}P/{hw.get('logical_cores')}T "
            f"ram={hw.get('ram_gb')}GB os={hw.get('os')}"
        )
    if message_type == "welcome":
        return (
            f"worker_id={payload.get('worker_id')} "
            f"session={_redact_secret(payload.get('session_id'))} "
            f"heartbeat_interval_ms={payload.get('heartbeat_interval_ms')}"
        )
    if message_type == "assignment":
        assignment = payload.get("assignment") or {}
        engines = payload.get("engines") or {}
        engine_names = ", ".join(
            str(engine.get("name", engine_id))
            for engine_id, engine in engines.items()
            if isinstance(engine, dict)
        )
        return (
            f"assignment_id={assignment.get('assignment_id')} "
            f"game_id={assignment.get('game_id')} "
            f"tournament={payload.get('tournament_name')} "
            f"round={payload.get('round')} max_plies={payload.get('max_plies')} "
            f"engines={engine_names}"
        )
    if message_type == "assignment_complete":
        return _assignment_context(payload)
    if message_type == "engine_command":
        return (
            f"{_assignment_context(payload)} "
            f"engine_id={payload.get('engine_id')} command={payload.get('command')}"
        )
    if message_type in {"engine_info", "engine_command_result"}:
        lines = payload.get("lines") or []
        return (
            f"{_assignment_context(payload)} "
            f"engine_id={payload.get('engine_id')} lines={len(lines)}{_line_sample(lines)}"
        )
    return f"keys={','.join(sorted(payload))}"


def _model_data(data: Any) -> dict[str, Any]:
    if hasattr(data, "model_dump"):
        return data.model_dump(mode="json")
    if isinstance(data, dict):
        return data
    return {}


def _assignment_context(payload: dict[str, Any]) -> str:
    return (
        f"assignment_id={payload.get('assignment_id')} "
        f"game_id={payload.get('game_id')}"
    )


def _line_sample(lines: list[str]) -> str:
    if not lines:
        return ""
    line = lines[-1]
    if len(line) > 200:
        line = f"{line[:197]}..."
    return f" last_line={line!r}"


def _redact_secret(value: Any) -> str:
    text = "" if value is None else str(value)
    if not text:
        return "<empty>"
    if len(text) <= 8:
        return "<redacted>"
    return f"{text[:4]}...{text[-4:]}"


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
