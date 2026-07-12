from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from .network import (
    default_admin_token,
    default_web_event_token,
    default_web_event_timeout_s,
    default_web_stream_url,
    default_web_host,
    default_web_port,
    default_worker_host,
    default_worker_port,
    default_worker_server_url,
)


LOG = logging.getLogger("cope.cli")


def main(argv: list[str] | None = None) -> int:
    _install_sigterm_handler()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(prog="python -m cope")
    subparsers = parser.add_subparsers(dest="role", required=True)

    init_db_parser = subparsers.add_parser("init-db", help="initialize the PostgreSQL database")
    init_db_parser.add_argument(
        "--database-url",
        dest="db_path",
        default=_default_db_path(),
        help="PostgreSQL connection URL",
    )

    db_parser = subparsers.add_parser("db", help="database lifecycle operations")
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)
    for command in ("migrate", "check"):
        command_parser = db_subparsers.add_parser(command)
        command_parser.add_argument(
            "--database-url", dest="db_path", default=_default_db_path()
        )
    backup_parser = db_subparsers.add_parser("backup")
    backup_parser.add_argument(
        "--database-url", dest="db_path", default=_default_db_path()
    )
    backup_parser.add_argument("--output", type=Path)
    backup_parser.add_argument("--keep", type=_positive_int, default=7)
    restore_parser = db_subparsers.add_parser("restore")
    restore_parser.add_argument("source", type=Path)
    restore_parser.add_argument(
        "--database-url", dest="db_path", default=_default_db_path()
    )

    subparsers.add_parser("doctor", help="check database and production configuration")
    subparsers.add_parser("version", help="print the COPE release and protocol version")

    build_css_parser = subparsers.add_parser("build-css", help="compile web SCSS")
    build_css_parser.add_argument(
        "--source",
        default="cope/web/static/scss/style.scss",
        help="SCSS source file",
    )
    build_css_parser.add_argument(
        "--output",
        default="cope/web/static/style.css",
        help="CSS output file",
    )

    mint_worker_parser = subparsers.add_parser(
        "mint-worker-token",
        help="mint a one-time worker registration token",
    )
    mint_worker_parser.add_argument("label", help="admin label for the worker")
    mint_worker_parser.add_argument(
        "--ttl-seconds",
        type=int,
        default=7200,
        help="token lifetime in seconds",
    )
    mint_worker_parser.add_argument(
        "--database-url",
        dest="db_path",
        default=_default_db_path(),
        help="PostgreSQL connection URL",
    )
    mint_worker_parser.add_argument("--threads", type=_positive_int, default=1)
    mint_worker_parser.add_argument("--hash-mb", type=_positive_int, default=32)

    web_parser = subparsers.add_parser("web", help="start the web server")
    web_parser.add_argument("--host", default=default_web_host())
    web_parser.add_argument("--port", type=int, default=default_web_port())
    web_parser.add_argument(
        "--worker-server-url",
        default=os.environ.get("COPE_WORKER_SERVER_URL") or None,
        help=(
            "public websocket URL workers should use; by default the web service "
            "uses the worker server endpoint registered in the shared database"
        ),
    )
    web_parser.add_argument(
        "--event-token",
        default=default_web_event_token(),
        help="shared token required for internal service streams",
    )
    web_parser.add_argument(
        "--admin-token",
        default=default_admin_token(),
        help="admin login token, or COPE_ADMIN_TOKEN",
    )
    web_parser.add_argument(
        "--database-url",
        dest="db_path",
        default=_default_db_path(),
        help="PostgreSQL connection URL",
    )

    scheduler_parser = subparsers.add_parser(
        "scheduler",
        help="start the tournament scheduler and command processor",
    )
    scheduler_parser.add_argument(
        "--web-stream-url",
        dest="web_stream_url",
        default=default_web_stream_url(),
        help="web server websocket URL for scheduler event streams",
    )
    scheduler_parser.add_argument(
        "--web-event-token",
        default=default_web_event_token(),
        help="shared token used for the internal web stream",
    )
    scheduler_parser.add_argument(
        "--web-event-timeout-s",
        type=float,
        default=default_web_event_timeout_s(),
        help="seconds to wait when opening the internal web stream",
    )
    scheduler_parser.add_argument(
        "--database-url",
        dest="db_path",
        default=_default_db_path(),
        help="PostgreSQL connection URL",
    )
    scheduler_parser.add_argument(
        "--prototype",
        action="store_true",
        help="run the in-memory prototype tournament",
    )
    scheduler_parser.add_argument(
        "--poll-interval-s",
        type=float,
        default=2.0,
        help="seconds between fallback scans when no stream wake arrives",
    )
    scheduler_parser.add_argument(
        "--once",
        action="store_true",
        help="run one scheduler and command-processing pass, then exit",
    )

    worker_server_parser = subparsers.add_parser(
        "worker-server",
        help="start the worker websocket server",
    )
    worker_server_parser.add_argument(
        "--worker-host",
        default=default_worker_host(),
        help="worker websocket bind host",
    )
    worker_server_parser.add_argument(
        "--worker-port",
        type=_positive_int,
        default=default_worker_port(),
        help="worker websocket bind port",
    )
    worker_server_parser.add_argument("--app-commit", default=_default_app_commit())
    worker_server_parser.add_argument(
        "--web-stream-url",
        dest="web_stream_url",
        default=default_web_stream_url(),
        help="web server websocket URL for worker-server event streams",
    )
    worker_server_parser.add_argument(
        "--web-event-token",
        default=default_web_event_token(),
        help="shared token used for the internal web stream",
    )
    worker_server_parser.add_argument(
        "--web-event-timeout-s",
        type=float,
        default=default_web_event_timeout_s(),
        help="seconds to wait when opening the internal web stream",
    )
    worker_server_parser.add_argument(
        "--database-url",
        dest="db_path",
        default=_default_db_path(),
        help="PostgreSQL connection URL",
    )
    worker_server_parser.add_argument(
        "--poll-interval-s",
        type=float,
        default=float(os.environ.get("COPE_WORKER_ASSIGNMENT_POLL_INTERVAL_S", "10")),
        help="seconds between global worker assignment fallback scans",
    )
    worker_server_parser.add_argument(
        "--presence-flush-interval-s",
        type=float,
        default=float(os.environ.get("COPE_WORKER_PRESENCE_FLUSH_INTERVAL_S", "15")),
        help="seconds between batched worker presence writes",
    )
    worker_server_parser.add_argument(
        "--game-threads",
        type=_positive_int,
        default=int(os.environ.get("COPE_WORKER_GAME_THREADS", "2048")),
        help="maximum simultaneous game orchestration threads",
    )

    worker_parser = subparsers.add_parser("worker", help="start a worker client")
    worker_parser.add_argument("--server-url", default=default_worker_server_url())
    worker_parser.add_argument("--token")
    worker_parser.add_argument("--session-id")
    worker_parser.add_argument("--label-hint", default="")
    worker_parser.add_argument("--app-commit", default=_default_app_commit())
    worker_parser.add_argument(
        "--threads",
        type=_positive_int,
        default=1,
        help="CPU threads reserved for this worker process",
    )
    worker_parser.add_argument(
        "--hash-mb",
        type=_positive_int,
        default=32,
        help="total engine hash memory reserved for this worker process",
    )
    worker_parser.add_argument(
        "--machine-id",
        help="stable machine identity override for containers or isolated environments",
    )

    worker_pool_parser = subparsers.add_parser(
        "worker-pool",
        help="enroll or resume a machine worker pool",
    )
    worker_pool_parser.add_argument("--server-url", default=default_worker_server_url())
    worker_pool_parser.add_argument("--app-commit", default=_default_app_commit())
    worker_pool_parser.add_argument(
        "--state-file",
        type=Path,
        default=Path(".cope-worker/pool.json"),
        help="current-user-only file used to persist pool slot credentials",
    )
    worker_pool_parser.add_argument(
        "--enrollment-token-file",
        type=Path,
        help="read the one-time enrollment token from a file instead of prompting",
    )
    worker_pool_parser.add_argument(
        "--machine-id",
        help="stable machine identity override for containers or isolated environments",
    )

    args = parser.parse_args(argv)

    if args.role == "version":
        from .core.models import PROTOCOL_VERSION

        print(f"cope-chess 0.1.0 commit={_default_app_commit()} protocol={PROTOCOL_VERSION}")
        return 0

    if args.role == "doctor":
        return _doctor()

    if args.role == "db":
        return _database_command(args)

    if args.role == "init-db":
        from .db import initialize_database

        db_path = args.db_path
        initialize_database(db_path)
        print("initialized PostgreSQL database")
        return 0

    if args.role == "build-css":
        _build_css(Path(args.source), Path(args.output))
        return 0

    if args.role == "mint-worker-token":
        from .db import connect_database, initialize_database, mint_worker_token

        db_path = args.db_path
        initialize_database(db_path)
        connection = connect_database(db_path)
        try:
            token = mint_worker_token(
                connection,
                label=args.label,
                ttl_seconds=args.ttl_seconds,
                assigned_threads=args.threads,
                assigned_hash_mb=args.hash_mb,
            )
            connection.commit()
        finally:
            connection.close()

        print(f"worker_id={token.worker_id}")
        print(f"expires_at={token.expires_at}")
        print(f"token={token.token}")
        return 0

    if args.role in {"scheduler", "worker-server"}:
        from .runner.events import configure_event_publisher

        configure_event_publisher(
            url=args.web_stream_url,
            token=args.web_event_token,
            timeout_s=args.web_event_timeout_s,
        )

    if args.role == "worker-server":
        from .runner.worker_server import WorkerServerConfig, run_worker_server

        config = WorkerServerConfig(
            host=args.worker_host,
            port=args.worker_port,
            db_path=args.db_path,
            expected_app_commit=args.app_commit,
            assignment_poll_interval_s=args.poll_interval_s,
            presence_flush_interval_s=args.presence_flush_interval_s,
            game_thread_count=args.game_threads,
        )
        try:
            asyncio.run(run_worker_server(config))
        except KeyboardInterrupt:
            LOG.info("worker server stopped")
            return 130
        return 0

    if args.role == "scheduler":
        if args.prototype:
            from .prototype import run_prototype_tournament

            run_prototype_tournament()
            return 0

        from .db import connect_database
        from .runner import (
            RunnerServiceConfig,
            print_runner_report,
            run_tournament_matches,
            run_tournament_service,
        )

        db_path = args.db_path
        if not args.once:
            config = RunnerServiceConfig(
                db_path=db_path,
                poll_interval_s=args.poll_interval_s,
            )
            try:
                run_tournament_service(config)
            except KeyboardInterrupt:
                LOG.info("scheduler stopped")
                return 130
            return 0

        connection = connect_database(db_path)
        try:
            report = run_tournament_matches(connection)
        finally:
            connection.close()

        print_runner_report(report)

        if (
            not report.prepared
            and report.tournaments_finished == 0
            and report.commands_applied == 0
            and report.commands_failed == 0
        ):
            LOG.info("no scheduled tournaments to prepare")
            return 0

        return 0

    if args.role == "web":
        import uvicorn

        from .web.app import create_app

        uvicorn.run(
            create_app(
                args.db_path,
                worker_server_url=args.worker_server_url,
                event_token=args.event_token,
                admin_token=args.admin_token,
            ),
            host=args.host,
            port=args.port,
        )
        return 0

    if args.role == "worker":
        from .worker.client import WorkerClientConfig, run_worker_client

        config = WorkerClientConfig(
            server_url=args.server_url,
            app_commit=args.app_commit,
            token=args.token,
            session_id=args.session_id,
            label_hint=args.label_hint,
            threads=args.threads,
            hash_mb=args.hash_mb,
            machine_id=args.machine_id,
        )
        try:
            asyncio.run(run_worker_client(config))
        except KeyboardInterrupt:
            LOG.info("worker stopped")
            return 130
        return 0

    if args.role == "worker-pool":
        from .worker.pool import WorkerPoolConfig, run_worker_pool

        config = WorkerPoolConfig(
            server_url=args.server_url,
            app_commit=args.app_commit,
            state_file=args.state_file,
            enrollment_token_file=args.enrollment_token_file,
            machine_id=args.machine_id,
        )
        try:
            asyncio.run(run_worker_pool(config))
        except KeyboardInterrupt:
            LOG.info("worker pool stopped")
            return 130
        return 0

    parser.error(f"unknown role: {args.role}")
    return 2


