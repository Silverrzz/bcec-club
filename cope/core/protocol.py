from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from .models import Envelope


class ProtocolError(ValueError):
    close_code = 4000


class ProtocolValidationError(ProtocolError):
    close_code = 4000


def make_message(
    message_type: str,
    data: BaseModel | Mapping[str, Any] | None = None,
    *,
    seq: int = 0,
) -> Envelope:
    if isinstance(data, BaseModel):
        payload = data.model_dump(mode="json")
    else:
        payload = dict(data or {})

    return Envelope(
        type=message_type,
        seq=seq,
        t_mono_ms=time.monotonic_ns() // 1_000_000,
        data=payload,
    )


def encode_message(message: Envelope) -> str:
    return message.model_dump_json()


def decode_message(
    payload: str | bytes | bytearray,
    message_type: str,
    data_type: Any,
) -> Any:
    envelope = _decode_envelope(payload)
    if envelope.type != message_type:
        raise ProtocolValidationError(
            f"expected {message_type} message, got {envelope.type}"
        )

    try:
        return TypeAdapter(data_type).validate_python(envelope.data)
    except ValidationError as error:
        raise ProtocolValidationError(str(error)) from error


def _decode_envelope(payload: str | bytes | bytearray) -> Envelope:
    try:
        return Envelope.model_validate_json(payload)
    except ValidationError as error:
        raise ProtocolValidationError(str(error)) from error
    except ValueError as error:
        raise ProtocolValidationError(str(error)) from error
