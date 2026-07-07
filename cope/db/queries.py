from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from cope.core.models import EngineSpec, HardwareInfo

from .repo import (
    GameRecord,
    TournamentRecord,
    _engine_from_row,
    _game_from_row,
    list_tournaments,
)


@dataclass(frozen=True, slots=True)
class OpeningPositionRecord:
    name: str
    fen: str


@dataclass(frozen=True, slots=True)
class RatingRowRecord:
    engine: EngineSpec
    elo: float
    games_played: int
    updated_at: str | None


@dataclass(frozen=True, slots=True)
class WorkerActivityRecord:
    assignment_status: str
    game_id: int
    round: int
    white_engine_id: int
    black_engine_id: int
    tournament_id: int
    tournament_name: str
    plies: int


_DB_STAT_TABLES = (
    "categories",
    "engines",
    "tournaments",
    "games",
    "workers",
    "opening_suites",
)


def get_engine_name(connection: sqlite3.Connection, engine_id: int) -> str:
    row = connection.execute(
        "SELECT name FROM engines WHERE id = ?",
        (engine_id,),
    ).fetchone()
    if row is None:
        return f"Engine {engine_id}"
    return row["name"]


def get_opening_position(
    connection: sqlite3.Connection,
    opening_id: int | None,
) -> OpeningPositionRecord | None:
    if opening_id is None:
        return None

    row = connection.execute(
        "SELECT name, fen FROM openings WHERE id = ?",
        (opening_id,),
    ).fetchone()
    if row is None:
        return None
    return OpeningPositionRecord(name=row["name"] or "Opening", fen=row["fen"])


def list_active_games(connection: sqlite3.Connection) -> tuple[GameRecord, ...]:
    rows = connection.execute(
        """
        SELECT * FROM games
        WHERE status IN ('live', 'assigned')
        ORDER BY CASE status WHEN 'live' THEN 0 ELSE 1 END, id DESC
        """
    )
    return tuple(_game_from_row(row) for row in rows)


def list_upcoming_games(
    connection: sqlite3.Connection,
    *,
    limit: int,
) -> tuple[GameRecord, ...]:
    rows = connection.execute(
        """
        SELECT * FROM games
        WHERE status = 'pending'
        ORDER BY id ASC
        LIMIT ?
        """,
        (limit,),
    )
    return tuple(_game_from_row(row) for row in rows)


def list_games_by_status(
    connection: sqlite3.Connection,
    status: str,
    *,
    limit: int,
) -> tuple[GameRecord, ...]:
    rows = connection.execute(
        """
        SELECT * FROM games
        WHERE status = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (status, limit),
    )
    return tuple(_game_from_row(row) for row in rows)


def list_engine_games(
    connection: sqlite3.Connection,
    engine_id: int,
    *,
    limit: int = 50,
) -> tuple[GameRecord, ...]:
    rows = connection.execute(
        """
        SELECT * FROM games
        WHERE white_engine_id = ? OR black_engine_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (engine_id, engine_id, limit),
    )
    return tuple(_game_from_row(row) for row in rows)


def list_rating_rows(
    connection: sqlite3.Connection,
    category_id: int,
) -> tuple[RatingRowRecord, ...]:
    if not _table_exists(connection, "ratings"):
        return ()

    rows = connection.execute(
        """
        SELECT engines.*, ratings.elo, ratings.games_played, ratings.updated_at
        FROM ratings
        JOIN engines ON engines.id = ratings.engine_id
        WHERE ratings.category_id = ?
        ORDER BY ratings.elo DESC, engines.name
        """,
        (category_id,),
    )
    return tuple(
        RatingRowRecord(
            engine=_engine_from_row(row),
            elo=row["elo"],
            games_played=row["games_played"],
            updated_at=row["updated_at"],
        )
        for row in rows
    )


