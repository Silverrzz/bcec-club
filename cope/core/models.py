from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PROTOCOL_VERSION = 1
UciOptionValue = str | int | bool


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TimeControlCategory(StrEnum):
    INCREMENT = "increment"
    MOVETIME = "movetime"
    MOVESTOGO = "movestogo"
    MOVENODES = "movenodes"


class IncrementTimeControl(StrictModel):
    category: Literal["increment"] = "increment"
    initial_ms: int = Field(gt=0)
    increment_ms: int = Field(ge=0)


class MoveTimeControl(StrictModel):
    category: Literal["movetime"] = "movetime"
    move_time_ms: int = Field(gt=0)


class MovesToGoTimeControl(StrictModel):
    category: Literal["movestogo"] = "movestogo"
    initial_ms: int = Field(gt=0)
    moves_to_go: int = Field(gt=0)


class MoveNodesTimeControl(StrictModel):
    category: Literal["movenodes"] = "movenodes"
    nodes: int = Field(gt=0)


TimeControl = Annotated[
    IncrementTimeControl | MoveTimeControl | MovesToGoTimeControl | MoveNodesTimeControl,
    Field(discriminator="category"),
]


class DrawAdjudicationRule(StrictModel):
    min_fullmove: int = Field(gt=0)
    max_abs_cp: int = Field(ge=0)
    consecutive_plies: int = Field(gt=0)


class ResignAdjudicationRule(StrictModel):
    min_abs_cp: int = Field(gt=0)
    consecutive_plies: int = Field(gt=0)


class SyzygyAdjudicationRule(StrictModel):
    max_pieces: int = Field(ge=2, le=7)


class AdjudicationConfig(StrictModel):
    draw: DrawAdjudicationRule | None = None
    resign: ResignAdjudicationRule | None = None
    syzygy: SyzygyAdjudicationRule | None = None
    max_moves: int | None = Field(default=None, gt=0)


class EngineSpec(StrictModel):
    engine_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=80)
    git_url: str = Field(min_length=1)
    commit: str
    build_cmd: str = Field(min_length=1)
    binary_path: str = Field(min_length=1)
    uci_options: dict[str, UciOptionValue] = Field(default_factory=dict)

    @field_validator("commit")
    @classmethod
    def validate_commit(cls, value: str) -> str:
        if len(value) != 40 or any(char not in "0123456789abcdefABCDEF" for char in value):
            raise ValueError("commit must be a full 40-character hex SHA")
        return value.lower()

    @field_validator("uci_options")
    @classmethod
    def validate_uci_options(cls, value: dict[str, UciOptionValue]) -> dict[str, UciOptionValue]:
        for name in value:
            if not name.strip():
                raise ValueError("uci option names must be non-empty")
        return value


class TournamentFormat(StrEnum):
    ROUND_ROBIN = "round_robin"
    SWISS = "swiss"
    KNOCKOUT = "knockout"
    GAUNTLET = "gauntlet"


class RatingCategory(StrEnum):
    BULLET = "bullet"
    BLITZ = "blitz"
    RAPID = "rapid"
    CLASSICAL = "classical"
    NODES = "nodes"


class HardwareMode(StrEnum):
    SHARED = "shared"
    PAIRED = "paired"


class KnockoutTiebreak(StrEnum):
    ARMAGEDDON = "armageddon"
    EXTRA_PAIR = "extra_pair"


class RoundRobinFormatOptions(StrictModel):
    double_rr: bool = True


class SwissFormatOptions(StrictModel):
    rounds: int = Field(gt=0)


class KnockoutFormatOptions(StrictModel):
    games_per_match: int = Field(gt=0)
    tiebreak: KnockoutTiebreak


class GauntletFormatOptions(StrictModel):
    hero_engine_id: int = Field(gt=0)
    games_per_opponent: int = Field(gt=0)


FormatOptions = (
    RoundRobinFormatOptions | SwissFormatOptions | KnockoutFormatOptions | GauntletFormatOptions
)


