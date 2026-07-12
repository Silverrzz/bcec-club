from __future__ import annotations

import json
import sqlite3
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from cope.core.models import (
    EngineSpec,
    HardwareInfo,
    TournamentConfig,
    WorkerResources,
)


@dataclass(frozen=True, slots=True)
class CategoryRecord:
    id: int
    name: str
    description: str
    default_config: dict[str, Any]
    active: bool
    created_at: str


@dataclass(frozen=True, slots=True)
class TournamentRecord:
    id: int
    name: str
    category_id: int | None
    settings_unlinked: bool
    config: TournamentConfig
    status: str
    current_round: int
    worker_profile: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


@dataclass(frozen=True, slots=True)
class GameRecord:
    id: int
    tournament_id: int
    round: int
    pair_index: int
    white_engine_id: int
    black_engine_id: int
    match_id: int | None
    game_number: int
    tiebreak_kind: str | None
    opening_id: int | None
    status: str
    result: str | None
    termination: str | None
    pgn: str | None
    started_at: str | None
    finished_at: str | None


@dataclass(frozen=True, slots=True)
class TournamentMatchRecord:
    id: int
    tournament_id: int
    round: int
    match_index: int
    engine1_id: int
    engine2_id: int | None
    status: str
    winner_engine_id: int | None


@dataclass(frozen=True, slots=True)
class MoveRecord:
    game_id: int
    ply: int
    uci: str
    san: str
    is_book: bool
    eval_cp: int | None
    eval_mate: int | None
    depth: int | None
    nodes: int | None
    nps: int | None
    pv: str | None
    info_line: str | None
    time_ms: int
    clock_after_ms: int


@dataclass(frozen=True, slots=True)
class GameAssignmentRecord:
    id: int
    game_id: int
    assignment_key: str
    worker_id: int | None
    status: str
    sent_at: str | None
    acked_at: str | None
    finished_at: str | None
    last_error: str | None


@dataclass(frozen=True, slots=True)
class WorkerRecord:
    id: int
    label: str
    token_expires_at: str | None
    status: str
    session_id: str | None
    app_commit: str | None
    protocol_version: int | None
    machine_id: str | None
    pool_id: int | None
    assigned_threads: int
    assigned_hash_mb: int
    hw: HardwareInfo | None
    last_seen: str | None

    @property
    def resources(self) -> WorkerResources:
        return WorkerResources(
            threads=self.assigned_threads,
            hash_mb=self.assigned_hash_mb,
        )


@dataclass(frozen=True, slots=True)
class WorkerFailureRecord:
    id: int
    worker_id: int | None
    worker_label: str
    pool_id: int | None
    machine_id: str | None
    assignment_id: int | None
    game_id: int | None
    engine_id: int | None
    engine_name: str
    stage: str
    error: str
    occurred_at: str


@dataclass(frozen=True, slots=True)
class EngineRecord:
    id: int
    name: str
    author: str
    active: bool


@dataclass(frozen=True, slots=True)
class EngineVersionRecord:
    id: int
    engine_id: int
    name: str
    author: str
    version: str
    binary_filename: str
    binary_sha256: str
    binary_size: int
    storage_key: str
    uci_options: dict[str, Any]
    active: bool
    version_active: bool
    engine_active: bool
    created_at: str


@dataclass(frozen=True, slots=True)
class OpeningSuiteRecord:
    id: int
    name: str
    description: str
    created_at: str


@dataclass(frozen=True, slots=True)
class OpeningRecord:
    id: int
    suite_id: int
    position: int
    name: str
    fen: str


@dataclass(frozen=True, slots=True)
class ChatMessageRecord:
    id: int
    tournament_id: int
    display_name: str
    text: str
    at: str


@dataclass(frozen=True, slots=True)
class ChatSettingsRecord:
    enabled: bool
    slowmode_seconds: int
    max_message_length: int
    allow_anonymous_names: bool
    retention_days: int


@dataclass(frozen=True, slots=True)
class WorkerToken:
    worker_id: int
    token: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class WorkerPoolRecord:
    id: int
    label: str
    enrollment_expires_at: str | None
    status: str
    machine_id: str | None
    slot_count: int
    assigned_threads: int
    assigned_hash_mb: int
    created_at: str
    enrolled_at: str | None


@dataclass(frozen=True, slots=True)
class WorkerPoolEnrollment:
    pool_id: int
    token: str
    expires_at: str


@dataclass(frozen=True, slots=True)
class WorkerPoolSlotCredential:
    worker_id: int
    label: str
    token: str


@dataclass(frozen=True, slots=True)
class ServiceEndpointRecord:
    service: str
    host: str
    port: int
    path: str
    updated_at: str


@dataclass(frozen=True, slots=True)
class TournamentRatingCommitRecord:
    tournament_id: int
    category_id: int
    command_id: int | None
    status: str
    requested_at: str
    applied_at: str | None
    error: str | None


@dataclass(frozen=True, slots=True)
class RunnerCommandRecord:
    id: int
    command: str
    payload: dict[str, Any]
    status: str
    created_at: str
    claimed_at: str | None
    finished_at: str | None
    error: str | None


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def utc_now_datetime() -> datetime:
    return datetime.now(UTC)


def set_service_endpoint(
    connection: sqlite3.Connection,
    *,
    service: str,
    host: str,
    port: int,
    path: str,
) -> None:
    connection.execute(
        """
        INSERT INTO service_endpoints (service, host, port, path, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(service) DO UPDATE SET
          host = excluded.host,
          port = excluded.port,
          path = excluded.path,
          updated_at = excluded.updated_at
        """,
        (service, host, port, path, utc_now()),
    )


def get_service_endpoint(
    connection: sqlite3.Connection,
    service: str,
) -> ServiceEndpointRecord | None:
    row = connection.execute(
        "SELECT * FROM service_endpoints WHERE service = ?",
        (service,),
    ).fetchone()
    if row is None:
        return None
    return ServiceEndpointRecord(
        service=row["service"],
        host=row["host"],
        port=row["port"],
        path=row["path"],
        updated_at=row["updated_at"],
    )


def touch_service_heartbeat(
    connection: sqlite3.Connection,
    service: str,
    app_commit: str,
) -> None:
    connection.execute(
        """
        INSERT INTO service_heartbeats (service, app_commit, last_seen)
        VALUES (?, ?, ?)
        ON CONFLICT(service) DO UPDATE SET
          app_commit = excluded.app_commit,
          last_seen = excluded.last_seen
        """,
        (service, app_commit, utc_now()),
    )


def list_service_heartbeats(connection: sqlite3.Connection) -> tuple[dict[str, str], ...]:
    return tuple(
        {
            "service": str(row["service"]),
            "app_commit": str(row["app_commit"]),
            "last_seen": str(row["last_seen"]),
        }
        for row in connection.execute("SELECT * FROM service_heartbeats ORDER BY service")
    )


def create_engine(
    connection: sqlite3.Connection,
    *,
    name: str,
    author: str = "",
    active: bool = True,
) -> int:
    cursor = connection.execute(
        "INSERT INTO engines (name, author, active) VALUES (?, ?, ?)",
        (name, author, int(active)),
    )
    return int(cursor.lastrowid)


def update_engine(
    connection: sqlite3.Connection,
    engine_id: int,
    *,
    name: str,
    author: str = "",
    active: bool = True,
) -> None:
    connection.execute(
        "UPDATE engines SET name = ?, author = ?, active = ? WHERE id = ?",
        (name, author, int(active), engine_id),
    )


