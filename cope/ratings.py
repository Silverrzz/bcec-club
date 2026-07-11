from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from cope.db.repo import RunnerCommandRecord, get_tournament, list_games, utc_now


DEFAULT_ELO = 1500.0
ELO_K_FACTOR = 32.0
ELO_SCALE = 400.0


class RatingCommitError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RatingCommitResult:
    tournament_id: int
    category_id: int
    games_applied: int
    engines_updated: int


def apply_tournament_rating_commit(
    connection: sqlite3.Connection,
    command: RunnerCommandRecord,
) -> RatingCommitResult:
    tournament_id = _payload_id(command.payload, "tournament_id")
    category_id = _payload_id(command.payload, "category_id")

    commit = connection.execute(
        "SELECT * FROM tournament_rating_commits WHERE tournament_id = ?",
        (tournament_id,),
    ).fetchone()
    if commit is None:
        raise RatingCommitError("rating commit request no longer exists")
    if commit["command_id"] is None:
        connection.execute(
            """
            UPDATE tournament_rating_commits
            SET command_id = ?
            WHERE tournament_id = ? AND command_id IS NULL AND status = 'pending'
            """,
            (command.id, tournament_id),
        )
        commit = connection.execute(
            "SELECT * FROM tournament_rating_commits WHERE tournament_id = ?",
            (tournament_id,),
        ).fetchone()
    if commit is None or commit["command_id"] != command.id:
        raise RatingCommitError("rating commit command has been superseded")
    if commit["category_id"] != category_id:
        raise RatingCommitError("rating commit category does not match its request")
    if commit["status"] not in {"pending", "claimed"}:
        raise RatingCommitError(f"rating commit is already {commit['status']}")

    connection.execute(
        """
        UPDATE tournament_rating_commits
        SET status = 'claimed', error = NULL
        WHERE tournament_id = ? AND command_id = ?
        """,
        (tournament_id, command.id),
    )

    tournament = get_tournament(connection, tournament_id)
    if tournament is None:
        raise RatingCommitError("tournament no longer exists")
    if tournament.status != "finished":
        raise RatingCommitError("tournament is not complete")
    if not tournament.config.rated:
        raise RatingCommitError("tournament is not rated")
    if tournament.category_id != category_id:
        raise RatingCommitError("tournament category changed after the commit request")

    games = list_games(connection, tournament_id)
    if not games:
        raise RatingCommitError("tournament has no games")

    participants = set(tournament.config.participants)
    for game in games:
        if game.status != "finished" or game.result not in {"1-0", "0-1", "1/2-1/2"}:
            raise RatingCommitError(f"game {game.id} does not have a finished result")
        if game.white_engine_id not in participants or game.black_engine_id not in participants:
            raise RatingCommitError(f"game {game.id} contains a non-participant engine")

    existing_history = connection.execute(
        "SELECT 1 FROM rating_history WHERE tournament_id = ? LIMIT 1",
        (tournament_id,),
    ).fetchone()
    if existing_history is not None:
        raise RatingCommitError("tournament rating history already exists")

    engine_ids = sorted(
        {engine_id for game in games for engine_id in (game.white_engine_id, game.black_engine_id)}
    )
    ratings, games_played = _current_ratings(connection, category_id, engine_ids)
    games_added = {engine_id: 0 for engine_id in engine_ids}
    applied_at = utc_now()

    for game in games:
        white_id = game.white_engine_id
        black_id = game.black_engine_id
        white_before = ratings[white_id]
        black_before = ratings[black_id]
        white_score = _white_score(game.result)
        black_score = 1.0 - white_score
        white_expected = _expected_score(white_before, black_before)
        white_change = ELO_K_FACTOR * (white_score - white_expected)
        white_after = round(white_before + white_change, 6)
        black_after = round(black_before - white_change, 6)

        _record_history(
            connection,
            engine_id=white_id,
            opponent_engine_id=black_id,
            category_id=category_id,
            tournament_id=tournament_id,
            game_id=game.id,
            elo_before=white_before,
            elo=white_after,
            score=white_score,
            at=applied_at,
        )
        _record_history(
            connection,
            engine_id=black_id,
            opponent_engine_id=white_id,
            category_id=category_id,
            tournament_id=tournament_id,
            game_id=game.id,
            elo_before=black_before,
            elo=black_after,
            score=black_score,
            at=applied_at,
        )
        ratings[white_id] = white_after
        ratings[black_id] = black_after
        games_added[white_id] += 1
        games_added[black_id] += 1

    for engine_id in engine_ids:
        connection.execute(
            """
            INSERT INTO ratings (engine_id, category_id, elo, games_played, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(engine_id, category_id) DO UPDATE SET
              elo = excluded.elo,
              games_played = excluded.games_played,
              updated_at = excluded.updated_at
            """,
            (
                engine_id,
                category_id,
                ratings[engine_id],
                games_played[engine_id] + games_added[engine_id],
                applied_at,
            ),
        )

    cursor = connection.execute(
        """
        UPDATE tournament_rating_commits
        SET status = 'applied', applied_at = ?, error = NULL
        WHERE tournament_id = ? AND command_id = ? AND status = 'claimed'
        """,
        (applied_at, tournament_id, command.id),
    )
    if cursor.rowcount != 1:
        raise RatingCommitError("rating commit request changed while it was being applied")

    return RatingCommitResult(
        tournament_id=tournament_id,
        category_id=category_id,
        games_applied=len(games),
        engines_updated=len(engine_ids),
    )


def _current_ratings(
    connection: sqlite3.Connection,
    category_id: int,
    engine_ids: list[int],
) -> tuple[dict[int, float], dict[int, int]]:
    ratings = {engine_id: DEFAULT_ELO for engine_id in engine_ids}
    games_played = {engine_id: 0 for engine_id in engine_ids}
    placeholders = ", ".join("?" for _ in engine_ids)
    rows = connection.execute(
        f"""
        SELECT engine_id, elo, games_played
        FROM ratings
        WHERE category_id = ? AND engine_id IN ({placeholders})
        """,
        (category_id, *engine_ids),
    )
    for row in rows:
        ratings[row["engine_id"]] = float(row["elo"])
        games_played[row["engine_id"]] = int(row["games_played"])
    return ratings, games_played


def _record_history(
    connection: sqlite3.Connection,
    *,
    engine_id: int,
    opponent_engine_id: int,
    category_id: int,
    tournament_id: int,
    game_id: int,
    elo_before: float,
    elo: float,
    score: float,
    at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO rating_history (
          engine_id, category_id, tournament_id, opponent_engine_id,
          elo_before, elo, elo_change, score, game_id, at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            engine_id,
            category_id,
            tournament_id,
            opponent_engine_id,
            elo_before,
            elo,
            round(elo - elo_before, 6),
            score,
            game_id,
            at,
        ),
    )


def _payload_id(payload: dict, field: str) -> int:
    value = payload.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RatingCommitError(f"rating commit payload has an invalid {field}")
    return value


def _white_score(result: str) -> float:
    if result == "1-0":
        return 1.0
    if result == "0-1":
        return 0.0
    return 0.5


def _expected_score(rating: float, opponent_rating: float) -> float:
    return 1.0 / (1.0 + 10.0 ** ((opponent_rating - rating) / ELO_SCALE))
