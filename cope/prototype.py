from __future__ import annotations

import os
from pathlib import Path

from .core.models import (
    AdjudicationConfig,
    EngineSpec,
    HardwareMode,
    IncrementTimeControl,
    RatingCategory,
    RoundRobinFormatOptions,
    TournamentConfig,
    TournamentFormat,
)
from .db import (
    connect_database,
    create_engine,
    create_tournament,
    get_engine,
    initialize_database,
    list_engines,
    list_tournaments,
)
from .tournament.engine_instance import EngineInstance
from .tournament.time_control import RuntimeTimeControl, TimeControlCategory
from .tournament.tournament import Tournament
from .tournament.tournament_runner import TournamentRunner


def run_prototype_tournament() -> None:
    run_prototype_data_setup()

    engines = [
        EngineInstance("sable", "1.2.3.4"),
        EngineInstance("lacrima", "5.6.7.8"),
    ]

    time_control = RuntimeTimeControl(
        category=TimeControlCategory.INCREMENT,
        initial_time=500,
        increment=50,
    )

    tournament = Tournament(
        id=1,
        name="Prototype Blitz",
        engines=engines,
        time_control=time_control,
    )

    runner = TournamentRunner(tournament)
    active_tournament = runner.get_tournament()

    print(f"Tournament: {active_tournament.get_name()}")
    print(f"Engines: {len(active_tournament.get_engines())}")
    print(f"Games: {len(active_tournament.get_games())}")

    for game in active_tournament.get_games():
        print(
            f"Game {game.id}: "
            f"{game.white.get_name()} vs {game.black.get_name()}"
        )

    runner.run()

    print("Results:")
    for game in runner.get_completed_games():
        print(
            f"Game {game.id}: "
            f"{game.white.get_name()} vs {game.black.get_name()} "
            f"{game.state.get_summary()}"
        )


def run_prototype_data_setup() -> None:
    db_path = Path(os.environ.get("COPE_DB_PATH", "tmp/cope-prototype.db"))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    initialize_database(db_path)

    connection = connect_database(db_path)
    try:
        _seed_engine(
            connection,
            EngineSpec(
                engine_id=1,
                name="sable",
                git_url="local",
                commit="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                build_cmd="true",
                binary_path="engine",
            ),
        )
        _seed_engine(
            connection,
            EngineSpec(
                engine_id=2,
                name="lacrima",
                git_url="local",
                commit="bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                build_cmd="true",
                binary_path="engine",
            ),
        )

        config = TournamentConfig(
            format=TournamentFormat.ROUND_ROBIN,
            format_options=RoundRobinFormatOptions(double_rr=True),
            participants=[1, 2],
            time_control=IncrementTimeControl(initial_ms=60_000, increment_ms=1_000),
            rating_category=RatingCategory.BLITZ,
            hardware_mode=HardwareMode.SHARED,
            concurrency=1,
            adjudication=AdjudicationConfig(),
        )
        tournament_id = create_tournament(
            connection,
            "Prototype Persistent RR",
            config,
            status="scheduled",
        )
        connection.commit()

        print(f"Database: {db_path}")
        print(f"Persistent engines: {len(list_engines(connection))}")
        print(f"Persistent tournaments: {len(list_tournaments(connection))}")
        print(f"Created persistent tournament: {tournament_id}")
    finally:
        connection.close()


def _seed_engine(connection, spec: EngineSpec) -> None:
    if get_engine(connection, spec.engine_id) is not None:
        return

    create_engine(connection, spec)
