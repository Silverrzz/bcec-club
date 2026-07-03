from .tournament.engine_instance import EngineInstance
from .tournament.time_control import TimeControl, TimeControlCategory
from .tournament.tournament import Tournament
from .tournament.tournament_runner import TournamentRunner


def run_prototype_tournament() -> None:
    engines = [
        EngineInstance("sable", "1.2.3.4"),
        EngineInstance("lacrima", "5.6.7.8"),
    ]

    time_control = TimeControl(
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