def create_engine_version(
    connection: sqlite3.Connection,
    *,
    engine_id: int,
    version: str,
    binary_filename: str,
    binary_sha256: str,
    binary_size: int,
    storage_key: str,
    uci_options: dict[str, Any] | None = None,
    active: bool = True,
) -> int:
    cursor = connection.execute(
        """INSERT INTO engine_versions
           (engine_id, version, binary_filename, binary_sha256, binary_size, storage_key,
            uci_options, active, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (engine_id, version, binary_filename, binary_sha256, binary_size, storage_key,
         _json_dump(uci_options or {}), int(active), utc_now()),
    )
    return int(cursor.lastrowid)


def update_engine_version(
    connection: sqlite3.Connection,
    version_id: int,
    *,
    uci_options: dict[str, Any],
    active: bool,
) -> None:
    connection.execute(
        "UPDATE engine_versions SET uci_options = ?, active = ? WHERE id = ?",
        (_json_dump(uci_options), int(active), version_id),
    )


def engine_game_count(connection: sqlite3.Connection, engine_id: int) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM games WHERE white_engine_id = ? OR black_engine_id = ?",
        (engine_id, engine_id),
    ).fetchone()
    return int(row["count"])


def delete_engine(connection: sqlite3.Connection, engine_id: int) -> None:
    row = connection.execute("SELECT COUNT(*) AS count FROM engine_versions WHERE engine_id = ?", (engine_id,)).fetchone()
    if int(row["count"]) > 0:
        raise ValueError("engine has versions; delete those versions first")
    connection.execute("DELETE FROM engines WHERE id = ?", (engine_id,))


def delete_engine_version(connection: sqlite3.Connection, version_id: int) -> str:
    if engine_game_count(connection, version_id) > 0:
        raise ValueError("engine version has recorded games; deactivate it instead of deleting")
    row = connection.execute("SELECT COUNT(*) AS count FROM participants WHERE engine_id = ?", (version_id,)).fetchone()
    if int(row["count"]) > 0:
        raise ValueError("engine version participates in tournaments; deactivate it instead")
    record = get_engine_version_record(connection, version_id)
    if record is None:
        raise ValueError("engine version not found")
    connection.execute("DELETE FROM ratings WHERE engine_id = ?", (version_id,))
    connection.execute("DELETE FROM engine_versions WHERE id = ?", (version_id,))
    return record.storage_key


def get_engine_record(
    connection: sqlite3.Connection,
    engine_id: int,
) -> EngineVersionRecord | None:
    return get_engine_version_record(connection, engine_id)


def get_engine_family(connection: sqlite3.Connection, engine_id: int) -> EngineRecord | None:
    row = connection.execute("SELECT * FROM engines WHERE id = ?", (engine_id,)).fetchone()
    return None if row is None else _engine_record_from_row(row)


def get_engine_version_record(connection: sqlite3.Connection, version_id: int) -> EngineVersionRecord | None:
    row = connection.execute(
        """SELECT version.*, engine.name, engine.author, engine.active AS engine_active
           FROM engine_versions version JOIN engines engine ON engine.id = version.engine_id
           WHERE version.id = ?""",
        (version_id,),
    ).fetchone()
    if row is None:
        return None
    return _engine_version_from_row(row)


def list_engine_families(connection: sqlite3.Connection) -> tuple[EngineRecord, ...]:
    return tuple(
        _engine_record_from_row(row)
        for row in connection.execute("SELECT * FROM engines ORDER BY name")
    )


def list_engine_records(connection: sqlite3.Connection) -> tuple[EngineVersionRecord, ...]:
    return tuple(
        _engine_version_from_row(row)
        for row in connection.execute(
            """SELECT version.*, engine.name, engine.author, engine.active AS engine_active
               FROM engine_versions version JOIN engines engine ON engine.id = version.engine_id
               ORDER BY engine.name, version.created_at DESC, version.id DESC"""
        )
    )


def list_engine_versions(connection: sqlite3.Connection, engine_id: int) -> tuple[EngineVersionRecord, ...]:
    return tuple(record for record in list_engine_records(connection) if record.engine_id == engine_id)


def create_category(
    connection: sqlite3.Connection,
    *,
    name: str,
    description: str = "",
    default_config: dict[str, Any] | None = None,
    active: bool = True,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO categories (name, description, default_config, active, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (name, description, _json_dump(default_config or {}), int(active), utc_now()),
    )
    return int(cursor.lastrowid)


def update_category(
    connection: sqlite3.Connection,
    category_id: int,
    *,
    name: str,
    description: str = "",
    default_config: dict[str, Any] | None = None,
    active: bool = True,
) -> None:
    connection.execute(
        """
        UPDATE categories
        SET name = ?, description = ?, default_config = ?, active = ?
        WHERE id = ?
        """,
        (
            name,
            description,
            _json_dump(default_config or {}),
            int(active),
            category_id,
        ),
    )


def get_category(
    connection: sqlite3.Connection,
    category_id: int,
) -> CategoryRecord | None:
    row = connection.execute(
        "SELECT * FROM categories WHERE id = ?",
        (category_id,),
    ).fetchone()
    if row is None:
        return None
    return _category_from_row(row)


def list_categories(
    connection: sqlite3.Connection,
    *,
    active_only: bool = False,
) -> tuple[CategoryRecord, ...]:
    sql = "SELECT * FROM categories"
    params: tuple[Any, ...] = ()
    if active_only:
        sql = f"{sql} WHERE active = ?"
        params = (1,)
    sql = f"{sql} ORDER BY active DESC, name"
    return tuple(_category_from_row(row) for row in connection.execute(sql, params))


def category_tournament_count(connection: sqlite3.Connection, category_id: int) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM tournaments WHERE category_id = ?",
        (category_id,),
    ).fetchone()
    return int(row["count"])


def delete_category(connection: sqlite3.Connection, category_id: int) -> None:
    """Delete a category. Raises ValueError if tournaments or ratings reference it."""
    if category_id == 1:
        raise ValueError("the default category cannot be deleted")
    if category_tournament_count(connection, category_id) > 0:
        raise ValueError("category has tournaments; deactivate it instead of deleting")
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM ratings WHERE category_id = ?",
        (category_id,),
    ).fetchone()
    if int(row["count"]) > 0:
        raise ValueError("category has ratings; deactivate it instead of deleting")
    connection.execute("DELETE FROM categories WHERE id = ?", (category_id,))


def get_engine(connection: sqlite3.Connection, engine_id: int) -> EngineSpec | None:
    row = connection.execute(
        """SELECT version.*, engine.name, engine.author, engine.active AS engine_active
           FROM engine_versions version JOIN engines engine ON engine.id = version.engine_id
           WHERE version.id = ?""",
        (engine_id,),
    ).fetchone()
    if row is None:
        return None
    return _engine_from_row(row)


def list_engines(connection: sqlite3.Connection, *, active_only: bool = False) -> tuple[EngineSpec, ...]:
    sql = """SELECT version.*, engine.name, engine.author, engine.active AS engine_active
             FROM engine_versions version JOIN engines engine ON engine.id = version.engine_id"""
    params: tuple[Any, ...] = ()
    if active_only:
        sql = f"{sql} WHERE version.active = ? AND engine.active = ?"
        params = (1, 1)
    sql = f"{sql} ORDER BY version.id"
    return tuple(_engine_from_row(row) for row in connection.execute(sql, params))


def create_tournament(
    connection: sqlite3.Connection,
    name: str,
    config: TournamentConfig,
    *,
    status: str = "draft",
) -> int:
    config = _resolve_tournament_category_config(connection, config)
    created_at = utc_now()
    cursor = connection.execute(
        """
        INSERT INTO tournaments (
          name, category_id, settings_unlinked, config, status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            name,
            config.category_id,
            int(not config.category_settings_linked),
            config.model_dump_json(),
            status,
            created_at,
        ),
    )
    tournament_id = int(cursor.lastrowid)

    connection.executemany(
        """
        INSERT INTO participants (tournament_id, engine_id, seed)
        VALUES (?, ?, ?)
        """,
        (
            (tournament_id, engine_id, seed)
            for seed, engine_id in enumerate(config.participants, start=1)
        ),
    )
    return tournament_id


def get_tournament(
    connection: sqlite3.Connection,
    tournament_id: int,
) -> TournamentRecord | None:
    row = connection.execute(
        "SELECT * FROM tournaments WHERE id = ?",
        (tournament_id,),
    ).fetchone()
    if row is None:
        return None
    return _tournament_from_row(row)


def list_tournaments(connection: sqlite3.Connection) -> tuple[TournamentRecord, ...]:
    return tuple(
        _tournament_from_row(row)
        for row in connection.execute("SELECT * FROM tournaments ORDER BY id DESC")
    )


