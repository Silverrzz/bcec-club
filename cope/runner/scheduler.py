from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from cope.core.models import (
    GauntletFormatOptions,
    KnockoutFormatOptions,
    KnockoutTiebreak,
    RoundRobinFormatOptions,
    SwissFormatOptions,
    TournamentFormat,
)
from cope.chat import announce_tournament_started
from cope.db import (
    GameRecord,
    OpeningRecord,
    TournamentMatchRecord,
    TournamentRecord,
    create_game,
    create_tournament_match,
    finish_tournament_match,
    list_games,
    list_suite_openings,
    list_tournament_matches,
    list_tournaments,
    set_tournament_status,
)


@dataclass(frozen=True, slots=True)
class TournamentPreparation:
    tournament_id: int
    tournament_name: str
    created_games: int
    skipped_reason: str | None = None


@dataclass(frozen=True, slots=True)
class TournamentAdvance:
    created_games: int = 0
    complete: bool = False


def prepare_scheduled_tournaments(
    connection: sqlite3.Connection,
) -> tuple[TournamentPreparation, ...]:
    prepared: list[TournamentPreparation] = []
    for tournament in list_tournaments(connection):
        if tournament.status == "scheduled":
            prepared.append(prepare_tournament(connection, tournament))
    return tuple(prepared)


