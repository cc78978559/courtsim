"""Reusable player hazard sets shared by team and player attribution nodes."""

import math
from dataclasses import dataclass

from courtsim.domain.plans import Lineup, PlayerId


@dataclass(frozen=True, slots=True)
class PlayerHazard:
    player_id: PlayerId
    weight: float

    def __post_init__(self) -> None:
        if self.player_id < 0:
            raise ValueError("hazard player_id must be non-negative")
        if not math.isfinite(self.weight) or self.weight < 0:
            raise ValueError("hazard weight must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class StealHazards:
    entries: tuple[PlayerHazard, ...]
    team_pressure: float

    def __post_init__(self) -> None:
        _validate_entries(self.entries, "steal")
        if not math.isfinite(self.team_pressure):
            raise ValueError("team steal pressure must be finite")


@dataclass(frozen=True, slots=True)
class ReboundHazards:
    offense: tuple[PlayerHazard, ...]
    defense: tuple[PlayerHazard, ...]

    def __post_init__(self) -> None:
        _validate_entries(self.offense, "offensive rebound", allow_all_zero=True)
        _validate_entries(self.defense, "defensive rebound", allow_all_zero=True)
        if math.fsum(item.weight for item in (*self.offense, *self.defense)) <= 0:
            raise ValueError("at least one rebound hazard must be positive")

    def validate_lineups(self, offense_lineup: Lineup, defense_lineup: Lineup) -> None:
        if {item.player_id for item in self.offense} != set(offense_lineup):
            raise ValueError("offensive rebound hazards must cover the offense lineup")
        if {item.player_id for item in self.defense} != set(defense_lineup):
            raise ValueError("defensive rebound hazards must cover the defense lineup")


def _validate_entries(
    entries: tuple[PlayerHazard, ...],
    field: str,
    *,
    allow_all_zero: bool = False,
) -> None:
    if not entries:
        raise ValueError(f"{field} hazards must not be empty")
    ids = tuple(item.player_id for item in entries)
    if len(ids) != len(set(ids)):
        raise ValueError(f"{field} hazard players must be unique")
    if not allow_all_zero and math.fsum(item.weight for item in entries) <= 0:
        raise ValueError(f"{field} hazards need a positive weight")
