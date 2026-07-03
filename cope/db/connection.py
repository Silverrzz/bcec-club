from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path


DEFAULT_DB_PATH = Path("cope.db")


def connect_database(path: str | Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    connection = sqlite3.connect(path)
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
