from __future__ import annotations

import asyncio
import contextlib
import logging
import queue
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from websockets.client import connect
from websockets.exceptions import ConnectionClosed

from cope.core.stream import (
    MAX_STREAM_MESSAGE_BYTES,
    StreamEnvelope,
    StreamProtocolError,
    decode_stream_event,
    encode_stream_event,
    make_stream_event,
)
from cope.network import (
    default_web_event_token,
    default_web_event_timeout_s,
    default_web_stream_url,
)


LOG = logging.getLogger("cope.runner.events")
PUBLISH_FAILURE_LOG_INTERVAL_S = 30.0
PUBLISHER_QUEUE_SIZE = 10000
_last_failure_log_at = 0.0
_last_failure_key: tuple[str, str] | None = None
_config_lock = threading.Lock()
_config: EventPublisherConfig | None = None
_publisher: StreamEventPublisher | None = None
_wake_handler: Callable[[StreamEnvelope], None] | None = None


@dataclass(frozen=True, slots=True)
class EventPublisherConfig:
    url: str
    token: str | None = None
    timeout_s: float = 0.2


def configure_event_publisher(
    *,
    url: str | None = None,
    token: str | None = None,
    timeout_s: float | None = None,
    wake_handler: Callable[[StreamEnvelope], None] | None = None,
) -> None:
    global _config, _publisher, _wake_handler
    with _config_lock:
        _config = EventPublisherConfig(
            url=url or default_web_stream_url(),
            token=token or default_web_event_token(),
            timeout_s=timeout_s if timeout_s is not None else default_web_event_timeout_s(),
        )
        if wake_handler is not None:
            _wake_handler = wake_handler
        if _publisher is None:
            _publisher = StreamEventPublisher()
            _publisher.start()


def set_runner_wake_handler(handler: Callable[[StreamEnvelope], None] | None) -> None:
    global _wake_handler
    with _config_lock:
        _wake_handler = handler


def start_event_publisher() -> None:
    _event_publisher()


def publish_tournament_event(tournament_id: int, live: dict | None = None) -> None:
    event_type = "tournament.live" if live is not None else "tournament.changed"
    data: dict[str, Any] = {"tournament_id": tournament_id}
    if live is not None:
        data["live"] = live
    publish_stream_event(f"tournament.{tournament_id}", event_type, data)


def publish_game_move(tournament_id: int, game_id: int, ply: int) -> None:
    publish_stream_event(
        f"tournament.{tournament_id}",
        "game.move",
        {"tournament_id": tournament_id, "game_id": game_id, "ply": ply},
    )


def publish_engine_info(tournament_id: int, payload: dict[str, Any]) -> None:
    publish_stream_event(f"tournament.{tournament_id}", "engine.info", payload)


def publish_clock_sync(tournament_id: int, payload: dict[str, Any]) -> None:
    publish_stream_event(f"tournament.{tournament_id}", "clock.sync", payload)


def publish_workers_changed(reason: str, payload: dict[str, Any] | None = None) -> None:
    data = {"reason": reason}
    if payload:
        data.update(payload)
    publish_stream_event("workers", "workers.changed", data)


def publish_stream_event(
    topic: str,
    event_type: str,
    data: dict[str, Any] | None = None,
) -> None:
    event = make_stream_event(topic, event_type, data, source="runner")
    _event_publisher().publish(event)


class StreamEventPublisher:
    def __init__(self) -> None:
        self._queue: queue.Queue[StreamEnvelope] = queue.Queue(maxsize=PUBLISHER_QUEUE_SIZE)
        self._started = False
        self._start_lock = threading.Lock()

    def start(self) -> None:
        with self._start_lock:
            if self._started:
                return
            self._started = True
            thread = threading.Thread(
                target=self._run_thread,
                name="cope-stream-publisher",
                daemon=True,
            )
            thread.start()

    def publish(self, event: StreamEnvelope) -> None:
        self.start()
        try:
            self._queue.put(event, timeout=1.0)
        except queue.Full:
            _log_publish_failure(_event_publisher_config(), RuntimeError("stream queue full"))

    def _run_thread(self) -> None:
        asyncio.run(self._run_forever())

    async def _run_forever(self) -> None:
        backoff_s = 0.25
        while True:
            config = _event_publisher_config()
            try:
                await self._run_connection(config)
                backoff_s = 0.25
            except Exception as error:
                _log_publish_failure(config, error)
                await asyncio.sleep(backoff_s)
                backoff_s = min(backoff_s * 2, 5.0)

    async def _run_connection(self, config: EventPublisherConfig) -> None:
        async with connect(
            config.url,
            open_timeout=config.timeout_s,
            close_timeout=1,
            max_size=MAX_STREAM_MESSAGE_BYTES,
        ) as websocket:
            await websocket.send(
                encode_stream_event(
                    make_stream_event(
                        "internal",
                        "stream.hello",
                        {"token": config.token or ""},
                        source="runner",
                    )
                )
            )
            _notify_wake(make_stream_event("internal", "stream.connected", source="web"))
            sender = asyncio.create_task(self._send_loop(websocket))
            receiver = asyncio.create_task(self._recv_loop(websocket))
            done, pending = await asyncio.wait(
                {sender, receiver},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                task.result()

    async def _send_loop(self, websocket) -> None:
        while True:
            event = await self._next_event()
            try:
                await websocket.send(encode_stream_event(event))
            except StreamProtocolError:
                LOG.warning(
                    "dropping oversized stream event topic=%s type=%s",
                    event.topic,
                    event.type,
                )
            except ConnectionClosed:
                with contextlib.suppress(queue.Full):
                    self._queue.put_nowait(event)
                raise

    async def _next_event(self) -> StreamEnvelope:
        while True:
            try:
                return self._queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.05)

    async def _recv_loop(self, websocket) -> None:
        while True:
            raw_message = await websocket.recv()
            event = decode_stream_event(raw_message)
            if event.type in {"runner.wake", "stream.ready"}:
                _notify_wake(event)


def _event_publisher() -> StreamEventPublisher:
    global _config, _publisher
    with _config_lock:
        if _config is None:
            _config = EventPublisherConfig(
                url=default_web_stream_url(),
                token=default_web_event_token(),
                timeout_s=default_web_event_timeout_s(),
            )
        if _publisher is None:
            _publisher = StreamEventPublisher()
            _publisher.start()
        return _publisher


def _event_publisher_config() -> EventPublisherConfig:
    with _config_lock:
        if _config is not None:
            return _config
    return EventPublisherConfig(
        url=default_web_stream_url(),
        token=default_web_event_token(),
        timeout_s=default_web_event_timeout_s(),
    )


def _notify_wake(event: StreamEnvelope) -> None:
    with _config_lock:
        handler = _wake_handler
    if handler is None:
        return
    try:
        handler(event)
    except Exception:
        LOG.exception("runner wake handler failed type=%s", event.type)


def _log_publish_failure(config: EventPublisherConfig, error: Exception) -> None:
    global _last_failure_log_at, _last_failure_key

    label = str(error) or error.__class__.__name__
    key = (config.url, label)
    now = time.monotonic()
    if key == _last_failure_key and now - _last_failure_log_at < PUBLISH_FAILURE_LOG_INTERVAL_S:
        return

    _last_failure_key = key
    _last_failure_log_at = now
    LOG.warning("stream publisher unavailable url=%s error=%s", config.url, label)