def set_tournament_status(
    connection: sqlite3.Connection,
    tournament_id: int,
    status: str,
) -> None:
    now = utc_now()
    started_at_sql = ", started_at = COALESCE(started_at, ?)" if status == "running" else ""
    finished_at_sql = ", finished_at = ?" if status in {"finished", "aborted"} else ""
    params: list[Any] = [status]
    if status == "running":
        params.append(now)
    if status in {"finished", "aborted"}:
        params.append(now)
    params.append(tournament_id)

    connection.execute(
        f"UPDATE tournaments SET status = ?{started_at_sql}{finished_at_sql} WHERE id = ?",
        params,
    )
    if status == "aborted":
        _abandon_tournament_games(connection, tournament_id, now)


def set_tournament_current_round_at_least(
    connection: sqlite3.Connection,
    tournament_id: int,
    round_number: int,
) -> None:
    connection.execute(
        """
        UPDATE tournaments
        SET current_round = ?
        WHERE id = ? AND current_round < ?
        """,
        (round_number, tournament_id, round_number),
    )


def claim_tournament_worker_profile(
    connection: sqlite3.Connection,
    tournament_id: int,
    worker_profile: str,
) -> bool:
    cursor = connection.execute(
        """
        UPDATE tournaments
        SET worker_profile = COALESCE(worker_profile, ?)
        WHERE id = ?
          AND (worker_profile IS NULL OR worker_profile = ?)
        """,
        (worker_profile, tournament_id, worker_profile),
    )
    return cursor.rowcount > 0


def _abandon_tournament_games(
    connection: sqlite3.Connection,
    tournament_id: int,
    now: str,
) -> None:
    reason = "tournament aborted"
    connection.execute(
        """
        UPDATE game_assignments
        SET status = 'abandoned',
            finished_at = COALESCE(finished_at, ?),
            last_error = COALESCE(last_error, ?)
        WHERE status IN ('assigned', 'acked', 'live')
          AND game_id IN (
            SELECT id
            FROM games
            WHERE tournament_id = ?
              AND status != 'finished'
          )
        """,
        (now, reason, tournament_id),
    )
    connection.execute(
        """
        UPDATE games
        SET status = 'abandoned',
            termination = COALESCE(termination, ?),
            finished_at = COALESCE(finished_at, ?)
        WHERE tournament_id = ?
          AND status != 'finished'
        """,
        (reason, now, tournament_id),
    )


def update_tournament(
    connection: sqlite3.Connection,
    tournament_id: int,
    *,
    name: str,
    config: TournamentConfig,
) -> None:
    """Update a tournament's name, config, and participant list."""
    config = _resolve_tournament_category_config(connection, config)
    connection.execute(
        """
        UPDATE tournaments
        SET name = ?, category_id = ?, settings_unlinked = ?, config = ?
        WHERE id = ?
        """,
        (
            name,
            config.category_id,
            int(not config.category_settings_linked),
            config.model_dump_json(),
            tournament_id,
        ),
    )
    connection.execute("DELETE FROM participants WHERE tournament_id = ?", (tournament_id,))
    connection.executemany(
        """
        INSERT INTO participants (tournament_id, engine_id, seed)
        VALUES (?, ?, ?)
        """,
        (
            (tournament_id, engine_id, seed)
            for seed, engine_id in enumerate(config.participants, start=1)
        ),
    )


def _resolve_tournament_category_config(
    connection: sqlite3.Connection,
    config: TournamentConfig,
) -> TournamentConfig:
    if config.category_id is None:
        return config.model_copy(update={"rated": False})

    category = get_category(connection, config.category_id)
    if category is None or not category.active:
        raise ValueError("tournament rating category must be active")

    settings: dict[str, Any] = {
        "format": "round_robin",
        "format_options": {"games_per_pairing": 2},
        "time_control": {
            "category": "increment",
            "initial_ms": 60_000,
            "increment_ms": 1_000,
        },
        "concurrency": 1,
        "opening_suite_id": None,
        "adjudication": {
            "draw": None,
            "resign": None,
            "syzygy": None,
            "max_moves": None,
        },
        "rated": True,
        "lag_compensation_ms": 50,
        "engine_threads": 1,
        "engine_hash_mb": 16,
    }
    settings.update(category.default_config)
    settings.update(
        format=config.format,
        format_options=config.format_options,
        concurrency=config.concurrency,
        opening_suite_id=config.opening_suite_id,
    )
    return TournamentConfig(
        category_id=category.id,
        category_settings_linked=True,
        participants=config.participants,
        **settings,
    )


def delete_tournament(connection: sqlite3.Connection, tournament_id: int) -> None:
    """Delete a tournament and its games, moves, and participants (cascade)."""
    rating_commit = get_tournament_rating_commit(connection, tournament_id)
    if rating_commit is not None:
        if rating_commit.status == "applied":
            raise ValueError("tournament results are already part of the ratings")
        if rating_commit.status in {"pending", "claimed"}:
            raise ValueError("tournament has a rating commit in progress")
    connection.execute("DELETE FROM tournaments WHERE id = ?", (tournament_id,))


def create_game(
    connection: sqlite3.Connection,
    *,
    tournament_id: int,
    round: int,
    pair_index: int,
    white_engine_id: int,
    black_engine_id: int,
    match_id: int | None = None,
    game_number: int = 1,
    tiebreak_kind: str | None = None,
    opening_id: int | None = None,
    status: str = "pending",
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO games (
          tournament_id, round, pair_index, white_engine_id, black_engine_id,
          match_id, game_number, tiebreak_kind, opening_id, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tournament_id,
            round,
            pair_index,
            white_engine_id,
            black_engine_id,
            match_id,
            game_number,
            tiebreak_kind,
            opening_id,
            status,
        ),
    )
    return int(cursor.lastrowid)


def create_tournament_match(
    connection: sqlite3.Connection,
    *,
    tournament_id: int,
    round: int,
    match_index: int,
    engine1_id: int,
    engine2_id: int | None,
    status: str = "pending",
    winner_engine_id: int | None = None,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO tournament_matches (
          tournament_id, round, match_index, engine1_id, engine2_id, status,
          winner_engine_id
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tournament_id,
            round,
            match_index,
            engine1_id,
            engine2_id,
            status,
            winner_engine_id,
        ),
    )
    return int(cursor.lastrowid)


def list_tournament_matches(
    connection: sqlite3.Connection,
    tournament_id: int,
    *,
    round: int | None = None,
) -> tuple[TournamentMatchRecord, ...]:
    if round is None:
        rows = connection.execute(
            """
            SELECT * FROM tournament_matches
            WHERE tournament_id = ?
            ORDER BY round, match_index, id
            """,
            (tournament_id,),
        )
    else:
        rows = connection.execute(
            """
            SELECT * FROM tournament_matches
            WHERE tournament_id = ? AND round = ?
            ORDER BY match_index, id
            """,
            (tournament_id, round),
        )
    return tuple(_tournament_match_from_row(row) for row in rows)


def finish_tournament_match(
    connection: sqlite3.Connection,
    match_id: int,
    *,
    winner_engine_id: int | None,
) -> None:
    connection.execute(
        """
        UPDATE tournament_matches
        SET status = 'finished', winner_engine_id = ?
        WHERE id = ? AND status = 'pending'
        """,
        (winner_engine_id, match_id),
    )


def get_game(connection: sqlite3.Connection, game_id: int) -> GameRecord | None:
    row = connection.execute(
        "SELECT * FROM games WHERE id = ?",
        (game_id,),
    ).fetchone()
    if row is None:
        return None
    return _game_from_row(row)


def list_games(
    connection: sqlite3.Connection,
    tournament_id: int,
    *,
    status: str | None = None,
) -> tuple[GameRecord, ...]:
    if status is None:
        rows = connection.execute(
            """
            SELECT * FROM games
            WHERE tournament_id = ?
            ORDER BY round, pair_index, id
            """,
            (tournament_id,),
        )
    else:
        rows = connection.execute(
            """
            SELECT * FROM games
            WHERE tournament_id = ? AND status = ?
            ORDER BY round, pair_index, id
            """,
            (tournament_id, status),
        )
    return tuple(_game_from_row(row) for row in rows)


def mark_game_live(connection: sqlite3.Connection, game_id: int) -> None:
    connection.execute(
        """
        UPDATE games
        SET status = 'live', started_at = COALESCE(started_at, ?)
        WHERE id = ?
        """,
        (utc_now(), game_id),
    )


