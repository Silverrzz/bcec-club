from __future__ import annotations

import sqlite3
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


def _ensure_column(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    definition: str,
) -> None:
    columns = {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in connection.execute(f"PRAGMA table_info({table_name})")
    }
    if column_name in columns:
        return

    connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
