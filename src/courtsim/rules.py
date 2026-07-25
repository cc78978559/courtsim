"""Versioned game-rule decisions independent of the probability model."""

from __future__ import annotations

from dataclasses import dataclass

from courtsim.domain.plans import Lineup, PlayerId
from courtsim.domain.player import PlayerProfile
from courtsim.domain.results import (
    ActionSegmentResult,
    OffensiveFoulSegmentResult,
    TechnicalFoulSegmentResult,
)

RULES_VERSION = "nba-v1"


@dataclass(frozen=True, slots=True)
class RuleEventAudit:
    offensive_fouls: int
    technical_fouls: int


def audit_rule_events(segments: tuple[ActionSegmentResult, ...]) -> RuleEventAudit:
    """Count rule events without folding them into legacy event channels."""

    return RuleEventAudit(
        offensive_fouls=sum(isinstance(item, OffensiveFoulSegmentResult) for item in segments),
        technical_fouls=sum(isinstance(item, TechnicalFoulSegmentResult) for item in segments),
    )


def select_technical_free_throw_shooter(
    eligible_profiles: tuple[PlayerProfile, ...],
) -> PlayerId:
    """Select the best eligible free-throw shooter, breaking ties by player id."""

    if not eligible_profiles:
        raise ValueError("technical free-throw shooter selection requires an eligible player")
    return min(
        eligible_profiles,
        key=lambda profile: (-profile.abilities.free_throw_shooting, profile.player_id),
    ).player_id


@dataclass(frozen=True, slots=True)
class GameRules:
    version: str = RULES_VERSION
    player_foul_limit: int = 6
    regulation_bonus_threshold: int = 5
    final_two_minute_threshold: int = 2
    final_two_minute_seconds: int = 120
    overtime_bonus_threshold: int = 4

    def __post_init__(self) -> None:
        if self.version != RULES_VERSION:
            raise ValueError(f"unsupported rules version: {self.version}")
        values = (
            self.player_foul_limit,
            self.regulation_bonus_threshold,
            self.final_two_minute_threshold,
            self.final_two_minute_seconds,
            self.overtime_bonus_threshold,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in values
        ):
            raise ValueError("game-rule thresholds must be positive integers")


def non_shooting_foul_free_throws(
    rules: GameRules,
    *,
    period: int,
    regulation_periods: int,
    clock_seconds: int,
    period_team_fouls_before: int,
    final_two_minute_team_fouls_before: int,
) -> int:
    """Return the canonical two-shot penalty for the next defensive foul."""

    values = (
        period,
        regulation_periods,
        clock_seconds,
        period_team_fouls_before,
        final_two_minute_team_fouls_before,
    )
    if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
        raise ValueError("foul-state values must be integers")
    if period < 1 or regulation_periods < 1 or clock_seconds < 0:
        raise ValueError("period and clock state is invalid")
    if period_team_fouls_before < 0 or final_two_minute_team_fouls_before < 0:
        raise ValueError("foul counts must be non-negative")
    threshold = (
        rules.overtime_bonus_threshold
        if period > regulation_periods
        else rules.regulation_bonus_threshold
    )
    period_penalty = period_team_fouls_before + 1 >= threshold
    final_two_penalty = (
        clock_seconds <= rules.final_two_minute_seconds
        and final_two_minute_team_fouls_before + 1 >= rules.final_two_minute_threshold
    )
    return 2 if period_penalty or final_two_penalty else 0


def ineligible_players(player_fouls: dict[PlayerId, int], rules: GameRules) -> frozenset[PlayerId]:
    return frozenset(
        player_id for player_id, fouls in player_fouls.items() if fouls >= rules.player_foul_limit
    )


def select_legal_replacement(
    *,
    active_lineup: Lineup,
    roster_order: tuple[PlayerId, ...],
    ineligible: frozenset[PlayerId],
) -> PlayerId | None:
    """Select the first roster-order player who can legally enter."""

    return next(
        (
            player_id
            for player_id in roster_order
            if player_id not in active_lineup and player_id not in ineligible
        ),
        None,
    )


def replace_ineligible_players(
    *,
    active_lineup: Lineup,
    roster_order: tuple[PlayerId, ...],
    ineligible: frozenset[PlayerId],
) -> Lineup | None:
    """Return a deterministic legal lineup, or ``None`` when no replacement exists."""

    lineup = list(active_lineup)
    for index, player_id in enumerate(lineup):
        if player_id not in ineligible:
            continue
        replacement = select_legal_replacement(
            active_lineup=tuple(lineup),  # type: ignore[arg-type]
            roster_order=roster_order,
            ineligible=ineligible,
        )
        if replacement is None:
            return None
        lineup[index] = replacement
    return tuple(lineup)  # type: ignore[return-value]