def finish_game(
    connection: sqlite3.Connection,
    game_id: int,
    *,
    result: str,
    termination: str,
    pgn: str | None = None,
    white_hw: HardwareInfo | None = None,
    black_hw: HardwareInfo | None = None,
) -> None:
    connection.execute(
        """
        UPDATE games
        SET status = 'finished',
            result = ?,
            termination = ?,
            pgn = ?,
            white_hw = ?,
            black_hw = ?,
            finished_at = ?
        WHERE id = ?
        """,
        (
            result,
            termination,
            pgn,
            white_hw.model_dump_json() if white_hw is not None else None,
            black_hw.model_dump_json() if black_hw is not None else None,
            utc_now(),
            game_id,
        ),
    )


def record_move(
    connection: sqlite3.Connection,
    *,
    game_id: int,
    ply: int,
    uci: str,
    san: str,
    is_book: bool = False,
    eval_cp: int | None = None,
    eval_mate: int | None = None,
    depth: int | None = None,
    nodes: int | None = None,
    nps: int | None = None,
    pv: str | None = None,
    info_line: str | None = None,
    time_ms: int = 0,
    clock_after_ms: int = 0,
) -> None:
    connection.execute(
        """
        INSERT INTO moves (
          game_id, ply, uci, san, is_book, eval_cp, eval_mate, depth,
          nodes, nps, pv, info_line, time_ms, clock_after_ms
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            game_id,
            ply,
            uci,
            san,
            int(is_book),
            eval_cp,
            eval_mate,
            depth,
            nodes,
            nps,
            pv,
            info_line,
            time_ms,
            clock_after_ms,
        ),
    )


def list_moves(connection: sqlite3.Connection, game_id: int) -> tuple[MoveRecord, ...]:
    return tuple(
        _move_from_row(row)
        for row in connection.execute(
            "SELECT * FROM moves WHERE game_id = ? ORDER BY ply",
            (game_id,),
        )
    )


def create_game_assignment(
    connection: sqlite3.Connection,
    *,
    game_id: int,
    assignment_key: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO game_assignments (game_id, assignment_key, worker_id)
        VALUES (?, ?, NULL)
        """,
        (game_id, assignment_key),
    )
    return int(cursor.lastrowid)


def get_game_assignment(
    connection: sqlite3.Connection,
    assignment_id: int,
) -> GameAssignmentRecord | None:
    return _get_game_assignment(connection, "id", assignment_id)


def get_game_assignment_for_game(
    connection: sqlite3.Connection,
    game_id: int,
) -> GameAssignmentRecord | None:
    return _get_game_assignment(connection, "game_id", game_id)


def _get_game_assignment(
    connection: sqlite3.Connection,
    column: str,
    value: int,
) -> GameAssignmentRecord | None:
    row = connection.execute(
        f"SELECT * FROM game_assignments WHERE {column} = ?",
        (value,),
    ).fetchone()
    if row is None:
        return None
    return _game_assignment_from_row(row)


def assign_game_to_worker(
    connection: sqlite3.Connection,
    *,
    game_id: int,
    assignment_key: str,
    worker_id: int,
) -> GameAssignmentRecord | None:
    now = utc_now()
    claimed = connection.execute(
        """
        UPDATE games
        SET status = 'assigned'
        WHERE id = ? AND status = 'pending'
        RETURNING id
        """,
        (game_id,),
    ).fetchone()
    if claimed is None:
        return None
    connection.execute(
        """
        INSERT INTO game_assignments (
          game_id, assignment_key, worker_id,
          status, sent_at, acked_at, finished_at, last_error
        )
        VALUES (?, ?, ?, 'assigned', ?, NULL, NULL, NULL)
        ON CONFLICT(game_id) DO UPDATE SET
          assignment_key = excluded.assignment_key,
          worker_id = excluded.worker_id,
          status = 'assigned',
          sent_at = excluded.sent_at,
          acked_at = NULL,
          finished_at = NULL,
          last_error = NULL
        """,
        (
            game_id,
            assignment_key,
            worker_id,
            now,
        ),
    )
    assignment = get_game_assignment_for_game(connection, game_id)
    if assignment is None:
        raise RuntimeError(f"failed to assign game {game_id}")
    return assignment


def mark_game_assignment_live(
    connection: sqlite3.Connection,
    assignment_id: int,
) -> None:
    connection.execute(
        """
        UPDATE game_assignments
        SET status = 'live', acked_at = COALESCE(acked_at, ?)
        WHERE id = ? AND status IN ('assigned', 'acked', 'live')
        """,
        (utc_now(), assignment_id),
    )


def acknowledge_game_assignment(
    connection: sqlite3.Connection,
    assignment_id: int,
    assignment_key: str,
) -> None:
    cursor = connection.execute(
        """
        UPDATE game_assignments
        SET status = 'acked', acked_at = COALESCE(acked_at, ?)
        WHERE id = ? AND assignment_key = ? AND status IN ('assigned', 'acked')
        """,
        (utc_now(), assignment_id, assignment_key),
    )
    if cursor.rowcount != 1:
        raise RuntimeError(f"assignment {assignment_id} is no longer awaiting readiness")


def finish_game_assignment(
    connection: sqlite3.Connection,
    assignment_id: int,
    assignment_key: str,
) -> None:
    connection.execute(
        """
        UPDATE game_assignments
        SET status = 'finished', finished_at = ?
        WHERE id = ? AND assignment_key = ?
        """,
        (utc_now(), assignment_id, assignment_key),
    )


def fail_game_assignment(
    connection: sqlite3.Connection,
    assignment_id: int,
    assignment_key: str,
    error: str,
) -> None:
    assignment = get_game_assignment(connection, assignment_id)
    if assignment is None or assignment.assignment_key != assignment_key:
        return
    connection.execute(
        """
        UPDATE game_assignments
        SET status = 'abandoned', finished_at = ?, last_error = ?
        WHERE id = ? AND assignment_key = ? AND status IN ('assigned', 'acked', 'live')
        """,
        (utc_now(), error[:500], assignment_id, assignment_key),
    )
    connection.execute(
        """
        UPDATE games
        SET status = 'pending'
        WHERE id = ? AND status IN ('assigned', 'live')
        """,
        (assignment.game_id,),
    )


