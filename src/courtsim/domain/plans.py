"""Offensive plan unions and the frozen legality contract."""

from dataclasses import dataclass
from typing import TypeAlias

from courtsim.domain.enums import (
    Coverage,
    CreationMode,
    FinisherRoute,
    PlayFamily,
    ShotZone,
    TacticalAction,
)

PlayerId: TypeAlias = int
Lineup: TypeAlias = tuple[PlayerId, PlayerId, PlayerId, PlayerId, PlayerId]


def _require_player_id(player_id: PlayerId, field: str) -> None:
    if player_id < 0:
        raise ValueError(f"{field} must be non-negative")


@dataclass(frozen=True, slots=True)
class BallScreenPlan:
    handler_id: PlayerId
    screener_id: PlayerId

    def __post_init__(self) -> None:
        _require_player_id(self.handler_id, "handler_id")
        _require_player_id(self.screener_id, "screener_id")
        if self.handler_id == self.screener_id:
            raise ValueError("handler and screener must be distinct")

    @property
    def family(self) -> PlayFamily:
        return PlayFamily.BALL_SCREEN


@dataclass(frozen=True, slots=True)
class IsolationPlan:
    initiator_id: PlayerId

    def __post_init__(self) -> None:
        _require_player_id(self.initiator_id, "initiator_id")

    @property
    def family(self) -> PlayFamily:
        return PlayFamily.ISOLATION


@dataclass(frozen=True, slots=True)
class OffBallActionPlan:
    passer_id: PlayerId
    target_id: PlayerId
    screen_setter_id: PlayerId | None = None

    def __post_init__(self) -> None:
        _require_player_id(self.passer_id, "passer_id")
        _require_player_id(self.target_id, "target_id")
        if self.screen_setter_id is not None:
            _require_player_id(self.screen_setter_id, "screen_setter_id")
        participants = [self.passer_id, self.target_id]
        if self.screen_setter_id is not None:
            participants.append(self.screen_setter_id)
        if len(participants) != len(set(participants)):
            raise ValueError("off-ball plan participants must be pairwise distinct")

    @property
    def family(self) -> PlayFamily:
        return PlayFamily.OFF_BALL_ACTION


OffensivePlan: TypeAlias = BallScreenPlan | IsolationPlan | OffBallActionPlan

LEGAL_COVERAGES_BY_PLAY: dict[PlayFamily, frozenset[Coverage]] = {
    PlayFamily.BALL_SCREEN: frozenset(
        {Coverage.BASE, Coverage.DROP, Coverage.SWITCH, Coverage.BLITZ}
    ),
    PlayFamily.ISOLATION: frozenset({Coverage.BASE, Coverage.BLITZ}),
    PlayFamily.OFF_BALL_ACTION: frozenset({Coverage.BASE, Coverage.SWITCH}),
}

LEGAL_ROUTES_BY_PLAY: dict[PlayFamily, frozenset[FinisherRoute]] = {
    PlayFamily.BALL_SCREEN: frozenset(
        {
            FinisherRoute.INITIATOR_SELF,
            FinisherRoute.SCREENER_ROLL,
            FinisherRoute.SCREENER_POP,
            FinisherRoute.HELP_RELEASE,
        }
    ),
    PlayFamily.ISOLATION: frozenset({FinisherRoute.INITIATOR_SELF, FinisherRoute.HELP_RELEASE}),
    PlayFamily.OFF_BALL_ACTION: frozenset(
        {
            FinisherRoute.DESIGNED_OFF_BALL_TARGET,
            FinisherRoute.INITIATOR_BAILOUT,
        }
    ),
}

LEGAL_ZONES_BY_ROUTE: dict[FinisherRoute, frozenset[ShotZone]] = {
    FinisherRoute.INITIATOR_SELF: frozenset(ShotZone),
    FinisherRoute.SCREENER_ROLL: frozenset({ShotZone.RIM, ShotZone.MIDRANGE}),
    FinisherRoute.SCREENER_POP: frozenset({ShotZone.MIDRANGE, ShotZone.THREE}),
    FinisherRoute.HELP_RELEASE: frozenset({ShotZone.MIDRANGE, ShotZone.THREE}),
    FinisherRoute.DESIGNED_OFF_BALL_TARGET: frozenset({ShotZone.MIDRANGE, ShotZone.THREE}),
    FinisherRoute.INITIATOR_BAILOUT: frozenset(ShotZone),
}

CREATION_MODE_BY_ROUTE: dict[FinisherRoute, CreationMode] = {
    FinisherRoute.INITIATOR_SELF: CreationMode.SELF_CREATED,
    FinisherRoute.SCREENER_ROLL: CreationMode.SCREEN_PARTNER_FEED,
    FinisherRoute.SCREENER_POP: CreationMode.SCREEN_PARTNER_FEED,
    FinisherRoute.HELP_RELEASE: CreationMode.SPOT_UP_FEED,
    FinisherRoute.DESIGNED_OFF_BALL_TARGET: CreationMode.OFF_BALL_MOVEMENT_FEED,
    FinisherRoute.INITIATOR_BAILOUT: CreationMode.SELF_CREATED,
}

