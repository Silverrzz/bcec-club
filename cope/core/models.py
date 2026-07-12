from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


PROTOCOL_VERSION = 7
UciOptionValue = str | int | bool


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class WorkerResources(StrictModel):
    threads: int = Field(gt=0)
    hash_mb: int = Field(gt=0)

    def can_run(self, required: WorkerResources) -> bool:
        return self.threads >= required.threads and self.hash_mb >= required.hash_mb


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
    author: str = Field(default="", max_length=120)
    version: str = Field(min_length=1, max_length=80)
    binary_url: str = Field(min_length=1, max_length=500)
    binary_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    binary_size: int = Field(gt=0)
    uci_options: dict[str, UciOptionValue] = Field(default_factory=dict)

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


class KnockoutTiebreak(StrEnum):
    ARMAGEDDON = "armageddon"
    EXTRA_PAIR = "extra_pair"


class RoundRobinFormatOptions(StrictModel):
    games_per_pairing: int = Field(default=2, gt=0)


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
    category_id: int | None = Field(default=1, gt=0)
    category_settings_linked: bool = True
    format: TournamentFormat
    format_options: FormatOptions
    participants: list[int] = Field(min_length=2)
    time_control: TimeControl
    concurrency: int = Field(default=1, gt=0)
    opening_suite_id: int | None = Field(default=None, gt=0)
    adjudication: AdjudicationConfig
    rated: bool = True
    lag_compensation_ms: int = Field(default=50, ge=0)
    engine_threads: int = Field(default=1, gt=0)
    engine_hash_mb: int = Field(default=16, gt=0)
    uci_options: dict[int, dict[str, UciOptionValue]] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def normalize_category_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data = dict(data)
            data.pop("rating_category", None)
            data.pop("hardware_mode", None)
            data.setdefault("category_id", 1)
            data.setdefault("category_settings_linked", data["category_id"] is not None)
        return data

    @field_validator("participants")
    @classmethod
    def validate_participants(cls, value: list[int]) -> list[int]:
        if any(engine_id <= 0 for engine_id in value):
            raise ValueError("participant engine ids must be positive")
        if len(set(value)) != len(value):
            raise ValueError("participants must be unique")
        return value

    @field_validator("uci_options")
    @classmethod
    def validate_tournament_uci_options(
        cls,
        value: dict[int, dict[str, UciOptionValue]],
    ) -> dict[int, dict[str, UciOptionValue]]:
        for engine_id, options in value.items():
            if engine_id <= 0:
                raise ValueError("UCI option engine ids must be positive")
            for name in options:
                if not name.strip():
                    raise ValueError("UCI option names must be non-empty")
                if name.strip().lower() in {"threads", "hash"}:
                    raise ValueError(
                        "Threads and Hash are controlled by tournament resource settings"
                    )
        return value

    @model_validator(mode="after")
    def validate_format_options(self) -> TournamentConfig:
        if self.category_settings_linked != (self.category_id is not None):
            raise ValueError(
                "category tournaments must use category settings and custom tournaments "
                "must not have a rating category"
            )
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

        unknown_option_engines = set(self.uci_options).difference(self.participants)
        if unknown_option_engines:
            raise ValueError("UCI options can only target tournament participants")

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

    def message_fields(self) -> dict[str, int | str]:
        return {
            "assignment_id": self.assignment_id,
            "assignment_key": self.assignment_key,
            "game_id": self.game_id,
        }


class WorkerGameAssignment(StrictModel):
    assignment: GameAssignment
    tournament_name: str = Field(min_length=1)
    round: int = Field(gt=0)
    initial_fen: str = Field(min_length=1)
    opening_name: str | None = None
    max_plies: int = Field(gt=0)
    engines: dict[int, EngineSpec]
    required_resources: WorkerResources

    @field_validator("engines")
    @classmethod
    def validate_engines(cls, value: dict[int, EngineSpec]) -> dict[int, EngineSpec]:
        if not value:
            raise ValueError("assignment must include engine specs")
        for engine_id, spec in value.items():
            if engine_id <= 0:
                raise ValueError("engine ids must be positive")
            if spec.engine_id != engine_id:
                raise ValueError("engine spec id must match its assignment key")
        return value


class AssignmentMessage(StrictModel):
    assignment_id: int = Field(gt=0)
    assignment_key: str = Field(min_length=16, max_length=128)
    game_id: int = Field(gt=0)

    def matches_assignment(self, assignment: GameAssignment) -> bool:
        return (
            self.assignment_id == assignment.assignment_id
            and self.assignment_key == assignment.assignment_key
            and self.game_id == assignment.game_id
        )