def create_worker(
    connection: sqlite3.Connection,
    *,
    label: str,
    assigned_threads: int = 1,
    assigned_hash_mb: int = 32,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO workers (label, assigned_threads, assigned_hash_mb, status)
        VALUES (?, ?, ?, 'minted')
        """,
        (label, assigned_threads, assigned_hash_mb),
    )
    return int(cursor.lastrowid)


def create_worker_pool(
    connection: sqlite3.Connection,
    *,
    label: str,
    slot_count: int,
    assigned_threads: int,
    assigned_hash_mb: int,
    ttl_seconds: int = 900,
) -> WorkerPoolEnrollment:
    cursor = connection.execute(
        """
        INSERT INTO worker_pools (
          label, status, slot_count, assigned_threads, assigned_hash_mb, created_at
        )
        VALUES (?, 'pending', ?, ?, ?, ?)
        """,
        (
            label,
            slot_count,
            assigned_threads,
            assigned_hash_mb,
            utc_now(),
        ),
    )
    return mint_worker_pool_token(
        connection,
        pool_id=int(cursor.lastrowid),
        ttl_seconds=ttl_seconds,
    )


def mint_worker_pool_token(
    connection: sqlite3.Connection,
    *,
    pool_id: int,
    ttl_seconds: int = 900,
) -> WorkerPoolEnrollment:
    token = secrets.token_urlsafe(32)
    expires_at = (utc_now_datetime() + timedelta(seconds=ttl_seconds)).isoformat(
        timespec="seconds"
    )
    cursor = connection.execute(
        """
        UPDATE worker_pools
        SET enrollment_token_hash = ?, enrollment_expires_at = ?
        WHERE id = ? AND status = 'pending' AND machine_id IS NULL
        """,
        (hash_worker_token(token), expires_at, pool_id),
    )
    if cursor.rowcount == 0:
        raise ValueError("worker pool cannot receive an enrollment token")
    return WorkerPoolEnrollment(pool_id=pool_id, token=token, expires_at=expires_at)


def get_worker_pool(
    connection: sqlite3.Connection,
    pool_id: int,
) -> WorkerPoolRecord | None:
    row = connection.execute(
        "SELECT * FROM worker_pools WHERE id = ?",
        (pool_id,),
    ).fetchone()
    return _worker_pool_from_row(row) if row is not None else None


def get_worker_pool_by_token(
    connection: sqlite3.Connection,
    token: str,
) -> WorkerPoolRecord | None:
    row = connection.execute(
        "SELECT * FROM worker_pools WHERE enrollment_token_hash = ?",
        (hash_worker_token(token),),
    ).fetchone()
    return _worker_pool_from_row(row) if row is not None else None


def list_worker_pools(connection: sqlite3.Connection) -> tuple[WorkerPoolRecord, ...]:
    return tuple(
        _worker_pool_from_row(row)
        for row in connection.execute("SELECT * FROM worker_pools ORDER BY id")
    )


def worker_pool_token_is_valid(
    record: WorkerPoolRecord,
    *,
    now: datetime | None = None,
) -> bool:
    if record.status != "pending" or record.enrollment_expires_at is None:
        return False
    expires_at = datetime.fromisoformat(record.enrollment_expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > (now or utc_now_datetime())


def enroll_worker_pool(
    connection: sqlite3.Connection,
    *,
    pool: WorkerPoolRecord,
    machine_id: str,
    hw: HardwareInfo,
    app_commit: str,
    protocol_version: int,
) -> tuple[WorkerPoolSlotCredential, ...]:
    if not worker_pool_token_is_valid(pool):
        raise ValueError("invalid or expired worker pool enrollment token")
    existing = tuple(
        _worker_from_row(row)
        for row in connection.execute(
            """
            SELECT * FROM workers
            WHERE machine_id = ?
              AND status != 'revoked'
              AND (
                pool_id IS NOT NULL
                OR status IN ('connected', 'downloading', 'ready', 'busy')
              )
            """,
            (machine_id,),
        )
    )
    for worker in existing:
        if worker.hw is None:
            continue
        if worker.hw.physical_cores != hw.physical_cores:
            raise ValueError("existing workers on this machine report a different core count")
        if worker.hw.total_ram_mb != hw.total_ram_mb:
            raise ValueError("existing workers on this machine report a different RAM capacity")

    required_threads = (
        pool.slot_count * pool.assigned_threads
        + sum(worker.assigned_threads for worker in existing)
    )
    if required_threads > hw.physical_cores:
        raise ValueError(
            f"pool reserves {required_threads} threads but the machine reports "
            f"only {hw.physical_cores} physical cores"
        )
    required_hash_mb = (
        pool.slot_count * pool.assigned_hash_mb
        + sum(worker.assigned_hash_mb for worker in existing)
    )
    if required_hash_mb > hw.total_ram_mb:
        raise ValueError(
            f"pool reserves {required_hash_mb}MB hash but the machine reports "
            f"only {hw.total_ram_mb}MB RAM"
        )

    width = max(2, len(str(pool.slot_count)))
    credentials: list[WorkerPoolSlotCredential] = []
    for slot_number in range(1, pool.slot_count + 1):
        token = secrets.token_urlsafe(32)
        label = f"{pool.label} {slot_number:0{width}d}"
        cursor = connection.execute(
            """
            INSERT INTO workers (
              label, status, app_commit, protocol_version, machine_id, pool_id,
              pool_slot_token_hash, assigned_threads, assigned_hash_mb, hw, last_seen
            )
            VALUES (?, 'offline', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                label,
                app_commit,
                protocol_version,
                machine_id,
                pool.id,
                hash_worker_token(token),
                pool.assigned_threads,
                pool.assigned_hash_mb,
                hw.model_dump_json(),
                utc_now(),
            ),
        )
        credentials.append(
            WorkerPoolSlotCredential(
                worker_id=int(cursor.lastrowid),
                label=label,
                token=token,
            )
        )

    cursor = connection.execute(
        """
        UPDATE worker_pools
        SET enrollment_token_hash = NULL,
            enrollment_expires_at = NULL,
            status = 'enrolled',
            machine_id = ?,
            enrolled_at = ?
        WHERE id = ? AND status = 'pending' AND enrollment_token_hash IS NOT NULL
        """,
        (machine_id, utc_now(), pool.id),
    )
    if cursor.rowcount == 0:
        raise ValueError("worker pool enrollment was already consumed")
    return tuple(credentials)


def mint_worker_token(
    connection: sqlite3.Connection,
    *,
    label: str,
    ttl_seconds: int = 7200,
    assigned_threads: int = 1,
    assigned_hash_mb: int = 32,
) -> WorkerToken:
    worker_id = create_worker(
        connection,
        label=label,
        assigned_threads=assigned_threads,
        assigned_hash_mb=assigned_hash_mb,
    )
    return mint_worker_token_for_worker(
        connection,
        worker_id=worker_id,
        ttl_seconds=ttl_seconds,
    )


def mint_worker_token_for_worker(
    connection: sqlite3.Connection,
    *,
    worker_id: int,
    ttl_seconds: int = 7200,
) -> WorkerToken:
    token = secrets.token_urlsafe(32)
    expires_at = (utc_now_datetime() + timedelta(seconds=ttl_seconds)).isoformat(
        timespec="seconds"
    )
    cursor = connection.execute(
        """
        UPDATE workers
        SET token_hash = ?,
            token_expires_at = ?,
            status = 'minted'
        WHERE id = ?
          AND status != 'revoked'
          AND session_id IS NULL
          AND pool_id IS NULL
        """,
        (hash_worker_token(token), expires_at, worker_id),
    )
    if cursor.rowcount == 0:
        raise ValueError("worker cannot receive a registration token")
    return WorkerToken(
        worker_id=worker_id,
        token=token,
        expires_at=expires_at,
    )


def hash_worker_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def get_worker_by_token(
    connection: sqlite3.Connection,
    token: str,
) -> WorkerRecord | None:
    row = connection.execute(
        "SELECT * FROM workers WHERE token_hash = ?",
        (hash_worker_token(token),),
    ).fetchone()
    if row is None:
        return None
    return _worker_from_row(row)


def get_worker_by_session_id(
    connection: sqlite3.Connection,
    session_id: str,
) -> WorkerRecord | None:
    row = connection.execute(
        "SELECT * FROM workers WHERE session_id = ?",
        (session_id,),
    ).fetchone()
    if row is None:
        return None
    return _worker_from_row(row)


def get_worker_by_pool_slot_token(
    connection: sqlite3.Connection,
    token: str,
) -> WorkerRecord | None:
    row = connection.execute(
        "SELECT * FROM workers WHERE pool_slot_token_hash = ?",
        (hash_worker_token(token),),
    ).fetchone()
    if row is None:
        return None
    return _worker_from_row(row)


def worker_token_is_valid(record: WorkerRecord, *, now: datetime | None = None) -> bool:
    if record.status == "revoked":
        return False

    if record.token_expires_at is None:
        return False

    check_time = now or utc_now_datetime()
    expires_at = datetime.fromisoformat(record.token_expires_at)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at > check_time


def upsert_worker_connection(
    connection: sqlite3.Connection,
    *,
    worker_id: int,
    label: str,
    session_id: str,
    app_commit: str,
    protocol_version: int,
    machine_id: str,
    hw: HardwareInfo,
    status: str = "connected",
) -> int:
    connection.execute(
        """
        INSERT INTO workers (
          id, label, status, session_id, app_commit, protocol_version, machine_id,
          hw, last_seen
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          label = excluded.label,
          token_hash = NULL,
          token_expires_at = NULL,
          status = excluded.status,
          session_id = excluded.session_id,
          app_commit = excluded.app_commit,
          protocol_version = excluded.protocol_version,
          machine_id = excluded.machine_id,
          hw = excluded.hw,
          last_seen = excluded.last_seen
        WHERE workers.status != 'revoked'
        """,
        (
            worker_id,
            label,
            status,
            session_id,
            app_commit,
            protocol_version,
            machine_id,
            hw.model_dump_json(),
            utc_now(),
        ),
    )
    return worker_id


