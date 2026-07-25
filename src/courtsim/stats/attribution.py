"""Deterministic box-score attribution from canonical segment results."""

from dataclasses import dataclass
from enum import IntEnum

from courtsim.domain.enums import ShotZone
from courtsim.domain.plans import Lineup
from courtsim.domain.results import (
    ActionSegmentResult,
    BlockedShotSegmentResult,
    DefensiveRebound,
    MadeShotSegmentResult,
    NonShootingFoulSegmentResult,
    OffensiveFoulSegmentResult,
    OffensiveRebound,
    PossessionResult,
    ShootingFoulSegmentResult,
    StolenTurnover,
    TechnicalFoulSegmentResult,
    TurnoverSegmentResult,
    validate_possession_result,
)


class StatCode(IntEnum):
    PTS = 0
    FGM = 1
    FGA = 2
    TWO_PM = 3
    TWO_PA = 4
    THREE_PM = 5
    THREE_PA = 6
    OREB = 7
    DREB = 8
    REB = 9
    AST = 10
    STL = 11
    BLK = 12
    TOV = 13
    FTM = 14
    FTA = 15
    PF = 16
    TF = 17


@dataclass(frozen=True, slots=True)
class PlayerStatDelta:
    player_id: int
    stat: StatCode
    amount: int


@dataclass(frozen=True, slots=True)
class StatAttribution:
    player_deltas: tuple[PlayerStatDelta, ...]
    score_delta: int
    possession_delta: int
    opponent_score_delta: int = 0


def attribute_segment(result: ActionSegmentResult) -> StatAttribution:
    totals: dict[tuple[int, StatCode], int] = {}

    def add(player_id: int, stat: StatCode, amount: int = 1) -> None:
        key = (player_id, stat)
        totals[key] = totals.get(key, 0) + amount

    score_delta = 0
    opponent_score_delta = 0
    possession_delta = 1
    if isinstance(result, TurnoverSegmentResult):
        add(result.outcome.responsible_offender_id, StatCode.TOV)
        if isinstance(result.outcome, StolenTurnover):
            add(result.outcome.stealer_id, StatCode.STL)
    elif isinstance(result, OffensiveFoulSegmentResult):
        add(result.responsible_offender_id, StatCode.PF)
        add(result.responsible_offender_id, StatCode.TOV)
    elif isinstance(result, TechnicalFoulSegmentResult):
        free_throws_made = sum(result.free_throws)
        add(result.shooter_id, StatCode.FTA)
        if free_throws_made:
            add(result.shooter_id, StatCode.FTM)
            add(result.shooter_id, StatCode.PTS)
            if result.responsible_side.value == 0:
                opponent_score_delta = 1
            else:
                score_delta = 1
        if result.responsible_player_id is not None:
            add(result.responsible_player_id, StatCode.TF)
        possession_delta = int(not result.offense_retains_possession)
    elif isinstance(result, NonShootingFoulSegmentResult):
        add(result.fouler_id, StatCode.PF)
        possession_delta = 0
        if result.free_throws:
            shooter = result.offended_player_id
            add(shooter, StatCode.FTA, len(result.free_throws))
            free_throws_made = sum(result.free_throws)
            if free_throws_made:
                add(shooter, StatCode.FTM, free_throws_made)
                add(shooter, StatCode.PTS, free_throws_made)
                score_delta += free_throws_made
            if result.rebound is None or isinstance(result.rebound, DefensiveRebound):
                possession_delta = 1
            if result.rebound is not None:
                add(result.rebound.rebounder_id, StatCode.REB)
                add(
                    result.rebound.rebounder_id,
                    (
                        StatCode.OREB
                        if isinstance(result.rebound, OffensiveRebound)
                        else StatCode.DREB
                    ),
                )
    elif isinstance(result, ShootingFoulSegmentResult):
        shooter = result.selection.finisher_id
        add(result.fouler_id, StatCode.PF)
        add(shooter, StatCode.FTA, len(result.free_throws))
        free_throws_made = sum(result.free_throws)
        if free_throws_made:
            add(shooter, StatCode.FTM, free_throws_made)
            add(shooter, StatCode.PTS, free_throws_made)
            score_delta += free_throws_made
        if result.field_goal_made:
            field_goal_points = 3 if result.zone is ShotZone.THREE else 2
            score_delta += field_goal_points
            add(shooter, StatCode.PTS, field_goal_points)
            add(shooter, StatCode.FGA)
            add(shooter, StatCode.FGM)
            add(
                shooter,
                StatCode.THREE_PA if result.zone is ShotZone.THREE else StatCode.TWO_PA,
            )
            add(
                shooter,
                StatCode.THREE_PM if result.zone is ShotZone.THREE else StatCode.TWO_PM,
            )
            if result.assister_id is not None:
                add(result.assister_id, StatCode.AST)
        if result.rebound is not None:
            rebound = result.rebound
            add(rebound.rebounder_id, StatCode.REB)
            if isinstance(rebound, OffensiveRebound):
                add(rebound.rebounder_id, StatCode.OREB)
                possession_delta = 0
            else:
                add(rebound.rebounder_id, StatCode.DREB)
    else:
        shooter = result.selection.finisher_id
        add(shooter, StatCode.FGA)
        if result.zone is ShotZone.THREE:
            add(shooter, StatCode.THREE_PA)
        else:
            add(shooter, StatCode.TWO_PA)

        if isinstance(result, MadeShotSegmentResult):
            score_delta = 3 if result.zone is ShotZone.THREE else 2
            add(shooter, StatCode.PTS, score_delta)
            add(shooter, StatCode.FGM)
            add(
                shooter,
                StatCode.THREE_PM if result.zone is ShotZone.THREE else StatCode.TWO_PM,
            )
            if result.assister_id is not None:
                add(result.assister_id, StatCode.AST)
        else:
            if isinstance(result, BlockedShotSegmentResult):
                add(result.blocker_id, StatCode.BLK)
            rebound = result.rebound
            add(rebound.rebounder_id, StatCode.REB)
            if isinstance(rebound, OffensiveRebound):
                add(rebound.rebounder_id, StatCode.OREB)
                possession_delta = 0
            elif isinstance(rebound, DefensiveRebound):
                add(rebound.rebounder_id, StatCode.DREB)

    deltas = tuple(
        PlayerStatDelta(player_id, stat, amount)
        for (player_id, stat), amount in sorted(
            totals.items(), key=lambda item: (item[0][0], int(item[0][1]))
        )
    )
    return StatAttribution(deltas, score_delta, possession_delta, opponent_score_delta)


def attribute_possession(
    result: PossessionResult,
    offense_lineup: Lineup,
    defense_lineup: Lineup,
) -> StatAttribution:
    validate_possession_result(result, offense_lineup, defense_lineup)
    totals: dict[tuple[int, StatCode], int] = {}
    score_delta = 0
    opponent_score_delta = 0
    for segment in result.segments:
        attribution = attribute_segment(segment)
        score_delta += attribution.score_delta
        opponent_score_delta += attribution.opponent_score_delta
        for delta in attribution.player_deltas:
            key = (delta.player_id, delta.stat)
            totals[key] = totals.get(key, 0) + delta.amount
    deltas = tuple(
        PlayerStatDelta(player_id, stat, amount)
        for (player_id, stat), amount in sorted(
            totals.items(), key=lambda item: (item[0][0], int(item[0][1]))
        )
    )
    return StatAttribution(
        deltas,
        score_delta,
        int(result.completed),
        opponent_score_delta,
    )