ASSIST_ELIGIBLE_MODES = frozenset(
    {
        CreationMode.SCREEN_PARTNER_FEED,
        CreationMode.SPOT_UP_FEED,
        CreationMode.OFF_BALL_MOVEMENT_FEED,
    }
)


def validate_lineup(lineup: Lineup) -> None:
    if len(lineup) != 5 or len(set(lineup)) != 5:
        raise ValueError("lineup must contain exactly five distinct players")
    for player_id in lineup:
        _require_player_id(player_id, "lineup player")


def plan_participants(plan: OffensivePlan) -> tuple[PlayerId, ...]:
    if isinstance(plan, BallScreenPlan):
        return (plan.handler_id, plan.screener_id)
    if isinstance(plan, IsolationPlan):
        return (plan.initiator_id,)
    participants = (plan.passer_id, plan.target_id)
    if plan.screen_setter_id is None:
        return participants
    return (*participants, plan.screen_setter_id)


def validate_plan(plan: OffensivePlan, offense_lineup: Lineup) -> None:
    validate_lineup(offense_lineup)
    missing = set(plan_participants(plan)) - set(offense_lineup)
    if missing:
        raise ValueError(f"plan participants not in offense lineup: {sorted(missing)}")


def legal_coverages_for(plan: OffensivePlan) -> frozenset[Coverage]:
    if isinstance(plan, OffBallActionPlan) and plan.screen_setter_id is None:
        return frozenset({Coverage.BASE})
    return LEGAL_COVERAGES_BY_PLAY[plan.family]


def validate_coverage(plan: OffensivePlan, coverage: Coverage) -> None:
    if coverage not in legal_coverages_for(plan):
        raise ValueError(f"{coverage.name} is illegal for {plan.family.name}")


def validate_route(plan: OffensivePlan, route: FinisherRoute) -> None:
    if route not in LEGAL_ROUTES_BY_PLAY[plan.family]:
        raise ValueError(f"{route.name} is illegal for {plan.family.name}")


def validate_zone(route: FinisherRoute, zone: ShotZone) -> None:
    if zone not in LEGAL_ZONES_BY_ROUTE[route]:
        raise ValueError(f"{zone.name} is illegal for {route.name}")


def creation_mode_for(route: FinisherRoute) -> CreationMode:
    return CREATION_MODE_BY_ROUTE[route]


def tactical_action_for(plan: OffensivePlan, route: FinisherRoute) -> TacticalAction:
    """Name an existing plan/route combination without changing its probability."""
    validate_route(plan, route)
    if isinstance(plan, BallScreenPlan):
        return {
            FinisherRoute.INITIATOR_SELF: TacticalAction.BALL_SCREEN_KEEP,
            FinisherRoute.SCREENER_ROLL: TacticalAction.BALL_SCREEN_ROLL,
            FinisherRoute.SCREENER_POP: TacticalAction.BALL_SCREEN_POP,
            FinisherRoute.HELP_RELEASE: TacticalAction.BALL_SCREEN_KICKOUT,
        }[route]
    if isinstance(plan, IsolationPlan):
        return (
            TacticalAction.ISOLATION_ATTACK
            if route is FinisherRoute.INITIATOR_SELF
            else TacticalAction.ISOLATION_KICKOUT
        )
    if route is FinisherRoute.INITIATOR_BAILOUT:
        return TacticalAction.OFF_BALL_BAILOUT
    return (
        TacticalAction.PINDOWN if plan.screen_setter_id is not None else TacticalAction.BACKDOOR_CUT
    )


def plan_ball_handler_id(plan: OffensivePlan) -> PlayerId:
    if isinstance(plan, BallScreenPlan):
        return plan.handler_id
    if isinstance(plan, IsolationPlan):
        return plan.initiator_id
    return plan.passer_id


def expected_fixed_finisher(plan: OffensivePlan, route: FinisherRoute) -> PlayerId | None:
    validate_route(plan, route)
    if route is FinisherRoute.HELP_RELEASE:
        return None
    if isinstance(plan, BallScreenPlan):
        return plan.handler_id if route is FinisherRoute.INITIATOR_SELF else plan.screener_id
    if isinstance(plan, IsolationPlan):
        return plan.initiator_id
    return plan.target_id if route is FinisherRoute.DESIGNED_OFF_BALL_TARGET else plan.passer_id


def validate_finisher_identity(
    plan: OffensivePlan, route: FinisherRoute, finisher_id: PlayerId
) -> None:
    _require_player_id(finisher_id, "finisher_id")
    fixed = expected_fixed_finisher(plan, route)
    if fixed is not None and finisher_id != fixed:
        raise ValueError(f"{route.name} must finish through player {fixed}")
    if route is FinisherRoute.HELP_RELEASE and finisher_id in plan_participants(plan):
        raise ValueError("help release finisher must be outside the plan participants")


def last_passer_for(plan: OffensivePlan, route: FinisherRoute) -> PlayerId | None:
    validate_route(plan, route)
    if creation_mode_for(route) is CreationMode.SELF_CREATED:
        return None
    return plan_ball_handler_id(plan)


def assist_eligible_for(plan: OffensivePlan, route: FinisherRoute) -> bool:
    validate_route(plan, route)
    return creation_mode_for(route) in ASSIST_ELIGIBLE_MODES