def get_worker(connection: sqlite3.Connection, worker_id: int) -> WorkerRecord | None:
    row = connection.execute(
        "SELECT * FROM workers WHERE id = ?",
        (worker_id,),
    ).fetchone()
    if row is None:
        return None
    return _worker_from_row(row)


def list_workers(connection: sqlite3.Connection) -> tuple[WorkerRecord, ...]:
    return tuple(
        _worker_from_row(row)
        for row in connection.execute(
            "SELECT * FROM workers WHERE status != 'revoked' ORDER BY id"
        )
    )


def record_worker_failure(
    connection: sqlite3.Connection,
    *,
    worker: WorkerRecord,
    assignment_id: int,
    game_id: int,
    engine_id: int,
    engine_name: str,
    stage: str,
    error: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO worker_failures (
          worker_id, worker_label, pool_id, machine_id, assignment_id, game_id,
          engine_id, engine_name, stage, error, occurred_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            worker.id,
            worker.label,
            worker.pool_id,
            worker.machine_id,
            assignment_id,
            game_id,
            engine_id,
            engine_name[:80],
            stage,
            error[:8000],
            utc_now(),
        ),
    )
    return cursor.lastrowid


def list_worker_failures(
    connection: sqlite3.Connection,
    worker_id: int,
    *,
    limit: int = 20,
) -> tuple[WorkerFailureRecord, ...]:
    rows = connection.execute(
        """
        SELECT * FROM worker_failures
        WHERE worker_id = ?
        ORDER BY occurred_at DESC, id DESC
        LIMIT ?
        """,
        (worker_id, max(1, min(limit, 100))),
    )
    return tuple(
        WorkerFailureRecord(
            id=row["id"],
            worker_id=row["worker_id"],
            worker_label=row["worker_label"],
            pool_id=row["pool_id"],
            machine_id=row["machine_id"],
            assignment_id=row["assignment_id"],
            game_id=row["game_id"],
            engine_id=row["engine_id"],
            engine_name=row["engine_name"],
            stage=row["stage"],
            error=row["error"],
            occurred_at=row["occurred_at"],
        )
        for row in rows
    )


def update_worker_label(
    connection: sqlite3.Connection,
    worker_id: int,
    label: str,
) -> None:
    connection.execute(
        "UPDATE workers SET label = ? WHERE id = ?",
        (label, worker_id),
    )


def update_worker_status(
    connection: sqlite3.Connection,
    worker_id: int,
    status: str,
    *,
    session_id: str | None = None,
) -> bool:
    cursor = connection.execute(
        """
        UPDATE workers
        SET status = ?, last_seen = ?
        WHERE id = ? AND status != 'revoked'
          AND (CAST(? AS TEXT) IS NULL OR session_id = ?)
        """,
        (status, utc_now(), worker_id, session_id, session_id),
    )
    return cursor.rowcount > 0


def touch_worker_seen(
    connection: sqlite3.Connection,
    worker_id: int,
    *,
    session_id: str | None = None,
) -> bool:
    cursor = connection.execute(
        """
        UPDATE workers
        SET last_seen = ?
        WHERE id = ?
          AND status IN ('connected', 'downloading', 'ready', 'busy')
          AND (CAST(? AS TEXT) IS NULL OR session_id = ?)
        """,
        (utc_now(), worker_id, session_id, session_id),
    )
    return cursor.rowcount > 0


def touch_workers_seen(
    connection: sqlite3.Connection,
    sessions: list[tuple[int, str]],
) -> set[int]:
    """Persist many live worker sessions in one database transaction."""
    if not sessions:
        return set()
    now = utc_now()
    values = ", ".join("(?, ?)" for _ in sessions)
    parameters: list[Any] = [now]
    for worker_id, session_id in sessions:
        parameters.extend((worker_id, session_id))
    rows = connection.execute(
        f"""
        UPDATE workers AS worker
        SET last_seen = ?
        FROM (VALUES {values}) AS live(worker_id, session_id)
        WHERE worker.id = live.worker_id
          AND worker.session_id = live.session_id
          AND worker.status IN ('connected', 'downloading', 'ready', 'busy')
        RETURNING worker.id
        """,
        parameters,
    ).fetchall()
    return {int(row["id"]) for row in rows}


def disconnect_worker(
    connection: sqlite3.Connection,
    worker_id: int,
    *,
    session_id: str | None = None,
    reason: str = "worker connection lost",
) -> tuple[int, ...]:
    row = connection.execute(
        "SELECT status, session_id FROM workers WHERE id = ?",
        (worker_id,),
    ).fetchone()
    if row is None or row["status"] == "revoked":
        return ()
    if session_id is not None and row["session_id"] != session_id:
        return ()

    now = utc_now()
    tournament_ids = _active_worker_tournament_ids(connection, worker_id)
    _release_worker_active_assignments(
        connection,
        worker_id,
        now=now,
        reason=reason,
    )
    connection.execute(
        """
        UPDATE workers
        SET status = 'offline', last_seen = ?
        WHERE id = ? AND status != 'revoked'
          AND (CAST(? AS TEXT) IS NULL OR session_id = ?)
        """,
        (now, worker_id, session_id, session_id),
    )
    return tournament_ids


def revoke_worker(connection: sqlite3.Connection, worker_id: int) -> None:
    """Decommission a worker and remove its credentials and worker record."""
    now = utc_now()
    _release_worker_active_assignments(
        connection,
        worker_id,
        now=now,
        reason="worker revoked",
    )
    connection.execute("DELETE FROM workers WHERE id = ?", (worker_id,))


def revoke_worker_pool(connection: sqlite3.Connection, pool_id: int) -> None:
    worker_ids = tuple(
        int(row["id"])
        for row in connection.execute(
            "SELECT id FROM workers WHERE pool_id = ?",
            (pool_id,),
        )
    )
    for worker_id in worker_ids:
        revoke_worker(connection, worker_id)
    connection.execute(
        """
        UPDATE worker_pools
        SET status = 'revoked',
            enrollment_token_hash = NULL,
            enrollment_expires_at = NULL
        WHERE id = ?
        """,
        (pool_id,),
    )


def _active_worker_tournament_ids(
    connection: sqlite3.Connection,
    worker_id: int,
) -> tuple[int, ...]:
    return tuple(
        int(row["tournament_id"])
        for row in connection.execute(
            """
            SELECT DISTINCT games.tournament_id
            FROM game_assignments
            JOIN games ON games.id = game_assignments.game_id
            WHERE game_assignments.worker_id = ?
              AND game_assignments.status IN ('assigned', 'acked', 'live')
              AND games.status IN ('assigned', 'live')
            """,
            (worker_id,),
        )
    )


def _release_worker_active_assignments(
    connection: sqlite3.Connection,
    worker_id: int,
    *,
    now: str,
    reason: str,
) -> None:
    connection.execute(
        """
        UPDATE games
        SET status = 'pending'
        WHERE status IN ('assigned', 'live')
          AND id IN (
            SELECT game_id
            FROM game_assignments
            WHERE worker_id = ?
              AND status IN ('assigned', 'acked', 'live')
          )
        """,
        (worker_id,),
    )
    connection.execute(
        """
        UPDATE game_assignments
        SET status = 'abandoned',
            finished_at = ?,
            last_error = ?,
            worker_id = NULL
        WHERE worker_id = ?
          AND status IN ('assigned', 'acked', 'live')
        """,
        (now, reason[:500], worker_id),
    )


def delete_worker(connection: sqlite3.Connection, worker_id: int) -> None:
    """Delete a worker and return its active assignments to the pending pool."""
    row = connection.execute(
        "SELECT pool_id FROM workers WHERE id = ?",
        (worker_id,),
    ).fetchone()
    if row is not None and row["pool_id"] is not None:
        raise ValueError("pool worker slots cannot be deleted individually; revoke the slot instead")
    connection.execute(
        """
        UPDATE games
        SET status = 'pending'
        WHERE status IN ('assigned', 'live')
          AND id IN (
            SELECT game_id
            FROM game_assignments
            WHERE worker_id = ?
              AND status IN ('assigned', 'acked', 'live')
          )
        """,
        (worker_id,),
    )
    connection.execute(
        """
        UPDATE game_assignments
        SET status = CASE
              WHEN status IN ('assigned', 'acked', 'live') THEN 'expired'
              ELSE status
            END,
            finished_at = CASE
              WHEN status IN ('assigned', 'acked', 'live') THEN ?
              ELSE finished_at
            END,
            worker_id = NULL
        WHERE worker_id = ?
        """,
        (utc_now(), worker_id),
    )
    connection.execute("DELETE FROM workers WHERE id = ?", (worker_id,))