def prepare_tournament(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> TournamentPreparation:
    existing_games = list_games(connection, tournament.id)
    existing_matches = list_tournament_matches(connection, tournament.id)
    created_games = 0

    if not existing_games and not existing_matches:
        if tournament.config.format == TournamentFormat.ROUND_ROBIN:
            created_games = generate_round_robin_games(connection, tournament)
        elif tournament.config.format == TournamentFormat.SWISS:
            created_games = generate_swiss_round(connection, tournament, 1)
        elif tournament.config.format == TournamentFormat.KNOCKOUT:
            created_games = generate_knockout_first_round(connection, tournament)
        elif tournament.config.format == TournamentFormat.GAUNTLET:
            created_games = generate_gauntlet_games(connection, tournament)
        else:
            return _invalid_preparation(connection, tournament, "unsupported tournament format")

    set_tournament_status(connection, tournament.id, "running")
    current = _refresh_tournament(connection, tournament)
    advance = advance_tournament(connection, current)
    announce_tournament_started(
        connection,
        current,
        scheduled_games=len(list_games(connection, tournament.id)),
    )
    return TournamentPreparation(
        tournament_id=tournament.id,
        tournament_name=tournament.name,
        created_games=created_games + advance.created_games,
    )


def _invalid_preparation(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
    reason: str,
) -> TournamentPreparation:
    set_tournament_status(connection, tournament.id, "paused")
    return TournamentPreparation(
        tournament_id=tournament.id,
        tournament_name=tournament.name,
        created_games=0,
        skipped_reason=reason,
    )


def advance_tournament(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> TournamentAdvance:
    games = list_games(connection, tournament.id)
    if tournament.config.format in {TournamentFormat.ROUND_ROBIN, TournamentFormat.GAUNTLET}:
        return TournamentAdvance(complete=bool(games) and all(game.status == "finished" for game in games))
    if tournament.config.format == TournamentFormat.SWISS:
        return _advance_swiss(connection, tournament)
    if tournament.config.format == TournamentFormat.KNOCKOUT:
        return _advance_knockout(connection, tournament)
    return TournamentAdvance()


def generate_round_robin_games(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> int:
    options = tournament.config.format_options
    if not isinstance(options, RoundRobinFormatOptions):
        raise ValueError("round robin tournament has invalid format options")

    participants = tournament.config.participants
    created_games = 0
    opening_offset = len(list_games(connection, tournament.id))
    opening_ids = _opening_ids(connection, tournament)
    round_pairings = _round_robin_pairings(participants)
    rounds_per_cycle = len(round_pairings)

    for cycle_index in range(options.games_per_pairing):
        for base_round, pairings in enumerate(round_pairings, start=1):
            round_number = base_round + cycle_index * rounds_per_cycle
            for pair_index, pairing in enumerate(pairings, start=1):
                white_engine_id, black_engine_id = pairing
                if cycle_index % 2 == 1:
                    white_engine_id, black_engine_id = black_engine_id, white_engine_id
                _create_scheduled_game(
                    connection,
                    tournament,
                    round_number=round_number,
                    pair_index=pair_index,
                    white_engine_id=white_engine_id,
                    black_engine_id=black_engine_id,
                    game_number=cycle_index + 1,
                    opening_offset=opening_offset + created_games,
                    opening_ids=opening_ids,
                )
                created_games += 1
    return created_games


def generate_gauntlet_games(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> int:
    options = tournament.config.format_options
    if not isinstance(options, GauntletFormatOptions):
        raise ValueError("gauntlet tournament has invalid format options")

    hero = options.hero_engine_id
    opponents = [engine_id for engine_id in tournament.config.participants if engine_id != hero]
    created_games = 0
    opening_offset = len(list_games(connection, tournament.id))
    opening_ids = _opening_ids(connection, tournament)
    for game_number in range(1, options.games_per_opponent + 1):
        for opponent_index, opponent in enumerate(opponents, start=1):
            round_number = (game_number - 1) * len(opponents) + opponent_index
            hero_is_white = (game_number + opponent_index) % 2 == 0
            white, black = (hero, opponent) if hero_is_white else (opponent, hero)
            _create_scheduled_game(
                connection,
                tournament,
                round_number=round_number,
                pair_index=1,
                white_engine_id=white,
                black_engine_id=black,
                game_number=game_number,
                opening_offset=opening_offset + created_games,
                opening_ids=opening_ids,
            )
            created_games += 1
    return created_games


def generate_swiss_round(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
    round_number: int,
) -> int:
    options = tournament.config.format_options
    if not isinstance(options, SwissFormatOptions):
        raise ValueError("Swiss tournament has invalid format options")
    if round_number < 1 or round_number > options.rounds:
        return 0

    games = list_games(connection, tournament.id)
    matches = list_tournament_matches(connection, tournament.id)
    points = _swiss_points(tournament, games, matches)
    buchholz = _swiss_buchholz(tournament, games, matches, points)
    seed = {engine_id: index for index, engine_id in enumerate(tournament.config.participants)}
    ranked = sorted(
        tournament.config.participants,
        key=lambda engine_id: (-points[engine_id], -buchholz[engine_id], seed[engine_id]),
    )

    bye: int | None = None
    if len(ranked) % 2:
        previous_byes = {
            match.engine1_id
            for match in matches
            if match.status == "bye" and match.engine2_id is None
        }
        bye = next((engine_id for engine_id in reversed(ranked) if engine_id not in previous_byes), ranked[-1])
        ranked.remove(bye)

    opponents = _opponent_history(games)
    if round_number == 1:
        midpoint = len(ranked) // 2
        pairings = list(zip(ranked[:midpoint], ranked[midpoint:], strict=True))
    else:
        pairings = _swiss_pairings(ranked, points, opponents)

    created_games = 0
    opening_offset = len(games)
    opening_ids = _opening_ids(connection, tournament)
    match_index = 1
    for first, second in pairings:
        white, black = _swiss_colours(first, second, games)
        match_id = create_tournament_match(
            connection,
            tournament_id=tournament.id,
            round=round_number,
            match_index=match_index,
            engine1_id=first,
            engine2_id=second,
        )
        _create_scheduled_game(
            connection,
            tournament,
            round_number=round_number,
            pair_index=match_index,
            white_engine_id=white,
            black_engine_id=black,
            match_id=match_id,
            opening_offset=opening_offset + created_games,
            opening_ids=opening_ids,
        )
        created_games += 1
        match_index += 1

    if bye is not None:
        create_tournament_match(
            connection,
            tournament_id=tournament.id,
            round=round_number,
            match_index=match_index,
            engine1_id=bye,
            engine2_id=None,
            status="bye",
            winner_engine_id=bye,
        )
    return created_games


def generate_knockout_first_round(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> int:
    options = tournament.config.format_options
    if not isinstance(options, KnockoutFormatOptions):
        raise ValueError("knockout tournament has invalid format options")

    participants = tournament.config.participants
    bracket_size = 1
    while bracket_size < len(participants):
        bracket_size *= 2
    seeded = [
        participants[seed_number - 1] if seed_number <= len(participants) else None
        for seed_number in _bracket_seed_order(bracket_size)
    ]
    pairings = [(seeded[index], seeded[index + 1]) for index in range(0, bracket_size, 2)]
    return _create_knockout_round(connection, tournament, 1, pairings)


def _advance_swiss(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> TournamentAdvance:
    options = tournament.config.format_options
    if not isinstance(options, SwissFormatOptions):
        return TournamentAdvance()
    matches = list_tournament_matches(connection, tournament.id)
    if not matches:
        return TournamentAdvance(created_games=generate_swiss_round(connection, tournament, 1))

    current_round = max(match.round for match in matches)
    round_matches = [match for match in matches if match.round == current_round]
    games_by_match = _games_by_match(list_games(connection, tournament.id))
    if any(
        any(game.status != "finished" for game in games_by_match.get(match.id, ()))
        for match in round_matches
        if match.status != "bye"
    ):
        return TournamentAdvance()

    for match in round_matches:
        if match.status != "pending":
            continue
        games = games_by_match.get(match.id, ())
        if not games:
            return TournamentAdvance()
        winner = _game_winner(games[0])
        finish_tournament_match(connection, match.id, winner_engine_id=winner)

    if current_round >= options.rounds:
        return TournamentAdvance(complete=True)
    created = generate_swiss_round(connection, tournament, current_round + 1)
    return TournamentAdvance(created_games=created)


def _advance_knockout(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> TournamentAdvance:
    options = tournament.config.format_options
    if not isinstance(options, KnockoutFormatOptions):
        return TournamentAdvance()

    total_created = 0
    while True:
        matches = list_tournament_matches(connection, tournament.id)
        if not matches:
            return TournamentAdvance(
                created_games=generate_knockout_first_round(connection, tournament)
            )
        current_round = max(match.round for match in matches)
        round_matches = [match for match in matches if match.round == current_round]
        games = list_games(connection, tournament.id)
        games_by_match = _games_by_match(games)

        waiting = False
        for match in round_matches:
            if match.status != "pending":
                continue
            match_games = games_by_match.get(match.id, ())
            if not match_games or any(game.status != "finished" for game in match_games):
                waiting = True
                continue
            winner, created = _resolve_knockout_match(
                connection,
                tournament,
                match,
                match_games,
                options,
            )
            total_created += created
            if winner is None:
                waiting = True
            else:
                finish_tournament_match(connection, match.id, winner_engine_id=winner)

        round_matches = list_tournament_matches(connection, tournament.id, round=current_round)
        if waiting or any(match.status == "pending" for match in round_matches):
            return TournamentAdvance(created_games=total_created)
        if len(round_matches) == 1:
            return TournamentAdvance(created_games=total_created, complete=True)

        winners = [match.winner_engine_id for match in round_matches]
        if any(winner is None for winner in winners):
            return TournamentAdvance(created_games=total_created)
        next_pairings = [
            (winners[index], winners[index + 1])
            for index in range(0, len(winners), 2)
        ]
        total_created += _create_knockout_round(
            connection,
            tournament,
            current_round + 1,
            next_pairings,
        )


def _create_knockout_round(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
    round_number: int,
    pairings: list[tuple[int | None, int | None]],
) -> int:
    options = tournament.config.format_options
    if not isinstance(options, KnockoutFormatOptions):
        raise ValueError("knockout tournament has invalid format options")
    created_games = 0
    pair_index = 1
    opening_offset = len(list_games(connection, tournament.id))
    opening_ids = _opening_ids(connection, tournament)
    for match_index, (first, second) in enumerate(pairings, start=1):
        entrant = first if first is not None else second
        if entrant is None:
            continue
        is_bye = first is None or second is None
        match_id = create_tournament_match(
            connection,
            tournament_id=tournament.id,
            round=round_number,
            match_index=match_index,
            engine1_id=entrant if first is None else first,
            engine2_id=None if is_bye else second,
            status="bye" if is_bye else "pending",
            winner_engine_id=entrant if is_bye else None,
        )
        if is_bye:
            continue
        assert first is not None and second is not None
        for game_number in range(1, options.games_per_match + 1):
            white, black = (first, second) if game_number % 2 else (second, first)
            _create_scheduled_game(
                connection,
                tournament,
                round_number=round_number,
                pair_index=pair_index,
                white_engine_id=white,
                black_engine_id=black,
                match_id=match_id,
                game_number=game_number,
                opening_offset=opening_offset + created_games,
                opening_ids=opening_ids,
            )
            pair_index += 1
            created_games += 1
    return created_games


def _resolve_knockout_match(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
    match: TournamentMatchRecord,
    games: tuple[GameRecord, ...],
    options: KnockoutFormatOptions,
) -> tuple[int | None, int]:
    armageddon = next((game for game in games if game.tiebreak_kind == "armageddon"), None)
    if armageddon is not None:
        winner = _game_winner(armageddon)
        return (armageddon.black_engine_id if winner is None else winner), 0

    first_points, second_points = _match_points(match, games)
    extra_games = [game for game in games if game.tiebreak_kind == "extra_pair"]
    base_complete = len(games) >= options.games_per_match
    extra_complete = not extra_games or len(extra_games) % 2 == 0
    if base_complete and extra_complete and first_points != second_points:
        return (match.engine1_id if first_points > second_points else match.engine2_id), 0

    if not base_complete or not extra_complete:
        return None, 0

    if options.tiebreak == KnockoutTiebreak.ARMAGEDDON:
        created = _append_knockout_games(
            connection,
            tournament,
            match,
            games,
            count=1,
            tiebreak_kind="armageddon",
        )
    else:
        created = _append_knockout_games(
            connection,
            tournament,
            match,
            games,
            count=2,
            tiebreak_kind="extra_pair",
        )
    return None, created


def _append_knockout_games(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
    match: TournamentMatchRecord,
    games: tuple[GameRecord, ...],
    *,
    count: int,
    tiebreak_kind: str,
) -> int:
    if match.engine2_id is None:
        return 0
    next_game_number = max(game.game_number for game in games) + 1
    tournament_games = list_games(connection, tournament.id)
    round_games = [game for game in tournament_games if game.round == match.round]
    next_pair_index = max((game.pair_index for game in round_games), default=0) + 1
    opening_offset = len(tournament_games)
    opening_ids = _opening_ids(connection, tournament)
    for offset in range(count):
        game_number = next_game_number + offset
        white, black = (
            (match.engine1_id, match.engine2_id)
            if game_number % 2
            else (match.engine2_id, match.engine1_id)
        )
        _create_scheduled_game(
            connection,
            tournament,
            round_number=match.round,
            pair_index=next_pair_index + offset,
            white_engine_id=white,
            black_engine_id=black,
            match_id=match.id,
            game_number=game_number,
            tiebreak_kind=tiebreak_kind,
            opening_offset=opening_offset + offset,
            opening_ids=opening_ids,
        )
    return count


def _create_scheduled_game(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
    *,
    round_number: int,
    pair_index: int,
    white_engine_id: int,
    black_engine_id: int,
    match_id: int | None = None,
    game_number: int = 1,
    tiebreak_kind: str | None = None,
    opening_offset: int | None = None,
    opening_ids: tuple[int, ...] | None = None,
) -> int:
    if opening_ids is None:
        opening_ids = _opening_ids(connection, tournament)
    if opening_offset is None:
        opening_offset = len(list_games(connection, tournament.id))
    opening_id = opening_ids[opening_offset % len(opening_ids)] if opening_ids else None
    return create_game(
        connection,
        tournament_id=tournament.id,
        round=round_number,
        pair_index=pair_index,
        white_engine_id=white_engine_id,
        black_engine_id=black_engine_id,
        match_id=match_id,
        game_number=game_number,
        tiebreak_kind=tiebreak_kind,
        opening_id=opening_id,
    )


def _swiss_points(
    tournament: TournamentRecord,
    games: tuple[GameRecord, ...],
    matches: tuple[TournamentMatchRecord, ...],
) -> dict[int, float]:
    points = {engine_id: 0.0 for engine_id in tournament.config.participants}
    for game in games:
        if game.result == "1-0":
            points[game.white_engine_id] += 1.0
        elif game.result == "0-1":
            points[game.black_engine_id] += 1.0
        elif game.result == "1/2-1/2":
            points[game.white_engine_id] += 0.5
            points[game.black_engine_id] += 0.5
    for match in matches:
        if match.status == "bye":
            points[match.engine1_id] += 1.0
    return points


def _swiss_buchholz(
    tournament: TournamentRecord,
    games: tuple[GameRecord, ...],
    matches: tuple[TournamentMatchRecord, ...],
    points: dict[int, float],
) -> dict[int, float]:
    buchholz = {engine_id: 0.0 for engine_id in tournament.config.participants}
    for game in games:
        if game.result is None:
            continue
        buchholz[game.white_engine_id] += points[game.black_engine_id]
        buchholz[game.black_engine_id] += points[game.white_engine_id]
    return buchholz


def _opponent_history(games: tuple[GameRecord, ...]) -> dict[int, set[int]]:
    opponents: dict[int, set[int]] = {}
    for game in games:
        opponents.setdefault(game.white_engine_id, set()).add(game.black_engine_id)
        opponents.setdefault(game.black_engine_id, set()).add(game.white_engine_id)
    return opponents


def _swiss_pairings(
    ranked: list[int],
    points: dict[int, float],
    opponents: dict[int, set[int]],
) -> list[tuple[int, int]]:
    rank = {engine_id: index for index, engine_id in enumerate(ranked)}

    def pair(remaining: tuple[int, ...], allow_rematches: bool) -> list[tuple[int, int]] | None:
        if not remaining:
            return []
        first = remaining[0]
        candidates = sorted(
            remaining[1:],
            key=lambda second: (
                second in opponents.get(first, set()),
                abs(points[first] - points[second]),
                abs(rank[first] - rank[second]),
            ),
        )
        for second in candidates:
            if not allow_rematches and second in opponents.get(first, set()):
                continue
            rest = tuple(engine_id for engine_id in remaining[1:] if engine_id != second)
            paired_rest = pair(rest, allow_rematches)
            if paired_rest is not None:
                return [(first, second), *paired_rest]
        return None

    return pair(tuple(ranked), False) or pair(tuple(ranked), True) or []


def _swiss_colours(
    first: int,
    second: int,
    games: tuple[GameRecord, ...],
) -> tuple[int, int]:
    balances = {first: 0, second: 0}
    histories: dict[int, list[str]] = {first: [], second: []}
    for game in games:
        if game.white_engine_id in balances:
            balances[game.white_engine_id] += 1
            histories[game.white_engine_id].append("white")
        if game.black_engine_id in balances:
            balances[game.black_engine_id] -= 1
            histories[game.black_engine_id].append("black")

    def cost(white: int, black: int) -> int:
        value = abs(balances[white] + 1) + abs(balances[black] - 1)
        if histories[white][-1:] == ["white"]:
            value += 2
        if histories[black][-1:] == ["black"]:
            value += 2
        if histories[white][-2:] == ["white", "white"]:
            value += 8
        if histories[black][-2:] == ["black", "black"]:
            value += 8
        return value

    return min(((first, second), (second, first)), key=lambda colours: cost(*colours))


def _match_points(
    match: TournamentMatchRecord,
    games: tuple[GameRecord, ...],
) -> tuple[float, float]:
    first_points = 0.0
    second_points = 0.0
    for game in games:
        if game.tiebreak_kind == "armageddon":
            continue
        if game.result == "1/2-1/2":
            first_points += 0.5
            second_points += 0.5
        elif _game_winner(game) == match.engine1_id:
            first_points += 1.0
        elif _game_winner(game) == match.engine2_id:
            second_points += 1.0
    return first_points, second_points


def _game_winner(game: GameRecord) -> int | None:
    if game.result == "1-0":
        return game.white_engine_id
    if game.result == "0-1":
        return game.black_engine_id
    return None


def _games_by_match(games: tuple[GameRecord, ...]) -> dict[int, tuple[GameRecord, ...]]:
    grouped: dict[int, list[GameRecord]] = {}
    for game in games:
        if game.match_id is not None:
            grouped.setdefault(game.match_id, []).append(game)
    return {
        match_id: tuple(sorted(match_games, key=lambda game: (game.game_number, game.id)))
        for match_id, match_games in grouped.items()
    }


def _bracket_seed_order(size: int) -> list[int]:
    order = [1, 2]
    while len(order) < size:
        mirror = len(order) * 2 + 1
        order = [seed for current in order for seed in (current, mirror - current)]
    return order[:size]


def _round_robin_pairings(participants: list[int]) -> tuple[tuple[tuple[int, int], ...], ...]:
    if len(participants) < 2:
        return ()
    players: list[int | None] = list(participants)
    if len(players) % 2 == 1:
        players.append(None)
    rounds: list[tuple[tuple[int, int], ...]] = []
    player_count = len(players)
    for round_index in range(player_count - 1):
        pairings: list[tuple[int, int]] = []
        for pair_index in range(player_count // 2):
            first = players[pair_index]
            second = players[player_count - 1 - pair_index]
            if first is None or second is None:
                continue
            if (round_index + pair_index) % 2 == 0:
                pairings.append((first, second))
            else:
                pairings.append((second, first))
        rounds.append(tuple(pairings))
        players = [players[0], players[-1], *players[1:-1]]
    return tuple(rounds)


def _opening_ids(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> tuple[int, ...]:
    suite_id = tournament.config.opening_suite_id
    if suite_id is None:
        return ()
    openings: tuple[OpeningRecord, ...] = list_suite_openings(connection, suite_id)
    return tuple(opening.id for opening in openings)


def _refresh_tournament(
    connection: sqlite3.Connection,
    tournament: TournamentRecord,
) -> TournamentRecord:
    return next(
        current for current in list_tournaments(connection) if current.id == tournament.id
    )
