"""Canonical action-segment facts. Statistics may read only this union."""

from dataclasses import dataclass
from typing import TypeAlias

from courtsim.domain.enums import (
    ContestLevel,
    Coverage,
    CreationMode,
    FoulTeamSide,
    PossessionEndReason,
    ShotZone,
    TechnicalFoulType,
    TurnoverKind,
)
from courtsim.domain.interaction import FinisherSelection
from courtsim.domain.plans import (
    Lineup,
    OffensivePlan,
    PlayerId,
    assist_eligible_for,
    creation_mode_for,
    last_passer_for,
    plan_ball_handler_id,
    validate_coverage,
    validate_finisher_identity,
    validate_lineup,
    validate_plan,
    validate_zone,
)


@dataclass(frozen=True, slots=True)
class StolenTurnover:
    kind: TurnoverKind
    responsible_offender_id: PlayerId
    stealer_id: PlayerId

    def __post_init__(self) -> None:
        if self.kind not in {
            TurnoverKind.LOST_BALL_STEAL,
            TurnoverKind.BAD_PASS_STEAL,
        }:
            raise ValueError("stolen turnover requires a steal turnover kind")


@dataclass(frozen=True, slots=True)
class UnforcedTurnover:
    kind: TurnoverKind
    responsible_offender_id: PlayerId

    def __post_init__(self) -> None:
        if self.kind not in {
            TurnoverKind.LOST_BALL_UNFORCED,
            TurnoverKind.BAD_PASS_UNFORCED,
        }:
            raise ValueError("unforced turnover requires an unforced turnover kind")


@dataclass(frozen=True, slots=True)
class ViolationTurnover:
    responsible_offender_id: PlayerId


TurnoverOutcome: TypeAlias = StolenTurnover | UnforcedTurnover | ViolationTurnover


@dataclass(frozen=True, slots=True)
class OffensiveRebound:
    rebounder_id: PlayerId


@dataclass(frozen=True, slots=True)
class DefensiveRebound:
    rebounder_id: PlayerId


ReboundOutcome: TypeAlias = OffensiveRebound | DefensiveRebound


@dataclass(frozen=True, slots=True)
class TurnoverSegmentResult:
    plan: OffensivePlan
    coverage: Coverage
    outcome: TurnoverOutcome


@dataclass(frozen=True, slots=True)
class NonShootingFoulSegmentResult:
    plan: OffensivePlan
    coverage: Coverage
    offended_player_id: PlayerId
    fouler_id: PlayerId
    free_throws: tuple[bool, ...] = ()
    rebound: ReboundOutcome | None = None

    def __post_init__(self) -> None:
        if len(self.free_throws) not in {0, 2}:
            raise ValueError("non-shooting foul requires zero or two free throws")
        if any(not isinstance(made, bool) for made in self.free_throws):
            raise ValueError("free throw outcomes must be booleans")
        if not self.free_throws:
            if self.rebound is not None:
                raise ValueError("a non-bonus foul cannot have a rebound")
            return
        final_missed = not self.free_throws[-1]
        if final_missed != (self.rebound is not None):
            raise ValueError("only a missed final free throw requires a rebound")

    @property
    def in_bonus(self) -> bool:
        return bool(self.free_throws)


@dataclass(frozen=True, slots=True)
class OffensiveFoulSegmentResult:
    plan: OffensivePlan
    coverage: Coverage
    responsible_offender_id: PlayerId
    defender_id: PlayerId


@dataclass(frozen=True, slots=True)
class TechnicalFoulSegmentResult:
    plan: OffensivePlan
    coverage: Coverage
    foul_type: TechnicalFoulType
    responsible_side: FoulTeamSide
    responsible_player_id: PlayerId | None
    shooter_id: PlayerId
    free_throws: tuple[bool, ...]
    offense_retains_possession: bool

    def __post_init__(self) -> None:
        if len(self.free_throws) != 1 or not isinstance(self.free_throws[0], bool):
            raise ValueError("a technical foul requires exactly one free throw")
        if self.foul_type is TechnicalFoulType.PLAYER and self.responsible_player_id is None:
            raise ValueError("a player technical requires a responsible player")
        if (
            self.foul_type is not TechnicalFoulType.PLAYER
            and self.responsible_player_id is not None
        ):
            raise ValueError("a non-player technical cannot name a responsible player")


@dataclass(frozen=True, slots=True)
class MadeShotSegmentResult:
    plan: OffensivePlan
    coverage: Coverage
    selection: FinisherSelection
    zone: ShotZone
    contest_level: ContestLevel
    assister_id: PlayerId | None = None

    @property
    def creation_mode(self) -> CreationMode:
        return creation_mode_for(self.selection.route)

    @property
    def last_passer_id(self) -> PlayerId | None:
        return last_passer_for(self.plan, self.selection.route)

    @property
    def assist_eligible(self) -> bool:
        return assist_eligible_for(self.plan, self.selection.route)

    @property
    def assisted(self) -> bool:
        return self.assister_id is not None