class EngineCommand(AssignmentMessage):
    engine_id: int = Field(gt=0)
    command: str = Field(min_length=1)


class EngineCommandResult(AssignmentMessage):
    engine_id: int = Field(gt=0)
    lines: list[str]


class EngineInfo(EngineCommandResult):
    pass


class AssignmentComplete(AssignmentMessage):
    pass


class AssignmentReady(AssignmentMessage):
    prepared_engine_ids: list[int] = Field(min_length=1)

    @field_validator("prepared_engine_ids")
    @classmethod
    def validate_prepared_engine_ids(cls, value: list[int]) -> list[int]:
        if any(engine_id <= 0 for engine_id in value):
            raise ValueError("prepared engine ids must be positive")
        if len(set(value)) != len(value):
            raise ValueError("prepared engine ids must be unique")
        return value


class AssignmentFailed(AssignmentMessage):
    engine_id: int = Field(gt=0)
    engine_name: str = Field(min_length=1, max_length=80)
    stage: Literal["cache", "download", "verify", "start", "runtime"]
    error: str = Field(min_length=1, max_length=8000)


class BenchInfo(StrictModel):
    nps_probe: int | None = Field(default=None, gt=0)


class HardwareInfo(StrictModel):
    cpu_model: str = Field(min_length=1)
    physical_cores: int = Field(gt=0)
    logical_cores: int = Field(gt=0)
    ram_gb: int = Field(gt=0)
    ram_mb: int | None = Field(default=None, gt=0)
    gpu: str | None = None
    os: str = Field(min_length=1)
    python: str = Field(min_length=1)
    bench: BenchInfo = Field(default_factory=BenchInfo)

    @model_validator(mode="after")
    def validate_core_counts(self) -> HardwareInfo:
        if self.logical_cores < self.physical_cores:
            raise ValueError("logical_cores must be >= physical_cores")
        return self

    @property
    def total_ram_mb(self) -> int:
        return self.ram_mb or self.ram_gb * 1024


class WorkerActiveAssignmentsMixin(StrictModel):
    active_assignment_ids: list[int] = Field(default_factory=list)
    machine_id: str = Field(min_length=8, max_length=128)
    resources: WorkerResources

    @field_validator("active_assignment_ids")
    @classmethod
    def validate_active_assignment_ids(cls, value: list[int]) -> list[int]:
        if any(assignment_id <= 0 for assignment_id in value):
            raise ValueError("active assignment ids must be positive")
        if len(set(value)) != len(value):
            raise ValueError("active assignment ids must be unique")
        return value


class WorkerTokenHello(WorkerActiveAssignmentsMixin):
    token: str = Field(min_length=1)
    label_hint: str = Field(default="", max_length=80)
    hw: HardwareInfo
    app_version: str = Field(min_length=1)


class WorkerSessionHello(WorkerActiveAssignmentsMixin):
    session_id: str = Field(min_length=1)
    hw: HardwareInfo
    app_version: str = Field(min_length=1)


class WorkerPoolSlotHello(WorkerActiveAssignmentsMixin):
    slot_token: str = Field(min_length=1)
    hw: HardwareInfo
    app_version: str = Field(min_length=1)


class WorkerPoolEnrollmentHello(StrictModel):
    enrollment_token: str = Field(min_length=1)
    machine_id: str = Field(min_length=8, max_length=128)
    hw: HardwareInfo
    app_version: str = Field(min_length=1)


class WorkerPoolSlotCredential(StrictModel):
    worker_id: int = Field(gt=0)
    label: str = Field(min_length=1, max_length=80)
    slot_token: str = Field(min_length=1)
    resources: WorkerResources


class WorkerPoolWelcome(StrictModel):
    pool_id: int = Field(gt=0)
    label: str = Field(min_length=1, max_length=80)
    machine_id: str = Field(min_length=8, max_length=128)
    slots: list[WorkerPoolSlotCredential] = Field(min_length=1)


class WorkerWelcome(StrictModel):
    worker_id: int = Field(gt=0)
    session_id: str = Field(min_length=1)
    heartbeat_interval_ms: int = Field(gt=0)
    resources: WorkerResources


class Envelope(StrictModel):
    v: Literal[7] = PROTOCOL_VERSION
    type: str = Field(min_length=1)
    seq: int = Field(ge=0)
    t_mono_ms: int = Field(ge=0)
    data: dict[str, Any] = Field(default_factory=dict)
