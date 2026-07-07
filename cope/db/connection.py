from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path


DEFAULT_DB_PATH = Path("cope.db")


def connect_database(
    path: str | Path = DEFAULT_DB_PATH,
    *,
    check_same_thread: bool = True,
) -> sqlite3.Connection:
    connection = sqlite3.connect(path, check_same_thread=check_same_thread)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


def initialize_database(path: str | Path = DEFAULT_DB_PATH) -> None:
    connection = connect_database(path)
    try:
        initialize_connection(connection)
        connection.commit()
    finally:
        connection.close()


def initialize_connection(connection: sqlite3.Connection) -> None:
    schema = resources.files("cope.db").joinpath("schema.sql").read_text(encoding="utf-8")
    connection.executescript(schema)
    _ensure_column(
        connection,
        "tournaments",
        "category_id",
        "INTEGER NOT NULL DEFAULT 1",
    )
    _ensure_column(
        connection,
        "tournaments",
        "settings_unlinked",
        "INTEGER NOT NULL DEFAULT 0 CHECK (settings_unlinked IN (0, 1))",
    )
    _ensure_column(
        connection,
        "engines",
        "version",
        "TEXT NOT NULL DEFAULT ''",
    )
    _ensure_column(
        connection,
        "engines",
        "branch",
        "TEXT NOT NULL DEFAULT ''",
    )
    _ensure_column(connection, "moves", "nps", "INTEGER")
    _ensure_column(connection, "moves", "pv", "TEXT")
    _ensure_column(connection, "moves", "info_line", "TEXT")
    _clear_legacy_worker_registration_tokens(connection)
    _repair_aborted_tournament_games(connection)


def _clear_legacy_worker_registration_tokens(connection: sqlite3.Connection) -> None:
    if not _column_exists(connection, "workers", "registration_token"):
        return

    connection.execute(
        "UPDATE workers SET registration_token = NULL WHERE registration_token IS NOT NULL"
    )


def _repair_aborted_tournament_games(connection: sqlite3.Connection) -> None:
    now = datetime.now(UTC).isoformat(timespec="seconds")
    reason = "tournament aborted"
    connection.execute(
        """
        UPDATE game_assignments
        SET status = 'abandoned',
            finished_at = COALESCE(finished_at, ?),
            last_error = COALESCE(last_error, ?)
        WHERE status IN ('assigned', 'acked', 'live')
          AND game_id IN (
            SELECT games.id
            FROM games
            JOIN tournaments ON tournaments.id = games.tournament_id
            WHERE tournaments.status = 'aborted'
              AND games.status != 'finished'
          )
        """,
        (now, reason),
    )
    connection.execute(
        """
        UPDATE games
        SET status = 'abandoned',
            termination = COALESCE(termination, ?),
            finished_at = COALESCE(
              finished_at,
              (
                SELECT tournaments.finished_at
                FROM tournaments
                WHERE tournaments.id = games.tournament_id
              ),
              ?
            )
        WHERE status != 'finished'
          AND tournament_id IN (
            SELECT id
            FROM tournaments
            WHERE status = 'aborted'
          )
        """,
        (reason, now),
    )


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    if _column_exists(connection, table_name, column_name):
        return

    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")


def _column_exists(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
) -> bool:
    return column_name in {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in connection.execute(f"PRAGMA table_info({table_name})")
    }
