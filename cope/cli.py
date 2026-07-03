from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

from .prototype import run_prototype_tournament


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cope")
    subparsers = parser.add_subparsers(dest="role", required=True)

    init_db_parser = subparsers.add_parser("init-db", help="initialize the SQLite database")
    init_db_parser.add_argument(
        "--db-path",
        default=_default_db_path(),
        help="path to the SQLite database file",
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

    subparsers.add_parser("web", help="start the web server")

    runner_parser = subparsers.add_parser("runner", help="start the tournament runner")
    runner_parser.add_argument(
        "--worker-server",
        action="store_true",
        help="run only the worker websocket handshake server",
    )
    runner_parser.add_argument("--worker-host", default="127.0.0.1")
    runner_parser.add_argument("--worker-port", type=int, default=8702)
    runner_parser.add_argument("--app-commit", default=_default_app_commit())
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

    worker_parser = subparsers.add_parser("worker", help="start a worker client")
    worker_parser.add_argument("--server-url", default="ws://127.0.0.1:8702/worker")
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
        if args.worker_server:
            from .runner.worker_server import WorkerServerConfig, run_worker_server

            config = WorkerServerConfig(
                host=args.worker_host,
                port=args.worker_port,
                db_path=args.db_path,
                expected_app_commit=args.app_commit,
            )
            asyncio.run(run_worker_server(config))
            return 0

        if args.prototype:
            run_prototype_tournament()
            return 0

        from .db import connect_database, initialize_database
        from .runner import prepare_scheduled_tournaments

        db_path = Path(args.db_path)
        initialize_database(db_path)
        connection = connect_database(db_path)
        try:
            prepared = prepare_scheduled_tournaments(connection)
            connection.commit()
        finally:
            connection.close()

        if not prepared:
            print("no scheduled tournaments to prepare")
            return 0

        for result in prepared:
            if result.skipped_reason is None:
                print(
                    f"prepared tournament {result.tournament_id} "
                    f"({result.tournament_name}): {result.created_games} games"
                )
            else:
                print(
                    f"skipped tournament {result.tournament_id} "
                    f"({result.tournament_name}): {result.skipped_reason}"
                )
        return 0

    if args.role == "web":
        print("cope web is not implemented yet")
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
