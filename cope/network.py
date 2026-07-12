from __future__ import annotations

import os
from pathlib import Path


DEFAULT_WEB_HOST = "127.0.0.1"
DEFAULT_WEB_PORT = 8701
DEFAULT_WEB_EVENT_TIMEOUT_S = 0.2
DEFAULT_WEB_STREAM_PATH = "/internal/stream"
DEFAULT_WORKER_HOST = "127.0.0.1"
DEFAULT_WORKER_PORT = 8702
DEFAULT_WORKER_PATH = "/worker"
ADMIN_TOKEN_ENV = "COPE_ADMIN_TOKEN"
LOCAL_EVENT_PUBLISHERS = {"127.0.0.1", "::1"}
WILDCARD_HOSTS = {"", "0.0.0.0", "::"}


def default_web_host() -> str:
    return os.environ.get("COPE_WEB_HOST", DEFAULT_WEB_HOST)


def default_web_port() -> int:
    return _env_int("COPE_WEB_PORT", DEFAULT_WEB_PORT)


def default_worker_host() -> str:
    return os.environ.get(
        "COPE_WORKER_BIND_HOST",
        os.environ.get("COPE_WORKER_HOST", DEFAULT_WORKER_HOST),
    )


def default_worker_port() -> int:
    return _env_int("COPE_WORKER_PORT", DEFAULT_WORKER_PORT)


def default_worker_server_url() -> str:
    explicit = os.environ.get("COPE_WORKER_SERVER_URL")
    if explicit:
        return explicit
    public_host = os.environ.get("COPE_WORKER_PUBLIC_HOST") or _public_host(
        default_worker_host(),
        DEFAULT_WORKER_HOST,
    )
    return f"ws://{_url_host(public_host)}:{default_worker_port()}{DEFAULT_WORKER_PATH}"


def default_web_stream_url() -> str:
    explicit = os.environ.get("COPE_WEB_STREAM_URL")
    if explicit:
        return _websocket_url(explicit)
    public_host = os.environ.get("COPE_WEB_PUBLIC_HOST") or _public_host(
        default_web_host(),
        DEFAULT_WEB_HOST,
    )
    return f"ws://{_url_host(public_host)}:{default_web_port()}{DEFAULT_WEB_STREAM_PATH}"


def default_web_event_token() -> str | None:
    return _secret_env("COPE_WEB_EVENT_TOKEN")


def default_admin_token() -> str | None:
    return _secret_env(ADMIN_TOKEN_ENV)


def default_web_event_timeout_s() -> float:
    return _env_float("COPE_WEB_EVENT_TIMEOUT_S", DEFAULT_WEB_EVENT_TIMEOUT_S)


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number") from exc


def _secret_env(name: str) -> str | None:
    value = os.environ.get(name)
    file_name = os.environ.get(f"{name}_FILE")
    if value and file_name:
        raise ValueError(f"set only one of {name} or {name}_FILE")
    if file_name:
        try:
            value = Path(file_name).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"could not read {name}_FILE: {exc}") from exc
    return value or None


def _public_host(bind_host: str, fallback: str) -> str:
    if bind_host in WILDCARD_HOSTS:
        return fallback
    return bind_host


def _url_host(host: str) -> str:
    if ":" in host and not (host.startswith("[") and host.endswith("]")):
        return f"[{host}]"
    return host


def _websocket_url(url: str) -> str:
    if url.startswith("https://"):
        return "wss://" + url[len("https://") :]
    if url.startswith("http://"):
        return "ws://" + url[len("http://") :]
    return url
