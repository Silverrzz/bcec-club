from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from importlib import resources
from pathlib import Path


DEFAULT_DB_PATH = Path("cope.db")
SCHEMA_VERSION = 1


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
    current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
    if current_version > SCHEMA_VERSION:
        raise RuntimeError(
            f"database schema version {current_version} is newer than supported version {SCHEMA_VERSION}"
        )
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
    _ensure_column(connection, "tournaments", "worker_profile", "TEXT")
    _allow_custom_tournaments_without_categories(connection)
    _backfill_tournament_worker_profiles(connection)
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
    _ensure_column(
        connection,
        "engines",
        "required_dependencies",
        "TEXT NOT NULL DEFAULT '[]'",
    )
    _ensure_column(connection, "moves", "nps", "INTEGER")
    _ensure_column(connection, "moves", "pv", "TEXT")
    _ensure_column(connection, "moves", "info_line", "TEXT")
    _ensure_column(
        connection,
        "chat_messages",
        "tournament_id",
        "INTEGER REFERENCES tournaments(id) ON DELETE CASCADE",
    )
    _enforce_tournament_chat_channels(connection)
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_chat_messages_tournament_id "
        "ON chat_messages(tournament_id, id DESC)"
    )
    _ensure_column(
        connection,
        "games",
        "match_id",
        "INTEGER REFERENCES tournament_matches(id) ON DELETE SET NULL",
    )
    _ensure_column(connection, "games", "game_number", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(connection, "games", "tiebreak_kind", "TEXT")
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_games_match_number ON games(match_id, game_number)"
    )
    _ensure_column(connection, "tournament_rating_commits", "command_id", "INTEGER")
    _ensure_column(connection, "rating_history", "tournament_id", "INTEGER")
    _ensure_column(connection, "rating_history", "opponent_engine_id", "INTEGER")
    _ensure_column(connection, "rating_history", "elo_before", "REAL")
    _ensure_column(connection, "rating_history", "elo_change", "REAL")
    _ensure_column(connection, "rating_history", "score", "REAL")
    _ensure_column(connection, "workers", "machine_id", "TEXT")
    _ensure_column(connection, "workers", "pool_id", "INTEGER")
    _ensure_column(connection, "workers", "pool_slot_token_hash", "TEXT")
    _ensure_column(
        connection,
        "workers",
        "available_dependencies",
        "TEXT NOT NULL DEFAULT '[]'",
    )
    _ensure_column(connection, "workers", "dependency_manifest_revision", "TEXT")
    _ensure_column(connection, "workers", "dependencies_checked_at", "TEXT")
    _ensure_column(
        connection,
        "workers",
        "assigned_threads",
        "INTEGER NOT NULL DEFAULT 1 CHECK (assigned_threads > 0)",
    )
    _ensure_column(
        connection,
        "workers",
        "assigned_hash_mb",
        "INTEGER NOT NULL DEFAULT 32 CHECK (assigned_hash_mb > 0)",
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_rating_history_engine_category_game
        ON rating_history(engine_id, category_id, game_id)
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tournament_rating_commits_command
        ON tournament_rating_commits(command_id)
        WHERE command_id IS NOT NULL
        """
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS idx_workers_pool_id ON workers(pool_id)"
    )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_workers_pool_slot_token_hash "
        "ON workers(pool_slot_token_hash) WHERE pool_slot_token_hash IS NOT NULL"
    )
    _migrate_game_assignments_to_single_worker(connection)
    _remove_legacy_hardware_mode_from_configs(connection)
    _migrate_round_robin_games_per_pairing(connection)
    _clear_legacy_worker_registration_tokens(connection)
    _repair_aborted_tournament_games(connection)
    _recover_interrupted_runner_commands(connection)
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def database_schema_version(connection: sqlite3.Connection) -> int:
    return int(connection.execute("PRAGMA user_version").fetchone()[0])


def _allow_custom_tournaments_without_categories(connection: sqlite3.Connection) -> None:
    columns = connection.execute("PRAGMA table_info(tournaments)").fetchall()
    category = next((column for column in columns if column["name"] == "category_id"), None)
    if category is None or not category["notnull"]:
        return

    foreign_keys_enabled = bool(connection.execute("PRAGMA foreign_keys").fetchone()[0])
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.executescript(
            """
            DROP TABLE IF EXISTS tournaments_new;
            CREATE TABLE tournaments_new (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              category_id INTEGER REFERENCES categories(id),
              settings_unlinked INTEGER NOT NULL DEFAULT 0
                CHECK (settings_unlinked IN (0, 1)),
              config TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft', 'scheduled', 'running', 'paused', 'finished', 'aborted')),
              current_round INTEGER NOT NULL DEFAULT 0,
              worker_profile TEXT,
              created_at TEXT NOT NULL,
              started_at TEXT,
              finished_at TEXT
            );

            INSERT INTO tournaments_new (
              id, name, category_id, settings_unlinked, config, status,
              current_round, worker_profile, created_at, started_at, finished_at
            )
            SELECT
              id, name,
              CASE WHEN settings_unlinked = 1 THEN NULL ELSE category_id END,
              settings_unlinked, config, status, current_round, worker_profile,
              created_at, started_at, finished_at
            FROM tournaments;

            DROP TABLE tournaments;
            ALTER TABLE tournaments_new RENAME TO tournaments;
            """
        )
    finally:
        if foreign_keys_enabled:
            connection.execute("PRAGMA foreign_keys = ON")


def _clear_legacy_worker_registration_tokens(connection: sqlite3.Connection) -> None:
    if not _column_exists(connection, "workers", "registration_token"):
        return

    connection.execute(
        "UPDATE workers SET registration_token = NULL WHERE registration_token IS NOT NULL"
    )


def _backfill_tournament_worker_profiles(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT tournaments.id AS tournament_id, games.white_hw
        FROM tournaments
        JOIN games ON games.tournament_id = tournaments.id
        WHERE tournaments.worker_profile IS NULL
          AND games.white_hw IS NOT NULL
        ORDER BY tournaments.id, games.id
        """
    )
    seen: set[int] = set()
    for row in rows:
        tournament_id = int(row["tournament_id"])
        if tournament_id in seen:
            continue
        seen.add(tournament_id)
        try:
            hardware = json.loads(row["white_hw"])
            cpu_model = str(hardware["cpu_model"]).strip()
            if cpu_model.casefold() in {
                "unknown",
                "x86_64",
                "amd64",
                "arm64",
                "aarch64",
            }:
                continue
            profile = {
                "cpu_model": cpu_model,
                "physical_cores": int(hardware["physical_cores"]),
                "logical_cores": int(hardware["logical_cores"]),
                "os": str(hardware["os"]).strip(),
            }
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
        connection.execute(
            "UPDATE tournaments SET worker_profile = ? WHERE id = ? AND worker_profile IS NULL",
            (json.dumps(profile, sort_keys=True, separators=(",", ":")), tournament_id),
        )


