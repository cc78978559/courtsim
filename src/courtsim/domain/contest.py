"""Shot contest structures, created only after route, finisher and zone selection."""

from dataclasses import dataclass
from math import isfinite
from typing import TypeAlias

from courtsim.domain.enums import ContestLevel, ShotZone
from courtsim.domain.interaction import FinisherSelection
from courtsim.domain.plans import Lineup, PlayerId, validate_lineup, validate_zone


@dataclass(frozen=True, slots=True)
class ShotContestContext:
    primary_contest: float
    help_contest: float
    primary_defender_id: PlayerId | None
    help_defender_id: PlayerId | None
    block_candidate_ids: tuple[PlayerId, ...]

    def __post_init__(self) -> None:
        if not isfinite(self.primary_contest) or not isfinite(self.help_contest):
            raise ValueError("contest values must be finite")
        if len(self.block_candidate_ids) != len(set(self.block_candidate_ids)):
            raise ValueError("block candidates must be unique")
        for player_id in self.block_candidate_ids:
            if player_id < 0:
                raise ValueError("block candidate ids must be non-negative")


@dataclass(frozen=True, slots=True)
class LiveAttempt:
    contest_level: ContestLevel


@dataclass(frozen=True, slots=True)
class BlockedAttempt:
    blocker_id: PlayerId

    def __post_init__(self) -> None:
        if self.blocker_id < 0:
            raise ValueError("blocker_id must be non-negative")


ContestResolution: TypeAlias = LiveAttempt | BlockedAttempt


def validate_shot_contest_context(
    context: ShotContestContext,
    selection: FinisherSelection,
    zone: ShotZone,
    offense_lineup: Lineup,
    defense_lineup: Lineup,
) -> None:
    validate_lineup(offense_lineup)
    validate_lineup(defense_lineup)
    validate_zone(selection.route, zone)
    if selection.finisher_id not in offense_lineup:
        raise ValueError("shot finisher must belong to offense")
    defender_ids = (
        context.primary_defender_id,
        context.help_defender_id,
        *context.block_candidate_ids,
    )
    if any(player_id is not None and player_id not in defense_lineup for player_id in defender_ids):
        raise ValueError("contest defenders must belong to defense")


def validate_contest_resolution(context: ShotContestContext, resolution: ContestResolution) -> None:
    if (
        isinstance(resolution, BlockedAttempt)
        and resolution.blocker_id not in context.block_candidate_ids
    ):
        raise ValueError("blocker must be one of the post-zone block candidates")
