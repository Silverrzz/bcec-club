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
    category_id: int
    settings_unlinked: bool
    config: TournamentConfig
    status: str
    current_round: int
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
    opening_id: int | None
    status: str
    result: str | None
    termination: str | None
    pgn: str | None
    started_at: str | None
    finished_at: str | None


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
    hardware_mode: str
    white_worker_id: int | None
    black_worker_id: int | None
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
    hw: HardwareInfo | None
    last_seen: str | None


@dataclass(frozen=True, slots=True)
class EngineRecord:
    id: int
    name: str
    author: str
    version: str
    git_url: str
    branch: str
    commit: str
    build_cmd: str
    binary_path: str
    uci_options: dict[str, Any]
    active: bool


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
class TournamentRatingCommitRecord:
    tournament_id: int
    category_id: int
    status: str
    requested_at: str
    applied_at: str | None
    error: str | None


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def utc_now_datetime() -> datetime:
    return datetime.now(UTC)


def create_engine(
    connection: sqlite3.Connection,
    spec: EngineSpec,
    *,
    author: str = "",
    active: bool = True,
) -> int:
    connection.execute(
        """
        INSERT INTO engines (
          id, name, author, version, git_url, branch, commit_hash, build_cmd, binary_path,
          uci_options, active
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            spec.engine_id,
            spec.name,
            author,
            spec.version,
            spec.git_url,
            spec.branch,
            spec.commit,
            spec.build_cmd,
            spec.binary_path,
            _json_dump(spec.uci_options),
            int(active),
        ),
    )
    return spec.engine_id


def next_engine_id(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COALESCE(MAX(id), 0) AS max_id FROM engines").fetchone()
    return int(row["max_id"]) + 1


def update_engine(
    connection: sqlite3.Connection,
    engine_id: int,
    *,
    name: str,
    author: str = "",
    git_url: str,
    branch: str = "",
    commit: str,
    build_cmd: str,
    binary_path: str,
    version: str = "",
    uci_options: dict[str, Any] | None = None,
    active: bool = True,
) -> None:
    connection.execute(
        """
        UPDATE engines
        SET name = ?, author = ?, version = ?, git_url = ?, branch = ?, commit_hash = ?, build_cmd = ?,
            binary_path = ?, uci_options = ?, active = ?
        WHERE id = ?
        """,
        (
            name,
            author,
            version,
            git_url,
            branch,
            commit,
            build_cmd,
            binary_path,
            _json_dump(uci_options or {}),
            int(active),
            engine_id,
        ),
    )


def engine_game_count(connection: sqlite3.Connection, engine_id: int) -> int:
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM games WHERE white_engine_id = ? OR black_engine_id = ?",
        (engine_id, engine_id),
    ).fetchone()
    return int(row["count"])


def delete_engine(connection: sqlite3.Connection, engine_id: int) -> None:
    """Delete an engine. Raises ValueError if it has recorded games or participations."""
    if engine_game_count(connection, engine_id) > 0:
        raise ValueError("engine has recorded games; deactivate it instead of deleting")
    row = connection.execute(
        "SELECT COUNT(*) AS count FROM participants WHERE engine_id = ?",
        (engine_id,),
    ).fetchone()
    if int(row["count"]) > 0:
        raise ValueError("engine participates in tournaments; deactivate it instead of deleting")
    connection.execute("DELETE FROM ratings WHERE engine_id = ?", (engine_id,))
    connection.execute("DELETE FROM engines WHERE id = ?", (engine_id,))


def get_engine_record(
    connection: sqlite3.Connection,
    engine_id: int,
) -> EngineRecord | None:
    row = connection.execute(
        "SELECT * FROM engines WHERE id = ?",
        (engine_id,),
    ).fetchone()
    if row is None:
        return None
    return _engine_record_from_row(row)


def list_engine_records(connection: sqlite3.Connection) -> tuple[EngineRecord, ...]:
    return tuple(
        _engine_record_from_row(row)
        for row in connection.execute("SELECT * FROM engines ORDER BY name")
    )


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
        "SELECT * FROM engines WHERE id = ?",
        (engine_id,),
    ).fetchone()
    if row is None:
        return None
    return _engine_from_row(row)


def list_engines(connection: sqlite3.Connection, *, active_only: bool = False) -> tuple[EngineSpec, ...]:
    sql = "SELECT * FROM engines"
    params: tuple[Any, ...] = ()
    if active_only:
        sql = f"{sql} WHERE active = ?"
        params = (1,)
    sql = f"{sql} ORDER BY id"
    return tuple(_engine_from_row(row) for row in connection.execute(sql, params))


def create_tournament(
    connection: sqlite3.Connection,
    name: str,
    config: TournamentConfig,
    *,
    status: str = "draft",
) -> int:
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


def delete_tournament(connection: sqlite3.Connection, tournament_id: int) -> None:
    """Delete a tournament and its games, moves, and participants (cascade)."""
    connection.execute("DELETE FROM tournaments WHERE id = ?", (tournament_id,))


def create_game(
    connection: sqlite3.Connection,
    *,
    tournament_id: int,
    round: int,
    pair_index: int,
    white_engine_id: int,
    black_engine_id: int,
    opening_id: int | None = None,
    status: str = "pending",
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO games (
          tournament_id, round, pair_index, white_engine_id, black_engine_id,
          opening_id, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tournament_id,
            round,
            pair_index,
            white_engine_id,
            black_engine_id,
            opening_id,
            status,
        ),
    )
    return int(cursor.lastrowid)


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
    hardware_mode: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO game_assignments (
          game_id, assignment_key, hardware_mode, white_worker_id, black_worker_id
        )
        VALUES (?, ?, ?, NULL, NULL)
        """,
        (
            game_id,
            assignment_key,
            hardware_mode,
        ),
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
    hardware_mode: str,
    worker_id: int,
) -> GameAssignmentRecord:
    now = utc_now()
    connection.execute(
        """
        INSERT INTO game_assignments (
          game_id, assignment_key, hardware_mode, white_worker_id, black_worker_id,
          status, sent_at, acked_at, finished_at, last_error
        )
        VALUES (?, ?, ?, ?, ?, 'assigned', ?, NULL, NULL, NULL)
        ON CONFLICT(game_id) DO UPDATE SET
          assignment_key = excluded.assignment_key,
          hardware_mode = excluded.hardware_mode,
          white_worker_id = excluded.white_worker_id,
          black_worker_id = excluded.black_worker_id,
          status = 'assigned',
          sent_at = excluded.sent_at,
          acked_at = NULL,
          finished_at = NULL,
          last_error = NULL
        """,
        (
            game_id,
            assignment_key,
            hardware_mode,
            worker_id,
            worker_id,
            now,
        ),
    )
    connection.execute(
        """
        UPDATE games
        SET status = 'assigned'
        WHERE id = ? AND status IN ('pending', 'assigned')
        """,
        (game_id,),
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


def finish_game_assignment(
    connection: sqlite3.Connection,
    assignment_id: int,
) -> None:
    connection.execute(
        """
        UPDATE game_assignments
        SET status = 'finished', finished_at = ?
        WHERE id = ?
        """,
        (utc_now(), assignment_id),
    )


def fail_game_assignment(
    connection: sqlite3.Connection,
    assignment_id: int,
    error: str,
) -> None:
    assignment = get_game_assignment(connection, assignment_id)
    connection.execute(
        """
        UPDATE game_assignments
        SET status = 'abandoned', finished_at = ?, last_error = ?
        WHERE id = ? AND status IN ('assigned', 'acked', 'live')
        """,
        (utc_now(), error[:500], assignment_id),
    )
    if assignment is None:
        return
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
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO workers (label, status)
        VALUES (?, 'minted')
        """,
        (label,),
    )
    return int(cursor.lastrowid)


def mint_worker_token(
    connection: sqlite3.Connection,
    *,
    label: str,
    ttl_seconds: int = 7200,
) -> WorkerToken:
    worker_id = create_worker(connection, label=label)
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
    hw: HardwareInfo,
    status: str = "connected",
) -> int:
    connection.execute(
        """
        INSERT INTO workers (
          id, label, status, session_id, app_commit, protocol_version, hw, last_seen
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
          label = excluded.label,
          token_hash = NULL,
          token_expires_at = NULL,
          status = excluded.status,
          session_id = excluded.session_id,
          app_commit = excluded.app_commit,
          protocol_version = excluded.protocol_version,
          hw = excluded.hw,
          last_seen = excluded.last_seen
        WHERE status != 'revoked'
        """,
        (
            worker_id,
            label,
            status,
            session_id,
            app_commit,
            protocol_version,
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
        for row in connection.execute("SELECT * FROM workers ORDER BY id")
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
          AND (? IS NULL OR session_id = ?)
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
          AND status IN ('connected', 'building', 'ready', 'busy')
          AND (? IS NULL OR session_id = ?)
        """,
        (utc_now(), worker_id, session_id, session_id),
    )
    return cursor.rowcount > 0


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
          AND (? IS NULL OR session_id = ?)
        """,
        (now, worker_id, session_id, session_id),
    )
    return tournament_ids


def revoke_worker(connection: sqlite3.Connection, worker_id: int) -> None:
    now = utc_now()
    _release_worker_active_assignments(
        connection,
        worker_id,
        now=now,
        reason="worker revoked",
    )
    connection.execute(
        """
        UPDATE workers
        SET status = 'revoked',
            token_hash = NULL,
            token_expires_at = NULL,
            session_id = NULL,
            last_seen = ?
        WHERE id = ?
        """,
        (now, worker_id),
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
            WHERE (game_assignments.white_worker_id = ? OR game_assignments.black_worker_id = ?)
              AND game_assignments.status IN ('assigned', 'acked', 'live')
              AND games.status IN ('assigned', 'live')
            """,
            (worker_id, worker_id),
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
            WHERE (white_worker_id = ? OR black_worker_id = ?)
              AND status IN ('assigned', 'acked', 'live')
          )
        """,
        (worker_id, worker_id),
    )
    connection.execute(
        """
        UPDATE game_assignments
        SET status = 'abandoned',
            finished_at = ?,
            last_error = ?,
            white_worker_id = CASE WHEN white_worker_id = ? THEN NULL ELSE white_worker_id END,
            black_worker_id = CASE WHEN black_worker_id = ? THEN NULL ELSE black_worker_id END
        WHERE (white_worker_id = ? OR black_worker_id = ?)
          AND status IN ('assigned', 'acked', 'live')
        """,
        (now, reason[:500], worker_id, worker_id, worker_id, worker_id),
    )


def delete_worker(connection: sqlite3.Connection, worker_id: int) -> None:
    """Delete a worker and return its active assignments to the pending pool."""
    connection.execute(
        """
        UPDATE games
        SET status = 'pending'
        WHERE status IN ('assigned', 'live')
          AND id IN (
            SELECT game_id
            FROM game_assignments
            WHERE (white_worker_id = ? OR black_worker_id = ?)
              AND status IN ('assigned', 'acked', 'live')
          )
        """,
        (worker_id, worker_id),
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
            white_worker_id = CASE WHEN white_worker_id = ? THEN NULL ELSE white_worker_id END,
            black_worker_id = CASE WHEN black_worker_id = ? THEN NULL ELSE black_worker_id END
        WHERE white_worker_id = ? OR black_worker_id = ?
        """,
        (utc_now(), worker_id, worker_id, worker_id, worker_id),
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
    display_name: str,
    text: str,
) -> int:
    cursor = connection.execute(
        """
        INSERT INTO chat_messages (display_name, text, at)
        VALUES (?, ?, ?)
        """,
        (display_name, text, utc_now()),
    )
    return int(cursor.lastrowid)


