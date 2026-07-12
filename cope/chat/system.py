from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from cope.db.repo import (
    ChatMessageRecord,
    GameRecord,
    TournamentRecord,
    create_chat_message,
    get_chat_message,
    get_engine,
    list_games,
    list_tournament_matches,
)


class SystemEvent(StrEnum):
    TOURNAMENT_STARTED = "tournament.started"
    GAME_FINISHED = "game.finished"
    TOURNAMENT_FINISHED = "tournament.finished"
    RESULTS_COMMITTED = "tournament.results_committed"


@dataclass(frozen=True, slots=True)
class SystemAnnouncement:
    tournament_id: int
    event: SystemEvent
    event_key: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


class SystemMessenger:
    """Persists idempotent, typed system messages in tournament chat."""

    def emit(
        self,
        connection: sqlite3.Connection,
        announcement: SystemAnnouncement,
    ) -> ChatMessageRecord:
        existing = connection.execute(
            """
            SELECT message_id
            FROM system_chat_events
            WHERE tournament_id = ? AND event_key = ?
            """,
            (announcement.tournament_id, announcement.event_key),
        ).fetchone()
        if existing is not None:
            message = get_chat_message(connection, existing["message_id"])
            if message is not None:
                return message

        message_id = create_chat_message(
            connection,
            tournament_id=announcement.tournament_id,
            display_name="System",
            text=announcement.text,
        )
        connection.execute(
            """
            INSERT INTO system_chat_events (
              tournament_id, event_key, event_type, message_id, metadata
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                announcement.tournament_id,
                announcement.event_key,
                announcement.event.value,
                message_id,
                json.dumps(
                    announcement.metadata,
                    separators=(",", ":"),
                    sort_keys=True,
                ),
            ),
        )
        message = get_chat_message(connection, message_id)
        if message is None:
            raise RuntimeError("system chat message disappeared after creation")
        return message


SYSTEM_MESSENGER = SystemMessenger()


def announce_tournament_started(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
    *,
    scheduled_games: int,
) -> ChatMessageRecord:
    return SYSTEM_MESSENGER.emit(
        connection,
        SystemAnnouncement(
            tournament_id=tournament.id,
            event=SystemEvent.TOURNAMENT_STARTED,
            event_key="tournament.started",
            text=(
                f"{tournament.name} has started. "
                f"{scheduled_games} game{'s' if scheduled_games != 1 else ''} scheduled."
            ),
            metadata={"scheduled_games": scheduled_games},
        ),
    )


def announce_game_finished(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
    game: GameRecord,
    *,
    result: str,
    termination: str,
) -> ChatMessageRecord:
    white = _engine_label(connection, game.white_engine_id)
    black = _engine_label(connection, game.black_engine_id)
    text = _game_finished_text(white, black, result, termination)
    return SYSTEM_MESSENGER.emit(
        connection,
        SystemAnnouncement(
            tournament_id=tournament.id,
            event=SystemEvent.GAME_FINISHED,
            event_key=f"game.{game.id}.finished",
            text=text,
            metadata={
                "game_id": game.id,
                "round": game.round,
                "result": result,
                "termination": termination,
            },
        ),
    )


def _game_finished_text(
    white: str,
    black: str,
    result: str,
    termination: str,
) -> str:
    if termination.startswith("max moves") or "adjudicat" in termination.lower():
        outcome = "Draw" if result == "1/2-1/2" else "Win"
        return f"{white} vs {black}: ({result}) {outcome} by adjudication."
    return f"Game finished: {white} vs {black}, {result}. Termination: {termination}."


def announce_tournament_finished(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> ChatMessageRecord:
    leaders = _tournament_leaders(connection, tournament)
    if not leaders:
        result_text = "Final results are available."
    elif len(leaders) == 1:
        result_text = f"Winner: {leaders[0]}."
    else:
        result_text = f"Joint winners: {', '.join(leaders)}."
    return SYSTEM_MESSENGER.emit(
        connection,
        SystemAnnouncement(
            tournament_id=tournament.id,
            event=SystemEvent.TOURNAMENT_FINISHED,
            event_key="tournament.finished",
            text=f"{tournament.name} has finished. {result_text}",
            metadata={"leaders": leaders},
        ),
    )


def announce_results_committed(
    connection: sqlite3.Connection,
    *,
    tournament_id: int,
    category_id: int,
    games_applied: int,
    engines_updated: int,
) -> ChatMessageRecord:
    return SYSTEM_MESSENGER.emit(
        connection,
        SystemAnnouncement(
            tournament_id=tournament_id,
            event=SystemEvent.RESULTS_COMMITTED,
            event_key=f"tournament.results_committed.{category_id}",
            text=(
                f"Tournament results committed to ratings: {games_applied} games applied "
                f"across {engines_updated} engines."
            ),
            metadata={
                "category_id": category_id,
                "games_applied": games_applied,
                "engines_updated": engines_updated,
            },
        ),
    )


def _engine_label(connection: sqlite3.Connection, engine_id: int) -> str:
    engine = get_engine(connection, engine_id)
    if engine is None:
        return f"Engine {engine_id}"
    return " ".join(part for part in (engine.name, engine.version.strip()) if part)


def _tournament_leaders(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> list[str]:
    matches = list_tournament_matches(connection, tournament.id)
    if tournament.config.format.value == "knockout" and matches:
        final_round = max(match.round for match in matches)
        final = next(
            (
                match
                for match in matches
                if match.round == final_round and match.winner_engine_id is not None
            ),
            None,
        )
        return [] if final is None else [_engine_label(connection, final.winner_engine_id)]

    points = {engine_id: 0.0 for engine_id in tournament.config.participants}
    for game in list_games(connection, tournament.id):
        if game.status != "finished":
            continue
        if game.result == "1-0":
            points[game.white_engine_id] += 1.0
        elif game.result == "0-1":
            points[game.black_engine_id] += 1.0
        elif game.result == "1/2-1/2":
            points[game.white_engine_id] += 0.5
            points[game.black_engine_id] += 0.5
    if tournament.config.format.value == "swiss":
        for match in matches:
            if match.status == "bye":
                points[match.engine1_id] += 1.0
    if not points:
        return []
    best = max(points.values())
    return [
        _engine_label(connection, engine_id)
        for engine_id in tournament.config.participants
        if points[engine_id] == best
    ]
