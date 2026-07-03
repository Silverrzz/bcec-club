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
class TournamentRecord:
    id: int
    name: str
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
    time_ms: int
    clock_after_ms: int


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
class WorkerToken:
    worker_id: int
    token: str
    expires_at: str


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
          id, name, author, git_url, commit_hash, build_cmd, binary_path,
          uci_options, active
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            spec.engine_id,
            spec.name,
            author,
            spec.git_url,
            spec.commit,
            spec.build_cmd,
            spec.binary_path,
            _json_dump(spec.uci_options),
            int(active),
        ),
    )
    return spec.engine_id


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
        INSERT INTO tournaments (name, config, status, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (name, config.model_dump_json(), status, created_at),
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
    time_ms: int = 0,
    clock_after_ms: int = 0,
) -> None:
    connection.execute(
        """
        INSERT INTO moves (
          game_id, ply, uci, san, is_book, eval_cp, eval_mate, depth,
          nodes, time_ms, clock_after_ms
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def mint_worker_token(
    connection: sqlite3.Connection,
    *,
    label: str,
    ttl_seconds: int = 7200,
) -> WorkerToken:
    token = secrets.token_urlsafe(32)
    expires_at = (utc_now_datetime() + timedelta(seconds=ttl_seconds)).isoformat(
        timespec="seconds"
    )
    cursor = connection.execute(
        """
        INSERT INTO workers (label, token_hash, token_expires_at, status)
        VALUES (?, ?, ?, 'minted')
        """,
        (label, hash_worker_token(token), expires_at),
    )
    return WorkerToken(
        worker_id=int(cursor.lastrowid),
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


def _engine_from_row(row: sqlite3.Row) -> EngineSpec:
    return EngineSpec(
        engine_id=row["id"],
        name=row["name"],
        git_url=row["git_url"],
        commit=row["commit_hash"],
        build_cmd=row["build_cmd"],
        binary_path=row["binary_path"],
        uci_options=json.loads(row["uci_options"]),
    )


def _tournament_from_row(row: sqlite3.Row) -> TournamentRecord:
    config = TournamentConfig.model_validate_json(row["config"])
    return TournamentRecord(
        id=row["id"],
        name=row["name"],
        config=config,
        status=row["status"],
        current_round=row["current_round"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
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
        time_ms=row["time_ms"],
        clock_after_ms=row["clock_after_ms"],
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