def create_opening_suite(
    connection: sqlite3.Connection,
    *,
    name: str,
    description: str = "",
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO opening_suites (name, description, created_at)
        VALUES (?, ?, ?)
        """,
        (name, description, utc_now()),
    )
    return int(cursor.lastrowid)


def update_opening_suite(
    connection: sqlite3.Connection,
    suite_id: int,
    *,
    name: str,
    description: str = "",
) -> None:
    connection.execute(
        "UPDATE opening_suites SET name = ?, description = ? WHERE id = ?",
        (name, description, suite_id),
    )


def delete_opening_suite(connection: sqlite3.Connection, suite_id: int) -> None:
    connection.execute("DELETE FROM opening_suites WHERE id = ?", (suite_id,))


def get_opening_suite(
    connection: sqlite3.Connection,
    suite_id: int,
) -> OpeningSuiteRecord | None:
    row = connection.execute(
        "SELECT * FROM opening_suites WHERE id = ?",
        (suite_id,),
    ).fetchone()
    if row is None:
        return None
    return _opening_suite_from_row(row)


def list_opening_suites(connection: sqlite3.Connection) -> tuple[OpeningSuiteRecord, ...]:
    return tuple(
        _opening_suite_from_row(row)
        for row in connection.execute("SELECT * FROM opening_suites ORDER BY name")
    )


def replace_suite_openings(
    connection: sqlite3.Connection,
    suite_id: int,
    openings: list[tuple[str, str]],
) -> int:
    """Replace all openings in a suite with (name, fen) pairs. Returns the new count."""
    connection.execute("DELETE FROM openings WHERE suite_id = ?", (suite_id,))
    connection.executemany(
        """
        INSERT INTO openings (suite_id, position, name, fen)
        VALUES (?, ?, ?, ?)
        """,
        (
            (suite_id, position, name, fen)
            for position, (name, fen) in enumerate(openings, start=1)
        ),
    )
    return len(openings)


def list_suite_openings(
    connection: sqlite3.Connection,
    suite_id: int,
) -> tuple[OpeningRecord, ...]:
    return tuple(
        _opening_from_row(row)
        for row in connection.execute(
            "SELECT * FROM openings WHERE suite_id = ? ORDER BY position",
            (suite_id,),
        )
    )


def suite_opening_count(connection: sqlite3.Connection, suite_id: int) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM openings WHERE suite_id = ?",
        (suite_id,),
    ).fetchone()
    return int(row["count"])


def create_chat_message(
    connection: sqlite3.Connection,
    *,
    tournament_id: int,
    display_name: str,
    text: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO chat_messages (tournament_id, display_name, text, at)
        VALUES (?, ?, ?, ?)
        """,
        (tournament_id, display_name, text, utc_now()),
    )
    return int(cursor.lastrowid)


def get_chat_message(
    connection: sqlite3.Connection,
    message_id: int,
) -> ChatMessageRecord | None:
    row = connection.execute(
        "SELECT * FROM chat_messages WHERE id = ?",
        (message_id,),
    ).fetchone()
    return None if row is None else _chat_message_from_row(row)


def list_chat_messages(
    connection: sqlite3.Connection,
    *,
    limit: int = 50,
    tournament_id: int | None = None,
) -> tuple[ChatMessageRecord, ...]:
    if tournament_id is None:
        rows = connection.execute(
            "SELECT * FROM chat_messages WHERE tournament_id IS NOT NULL ORDER BY id DESC LIMIT ?",
            (limit,),
        )
    else:
        rows = connection.execute(
            """
            SELECT * FROM chat_messages
            WHERE tournament_id = ?
            ORDER BY id DESC LIMIT ?
            """,
            (tournament_id, limit),
        )
    return tuple(
        _chat_message_from_row(row)
        for row in rows
    )


def get_chat_settings(connection: sqlite3.Connection) -> ChatSettingsRecord:
    values = {
        row["key"]: row["value"]
        for row in connection.execute("SELECT key, value FROM chat_settings")
    }
    return ChatSettingsRecord(
        enabled=_bool_setting(values.get("enabled"), default=True),
        slowmode_seconds=_int_setting(values.get("slowmode_seconds"), default=0),
        max_message_length=_int_setting(values.get("max_message_length"), default=300),
        allow_anonymous_names=_bool_setting(
            values.get("allow_anonymous_names"), default=True
        ),
        retention_days=_int_setting(values.get("retention_days"), default=30),
    )


def update_chat_settings(
    connection: sqlite3.Connection,
    settings: ChatSettingsRecord,
) -> None:
    values = {
        "enabled": str(settings.enabled).lower(),
        "slowmode_seconds": str(settings.slowmode_seconds),
        "max_message_length": str(settings.max_message_length),
        "allow_anonymous_names": str(settings.allow_anonymous_names).lower(),
        "retention_days": str(settings.retention_days),
    }
    connection.executemany(
        """
        INSERT INTO chat_settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        values.items(),
    )


def delete_chat_message(
    connection: sqlite3.Connection,
    message_id: int,
) -> ChatMessageRecord | None:
    row = connection.execute(
        "SELECT * FROM chat_messages WHERE id = ?",
        (message_id,),
    ).fetchone()
    if row is None:
        return None
    connection.execute("DELETE FROM chat_messages WHERE id = ?", (message_id,))
    return _chat_message_from_row(row)


def enqueue_runner_command(
    connection: sqlite3.Connection,
    command: str,
    payload: dict[str, Any] | None = None,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO runner_commands (command, payload, created_at)
        VALUES (?, ?, ?)
        """,
        (command, _json_dump(payload or {}), utc_now()),
    )
    return int(cursor.lastrowid)