def get_worker_activity(
    connection: sqlite3.Connection,
    worker_id: int,
) -> WorkerActivityRecord | None:
    row = connection.execute(
        """
        SELECT
          game_assignments.status AS assignment_status,
          games.id AS game_id,
          games.round,
          games.white_engine_id,
          games.black_engine_id,
          tournaments.id AS tournament_id,
          tournaments.name AS tournament_name,
          COUNT(moves.ply) AS plies
        FROM game_assignments
        JOIN games ON games.id = game_assignments.game_id
        JOIN tournaments ON tournaments.id = games.tournament_id
        LEFT JOIN moves ON moves.game_id = games.id
        WHERE (game_assignments.white_worker_id = ? OR game_assignments.black_worker_id = ?)
          AND game_assignments.status IN ('assigned', 'acked', 'live')
          AND games.status IN ('assigned', 'live')
        GROUP BY game_assignments.id
        ORDER BY game_assignments.sent_at DESC, game_assignments.id DESC
        LIMIT 1
        """,
        (worker_id, worker_id),
    ).fetchone()
    if row is None:
        return None

    return WorkerActivityRecord(
        assignment_status=row["assignment_status"],
        game_id=row["game_id"],
        round=row["round"],
        white_engine_id=row["white_engine_id"],
        black_engine_id=row["black_engine_id"],
        tournament_id=row["tournament_id"],
        tournament_name=row["tournament_name"],
        plies=row["plies"],
    )


def active_engine_hardware_profiles(
    connection: sqlite3.Connection,
    tournament_id: int,
) -> dict[int, tuple[HardwareInfo, ...]]:
    rows = connection.execute(
        """
        SELECT
          games.white_engine_id,
          games.black_engine_id,
          game_assignments.hardware_mode,
          white_workers.hw AS white_hw,
          black_workers.hw AS black_hw
        FROM game_assignments
        JOIN games ON games.id = game_assignments.game_id
        LEFT JOIN workers AS white_workers
          ON white_workers.id = game_assignments.white_worker_id
          AND white_workers.status IN ('connected', 'building', 'ready', 'busy')
        LEFT JOIN workers AS black_workers
          ON black_workers.id = game_assignments.black_worker_id
          AND black_workers.status IN ('connected', 'building', 'ready', 'busy')
        WHERE games.tournament_id = ?
          AND games.status IN ('assigned', 'live')
          AND game_assignments.status IN ('assigned', 'acked', 'live')
        """,
        (tournament_id,),
    )

    hardware_by_engine: dict[int, list[HardwareInfo]] = {}
    seen: dict[int, set[str]] = {}
    for row in rows:
        white_hw = _hardware_from_json(row["white_hw"])
        black_hw = _hardware_from_json(row["black_hw"])

        if row["hardware_mode"] == "shared":
            white_hw = white_hw or black_hw
            black_hw = black_hw or white_hw

        for engine_id, hw in (
            (row["white_engine_id"], white_hw),
            (row["black_engine_id"], black_hw),
        ):
            if hw is None:
                continue
            profile_key = hw.model_dump_json()
            engine_seen = seen.setdefault(engine_id, set())
            if profile_key in engine_seen:
                continue
            engine_seen.add(profile_key)
            hardware_by_engine.setdefault(engine_id, []).append(hw)

    return {
        engine_id: tuple(profiles)
        for engine_id, profiles in hardware_by_engine.items()
    }


def database_stats(connection: sqlite3.Connection) -> dict[str, int]:
    return {table_name: _count_rows(connection, table_name) for table_name in _DB_STAT_TABLES}


def list_uncommitted_finished_tournaments(
    connection: sqlite3.Connection,
) -> tuple[TournamentRecord, ...]:
    committed_ids = {
        row["tournament_id"]
        for row in connection.execute("SELECT tournament_id FROM tournament_rating_commits")
    }
    return tuple(
        tournament
        for tournament in list_tournaments(connection)
        if tournament.status == "finished" and tournament.id not in committed_ids
    )


def _table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def _count_rows(connection: sqlite3.Connection, table_name: str) -> int:
    if not _table_exists(connection, table_name):
        return 0
    row = connection.execute(f"SELECT COUNT(*) AS count FROM {table_name}").fetchone()
    return int(row["count"])


def _hardware_from_json(value: str | None) -> HardwareInfo | None:
    if value is None:
        return None
    try:
        return HardwareInfo.model_validate_json(value)
    except ValueError:
        return None
