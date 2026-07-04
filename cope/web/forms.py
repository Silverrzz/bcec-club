"""Parse human-friendly HTML form fields into validated tournament settings."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from cope.core.models import (
    AdjudicationConfig,
    DrawAdjudicationRule,
    GauntletFormatOptions,
    IncrementTimeControl,
    KnockoutFormatOptions,
    MoveNodesTimeControl,
    MovesToGoTimeControl,
    MoveTimeControl,
    ResignAdjudicationRule,
    RoundRobinFormatOptions,
    SwissFormatOptions,
    SyzygyAdjudicationRule,
    TournamentConfig,
)


class FormError(Exception):
    """Raised when submitted form values cannot be parsed into valid settings."""

    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


FormValues = dict[str, list[str]]


def form_value(form: FormValues, key: str, default: str = "") -> str:
    values = form.get(key)
    if not values:
        return default
    return values[-1].strip()


def form_flag(form: FormValues, key: str) -> bool:
    return form_value(form, key) in {"on", "true", "1"}


def build_settings(form: FormValues) -> dict[str, Any]:
    """Build the settings portion of a tournament config (everything except
    participants and category linkage) from form fields."""
    errors: list[str] = []
    settings: dict[str, Any] = {}

    settings["format"] = form_value(form, "format", "round_robin")
    settings["format_options"] = _format_options(form, settings["format"], errors)
    settings["time_control"] = _time_control(form, errors)
    settings["hardware_mode"] = form_value(form, "hardware_mode", "shared")
    settings["concurrency"] = _int_field(form, "concurrency", errors, "Concurrency", minimum=1, default=1)
    settings["rated"] = form_flag(form, "rated")
    settings["lag_compensation_ms"] = _int_field(
        form, "lag_compensation_ms", errors, "Lag compensation", minimum=0, default=50
    )

    suite = form_value(form, "opening_suite_id")
    settings["opening_suite_id"] = int(suite) if suite.isdigit() and int(suite) > 0 else None

    settings["adjudication"] = _adjudication(form, errors)

    if errors:
        raise FormError(errors)
    return settings


def settings_as_dict(settings: dict[str, Any]) -> dict[str, Any]:
    """Serialize the models returned by build_settings into a plain JSON dict."""
    serialized = dict(settings)
    for key in ("format_options", "time_control", "adjudication"):
        serialized[key] = settings[key].model_dump(mode="json")
    return serialized


def build_tournament_config(form: FormValues) -> TournamentConfig:
    settings = build_settings(form)

    errors: list[str] = []
    participants: list[int] = []
    for raw in form.get("participants", []):
        raw = raw.strip()
        if not raw:
            continue
        if not raw.isdigit():
            errors.append("Participants must be engine ids.")
            continue
        participants.append(int(raw))
    if len(participants) < 2:
        errors.append("Select at least two participating engines.")

    category = form_value(form, "category_id")
    category_id = int(category) if category.isdigit() else 1

    if errors:
        raise FormError(errors)

    try:
        return TournamentConfig(
            category_id=category_id,
            category_settings_linked=form_flag(form, "category_settings_linked"),
            participants=participants,
            **settings,
        )
    except ValidationError as exc:
        raise FormError(_validation_messages(exc)) from exc


def _format_options(form: FormValues, format_name: str, errors: list[str]) -> Any:
    try:
        if format_name == "swiss":
            return SwissFormatOptions(
                rounds=_int_field(form, "swiss_rounds", errors, "Swiss rounds", minimum=1, default=7),
            )
        if format_name == "knockout":
            return KnockoutFormatOptions(
                games_per_match=_int_field(
                    form, "knockout_games_per_match", errors, "Games per match", minimum=1, default=2
                ),
                tiebreak=form_value(form, "knockout_tiebreak", "armageddon"),
            )
        if format_name == "gauntlet":
            return GauntletFormatOptions(
                hero_engine_id=_int_field(
                    form, "gauntlet_hero_engine_id", errors, "Gauntlet hero engine", minimum=1, default=0
                ),
                games_per_opponent=_int_field(
                    form, "gauntlet_games_per_opponent", errors, "Games per opponent", minimum=1, default=2
                ),
            )
        return RoundRobinFormatOptions(double_rr=form_flag(form, "round_robin_double"))
    except ValidationError as exc:
        errors.extend(_validation_messages(exc))
        return RoundRobinFormatOptions()


def _time_control(form: FormValues, errors: list[str]) -> Any:
    tc_type = form_value(form, "tc_type", "increment")
    try:
        if tc_type == "movetime":
            return MoveTimeControl(
                move_time_ms=_seconds_field(form, "tc_move_time_s", errors, "Move time", default=1.0),
            )
        if tc_type == "movestogo":
            return MovesToGoTimeControl(
                initial_ms=_seconds_field(form, "tc_initial_s", errors, "Initial time", default=60.0),
                moves_to_go=_int_field(form, "tc_moves_to_go", errors, "Moves to go", minimum=1, default=40),
            )
        if tc_type == "movenodes":
            return MoveNodesTimeControl(
                nodes=_int_field(form, "tc_nodes", errors, "Nodes per move", minimum=1, default=100_000),
            )
        return IncrementTimeControl(
            initial_ms=_seconds_field(form, "tc_initial_s", errors, "Initial time", default=60.0),
            increment_ms=_seconds_field(
                form, "tc_increment_s", errors, "Increment", default=1.0, allow_zero=True
            ),
        )
    except ValidationError as exc:
        errors.extend(_validation_messages(exc))
        return IncrementTimeControl(initial_ms=60_000, increment_ms=1_000)


def _adjudication(form: FormValues, errors: list[str]) -> AdjudicationConfig:
    draw = resign = syzygy = None
    max_moves = None
    try:
        if form_flag(form, "adjudication_draw"):
            draw = DrawAdjudicationRule(
                min_fullmove=_int_field(form, "draw_min_fullmove", errors, "Draw: minimum move", minimum=1, default=40),
                max_abs_cp=_int_field(form, "draw_max_abs_cp", errors, "Draw: max eval (cp)", minimum=0, default=10),
                consecutive_plies=_int_field(form, "draw_plies", errors, "Draw: consecutive plies", minimum=1, default=8),
            )
        if form_flag(form, "adjudication_resign"):
            resign = ResignAdjudicationRule(
                min_abs_cp=_int_field(form, "resign_min_abs_cp", errors, "Resign: min eval (cp)", minimum=1, default=800),
                consecutive_plies=_int_field(form, "resign_plies", errors, "Resign: consecutive plies", minimum=1, default=6),
            )
        if form_flag(form, "adjudication_syzygy"):
            syzygy = SyzygyAdjudicationRule(
                max_pieces=_int_field(form, "syzygy_max_pieces", errors, "Syzygy: max pieces", minimum=2, default=6),
            )
        raw_max_moves = form_value(form, "adjudication_max_moves")
        if raw_max_moves:
            max_moves = _int_field(form, "adjudication_max_moves", errors, "Maximum moves", minimum=1, default=0)
        return AdjudicationConfig(draw=draw, resign=resign, syzygy=syzygy, max_moves=max_moves)
    except ValidationError as exc:
        errors.extend(_validation_messages(exc))
        return AdjudicationConfig()


def _int_field(
    form: FormValues,
    key: str,
    errors: list[str],
    label: str,
    *,
    minimum: int,
    default: int,
) -> int:
    raw = form_value(form, key)
    if raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        errors.append(f"{label} must be a whole number.")
        return default
    if value < minimum:
        errors.append(f"{label} must be at least {minimum}.")
        return max(value, minimum)
    return value


def _seconds_field(
    form: FormValues,
    key: str,
    errors: list[str],
    label: str,
    *,
    default: float,
    allow_zero: bool = False,
) -> int:
    raw = form_value(form, key)
    if raw == "":
        value = default
    else:
        try:
            value = float(raw)
        except ValueError:
            errors.append(f"{label} must be a number of seconds.")
            value = default
    if value < 0 or (value == 0 and not allow_zero):
        errors.append(f"{label} must be greater than zero.")
        value = default
    return int(round(value * 1000))


def _validation_messages(exc: ValidationError) -> list[str]:
    messages = []
    for error in exc.errors():
        location = " -> ".join(str(part) for part in error["loc"]) or "settings"
        messages.append(f"{location}: {error['msg']}")
    return messages


_CHECKBOX_FIELDS = (
    "rated",
    "round_robin_double",
    "adjudication_draw",
    "adjudication_resign",
    "adjudication_syzygy",
)


def submitted_form_values(form: FormValues) -> dict[str, Any]:
    """Echo submitted form fields back as pre-fill values (used when a
    submission fails validation and the form is re-rendered)."""
    values = settings_form_values({})
    for key in values:
        if key in _CHECKBOX_FIELDS:
            values[key] = form_flag(form, key)
        elif key in form:
            values[key] = form_value(form, key)
    return values


def settings_form_values(settings: dict[str, Any]) -> dict[str, Any]:
    """Flatten a stored settings/config dict into the field values the
    settings form expects, for pre-filling inputs."""
    values: dict[str, Any] = {
        "format": settings.get("format", "round_robin"),
        "hardware_mode": settings.get("hardware_mode", "shared"),
        "concurrency": settings.get("concurrency", 1),
        "rated": settings.get("rated", True),
        "lag_compensation_ms": settings.get("lag_compensation_ms", 50),
        "opening_suite_id": settings.get("opening_suite_id") or "",
        "round_robin_double": True,
        "swiss_rounds": 7,
        "knockout_games_per_match": 2,
        "knockout_tiebreak": "armageddon",
        "gauntlet_hero_engine_id": "",
        "gauntlet_games_per_opponent": 2,
        "tc_type": "increment",
        "tc_initial_s": 60,
        "tc_increment_s": 1,
        "tc_move_time_s": 1,
        "tc_moves_to_go": 40,
        "tc_nodes": 100000,
        "adjudication_draw": False,
        "draw_min_fullmove": 40,
        "draw_max_abs_cp": 10,
        "draw_plies": 8,
        "adjudication_resign": False,
        "resign_min_abs_cp": 800,
        "resign_plies": 6,
        "adjudication_syzygy": False,
        "syzygy_max_pieces": 6,
        "adjudication_max_moves": "",
    }

    options = settings.get("format_options") or {}
    values["round_robin_double"] = options.get("double_rr", True)
    values["swiss_rounds"] = options.get("rounds", values["swiss_rounds"])
    values["knockout_games_per_match"] = options.get("games_per_match", values["knockout_games_per_match"])
    values["knockout_tiebreak"] = options.get("tiebreak", values["knockout_tiebreak"])
    values["gauntlet_hero_engine_id"] = options.get("hero_engine_id", values["gauntlet_hero_engine_id"])
    values["gauntlet_games_per_opponent"] = options.get(
        "games_per_opponent", values["gauntlet_games_per_opponent"]
    )

    time_control = settings.get("time_control") or {}
    values["tc_type"] = time_control.get("category", "increment")
    if "initial_ms" in time_control:
        values["tc_initial_s"] = time_control["initial_ms"] / 1000
    if "increment_ms" in time_control:
        values["tc_increment_s"] = time_control["increment_ms"] / 1000
    if "move_time_ms" in time_control:
        values["tc_move_time_s"] = time_control["move_time_ms"] / 1000
    if "moves_to_go" in time_control:
        values["tc_moves_to_go"] = time_control["moves_to_go"]
    if "nodes" in time_control:
        values["tc_nodes"] = time_control["nodes"]

    adjudication = settings.get("adjudication") or {}
    draw = adjudication.get("draw")
    if draw:
        values["adjudication_draw"] = True
        values["draw_min_fullmove"] = draw.get("min_fullmove", values["draw_min_fullmove"])
        values["draw_max_abs_cp"] = draw.get("max_abs_cp", values["draw_max_abs_cp"])
        values["draw_plies"] = draw.get("consecutive_plies", values["draw_plies"])
    resign = adjudication.get("resign")
    if resign:
        values["adjudication_resign"] = True
        values["resign_min_abs_cp"] = resign.get("min_abs_cp", values["resign_min_abs_cp"])
        values["resign_plies"] = resign.get("consecutive_plies", values["resign_plies"])
    syzygy = adjudication.get("syzygy")
    if syzygy:
        values["adjudication_syzygy"] = True
        values["syzygy_max_pieces"] = syzygy.get("max_pieces", values["syzygy_max_pieces"])
    if adjudication.get("max_moves"):
        values["adjudication_max_moves"] = adjudication["max_moves"]

    return values
