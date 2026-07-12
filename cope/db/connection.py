from __future__ import annotations

import os
import re
import sqlite3
import threading
import atexit
from importlib import resources
from pathlib import Path
from typing import Any, Iterable, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


DEFAULT_DATABASE_URL = "postgresql://cope@127.0.0.1:5432/cope"
# Kept as an import alias while the rest of the application moves from the old
# path-shaped setting to a PostgreSQL URL.
DEFAULT_DB_PATH = DEFAULT_DATABASE_URL
SCHEMA_VERSION = 4

_PLACEHOLDER = re.compile(r"\?")
_pools: dict[tuple[str, str | None], ConnectionPool] = {}
_pools_lock = threading.Lock()
_password_unset = object()
_password_cache: str | None | object = _password_unset


def default_database_url() -> str:
    return os.environ.get("COPE_DATABASE_URL", DEFAULT_DATABASE_URL)


def _database_password() -> str | None:
    global _password_cache
    if _password_cache is not _password_unset:
        return _password_cache  # type: ignore[return-value]
    value = os.environ.get("COPE_DATABASE_PASSWORD")
    file_name = os.environ.get("COPE_DATABASE_PASSWORD_FILE")
    if value and file_name:
        raise ValueError(
            "set only one of COPE_DATABASE_PASSWORD or COPE_DATABASE_PASSWORD_FILE"
        )
    if file_name:
        try:
            value = Path(file_name).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(f"could not read COPE_DATABASE_PASSWORD_FILE: {exc}") from exc
    _password_cache = value or None
    return _password_cache


def _pool(database_url: str) -> ConnectionPool:
    password = _database_password()
    key = (database_url, password)
    existing = _pools.get(key)
    if existing is not None:
        return existing
    with _pools_lock:
        pool = _pools.get(key)
        if pool is None:
            min_size = max(int(os.environ.get("COPE_DATABASE_POOL_MIN", "2")), 0)
            max_size = max(int(os.environ.get("COPE_DATABASE_POOL_MAX", "50")), 1)
            if min_size > max_size:
                raise ValueError("COPE_DATABASE_POOL_MIN cannot exceed COPE_DATABASE_POOL_MAX")
            kwargs: dict[str, Any] = {
                "row_factory": dict_row,
                "connect_timeout": 10,
                "application_name": "cope-chess",
            }
            if password is not None:
                kwargs["password"] = password
            pool = ConnectionPool(
                conninfo=database_url,
                min_size=min_size,
                max_size=max_size,
                timeout=10,
                kwargs=kwargs,
                open=True,
            )
            _pools[key] = pool
        return pool


def close_database_pools() -> None:
    with _pools_lock:
        pools = list(_pools.values())
        _pools.clear()
    for pool in pools:
        pool.close()


atexit.register(close_database_pools)


class DatabaseCursor:
    def __init__(self, connection: DatabaseConnection, cursor) -> None:
        self._connection = connection
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self) -> int:
        row = self._connection.execute("SELECT lastval() AS id").fetchone()
        if row is None:
            raise RuntimeError("insert did not generate an id")
        return int(row["id"])

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def __iter__(self) -> Iterator[dict[str, Any]]:
        return iter(self._cursor)


class DatabaseConnection:
    """Lazy pooled PostgreSQL connection with the repository's small DB-API surface."""

    def __init__(self, database_url: str) -> None:
        self.database_url = database_url
        self._pool = _pool(database_url)
        self._raw = None
        self._closed = False

    def _connection(self):
        if self._closed:
            raise sqlite3.ProgrammingError("database connection is closed")
        if self._raw is None:
            try:
                self._raw = self._pool.getconn()
            except Exception as exc:
                raise sqlite3.DatabaseError(f"database pool unavailable: {exc}") from exc
        return self._raw

    def execute(self, sql: str, parameters: Iterable[Any] | None = None) -> DatabaseCursor:
        translated = _translate_sql(sql)
        try:
            cursor = self._connection().execute(translated, tuple(parameters or ()))
        except psycopg.IntegrityError as exc:
            raise sqlite3.IntegrityError(str(exc)) from exc
        except psycopg.Error as exc:
            raise sqlite3.DatabaseError(str(exc)) from exc
        return DatabaseCursor(self, cursor)

    def executemany(self, sql: str, parameters: Iterable[Iterable[Any]]) -> DatabaseCursor:
        translated = _translate_sql(sql)
        try:
            cursor = self._connection().cursor()
            cursor.executemany(translated, parameters)
        except psycopg.IntegrityError as exc:
            raise sqlite3.IntegrityError(str(exc)) from exc
        except psycopg.Error as exc:
            raise sqlite3.DatabaseError(str(exc)) from exc
        return DatabaseCursor(self, cursor)

    def commit(self) -> None:
        if self._raw is None:
            return
        raw, self._raw = self._raw, None
        try:
            raw.commit()
        finally:
            self._pool.putconn(raw)

    def rollback(self) -> None:
        if self._raw is None:
            return
        raw, self._raw = self._raw, None
        try:
            raw.rollback()
        finally:
            self._pool.putconn(raw)

    def close(self) -> None:
        if self._closed:
            return
        self.rollback()
        self._closed = True


def _translate_sql(sql: str) -> str:
    statement = sql.strip()
    if statement.upper() == "BEGIN IMMEDIATE":
        return "BEGIN"
    return _PLACEHOLDER.sub("%s", sql)


def connect_database(
    database_url: str | Path | None = None,
    *,
    check_same_thread: bool = True,
) -> DatabaseConnection:
    del check_same_thread
    value = str(database_url) if database_url is not None else default_database_url()
    if not value.startswith(("postgresql://", "postgres://")):
        raise ValueError("COPE_DATABASE_URL must be a PostgreSQL URL")
    return DatabaseConnection(value)


def initialize_database(database_url: str | Path | None = None) -> None:
    connection = connect_database(database_url)
    try:
        initialize_connection(connection)
        connection.commit()
    finally:
        connection.close()


def initialize_connection(connection: DatabaseConnection) -> None:
    schema = resources.files("cope.db").joinpath("schema.sql").read_text(encoding="utf-8")
    try:
        connection._connection().execute(schema)
    except psycopg.Error as exc:
        raise sqlite3.DatabaseError(str(exc)) from exc


def database_schema_version(connection: DatabaseConnection) -> int:
    row = connection.execute(
        "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
    ).fetchone()
    return int(row["value"]) if row is not None else 0
