from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import platform
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from websockets.client import connect
from websockets.exceptions import ConnectionClosed

from cope.core.models import (
    AssignmentComplete,
    AssignmentFailed,
    AssignmentReady,
    BenchInfo,
    EngineCommand,
    EngineCommandResult,
    EngineInfo,
    HardwareInfo,
    WorkerGameAssignment,
    WorkerPoolSlotHello,
    WorkerSessionHello,
    WorkerTokenHello,
    WorkerWelcome,
    WorkerResources,
)
from cope.core.protocol import (
    ProtocolValidationError,
    decode_envelope,
    encode_message,
    make_message,
)
from cope.core.stream import clamp_uci_info_line

from .uci_engine import EnginePreparationError, UciEngineProcess


LOG = logging.getLogger("cope.worker")
RECONNECT_INITIAL_DELAY_S = 1.0
RECONNECT_MAX_DELAY_S = 30.0


@dataclass(frozen=True)
class WorkerClientConfig:
    server_url: str
    app_version: str
    token: str | None = None
    session_id: str | None = None
    pool_slot_token: str | None = None
    label_hint: str = ""
    threads: int = 1
    hash_mb: int = 32
    machine_id: str | None = None

    @property
    def resources(self) -> WorkerResources:
        return WorkerResources(threads=self.threads, hash_mb=self.hash_mb)


async def run_worker_client(config: WorkerClientConfig) -> None:
    state = _WorkerConnectionState(session_id=config.session_id)
    reconnect_delay_s = RECONNECT_INITIAL_DELAY_S
    while True:
        state.connected = False
        try:
            await _run_worker_connection(config, state)
        except ConnectionClosed as error:
            _log_connection_closed(error)
        except (OSError, asyncio.TimeoutError) as error:
            LOG.warning("runner connection failed: %s", error)
        except Exception:
            LOG.exception("worker client failed")
            raise

        if state.connected:
            reconnect_delay_s = RECONNECT_INITIAL_DELAY_S
        LOG.info("reconnecting to runner in %.1fs", reconnect_delay_s)
        await asyncio.sleep(reconnect_delay_s)
        reconnect_delay_s = min(reconnect_delay_s * 2, RECONNECT_MAX_DELAY_S)


@dataclass
class _WorkerConnectionState:
    session_id: str | None
    connected: bool = False


async def _run_worker_connection(
    config: WorkerClientConfig,
    state: _WorkerConnectionState,
) -> None:
    connection_config = (
        replace(config, token=None, session_id=state.session_id)
        if state.session_id is not None and config.pool_slot_token is None
        else config
    )
    LOG.info(
        "connecting to runner url=%s app_version=%s",
        connection_config.server_url,
        connection_config.app_version,
    )
    async with connect(connection_config.server_url) as websocket:
        await _send_message(websocket, "hello", _build_hello(connection_config))
        welcome = await _recv_message(websocket, "welcome", WorkerWelcome)
        if welcome.resources != connection_config.resources:
            raise ProtocolValidationError(
                "runner accepted a different resource reservation than the worker requested"
            )
        state.session_id = welcome.session_id
        state.connected = True
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
            if not connection_config.resources.can_run(assignment.required_resources):
                raise ProtocolValidationError(
                    "assignment exceeds worker reservation: "
                    f"requires {assignment.required_resources.threads} threads and "
                    f"{assignment.required_resources.hash_mb}MB hash, worker has "
                    f"{connection_config.resources.threads} threads and "
                    f"{connection_config.resources.hash_mb}MB hash"
                )
            await _serve_assignment(
                websocket,
                assignment,
                server_url=connection_config.server_url,
                credential=welcome.session_id,
            )


def _build_hello(
    config: WorkerClientConfig,
) -> WorkerTokenHello | WorkerSessionHello | WorkerPoolSlotHello:
    credential_count = sum(
        value is not None
        for value in (config.token, config.session_id, config.pool_slot_token)
    )
    if credential_count != 1:
        raise ValueError(
            "worker client needs exactly one of token, session_id, or pool_slot_token"
        )

    hw = _detect_hardware()
    machine_id = config.machine_id or _detect_machine_id()

    if config.token is not None:
        return WorkerTokenHello(
            token=config.token,
            label_hint=config.label_hint,
            hw=hw,
            app_version=config.app_version,
            machine_id=machine_id,
            resources=config.resources,
        )

    if config.pool_slot_token is not None:
        return WorkerPoolSlotHello(
            slot_token=config.pool_slot_token,
            hw=hw,
            app_version=config.app_version,
            machine_id=machine_id,
            resources=config.resources,
        )

    return WorkerSessionHello(
        session_id=config.session_id or "",
        hw=hw,
        app_version=config.app_version,
        machine_id=machine_id,
        resources=config.resources,
    )


