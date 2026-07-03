from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from cope.core.models import RoundRobinFormatOptions, TournamentFormat
from cope.db import (
    TournamentRecord,
    create_game,
    list_games,
    list_tournaments,
    set_tournament_status,
)


@dataclass(frozen=True, slots=True)
class TournamentPreparation:
    tournament_id: int
    tournament_name: str
    created_games: int
    skipped_reason: str | None = None


def prepare_scheduled_tournaments(
    connection: sqlite3.Connection,
) -> tuple[TournamentPreparation, ...]:
    prepared: list[TournamentPreparation] = []

    for tournament in list_tournaments(connection):
        if tournament.status != "scheduled":
            continue

        prepared.append(prepare_tournament(connection, tournament))

    return tuple(prepared)


def prepare_tournament(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> TournamentPreparation:
    existing_games = list_games(connection, tournament.id)
    if existing_games:
        set_tournament_status(connection, tournament.id, "running")
        return TournamentPreparation(
            tournament_id=tournament.id,
            tournament_name=tournament.name,
            created_games=0,
            skipped_reason="games already exist",
        )

    if tournament.config.format != TournamentFormat.ROUND_ROBIN:
        set_tournament_status(connection, tournament.id, "paused")
        return TournamentPreparation(
            tournament_id=tournament.id,
            tournament_name=tournament.name,
            created_games=0,
            skipped_reason=f"{tournament.config.format.value} is not implemented yet",
        )

    if not isinstance(tournament.config.format_options, RoundRobinFormatOptions):
        set_tournament_status(connection, tournament.id, "paused")
        return TournamentPreparation(
            tournament_id=tournament.id,
            tournament_name=tournament.name,
            created_games=0,
            skipped_reason="round robin options are invalid",
        )

    created_games = generate_round_robin_games(connection, tournament)
    set_tournament_status(connection, tournament.id, "running")
    return TournamentPreparation(
        tournament_id=tournament.id,
        tournament_name=tournament.name,
        created_games=created_games,
    )


def generate_round_robin_games(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> int:
    participants = tournament.config.participants
    double_rr = tournament.config.format_options.double_rr
    created_games = 0
    pair_index = 1

    for white_index in range(len(participants)):
        for black_index in range(white_index + 1, len(participants)):
            white_engine_id = participants[white_index]
            black_engine_id = participants[black_index]

            create_game(
                connection,
                tournament_id=tournament.id,
                round=1,
                pair_index=pair_index,
                white_engine_id=white_engine_id,
                black_engine_id=black_engine_id,
            )
            created_games += 1

            if double_rr:
                create_game(
                    connection,
                    tournament_id=tournament.id,
                    round=1,
                    pair_index=pair_index,
                    white_engine_id=black_engine_id,
                    black_engine_id=white_engine_id,
                )
                created_games += 1

            pair_index += 1

    return created_games
