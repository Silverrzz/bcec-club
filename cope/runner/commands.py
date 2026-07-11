from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from cope.db import (
    RunnerCommandRecord,
    claim_next_runner_command,
    fail_runner_command,
    finish_runner_command,
)
from cope.ratings import RatingCommitResult, apply_tournament_rating_commit


MAX_COMMAND_ERROR_LENGTH = 1000


@dataclass(frozen=True, slots=True)
class CommandProcessingReport:
    applied: int
    failed: int
    errors: tuple[str, ...]
    rating_commits: tuple[RatingCommitResult, ...]


def process_pending_runner_commands(
    connection: sqlite3.Connection,
) -> CommandProcessingReport:
    applied = 0
    failed = 0
    errors: list[str] = []
    rating_commits: list[RatingCommitResult] = []

    while command := claim_next_runner_command(connection):
        connection.execute("SAVEPOINT apply_runner_command")
        try:
            result = _dispatch_runner_command(connection, command)
        except Exception as error:
            connection.execute("ROLLBACK TO SAVEPOINT apply_runner_command")
            connection.execute("RELEASE SAVEPOINT apply_runner_command")
            message = _command_error(command, error)
            fail_runner_command(connection, command.id, message)
            _fail_linked_rating_commit(connection, command, message)
            failed += 1
            errors.append(message)
        else:
            connection.execute("RELEASE SAVEPOINT apply_runner_command")
            finish_runner_command(connection, command.id)
            applied += 1
            if result is not None:
                rating_commits.append(result)

    return CommandProcessingReport(
        applied=applied,
        failed=failed,
        errors=tuple(errors),
        rating_commits=tuple(rating_commits),
    )


def _dispatch_runner_command(
    connection: sqlite3.Connection,
    command: RunnerCommandRecord,
) -> RatingCommitResult | None:
    if command.command == "commit_tournament_results":
        return apply_tournament_rating_commit(connection, command)
    raise ValueError(f"unknown runner command {command.command!r}")


def _fail_linked_rating_commit(
    connection: sqlite3.Connection,
    command: RunnerCommandRecord,
    error: str,
) -> None:
    if command.command != "commit_tournament_results":
        return
    tournament_id = command.payload.get("tournament_id")
    category_id = command.payload.get("category_id")
    if (
        isinstance(tournament_id, bool)
        or not isinstance(tournament_id, int)
        or isinstance(category_id, bool)
        or not isinstance(category_id, int)
    ):
        return
    connection.execute(
        """
        UPDATE tournament_rating_commits
        SET command_id = COALESCE(command_id, ?),
            status = 'failed',
            applied_at = NULL,
            error = ?
        WHERE status IN ('pending', 'claimed')
          AND (
            command_id = ?
            OR (command_id IS NULL AND tournament_id = ? AND category_id = ?)
          )
        """,
        (command.id, error, command.id, tournament_id, category_id),
    )


def _command_error(command: RunnerCommandRecord, error: Exception) -> str:
    detail = str(error).strip() or error.__class__.__name__
    return f"Command {command.id} ({command.command}) failed: {detail}"[:MAX_COMMAND_ERROR_LENGTH]