def _default_app_commit() -> str:
    return os.environ.get("COPE_DEPLOY_COMMIT", "dev")


def _install_sigterm_handler() -> None:
    if not hasattr(signal, "SIGTERM"):
        return

    def stop(_signum, _frame) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def _default_db_path() -> str:
    return os.environ.get("COPE_DATABASE_URL", "postgresql://cope@127.0.0.1:5432/cope")


def _build_css(source: Path, output: Path) -> None:
    try:
        import sass
    except ImportError as exc:
        raise SystemExit(
            "Missing SCSS compiler. Install web dependencies with: "
            'py -m pip install -e ".[web]"'
        ) from exc

    output.parent.mkdir(parents=True, exist_ok=True)
    css = sass.compile(filename=str(source), output_style="expanded")
    output.write_text(css, encoding="utf-8")
    print(f"compiled {source} -> {output}")


def _database_command(args) -> int:
    from .db import (
        SCHEMA_VERSION,
        connect_database,
        database_schema_version,
        initialize_database,
    )

    database_url = args.db_path
    if args.db_command == "migrate":
        initialize_database(database_url)
        print(f"database migrated schema={SCHEMA_VERSION}")
        return 0

    if args.db_command == "check":
        connection = connect_database(database_url)
        try:
            result = connection.execute("SELECT 1 AS ready").fetchone()
            version = database_schema_version(connection)
        finally:
            connection.close()
        ready = bool(result and result["ready"] == 1)
        print(f"database ready={ready} schema={version}/{SCHEMA_VERSION}")
        return 0 if ready and version == SCHEMA_VERSION else 1

    if args.db_command == "backup":
        initialize_database(database_url)
        output = args.output or Path("backups") / (
            "cope-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + ".dump"
        )
        output = output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["pg_dump", "--format=custom", "--file", str(output), database_url],
            check=True,
            env=_postgres_command_env(),
        )
        backups = sorted(
            output.parent.glob("cope-*.dump"), key=lambda path: path.stat().st_mtime
        )
        for stale in backups[:-args.keep]:
            stale.unlink()
        print(f"database backup created at {output}")
        return 0

    if args.db_command == "restore":
        source_path = args.source.expanduser().resolve()
        if not source_path.is_file():
            raise SystemExit(f"backup does not exist: {source_path}")
        subprocess.run(
            [
                "pg_restore",
                "--clean",
                "--if-exists",
                "--no-owner",
                "--dbname",
                database_url,
                str(source_path),
            ],
            check=True,
            env=_postgres_command_env(),
        )
        print(f"database restored from {source_path}")
        return 0

    raise SystemExit(f"unknown database command: {args.db_command}")


