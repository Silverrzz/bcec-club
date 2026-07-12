from __future__ import annotations

import asyncio
import getpass
import json
import logging
import os
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field
from websockets.client import connect

from cope.core.models import (
    WorkerPoolEnrollmentHello,
    WorkerPoolSlotCredential,
    WorkerPoolWelcome,
)
from cope.core.protocol import decode_message, encode_message, make_message

from .client import WorkerClientConfig, _detect_hardware, _detect_machine_id, run_worker_client


LOG = logging.getLogger("cope.worker_pool")
STATE_VERSION = 1
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


class WorkerPoolState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    version: Literal[1] = STATE_VERSION
    server_url: str
    app_commit: str
    pool_id: int = Field(gt=0)
    label: str
    machine_id: str
    slots: list[WorkerPoolSlotCredential] = Field(min_length=1)


@dataclass(frozen=True)
class WorkerPoolConfig:
    server_url: str
    app_commit: str
    state_file: Path
    enrollment_token_file: Path | None = None
    machine_id: str | None = None


async def run_worker_pool(config: WorkerPoolConfig) -> None:
    state_file = config.state_file.expanduser().resolve()
    _prepare_state_storage(state_file)
    if state_file.is_file():
        state = _read_state(state_file)
        if state.server_url != config.server_url:
            raise ValueError(
                "pool state belongs to a different worker server; use its original --server-url"
            )
        if state.app_commit != config.app_commit:
            raise ValueError(
                "pool state belongs to a different app commit; deploy matching worker code"
            )
    else:
        token = _read_enrollment_token(config.enrollment_token_file)
        state = await _enroll_pool(config, token)
        _write_state(state_file, state)
        LOG.info(
            "worker pool enrolled pool_id=%s slots=%s state=%s",
            state.pool_id,
            len(state.slots),
            state_file,
        )

    LOG.info(
        "starting worker pool pool_id=%s label=%s slots=%s",
        state.pool_id,
        state.label,
        len(state.slots),
    )
    await asyncio.gather(
        *(_run_slot(state, slot) for slot in state.slots),
    )


async def _enroll_pool(config: WorkerPoolConfig, token: str) -> WorkerPoolState:
    _require_secure_enrollment_url(config.server_url)
    machine_id = config.machine_id or _detect_machine_id()
    hello = WorkerPoolEnrollmentHello(
        enrollment_token=token,
        machine_id=machine_id,
        hw=_detect_hardware(),
        app_commit=config.app_commit,
    )
    async with connect(config.server_url) as websocket:
        await websocket.send(encode_message(make_message("hello", hello)))
        raw_message = await websocket.recv()
        welcome = decode_message(raw_message, "pool_welcome", WorkerPoolWelcome)
    if welcome.machine_id != machine_id:
        raise ValueError("worker server enrolled the pool for a different machine identity")
    return WorkerPoolState(
        server_url=config.server_url,
        app_commit=config.app_commit,
        pool_id=welcome.pool_id,
        label=welcome.label,
        machine_id=welcome.machine_id,
        slots=welcome.slots,
    )


async def _run_slot(
    state: WorkerPoolState,
    slot: WorkerPoolSlotCredential,
) -> None:
    while True:
        try:
            await run_worker_client(
                WorkerClientConfig(
                    server_url=state.server_url,
                    app_commit=state.app_commit,
                    pool_slot_token=slot.slot_token,
                    label_hint=slot.label,
                    threads=slot.resources.threads,
                    hash_mb=slot.resources.hash_mb,
                    machine_id=state.machine_id,
                )
            )
        except asyncio.CancelledError:
            raise
        except Exception as error:
            LOG.error(
                "pool slot stopped worker_id=%s reason=%s; retrying in 30s",
                slot.worker_id,
                error,
            )
            await asyncio.sleep(30)


def _read_enrollment_token(path: Path | None) -> str:
    if path is None:
        token = getpass.getpass("One-time worker pool enrollment token: ").strip()
    else:
        token = path.expanduser().read_text(encoding="utf-8").strip()
    if not token:
        raise ValueError("worker pool enrollment token is empty")
    return token


def _read_state(path: Path) -> WorkerPoolState:
    return WorkerPoolState.model_validate_json(path.read_text(encoding="utf-8"))


def _write_state(path: Path, state: WorkerPoolState) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _restrict_path(path.parent, directory=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(state.model_dump(mode="json"), indent=2) + "\n",
            encoding="utf-8",
        )
        _restrict_path(temporary, directory=False)
        os.replace(temporary, path)
        _restrict_path(path, directory=False)
    finally:
        if temporary.exists():
            temporary.unlink()


def _prepare_state_storage(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _restrict_path(path.parent, directory=True)
    probe = path.parent / f".credential-permission-check-{uuid.uuid4().hex}"
    try:
        probe.write_text("permission check\n", encoding="utf-8")
        _restrict_path(probe, directory=False)
    finally:
        if probe.exists():
            probe.unlink()


def _restrict_path(path: Path, *, directory: bool) -> None:
    os.chmod(path, 0o700 if directory else 0o600)
    if os.name != "nt":
        return
    user = getpass.getuser()
    domain = os.environ.get("USERDOMAIN", "").strip()
    principal = f"{domain}\\{user}" if domain else user
    permission = "(OI)(CI)F" if directory else "F"
    result = subprocess.run(
        [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"{principal}:{permission}",
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        raise PermissionError(
            f"could not restrict worker pool credential file permissions: {result.stderr.strip()}"
        )


def _require_secure_enrollment_url(server_url: str) -> None:
    parsed = urlsplit(server_url)
    if parsed.scheme == "wss":
        return
    if parsed.scheme == "ws" and (parsed.hostname or "").lower() in LOCAL_HOSTS:
        return
    raise ValueError("worker pool enrollment requires wss:// except on localhost")
