"""Deterministic rotation schedules and bounded fatigue state."""

from __future__ import annotations

from dataclasses import dataclass, replace

from courtsim.domain.enums import SubstitutionReason
from courtsim.domain.game import GameResult
from courtsim.domain.plans import Lineup, PlayerId, validate_lineup
from courtsim.domain.player import AbilityRatings, PlayerProfile

FATIGUE_VERSION = "fatigue-v1"
ROTATION_VERSION = "rotation-v1"


@dataclass(frozen=True, slots=True)
class RotationAudit:
    scheduled_substitutions: int
    foul_out_substitutions: int
    players_used: int
    total_player_seconds: int
    maximum_final_fatigue: int


def audit_rotations(result: GameResult) -> RotationAudit:
    return RotationAudit(
        scheduled_substitutions=sum(
            item.reason is SubstitutionReason.ROTATION for item in result.substitutions
        ),
        foul_out_substitutions=sum(
            item.reason is SubstitutionReason.FOUL_OUT for item in result.substitutions
        ),
        players_used=len(result.playing_time),
        total_player_seconds=sum(item.seconds for item in result.playing_time),
        maximum_final_fatigue=max(
            (item.fatigue for item in result.final_fatigue),
            default=0,
        ),
    )


@dataclass(frozen=True, slots=True)
class RotationStint:
    period: int
    start_clock_seconds: int
    lineup: Lineup

    def __post_init__(self) -> None:
        if not isinstance(self.period, int) or isinstance(self.period, bool) or self.period < 1:
            raise ValueError("rotation period must be a positive integer")
        if (
            not isinstance(self.start_clock_seconds, int)
            or isinstance(self.start_clock_seconds, bool)
            or self.start_clock_seconds < 0
        ):
            raise ValueError("rotation clock must be a non-negative integer")
        validate_lineup(self.lineup)


@dataclass(frozen=True, slots=True)
class RotationPlan:
    stints: tuple[RotationStint, ...]
    version: str = ROTATION_VERSION

    def __post_init__(self) -> None:
        if self.version != ROTATION_VERSION:
            raise ValueError(f"unsupported rotation version: {self.version}")
        addresses = tuple((item.period, item.start_clock_seconds) for item in self.stints)
        if len(addresses) != len(set(addresses)):
            raise ValueError("rotation stint addresses must be unique")
        if addresses != tuple(sorted(addresses, key=lambda item: (item[0], -item[1]))):
            raise ValueError("rotation stints must be ordered by period and descending clock")

    def target_lineup(self, period: int, clock_seconds: int, default: Lineup) -> Lineup:
        eligible = tuple(
            item
            for item in self.stints
            if item.period == period and clock_seconds <= item.start_clock_seconds
        )
        return eligible[-1].lineup if eligible else default


@dataclass(frozen=True, slots=True)
class FatigueConfig:
    version: str = FATIGUE_VERSION
    active_load_per_second: int = 2
    bench_recovery_per_second: int = 3
    maximum_ability_penalty: int = 12
    maximum_fatigue: int = 10_000

    def __post_init__(self) -> None:
        if self.version != FATIGUE_VERSION:
            raise ValueError(f"unsupported fatigue version: {self.version}")
        rates = (self.active_load_per_second, self.bench_recovery_per_second)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in rates
        ):
            raise ValueError("fatigue load and recovery must be non-negative integers")
        bounds = (self.maximum_ability_penalty, self.maximum_fatigue)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in bounds
        ):
            raise ValueError("fatigue bounds must be positive integers")
        if self.maximum_ability_penalty > 100:
            raise ValueError("maximum_ability_penalty cannot exceed 100")


def update_fatigue(
    fatigue: dict[PlayerId, int],
    *,
    active_lineup: Lineup,
    roster_order: tuple[PlayerId, ...],
    elapsed_seconds: int,
    config: FatigueConfig,
) -> dict[PlayerId, int]:
    if (
        not isinstance(elapsed_seconds, int)
        or isinstance(elapsed_seconds, bool)
        or elapsed_seconds < 0
    ):
        raise ValueError("elapsed_seconds must be a non-negative integer")
    active = set(active_lineup)
    result = dict(fatigue)
    for player_id in roster_order:
        result[player_id] = (
            min(
                config.maximum_fatigue,
                fatigue.get(player_id, 0) + elapsed_seconds * config.active_load_per_second,
            )
            if player_id in active
            else max(
                0,
                fatigue.get(player_id, 0) - elapsed_seconds * config.bench_recovery_per_second,
            )
        )
    return result


_FATIGUE_AFFECTED_ABILITIES = frozenset(
    {
        "perimeter_creation",
        "ball_security",
        "rim_finishing",
        "midrange_shooting",
        "three_point_shooting",
        "free_throw_shooting",
        "point_of_attack_defense",
        "rim_protection",
        "offensive_rebounding",
        "defensive_rebounding",
        "offensive_decision",
        "defensive_awareness",
    }
)


def fatigue_adjusted_profile(
    profile: PlayerProfile,
    fatigue: int,
    config: FatigueConfig,
) -> PlayerProfile:
    if (
        not isinstance(fatigue, int)
        or isinstance(fatigue, bool)
        or not 0 <= fatigue <= config.maximum_fatigue
    ):
        raise ValueError("fatigue must be within the configured range")
    penalty = fatigue * config.maximum_ability_penalty // config.maximum_fatigue
    if penalty == 0:
        return profile
    values = {
        field_name: max(0, getattr(profile.abilities, field_name) - penalty)
        if field_name in _FATIGUE_AFFECTED_ABILITIES
        else getattr(profile.abilities, field_name)
        for field_name in AbilityRatings.__dataclass_fields__
    }
    return replace(profile, abilities=AbilityRatings(**values))