def _doctor() -> int:
    from .db import SCHEMA_VERSION, connect_database, database_schema_version

    failures: list[str] = []
    database_url = _default_db_path()
    try:
        connection = connect_database(database_url)
        try:
            ready = connection.execute("SELECT 1 AS ready").fetchone()
            version = database_schema_version(connection)
        finally:
            connection.close()
        if not ready or ready["ready"] != 1:
            failures.append("database readiness query failed")
        if version != SCHEMA_VERSION:
            failures.append(f"database schema is {version}, expected {SCHEMA_VERSION}")
    except Exception as exc:
        failures.append(f"database unavailable: {exc}")
    if not default_admin_token():
        failures.append("COPE_ADMIN_TOKEN or COPE_ADMIN_TOKEN_FILE is not configured")
    if not default_web_event_token():
        failures.append("COPE_WEB_EVENT_TOKEN or COPE_WEB_EVENT_TOKEN_FILE is not configured")
    if failures:
        for failure in failures:
            print(f"FAIL {failure}")
        return 1
    print(f"OK database=postgresql schema={SCHEMA_VERSION}")
    return 0


def _postgres_command_env() -> dict[str, str]:
    environment = os.environ.copy()
    password = os.environ.get("COPE_DATABASE_PASSWORD")
    password_file = os.environ.get("COPE_DATABASE_PASSWORD_FILE")
    if password_file:
        password = Path(password_file).read_text(encoding="utf-8").strip()
    if password:
        environment["PGPASSWORD"] = password
    return environment


if __name__ == "__main__":
    raise SystemExit(main())