@dataclass(frozen=True, slots=True)
class MissedShotSegmentResult:
    plan: OffensivePlan
    coverage: Coverage
    selection: FinisherSelection
    zone: ShotZone
    contest_level: ContestLevel
    rebound: ReboundOutcome


@dataclass(frozen=True, slots=True)
class BlockedShotSegmentResult:
    plan: OffensivePlan
    coverage: Coverage
    selection: FinisherSelection
    zone: ShotZone
    blocker_id: PlayerId
    rebound: ReboundOutcome


@dataclass(frozen=True, slots=True)
class ShootingFoulSegmentResult:
    plan: OffensivePlan
    coverage: Coverage
    selection: FinisherSelection
    zone: ShotZone
    contest_level: ContestLevel
    fouler_id: PlayerId
    field_goal_made: bool
    free_throws: tuple[bool, ...]
    rebound: ReboundOutcome | None
    assister_id: PlayerId | None = None

    def __post_init__(self) -> None:
        expected_attempts = 1 if self.field_goal_made else (3 if self.zone is ShotZone.THREE else 2)
        if len(self.free_throws) != expected_attempts:
            raise ValueError("free throw count does not match the shooting foul")
        if not self.free_throws:
            raise ValueError("shooting foul requires at least one free throw")
        if any(not isinstance(made, bool) for made in self.free_throws):
            raise ValueError("free throw outcomes must be booleans")
        final_missed = not self.free_throws[-1]
        if final_missed != (self.rebound is not None):
            raise ValueError("only a missed final free throw requires a rebound")
        if not self.field_goal_made and self.assister_id is not None:
            raise ValueError("a missed field goal cannot have an assister")

    @property
    def assisted(self) -> bool:
        return self.assister_id is not None


ActionSegmentResult: TypeAlias = (
    TurnoverSegmentResult
    | NonShootingFoulSegmentResult
    | OffensiveFoulSegmentResult
    | TechnicalFoulSegmentResult
    | MadeShotSegmentResult
    | MissedShotSegmentResult
    | BlockedShotSegmentResult
    | ShootingFoulSegmentResult
)
ShotSegmentResult: TypeAlias = (
    MadeShotSegmentResult
    | MissedShotSegmentResult
    | BlockedShotSegmentResult
    | ShootingFoulSegmentResult
)


def is_defensive_foul(result: ActionSegmentResult) -> bool:
    return isinstance(
        result,
        (NonShootingFoulSegmentResult, ShootingFoulSegmentResult),
    )


def _validate_player(player_id: PlayerId, lineup: Lineup, role: str) -> None:
    if player_id not in lineup:
        raise ValueError(f"{role} must belong to the expected lineup")


def _validate_rebound(
    rebound: ReboundOutcome, offense_lineup: Lineup, defense_lineup: Lineup
) -> None:
    if isinstance(rebound, OffensiveRebound):
        _validate_player(rebound.rebounder_id, offense_lineup, "offensive rebounder")
    else:
        _validate_player(rebound.rebounder_id, defense_lineup, "defensive rebounder")