class TournamentConfig(StrictModel):
    format: TournamentFormat
    format_options: FormatOptions
    participants: list[int] = Field(min_length=2)
    time_control: TimeControl
    rating_category: RatingCategory
    hardware_mode: HardwareMode
    concurrency: int = Field(gt=0)
    opening_suite_id: int | None = Field(default=None, gt=0)
    adjudication: AdjudicationConfig
    rated: bool = True
    lag_compensation_ms: int = Field(default=50, ge=0)

    @field_validator("participants")
    @classmethod
    def validate_participants(cls, value: list[int]) -> list[int]:
        if any(engine_id <= 0 for engine_id in value):
            raise ValueError("participant engine ids must be positive")
        if len(set(value)) != len(value):
            raise ValueError("participants must be unique")
        return value

    @model_validator(mode="after")
    def validate_format_options(self) -> TournamentConfig:
        expected: dict[TournamentFormat, type[StrictModel]] = {
            TournamentFormat.ROUND_ROBIN: RoundRobinFormatOptions,
            TournamentFormat.SWISS: SwissFormatOptions,
            TournamentFormat.KNOCKOUT: KnockoutFormatOptions,
            TournamentFormat.GAUNTLET: GauntletFormatOptions,
        }
        expected_type = expected[self.format]
        if not isinstance(self.format_options, expected_type):
            raise ValueError(f"{self.format.value} requires {expected_type.__name__}")

        if isinstance(self.format_options, GauntletFormatOptions):
            if self.format_options.hero_engine_id not in self.participants:
                raise ValueError("gauntlet hero_engine_id must be in participants")

        return self


class ColorSlot(StrEnum):
    WHITE = "W"
    BLACK = "B"


class GameAssignment(StrictModel):
    assignment_id: int = Field(gt=0)
    assignment_key: str = Field(min_length=16, max_length=128)
    game_id: int = Field(gt=0)
    slots: dict[ColorSlot, int]
    time_control: TimeControl
    uci_options_overrides: dict[int, dict[str, UciOptionValue]] = Field(default_factory=dict)

    @field_validator("slots")
    @classmethod
    def validate_slots(cls, value: dict[ColorSlot, int]) -> dict[ColorSlot, int]:
        if not 1 <= len(value) <= 2:
            raise ValueError("slots must contain one or two colour assignments")
        for engine_id in value.values():
            if engine_id <= 0:
                raise ValueError("slot engine ids must be positive")
        return value

    @field_validator("uci_options_overrides")
    @classmethod
    def validate_overrides(
        cls,
        value: dict[int, dict[str, UciOptionValue]],
    ) -> dict[int, dict[str, UciOptionValue]]:
        for engine_id, options in value.items():
            if engine_id <= 0:
                raise ValueError("override engine ids must be positive")
            for name in options:
                if not name.strip():
                    raise ValueError("uci option override names must be non-empty")
        return value


class BenchInfo(StrictModel):
    nps_probe: int | None = Field(default=None, gt=0)


class HardwareInfo(StrictModel):
    cpu_model: str = Field(min_length=1)
    physical_cores: int = Field(gt=0)
    logical_cores: int = Field(gt=0)
    ram_gb: int = Field(gt=0)
    gpu: str | None = None
    os: str = Field(min_length=1)
    python: str = Field(min_length=1)
    bench: BenchInfo = Field(default_factory=BenchInfo)

    @model_validator(mode="after")
    def validate_core_counts(self) -> HardwareInfo:
        if self.logical_cores < self.physical_cores:
            raise ValueError("logical_cores must be >= physical_cores")
        return self


class WorkerTokenHello(StrictModel):
    token: str = Field(min_length=1)
    label_hint: str = Field(default="", max_length=80)
    hw: HardwareInfo
    app_commit: str = Field(min_length=1)
    active_assignment_ids: list[int] = Field(default_factory=list)

    @field_validator("active_assignment_ids")
    @classmethod
    def validate_active_assignment_ids(cls, value: list[int]) -> list[int]:
        if any(assignment_id <= 0 for assignment_id in value):
            raise ValueError("active assignment ids must be positive")
        if len(set(value)) != len(value):
            raise ValueError("active assignment ids must be unique")
        return value


class WorkerSessionHello(StrictModel):
    session_id: str = Field(min_length=1)
    hw: HardwareInfo
    app_commit: str = Field(min_length=1)
    active_assignment_ids: list[int] = Field(default_factory=list)

    @field_validator("active_assignment_ids")
    @classmethod
    def validate_active_assignment_ids(cls, value: list[int]) -> list[int]:
        if any(assignment_id <= 0 for assignment_id in value):
            raise ValueError("active assignment ids must be positive")
        if len(set(value)) != len(value):
            raise ValueError("active assignment ids must be unique")
        return value


class WorkerWelcome(StrictModel):
    worker_id: int = Field(gt=0)
    session_id: str = Field(min_length=1)
    heartbeat_interval_ms: int = Field(gt=0)


class Envelope(StrictModel):
    v: Literal[1] = PROTOCOL_VERSION
    type: str = Field(min_length=1)
    seq: int = Field(ge=0)
    t_mono_ms: int = Field(ge=0)
    data: dict[str, Any] = Field(default_factory=dict)
