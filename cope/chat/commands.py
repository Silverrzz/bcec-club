from __future__ import annotations

import shlex
import sqlite3
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any


class ChatCommandError(ValueError):
    """A command could not be parsed or executed."""


class UnknownChatCommand(ChatCommandError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    name: str
    arguments: tuple[str, ...]
    source: str


@dataclass(frozen=True, slots=True)
class ChatCommandContext:
    connection: sqlite3.Connection
    tournament_id: int
    display_name: str


@dataclass(frozen=True, slots=True)
class ChatCommandResult:
    private_message: str | None = None
    broadcast_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


ChatCommandHandler = Callable[[ChatCommandContext, ParsedCommand], ChatCommandResult]


@dataclass(frozen=True, slots=True)
class _RegisteredCommand:
    name: str
    handler: ChatCommandHandler
    aliases: tuple[str, ...]


class CommandRegistry:
    """Owns command discovery and dispatch without coupling commands to web routes."""

    def __init__(self) -> None:
        self._commands: dict[str, _RegisteredCommand] = {}

    @property
    def commands(self):
        return MappingProxyType(self._commands)

    def register(
        self,
        name: str,
        handler: ChatCommandHandler,
        *,
        aliases: Iterable[str] = (),
    ) -> None:
        canonical = _normalize_command_name(name)
        normalized_aliases = tuple(_normalize_command_name(alias) for alias in aliases)
        keys = (canonical, *normalized_aliases)
        duplicate = next((key for key in keys if key in self._commands), None)
        if duplicate is not None:
            raise ValueError(f"chat command {duplicate!r} is already registered")
        command = _RegisteredCommand(canonical, handler, normalized_aliases)
        for key in keys:
            self._commands[key] = command

    def dispatch(
        self,
        context: ChatCommandContext,
        source: str,
    ) -> ChatCommandResult:
        parsed = parse_chat_command(source)
        if parsed is None:
            raise ChatCommandError("chat input is not a command")
        command = self._commands.get(parsed.name)
        if command is None:
            raise UnknownChatCommand(f"Unknown command: !{parsed.name}")
        return command.handler(context, parsed)


def parse_chat_command(source: str) -> ParsedCommand | None:
    stripped = source.strip()
    if not stripped.startswith("!"):
        return None
    command_source = stripped[1:].strip()
    if not command_source:
        raise ChatCommandError("Enter a command after !")
    try:
        tokens = shlex.split(command_source)
    except ValueError as error:
        raise ChatCommandError(f"Invalid command syntax: {error}") from error
    if not tokens:
        raise ChatCommandError("Enter a command after !")
    return ParsedCommand(
        name=_normalize_command_name(tokens[0]),
        arguments=tuple(tokens[1:]),
        source=stripped,
    )


def _normalize_command_name(value: str) -> str:
    normalized = value.strip().lower()
    if not normalized or not normalized.replace("-", "").replace("_", "").isalnum():
        raise ValueError("command names may only contain letters, numbers, hyphens, and underscores")
    return normalized


DEFAULT_COMMAND_REGISTRY = CommandRegistry()