async def _serve_assignment(
    websocket,
    assignment: WorkerGameAssignment,
    *,
    server_url: str,
    credential: str,
) -> None:
    engines = {
        engine_id: UciEngineProcess(engine, server_url=server_url, credential=credential)
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
        await asyncio.gather(
            *(asyncio.to_thread(engine.prepare) for engine in engines.values())
        )
        ready = AssignmentReady(
            **assignment.assignment.message_fields(),
            prepared_engine_ids=sorted(engines),
        )
        await _send_message(websocket, "assignment_ready", ready)
        LOG.info(
            "assignment prepared assignment_id=%s game_id=%s engines=%s",
            assignment.assignment.assignment_id,
            assignment.assignment.game_id,
            ready.prepared_engine_ids,
        )
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
            try:
                result_lines = await asyncio.to_thread(
                    engine.handle_command,
                    command.command,
                    line_callback,
                )
            except Exception as error:
                failure = AssignmentFailed(
                    **assignment.assignment.message_fields(),
                    engine_id=command.engine_id,
                    engine_name=assignment.engines[command.engine_id].name,
                    stage="runtime" if engine.process_started else "start",
                    error=(str(error).strip() or error.__class__.__name__)[-8000:],
                )
                await _send_message(websocket, "assignment_failed", failure)
                LOG.error(
                    "engine command failed assignment_id=%s game_id=%s engine_id=%s "
                    "engine=%s stage=%s error=%s",
                    command.assignment_id,
                    command.game_id,
                    failure.engine_id,
                    failure.engine_name,
                    failure.stage,
                    failure.error,
                )
                await _wait_for_failed_assignment_complete(websocket, assignment, failure)
                return

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
    except EnginePreparationError as error:
        failure = AssignmentFailed(
            **assignment.assignment.message_fields(),
            engine_id=error.engine_id,
            engine_name=error.engine_name,
            stage=error.stage,
            error=error.detail[-8000:],
        )
        await _send_message(websocket, "assignment_failed", failure)
        LOG.error(
            "assignment preparation failed assignment_id=%s game_id=%s engine_id=%s "
            "engine=%s stage=%s error=%s",
            assignment.assignment.assignment_id,
            assignment.assignment.game_id,
            error.engine_id,
            error.engine_name,
            error.stage,
            error.detail,
        )
        return
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


async def _wait_for_failed_assignment_complete(
    websocket,
    assignment: WorkerGameAssignment,
    failure: AssignmentFailed,
) -> None:
    while True:
        envelope = await _recv_envelope(websocket)
        if envelope.type == "assignment_complete":
            complete = AssignmentComplete.model_validate(envelope.data)
            _validate_assignment_message(complete, assignment, "assignment_complete")
            return
        if envelope.type == "engine_command":
            command = EngineCommand.model_validate(envelope.data)
            _validate_assignment_message(command, assignment, "engine_command")
            await _send_message(websocket, "assignment_failed", failure)
            continue
        raise ProtocolValidationError(
            f"unexpected runner message after engine failure: {envelope.type}"
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
        if payload.get("token"):
            auth = "token"
        elif payload.get("slot_token"):
            auth = "pool_slot"
        else:
            auth = "session"
        hw = payload.get("hw") or {}
        return (
            f"auth={auth} app_version={payload.get('app_version')} "
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
    if message_type in {"assignment_ready", "assignment_complete"}:
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
    ram_mb = 1024

    try:
        import psutil

        physical_cores = psutil.cpu_count(logical=False) or logical_cores
        logical_cores = psutil.cpu_count(logical=True) or logical_cores
        total_ram = psutil.virtual_memory().total
        ram_mb = max(1, total_ram // (1024**2))
        ram_gb = max(1, round(total_ram / (1024**3)))
    except ImportError:
        pass

    hw = HardwareInfo(
        cpu_model=_detect_cpu_model(),
        physical_cores=physical_cores,
        logical_cores=logical_cores,
        ram_gb=ram_gb,
        ram_mb=ram_mb,
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


def _detect_machine_id() -> str:
    configured = os.environ.get("COPE_MACHINE_ID", "").strip()
    if configured:
        return configured

    fingerprint = "|".join(
        (
            platform.node().strip().lower(),
            f"{uuid.getnode():012x}",
            platform.system().strip().lower(),
            platform.machine().strip().lower(),
        )
    )
    return hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()


def _detect_cpu_model() -> str:
    processor = platform.processor().strip()
    if processor and processor.lower() not in {"unknown", platform.machine().lower()}:
        return processor

    processor_identifier = os.environ.get("PROCESSOR_IDENTIFIER", "").strip()
    if processor_identifier:
        return processor_identifier

    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        try:
            for line in cpuinfo.read_text(encoding="utf-8", errors="replace").splitlines():
                key, separator, value = line.partition(":")
                if separator and key.strip().lower() in {"model name", "hardware"}:
                    model = value.strip()
                    if model:
                        return model
        except OSError:
            pass

    return platform.machine() or "unknown"


def _log_connection_closed(error: ConnectionClosed) -> None:
    reason = error.reason or str(error) or error.__class__.__name__
    if error.code == 1000:
        LOG.info("runner connection closed code=%s reason=%s", error.code, reason)
        return

    LOG.warning("runner connection lost code=%s reason=%s", error.code, reason)
