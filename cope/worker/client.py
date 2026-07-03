from __future__ import annotations

import os
import platform
from dataclasses import dataclass

from websockets.client import connect

from cope.core.models import BenchInfo, HardwareInfo, WorkerSessionHello, WorkerTokenHello, WorkerWelcome
from cope.core.protocol import (
    decode_message,
    encode_message,
    make_message,
)


@dataclass(frozen=True)
class WorkerClientConfig:
    server_url: str
    app_commit: str
    token: str | None = None
    session_id: str | None = None
    label_hint: str = ""


async def run_worker_client(config: WorkerClientConfig) -> WorkerWelcome:
    hello = _build_hello(config)
    message = make_message(
        "hello",
        hello,
    )

    async with connect(config.server_url) as websocket:
        await websocket.send(encode_message(message))
        welcome = decode_message(await websocket.recv(), "welcome", WorkerWelcome)
        print(f"worker accepted as id={welcome.worker_id} session={welcome.session_id}")
        return welcome


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

    return HardwareInfo(
        cpu_model=platform.processor() or platform.machine() or "unknown",
        physical_cores=physical_cores,
        logical_cores=logical_cores,
        ram_gb=ram_gb,
        gpu=None,
        os=f"{platform.system()} {platform.release()}".strip(),
        python=platform.python_version(),
        bench=BenchInfo(),
    )