def _migrate_game_assignments_to_single_worker(
    connection: sqlite3.Connection,
) -> None:
    columns = _table_columns(connection, "game_assignments")
    legacy_columns = {"hardware_mode", "white_worker_id", "black_worker_id"}
    if "worker_id" in columns and not columns.intersection(legacy_columns):
        return

    if "worker_id" in columns:
        worker_id = "COALESCE(worker_id, white_worker_id, black_worker_id)"
    else:
        worker_id = "COALESCE(white_worker_id, black_worker_id)"

    connection.execute("DROP TABLE IF EXISTS game_assignments_single_worker")
    connection.execute(
        """
        CREATE TABLE game_assignments_single_worker (
          id INTEGER PRIMARY KEY,
          game_id INTEGER NOT NULL UNIQUE REFERENCES games(id) ON DELETE CASCADE,
          assignment_key TEXT NOT NULL UNIQUE,
          worker_id INTEGER REFERENCES workers(id) ON DELETE SET NULL,
          status TEXT NOT NULL DEFAULT 'assigned'
            CHECK (status IN ('assigned', 'acked', 'live', 'finished', 'abandoned', 'expired')),
          sent_at TEXT,
          acked_at TEXT,
          finished_at TEXT,
          last_error TEXT
        )
        """
    )
    connection.execute(
        f"""
        INSERT INTO game_assignments_single_worker (
          id, game_id, assignment_key, worker_id, status, sent_at, acked_at,
          finished_at, last_error
        )
        SELECT
          id, game_id, assignment_key, {worker_id}, status, sent_at, acked_at,
          finished_at, last_error
        FROM game_assignments
        """
    )
    connection.execute("DROP TABLE game_assignments")
    connection.execute(
        "ALTER TABLE game_assignments_single_worker RENAME TO game_assignments"
    )