def list_chat_messages(
    connection: sqlite3.Connection,
    *,
    limit: int = 50,
) -> tuple[ChatMessageRecord, ...]:
    return tuple(
        _chat_message_from_row(row)
        for row in connection.execute(
            "SELECT * FROM chat_messages ORDER BY id DESC LIMIT ?",
            (limit,),
        )
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


def delete_chat_message(connection: sqlite3.Connection, message_id: int) -> None:
    connection.execute("DELETE FROM chat_messages WHERE id = ?", (message_id,))


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


def request_tournament_rating_commit(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> None:
    now = utc_now()
    connection.execute(
        """
        INSERT INTO tournament_rating_commits (
          tournament_id, category_id, status, requested_at
        )
        VALUES (?, ?, 'pending', ?)
        ON CONFLICT(tournament_id) DO UPDATE SET
          status = 'pending',
          category_id = excluded.category_id,
          requested_at = excluded.requested_at,
          applied_at = NULL,
          error = NULL
        """,
        (tournament.id, tournament.category_id, now),
    )
    enqueue_runner_command(
        connection,
        "commit_tournament_results",
        {
            "tournament_id": tournament.id,
            "category_id": tournament.category_id,
        },
    )


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
        version=row["version"],
        git_url=row["git_url"],
        branch=row["branch"],
        commit=row["commit_hash"],
        build_cmd=row["build_cmd"],
        binary_path=row["binary_path"],
        uci_options=json.loads(row["uci_options"]),
    )


def _engine_record_from_row(row: sqlite3.Row) -> EngineRecord:
    return EngineRecord(
        id=row["id"],
        name=row["name"],
        author=row["author"],
        version=row["version"],
        git_url=row["git_url"],
        branch=row["branch"],
        commit=row["commit_hash"],
        build_cmd=row["build_cmd"],
        binary_path=row["binary_path"],
        uci_options=json.loads(row["uci_options"]),
        active=bool(row["active"]),
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
        display_name=row["display_name"],
        text=row["text"],
        at=row["at"],
    )


def _tournament_from_row(row: sqlite3.Row) -> TournamentRecord:
    config = TournamentConfig.model_validate_json(row["config"])
    config = config.model_copy(
        update={
            "category_id": row["category_id"],
            "category_settings_linked": not bool(row["settings_unlinked"]),
        }
    )
    return TournamentRecord(
        id=row["id"],
        name=row["name"],
        category_id=row["category_id"],
        settings_unlinked=bool(row["settings_unlinked"]),
        config=config,
        status=row["status"],
        current_round=row["current_round"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
    )


def _tournament_rating_commit_from_row(row: sqlite3.Row) -> TournamentRatingCommitRecord:
    return TournamentRatingCommitRecord(
        tournament_id=row["tournament_id"],
        category_id=row["category_id"],
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
        opening_id=row["opening_id"],
        status=row["status"],
        result=row["result"],
        termination=row["termination"],
        pgn=row["pgn"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
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
        hardware_mode=row["hardware_mode"],
        white_worker_id=row["white_worker_id"],
        black_worker_id=row["black_worker_id"],
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
        hw=hw,
        last_seen=row["last_seen"],
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
