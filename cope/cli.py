from __future__ import annotations

import argparse
import asyncio
import logging
import os
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
from .prototype import run_prototype_tournament


LOG = logging.getLogger("cope.cli")


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    parser = argparse.ArgumentParser(prog="python -m cope")
    subparsers = parser.add_subparsers(dest="role", required=True)

    init_db_parser = subparsers.add_parser("init-db", help="initialize the SQLite database")
    init_db_parser.add_argument(
        "--db-path",
        default=_default_db_path(),
        help="path to the SQLite database file",
    )

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
        "--db-path",
        default=_default_db_path(),
        help="path to the SQLite database file",
    )

    web_parser = subparsers.add_parser("web", help="start the web server")
    web_parser.add_argument("--host", default=default_web_host())
    web_parser.add_argument("--port", type=int, default=default_web_port())
    web_parser.add_argument(
        "--worker-server-url",
        default=default_worker_server_url(),
        help="public websocket URL workers should use to reach the runner",
    )
    web_parser.add_argument(
        "--event-token",
        default=default_web_event_token(),
        help="shared token required for internal runner streams",
    )
    web_parser.add_argument(
        "--admin-token",
        default=default_admin_token(),
        help="admin login token, or COPE_ADMIN_TOKEN",
    )
    web_parser.add_argument(
        "--db-path",
        default=_default_db_path(),
        help="path to the SQLite database file",
    )

    runner_parser = subparsers.add_parser("runner", help="start the tournament runner")
    runner_parser.add_argument(
        "--worker-server",
        action="store_true",
        help="run only the worker websocket handshake server",
    )
    runner_parser.add_argument(
        "--worker-host",
        default=default_worker_host(),
        help="worker websocket bind host",
    )
    runner_parser.add_argument(
        "--worker-port",
        type=int,
        default=default_worker_port(),
        help="worker websocket bind port",
    )
    runner_parser.add_argument("--app-commit", default=_default_app_commit())
    runner_parser.add_argument(
        "--web-stream-url",
        dest="web_stream_url",
        default=default_web_stream_url(),
        help="web server websocket URL for runner event streams",
    )
    runner_parser.add_argument(
        "--web-event-token",
        default=default_web_event_token(),
        help="shared token used for the internal web stream",
    )
    runner_parser.add_argument(
        "--web-event-timeout-s",
        type=float,
        default=default_web_event_timeout_s(),
        help="seconds to wait when opening the internal web stream",
    )
    runner_parser.add_argument(
        "--db-path",
        default=_default_db_path(),
        help="path to the SQLite database file",
    )
    runner_parser.add_argument(
        "--prototype",
        action="store_true",
        help="run the in-memory prototype tournament",
    )
    runner_parser.add_argument(
        "--poll-interval-s",
        type=float,
        default=2.0,
        help="seconds between fallback scans when no stream wake arrives",
    )
    runner_parser.add_argument(
        "--once",
        action="store_true",
        help="run one scheduler/execution pass and exit",
    )

    worker_parser = subparsers.add_parser("worker", help="start a worker client")
    worker_parser.add_argument("--server-url", default=default_worker_server_url())
    worker_parser.add_argument("--token")
    worker_parser.add_argument("--session-id")
    worker_parser.add_argument("--label-hint", default="")
    worker_parser.add_argument("--app-commit", default=_default_app_commit())

    args = parser.parse_args(argv)

    if args.role == "init-db":
        from .db import initialize_database

        db_path = Path(args.db_path)
        initialize_database(db_path)
        print(f"initialized database at {db_path}")
        return 0

    if args.role == "build-css":
        _build_css(Path(args.source), Path(args.output))
        return 0

    if args.role == "mint-worker-token":
        from .db import connect_database, initialize_database, mint_worker_token

        db_path = Path(args.db_path)
        initialize_database(db_path)
        connection = connect_database(db_path)
        try:
            token = mint_worker_token(
                connection,
                label=args.label,
                ttl_seconds=args.ttl_seconds,
            )
            connection.commit()
        finally:
            connection.close()

        print(f"worker_id={token.worker_id}")
        print(f"expires_at={token.expires_at}")
        print(f"token={token.token}")
        return 0

    if args.role == "runner":
        from .runner.events import configure_event_publisher

        configure_event_publisher(
            url=args.web_stream_url,
            token=args.web_event_token,
            timeout_s=args.web_event_timeout_s,
        )

        if args.worker_server:
            from .runner.worker_server import WorkerServerConfig, run_worker_server

            config = WorkerServerConfig(
                host=args.worker_host,
                port=args.worker_port,
                db_path=args.db_path,
                expected_app_commit=args.app_commit,
                assignment_poll_interval_s=args.poll_interval_s,
            )
            try:
                asyncio.run(run_worker_server(config))
            except KeyboardInterrupt:
                LOG.info("runner stopped")
                return 130
            return 0

        if args.prototype:
            run_prototype_tournament()
            return 0

        from .db import connect_database, initialize_database
        from .runner import (
            RunnerServiceConfig,
            print_runner_report,
            run_tournament_matches,
            run_tournament_service,
        )

        db_path = Path(args.db_path)
        initialize_database(db_path)
        if not args.once:
            config = RunnerServiceConfig(
                db_path=db_path,
                poll_interval_s=args.poll_interval_s,
            )
            try:
                run_tournament_service(config)
            except KeyboardInterrupt:
                LOG.info("runner stopped")
                return 130
            return 0

        connection = connect_database(db_path)
        try:
            report = run_tournament_matches(connection)
        finally:
            connection.close()

        print_runner_report(report)

        if not report.prepared and report.tournaments_finished == 0 and not report.errors:
            LOG.info("no scheduled tournaments to prepare")
            return 0

        return 0

    if args.role == "web":
        import uvicorn

        from .db import initialize_database
        from .web.app import create_app

        initialize_database(Path(args.db_path))
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
        )
        asyncio.run(run_worker_client(config))
        return 0

    parser.error(f"unknown role: {args.role}")
    return 2


def _default_app_commit() -> str:
    return os.environ.get("COPE_DEPLOY_COMMIT", "dev")


def _default_db_path() -> str:
    return os.environ.get("COPE_DB_PATH", "cope.db")


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


if __name__ == "__main__":
    raise SystemExit(main())
