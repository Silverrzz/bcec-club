from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, ValidationError

from .models import StrictModel


STREAM_PROTOCOL_VERSION = 1
MAX_STREAM_MESSAGE_BYTES = 64 * 1024
MAX_UCI_INFO_LINE = 4096
WORKER_COMMAND_ELAPSED_PREFIX = "info string cope-worker-command-elapsed-ms "


class StreamProtocolError(ValueError):
    close_code = 4000


class StreamEnvelope(StrictModel):
    v: Literal[1] = STREAM_PROTOCOL_VERSION
    id: str = Field(default="", max_length=160)
    topic: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9_.:-]+$")
    type: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9_.:-]+$")
    seq: int = Field(ge=0)
    source: str = Field(min_length=1, max_length=80)
    sent_at: str = Field(min_length=1, max_length=40)
    data: dict[str, Any] = Field(default_factory=dict)


def make_stream_event(
    topic: str,
    event_type: str,
    data: BaseModel | Mapping[str, Any] | None = None,
    *,
    source: str,
    seq: int = 0,
    event_id: str = "",
) -> StreamEnvelope:
    if isinstance(data, BaseModel):
        payload = data.model_dump(mode="json")
    else:
        payload = dict(data or {})
    return StreamEnvelope(
        id=event_id,
        topic=topic,
        type=event_type,
        seq=seq,
        source=source,
        sent_at=datetime.now(UTC).isoformat(),
        data=payload,
    )


def encode_stream_event(event: StreamEnvelope) -> str:
    payload = event.model_dump_json()
    if len(payload.encode("utf-8")) > MAX_STREAM_MESSAGE_BYTES:
        raise StreamProtocolError("stream message exceeds maximum size")
    return payload


def decode_stream_event(payload: str | bytes | bytearray) -> StreamEnvelope:
    if len(payload) > MAX_STREAM_MESSAGE_BYTES:
        raise StreamProtocolError("stream message exceeds maximum size")
    try:
        return StreamEnvelope.model_validate_json(payload)
    except ValidationError as error:
        raise StreamProtocolError(str(error)) from error
    except ValueError as error:
        raise StreamProtocolError(str(error)) from error


def sse_stream_event(event: StreamEnvelope) -> str:
    payload = json.dumps(event.model_dump(mode="json"), separators=(",", ":"))
    return f"id: {event.id}\nevent: {event.type}\ndata: {payload}\n\n"


def clamp_uci_info_line(line: str) -> str:
    if len(line) <= MAX_UCI_INFO_LINE:
        return line
    return line[:MAX_UCI_INFO_LINE]


def worker_command_elapsed_line(elapsed_ms: int) -> str:
    return f"{WORKER_COMMAND_ELAPSED_PREFIX}{max(elapsed_ms, 0)}"


def parse_worker_command_elapsed(line: str) -> int | None:
    if not line.startswith(WORKER_COMMAND_ELAPSED_PREFIX):
        return None
    value = line[len(WORKER_COMMAND_ELAPSED_PREFIX) :]
    try:
        elapsed_ms = int(value)
    except ValueError:
        return None
    return elapsed_ms if elapsed_ms >= 0 else None