def validate_action_segment_result(
    result: ActionSegmentResult,
    offense_lineup: Lineup,
    defense_lineup: Lineup,
) -> None:
    validate_plan(result.plan, offense_lineup)
    validate_lineup(defense_lineup)
    if set(offense_lineup) & set(defense_lineup):
        raise ValueError("offense and defense lineups must be disjoint")
    validate_coverage(result.plan, result.coverage)

    if isinstance(result, TurnoverSegmentResult):
        responsible = result.outcome.responsible_offender_id
        if responsible != plan_ball_handler_id(result.plan):
            raise ValueError("phase-0 turnover belongs to the plan ball handler")
        if isinstance(result.outcome, StolenTurnover):
            _validate_player(result.outcome.stealer_id, defense_lineup, "stealer")
        return

    if isinstance(result, NonShootingFoulSegmentResult):
        if result.offended_player_id != plan_ball_handler_id(result.plan):
            raise ValueError("non-shooting foul belongs to the plan ball handler")
        _validate_player(result.offended_player_id, offense_lineup, "offended player")
        _validate_player(result.fouler_id, defense_lineup, "fouler")
        if result.rebound is not None:
            _validate_rebound(result.rebound, offense_lineup, defense_lineup)
        return

    if isinstance(result, OffensiveFoulSegmentResult):
        if result.responsible_offender_id != plan_ball_handler_id(result.plan):
            raise ValueError("offensive foul belongs to the plan ball handler")
        _validate_player(result.responsible_offender_id, offense_lineup, "offensive fouler")
        _validate_player(result.defender_id, defense_lineup, "fouled defender")
        return

    if isinstance(result, TechnicalFoulSegmentResult):
        responsible_lineup = (
            offense_lineup if result.responsible_side is FoulTeamSide.OFFENSE else defense_lineup
        )
        shooter_lineup = (
            defense_lineup if result.responsible_side is FoulTeamSide.OFFENSE else offense_lineup
        )
        if result.responsible_player_id is not None:
            _validate_player(
                result.responsible_player_id,
                responsible_lineup,
                "technical-foul responsible player",
            )
        _validate_player(result.shooter_id, shooter_lineup, "technical free-throw shooter")
        return

    validate_finisher_identity(result.plan, result.selection.route, result.selection.finisher_id)
    _validate_player(result.selection.finisher_id, offense_lineup, "finisher")
    validate_zone(result.selection.route, result.zone)
    if isinstance(result, BlockedShotSegmentResult):
        _validate_player(result.blocker_id, defense_lineup, "blocker")
        _validate_rebound(result.rebound, offense_lineup, defense_lineup)
    elif isinstance(result, MissedShotSegmentResult):
        _validate_rebound(result.rebound, offense_lineup, defense_lineup)
    elif isinstance(result, ShootingFoulSegmentResult):
        _validate_player(result.fouler_id, defense_lineup, "fouler")
        if result.rebound is not None:
            _validate_rebound(result.rebound, offense_lineup, defense_lineup)
        if result.assister_id is not None:
            _validate_player(result.assister_id, offense_lineup, "assister")
            if result.assister_id == result.selection.finisher_id:
                raise ValueError("assister must differ from the finisher")
            fixed_passer = last_passer_for(result.plan, result.selection.route)
            if fixed_passer is not None and result.assister_id != fixed_passer:
                raise ValueError("assister must match the fixed route passer")
    elif result.assister_id is not None:
        _validate_player(result.assister_id, offense_lineup, "assister")
        if result.assister_id == result.selection.finisher_id:
            raise ValueError("assister must differ from the finisher")
        fixed_passer = last_passer_for(result.plan, result.selection.route)
        if fixed_passer is not None and result.assister_id != fixed_passer:
            raise ValueError("assister must match the fixed route passer")


def offense_retains_ball(result: ActionSegmentResult) -> bool:
    if isinstance(result, NonShootingFoulSegmentResult):
        return not result.in_bonus or isinstance(result.rebound, OffensiveRebound)
    if isinstance(result, TechnicalFoulSegmentResult):
        return result.offense_retains_possession
    return isinstance(
        result,
        (MissedShotSegmentResult, BlockedShotSegmentResult, ShootingFoulSegmentResult),
    ) and (result.rebound is not None and isinstance(result.rebound, OffensiveRebound))


@dataclass(frozen=True, slots=True)
class PossessionResult:
    segments: tuple[ActionSegmentResult, ...]
    end_reason: PossessionEndReason

    @property
    def completed(self) -> bool:
        return self.end_reason is not PossessionEndReason.SEGMENT_LIMIT


def possession_end_reason(result: ActionSegmentResult) -> PossessionEndReason | None:
    if offense_retains_ball(result):
        return None
    if isinstance(result, MadeShotSegmentResult):
        return PossessionEndReason.MADE_SHOT
    if isinstance(result, NonShootingFoulSegmentResult):
        if not result.in_bonus:
            return None
        return PossessionEndReason.FREE_THROW_SEQUENCE
    if isinstance(result, OffensiveFoulSegmentResult):
        return PossessionEndReason.OFFENSIVE_FOUL
    if isinstance(result, TechnicalFoulSegmentResult):
        return PossessionEndReason.TECHNICAL_FREE_THROW
    if isinstance(result, ShootingFoulSegmentResult):
        return PossessionEndReason.FREE_THROW_SEQUENCE
    if isinstance(result, TurnoverSegmentResult):
        return PossessionEndReason.TURNOVER
    return PossessionEndReason.DEFENSIVE_REBOUND


def validate_possession_result(
    result: PossessionResult,
    offense_lineup: Lineup,
    defense_lineup: Lineup,
) -> None:
    if not result.segments:
        raise ValueError("possession must contain at least one segment")
    for segment in result.segments:
        validate_action_segment_result(segment, offense_lineup, defense_lineup)
    for segment in result.segments[:-1]:
        if not offense_retains_ball(segment):
            raise ValueError("only an offense-retaining event may continue a possession")
    natural_end = possession_end_reason(result.segments[-1])
    if result.end_reason is PossessionEndReason.SEGMENT_LIMIT:
        if natural_end is not None:
            raise ValueError("segment limit requires offense to retain the final event")
    elif natural_end is not result.end_reason:
        raise ValueError("possession end reason does not match its final segment")