def _remove_legacy_hardware_mode_from_configs(
    connection: sqlite3.Connection,
) -> None:
    for table_name, id_column, config_column in (
        ("tournaments", "id", "config"),
        ("categories", "id", "default_config"),
    ):
        for row in connection.execute(
            f"SELECT {id_column}, {config_column} FROM {table_name}"
        ):
            config = json.loads(row[config_column])
            if not isinstance(config, dict) or "hardware_mode" not in config:
                continue
            config.pop("hardware_mode")
            connection.execute(
                f"UPDATE {table_name} SET {config_column} = ? WHERE {id_column} = ?",
                (json.dumps(config, separators=(",", ":")), row[id_column]),
            )


def _migrate_round_robin_games_per_pairing(connection: sqlite3.Connection) -> None:
    for table_name, id_column, config_column in (
        ("tournaments", "id", "config"),
        ("categories", "id", "default_config"),
    ):
        for row in connection.execute(
            f"SELECT {id_column}, {config_column} FROM {table_name}"
        ):
            config = json.loads(row[config_column])
            if not isinstance(config, dict) or config.get("format") != "round_robin":
                continue
            options = config.get("format_options")
            if not isinstance(options, dict) or "double_rr" not in options:
                continue
            options["games_per_pairing"] = 2 if options.pop("double_rr") else 1
            connection.execute(
                f"UPDATE {table_name} SET {config_column} = ? WHERE {id_column} = ?",
                (json.dumps(config, separators=(",", ":")), row[id_column]),
            )


def _enforce_tournament_chat_channels(connection: sqlite3.Connection) -> None:
    tournament_column = next(
        (
            row
            for row in connection.execute("PRAGMA table_info(chat_messages)")
            if row["name"] == "tournament_id"
        ),
        None,
    )
    if tournament_column is not None and tournament_column["notnull"]:
        return

    connection.execute("DROP TABLE IF EXISTS chat_messages_with_channels")
    connection.execute(
        """
        CREATE TABLE chat_messages_with_channels (
          id INTEGER PRIMARY KEY,
          tournament_id INTEGER NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
          display_name TEXT NOT NULL,
          text TEXT NOT NULL,
          at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """
        INSERT INTO chat_messages_with_channels (id, tournament_id, display_name, text, at)
        SELECT id, tournament_id, display_name, text, at
        FROM chat_messages
        WHERE tournament_id IS NOT NULL
        """
    )
    connection.execute("DROP TABLE chat_messages")
    connection.execute("ALTER TABLE chat_messages_with_channels RENAME TO chat_messages")


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


def _recover_interrupted_runner_commands(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        UPDATE runner_commands
        SET status = 'pending', claimed_at = NULL
        WHERE status = 'claimed'
        """
    )
    connection.execute(
        """
        UPDATE tournament_rating_commits
        SET status = 'pending'
        WHERE status = 'claimed'
        """
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
    return column_name in _table_columns(connection, table_name)


def _table_columns(
    connection: sqlite3.Connection,
    table_name: str,
) -> set[str]:
    return {
        row["name"] if isinstance(row, sqlite3.Row) else row[1]
        for row in connection.execute(f"PRAGMA table_info({table_name})")
    }
