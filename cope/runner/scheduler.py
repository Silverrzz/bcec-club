from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from itertools import cycle

from cope.core.models import RoundRobinFormatOptions, TournamentFormat
from cope.db import (
    OpeningRecord,
    TournamentRecord,
    create_game,
    list_suite_openings,
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
    opening_ids = _opening_ids(connection, tournament)
    openings = cycle(opening_ids) if opening_ids else None
    created_games = 0

    round_pairings = _round_robin_pairings(participants)
    rounds_per_cycle = len(round_pairings)

    for round_number, pairings in enumerate(round_pairings, start=1):
        for pair_index, (white_engine_id, black_engine_id) in enumerate(pairings, start=1):
            opening_id = next(openings) if openings is not None else None

            create_game(
                connection,
                tournament_id=tournament.id,
                round=round_number,
                pair_index=pair_index,
                white_engine_id=white_engine_id,
                black_engine_id=black_engine_id,
                opening_id=opening_id,
            )
            created_games += 1

            if double_rr:
                opening_id = next(openings) if openings is not None else None
                create_game(
                    connection,
                    tournament_id=tournament.id,
                    round=round_number + rounds_per_cycle,
                    pair_index=pair_index,
                    white_engine_id=black_engine_id,
                    black_engine_id=white_engine_id,
                    opening_id=opening_id,
                )
                created_games += 1

    return created_games


def _round_robin_pairings(participants: list[int]) -> tuple[tuple[tuple[int, int], ...], ...]:
    if len(participants) < 2:
        return ()

    players: list[int | None] = list(participants)
    if len(players) % 2 == 1:
        players.append(None)

    rounds: list[tuple[tuple[int, int], ...]] = []
    player_count = len(players)

    for round_index in range(player_count - 1):
        pairings: list[tuple[int, int]] = []
        for pair_index in range(player_count // 2):
            first = players[pair_index]
            second = players[player_count - 1 - pair_index]
            if first is None or second is None:
                continue
            if (round_index + pair_index) % 2 == 0:
                pairings.append((first, second))
            else:
                pairings.append((second, first))

        rounds.append(tuple(pairings))
        players = [players[0], players[-1], *players[1:-1]]

    return tuple(rounds)


def _opening_ids(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> tuple[int, ...]:
    suite_id = tournament.config.opening_suite_id
    if suite_id is None:
        return ()

    openings: tuple[OpeningRecord, ...] = list_suite_openings(connection, suite_id)
    return tuple(opening.id for opening in openings)