def claim_next_runner_command(
    connection: sqlite3.Connection,
) -> RunnerCommandRecord | None:
    while True:
        row = connection.execute(
            """
            SELECT * FROM runner_commands
            WHERE status = 'pending'
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()
        if row is None:
            return None

        claimed_at = utc_now()
        cursor = connection.execute(
            """
            UPDATE runner_commands
            SET status = 'claimed', claimed_at = ?, finished_at = NULL, error = NULL
            WHERE id = ? AND status = 'pending'
            """,
            (claimed_at, row["id"]),
        )
        if cursor.rowcount == 0:
            continue

        try:
            payload = json.loads(row["payload"])
        except (TypeError, json.JSONDecodeError):
            payload = {"_invalid_payload": row["payload"]}
        if not isinstance(payload, dict):
            payload = {"_invalid_payload": row["payload"]}

        return RunnerCommandRecord(
            id=row["id"],
            command=row["command"],
            payload=payload,
            status="claimed",
            created_at=row["created_at"],
            claimed_at=claimed_at,
            finished_at=None,
            error=None,
        )


def finish_runner_command(connection: sqlite3.Connection, command_id: int) -> None:
    connection.execute(
        """
        UPDATE runner_commands
        SET status = 'applied', finished_at = ?, error = NULL
        WHERE id = ? AND status = 'claimed'
        """,
        (utc_now(), command_id),
    )


def fail_runner_command(
    connection: sqlite3.Connection,
    command_id: int,
    error: str,
) -> None:
    connection.execute(
        """
        UPDATE runner_commands
        SET status = 'failed', finished_at = ?, error = ?
        WHERE id = ? AND status = 'claimed'
        """,
        (utc_now(), error, command_id),
    )


def request_tournament_rating_commit(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> bool:
    if tournament.status != "finished":
        raise ValueError("tournament is not complete")
    if not tournament.config.rated:
        raise ValueError("unrated tournament results cannot be committed")
    if tournament.category_id is None or not tournament.config.category_settings_linked:
        raise ValueError("custom tournament results cannot be committed to ratings")

    existing = get_tournament_rating_commit(connection, tournament.id)
    if existing is not None:
        if existing.status in {"claimed", "applied"}:
            return False
        if existing.status == "pending" and existing.command_id is not None:
            command = connection.execute(
                "SELECT status FROM runner_commands WHERE id = ?",
                (existing.command_id,),
            ).fetchone()
            if command is not None and command["status"] in {"pending", "claimed"}:
                return False

    now = utc_now()
    command_id = enqueue_runner_command(
        connection,
        "commit_tournament_results",
        {
            "tournament_id": tournament.id,
            "category_id": tournament.category_id,
        },
    )
    connection.execute(
        """
        INSERT INTO tournament_rating_commits (
          tournament_id, category_id, command_id, status, requested_at
        )
        VALUES (?, ?, ?, 'pending', ?)
        ON CONFLICT(tournament_id) DO UPDATE SET
          status = 'pending',
          category_id = excluded.category_id,
          command_id = excluded.command_id,
          requested_at = excluded.requested_at,
          applied_at = NULL,
          error = NULL
        """,
        (tournament.id, tournament.category_id, command_id, now),
    )
    return True


def get_tournament_rating_commit(
    connection: sqlite3.Connection,
    tournament_id: int,
) -> TournamentRatingCommitRecord | None:
    row = connection.execute(
        "SELECT * FROM tournament_rating_commits WHERE tournament_id = ?",
        (tournament_id,),
    ).fetchone()
    if row is None:
        return None
    return _tournament_rating_commit_from_row(row)


def _category_from_row(row: sqlite3.Row) -> CategoryRecord:
    return CategoryRecord(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        default_config=json.loads(row["default_config"]),
        active=bool(row["active"]),
        created_at=row["created_at"],
    )


def _engine_from_row(row: sqlite3.Row) -> EngineSpec:
    return EngineSpec(
        engine_id=row["id"],
        name=row["name"],
        author=row["author"],
        version=row["version"],
        binary_url=f"/api/worker/engine-binaries/{row['id']}",
        binary_sha256=row["binary_sha256"],
        binary_size=row["binary_size"],
        uci_options=json.loads(row["uci_options"]),
    )


def _engine_record_from_row(row: sqlite3.Row) -> EngineRecord:
    return EngineRecord(
        id=row["id"],
        name=row["name"],
        author=row["author"],
        active=bool(row["active"]),
    )


def _engine_version_from_row(row: sqlite3.Row) -> EngineVersionRecord:
    return EngineVersionRecord(
        id=row["id"], engine_id=row["engine_id"], name=row["name"], author=row["author"],
        version=row["version"], binary_filename=row["binary_filename"],
        binary_sha256=row["binary_sha256"], binary_size=row["binary_size"],
        storage_key=row["storage_key"], uci_options=json.loads(row["uci_options"]),
        active=bool(row["active"]) and bool(row.get("engine_active", True)),
        version_active=bool(row["active"]), engine_active=bool(row.get("engine_active", True)),
        created_at=row["created_at"],
    )


def _opening_suite_from_row(row: sqlite3.Row) -> OpeningSuiteRecord:
    return OpeningSuiteRecord(
        id=row["id"],
        name=row["name"],
        description=row["description"],
        created_at=row["created_at"],
    )


def _opening_from_row(row: sqlite3.Row) -> OpeningRecord:
    return OpeningRecord(
        id=row["id"],
        suite_id=row["suite_id"],
        position=row["position"],
        name=row["name"],
        fen=row["fen"],
    )


def _chat_message_from_row(row: sqlite3.Row) -> ChatMessageRecord:
    return ChatMessageRecord(
        id=row["id"],
        tournament_id=row["tournament_id"],
        display_name=row["display_name"],
        text=row["text"],
        at=row["at"],
    )


def _tournament_from_row(row: sqlite3.Row) -> TournamentRecord:
    is_custom = row["category_id"] is None
    config_data = json.loads(row["config"])
    config_data.update(
        category_id=row["category_id"],
        category_settings_linked=not is_custom,
    )
    config = TournamentConfig.model_validate(config_data)
    return TournamentRecord(
        id=row["id"],
        name=row["name"],
        category_id=row["category_id"],
        settings_unlinked=is_custom,
        config=config,
        status=row["status"],
        current_round=row["current_round"],
        worker_profile=row["worker_profile"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _tournament_rating_commit_from_row(row: sqlite3.Row) -> TournamentRatingCommitRecord:
    return TournamentRatingCommitRecord(
        tournament_id=row["tournament_id"],
        category_id=row["category_id"],
        command_id=row["command_id"],
        status=row["status"],
        requested_at=row["requested_at"],
        applied_at=row["applied_at"],
        error=row["error"],
    )


def _game_from_row(row: sqlite3.Row) -> GameRecord:
    return GameRecord(
        id=row["id"],
        tournament_id=row["tournament_id"],
        round=row["round"],
        pair_index=row["pair_index"],
        white_engine_id=row["white_engine_id"],
        black_engine_id=row["black_engine_id"],
        match_id=row["match_id"],
        game_number=row["game_number"],
        tiebreak_kind=row["tiebreak_kind"],
        opening_id=row["opening_id"],
        status=row["status"],
        result=row["result"],
        termination=row["termination"],
        pgn=row["pgn"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _tournament_match_from_row(row: sqlite3.Row) -> TournamentMatchRecord:
    return TournamentMatchRecord(
        id=row["id"],
        tournament_id=row["tournament_id"],
        round=row["round"],
        match_index=row["match_index"],
        engine1_id=row["engine1_id"],
        engine2_id=row["engine2_id"],
        status=row["status"],
        winner_engine_id=row["winner_engine_id"],
    )


def _move_from_row(row: sqlite3.Row) -> MoveRecord:
    return MoveRecord(
        game_id=row["game_id"],
        ply=row["ply"],
        uci=row["uci"],
        san=row["san"],
        is_book=bool(row["is_book"]),
        eval_cp=row["eval_cp"],
        eval_mate=row["eval_mate"],
        depth=row["depth"],
        nodes=row["nodes"],
        nps=row["nps"],
        pv=row["pv"],
        info_line=row["info_line"],
        time_ms=row["time_ms"],
        clock_after_ms=row["clock_after_ms"],
    )


def _game_assignment_from_row(row: sqlite3.Row) -> GameAssignmentRecord:
    return GameAssignmentRecord(
        id=row["id"],
        game_id=row["game_id"],
        assignment_key=row["assignment_key"],
        worker_id=row["worker_id"],
        status=row["status"],
        sent_at=row["sent_at"],
        acked_at=row["acked_at"],
        finished_at=row["finished_at"],
        last_error=row["last_error"],
    )


def _worker_from_row(row: sqlite3.Row) -> WorkerRecord:
    hw = None
    if row["hw"] is not None:
        hw = HardwareInfo.model_validate_json(row["hw"])

    return WorkerRecord(
        id=row["id"],
        label=row["label"],
        token_expires_at=row["token_expires_at"],
        status=row["status"],
        session_id=row["session_id"],
        app_commit=row["app_commit"],
        protocol_version=row["protocol_version"],
        machine_id=row["machine_id"],
        pool_id=row["pool_id"],
        assigned_threads=row["assigned_threads"],
        assigned_hash_mb=row["assigned_hash_mb"],
        hw=hw,
        last_seen=row["last_seen"],
    )


def _worker_pool_from_row(row: sqlite3.Row) -> WorkerPoolRecord:
    return WorkerPoolRecord(
        id=row["id"],
        label=row["label"],
        enrollment_expires_at=row["enrollment_expires_at"],
        status=row["status"],
        machine_id=row["machine_id"],
        slot_count=row["slot_count"],
        assigned_threads=row["assigned_threads"],
        assigned_hash_mb=row["assigned_hash_mb"],
        created_at=row["created_at"],
        enrolled_at=row["enrolled_at"],
    )


def worker_hardware_profile(hw: HardwareInfo) -> str:
    return _json_dump(
        {
            "cpu_model": hw.cpu_model.strip(),
            "physical_cores": hw.physical_cores,
            "logical_cores": hw.logical_cores,
            "os": hw.os.strip(),
        }
    )


def _json_dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _bool_setting(value: str | None, *, default: bool) -> bool:
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _int_setting(value: str | None, *, default: int) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default
