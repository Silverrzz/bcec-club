from __future__ import annotations

import argparse
import asyncio
import os

from .prototype import run_prototype_tournament


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m cope")
    subparsers = parser.add_subparsers(dest="role", required=True)

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

    worker_parser = subparsers.add_parser("worker", help="start a worker client")
    worker_parser.add_argument("--server-url", default="ws://127.0.0.1:8702/worker")
    worker_parser.add_argument("--token")
    worker_parser.add_argument("--session-id")
    worker_parser.add_argument("--label-hint", default="")
    worker_parser.add_argument("--app-commit", default=_default_app_commit())

    args = parser.parse_args(argv)

    if args.role == "runner":
        if args.worker_server:
            from .runner.worker_server import WorkerServerConfig, run_worker_server

            config = WorkerServerConfig(
                host=args.worker_host,
                port=args.worker_port,
                expected_app_commit=args.app_commit,
            )
            asyncio.run(run_worker_server(config))
            return 0

        run_prototype_tournament()
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
