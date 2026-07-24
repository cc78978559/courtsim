"""Causal action-segment sampler whose numerical policy is externally supplied."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Protocol, TypeAlias, TypeVar

from courtsim.domain.contest import (
    BlockedAttempt,
    ContestResolution,
    LiveAttempt,
    ShotContestContext,
    validate_contest_resolution,
    validate_shot_contest_context,
)
from courtsim.domain.enums import (
    Coverage,
    FinisherRoute,
    ReboundSide,
    ShotZone,
    TurnoverKind,
)
from courtsim.domain.interaction import (
    FinisherSelection,
    InteractionState,
    select_candidate,
    validate_interaction_state,
)
from courtsim.domain.plans import (
    Lineup,
    OffensivePlan,
    PlayerId,
    plan_ball_handler_id,
    validate_coverage,
    validate_route,
    validate_zone,
)
from courtsim.domain.results import (
    ActionSegmentResult,
    BlockedShotSegmentResult,
    DefensiveRebound,
    MadeShotSegmentResult,
    MissedShotSegmentResult,
    NonShootingFoulSegmentResult,
    OffensiveRebound,
    ShootingFoulSegmentResult,
    StolenTurnover,
    TurnoverOutcome,
    TurnoverSegmentResult,
    UnforcedTurnover,
    ViolationTurnover,
    validate_action_segment_result,
)
from courtsim.model.hazards import ReboundHazards
from courtsim.model.trace_mode import TraceMode
from courtsim.probability import (
    ProbabilityNodeResult,
    ProbabilityOption,
    sample_probability_node,
    sample_probability_value,
)
from courtsim.randomness import RandomFrame, RandomSlot


@dataclass(frozen=True, slots=True)
class ShotOpportunity:
    pass


@dataclass(frozen=True, slots=True)
class TurnoverOpportunity:
    kind: TurnoverKind


TerminalOpportunity: TypeAlias = ShotOpportunity | TurnoverOpportunity
AnyNodeResult: TypeAlias = ProbabilityNodeResult[Any]
T = TypeVar("T")


class SegmentProbabilityPolicy(Protocol):
    def prepare_segment(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        interaction: InteractionState,
        offense_lineup: Lineup,
        defense_lineup: Lineup,
    ) -> SegmentProbabilityPolicy: ...

    def terminal_options(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[TerminalOpportunity], ...]: ...

    def non_shooting_foul_options(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[bool], ...] | None: ...

    def non_shooting_fouler_options(
        self,
        plan: OffensivePlan,
        interaction: InteractionState,
        defense_lineup: Lineup,
    ) -> tuple[ProbabilityOption[PlayerId], ...]: ...

    def stealer_options(
        self,
        kind: TurnoverKind,
        interaction: InteractionState,
        defense_lineup: Lineup,
    ) -> tuple[ProbabilityOption[PlayerId], ...]: ...

    def route_options(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[FinisherRoute], ...]: ...

    def finisher_options(
        self,
        route: FinisherRoute,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[PlayerId], ...]: ...

    def zone_options(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[ShotZone], ...]: ...

    def contest_context(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        selection: FinisherSelection,
        zone: ShotZone,
        interaction: InteractionState,
    ) -> ShotContestContext: ...

    def contest_options(
        self,
        context: ShotContestContext,
        zone: ShotZone,
    ) -> tuple[ProbabilityOption[ContestResolution], ...]: ...

    def make_options(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
        zone: ShotZone,
        live_attempt: LiveAttempt,
    ) -> tuple[ProbabilityOption[bool], ...]: ...

    def shooting_foul_options(
        self,
        context: ShotContestContext,
        selection: FinisherSelection,
        zone: ShotZone,
        live_attempt: LiveAttempt,
    ) -> tuple[ProbabilityOption[bool], ...]: ...

    def fouler_options(
        self,
        context: ShotContestContext,
        defense_lineup: Lineup,
    ) -> tuple[ProbabilityOption[PlayerId], ...]: ...

    def free_throw_make_options(
        self,
        shooter_id: PlayerId,
        attempt_number: int,
    ) -> tuple[ProbabilityOption[bool], ...]: ...

    def assist_options(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
    ) -> tuple[ProbabilityOption[bool], ...]: ...

    def assister_options(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
        offense_lineup: Lineup,
    ) -> tuple[ProbabilityOption[PlayerId], ...]: ...

    def rebound_hazards(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
        zone: ShotZone,
        blocker_id: PlayerId | None,
        offense_lineup: Lineup,
        defense_lineup: Lineup,
    ) -> ReboundHazards: ...


@dataclass(frozen=True, slots=True)
class SegmentSample:
    result: ActionSegmentResult
    node_results: tuple[AnyNodeResult, ...]


def _sample(
    frame: RandomFrame,
    slot: RandomSlot,
    options: tuple[ProbabilityOption[T], ...],
    trace: list[AnyNodeResult] | None,
) -> T:
    if trace is None:
        return sample_probability_value(frame, slot, options)
    result = sample_probability_node(frame, slot, options)
    trace.append(result)
    return result.selected


def _turnover_result(
    opportunity: TurnoverOpportunity,
    plan: OffensivePlan,
    coverage: Coverage,
    interaction: InteractionState,
    defense_lineup: Lineup,
    policy: SegmentProbabilityPolicy,
    frame: RandomFrame,
    trace: list[AnyNodeResult] | None,
) -> TurnoverSegmentResult:
    responsible = plan_ball_handler_id(plan)
    kind = opportunity.kind
    if kind in {TurnoverKind.LOST_BALL_STEAL, TurnoverKind.BAD_PASS_STEAL}:
        stealer_options = policy.stealer_options(kind, interaction, defense_lineup)
        if any(option.value not in defense_lineup for option in stealer_options):
            raise ValueError("all stealer options must belong to defense")
        stealer = _sample(
            frame,
            RandomSlot.STEALER,
            stealer_options,
            trace,
        )
        outcome: TurnoverOutcome = StolenTurnover(kind, responsible, stealer)
    elif kind is TurnoverKind.VIOLATION:
        outcome = ViolationTurnover(responsible)
    else:
        outcome = UnforcedTurnover(kind, responsible)
    return TurnoverSegmentResult(plan, coverage, outcome)


def _sample_rebound(
    *,
    plan: OffensivePlan,
    selection: FinisherSelection,
    zone: ShotZone,
    blocker_id: PlayerId | None,
    offense_lineup: Lineup,
    defense_lineup: Lineup,
    policy: SegmentProbabilityPolicy,
    frame: RandomFrame,
    trace: list[AnyNodeResult] | None,
) -> OffensiveRebound | DefensiveRebound:
    hazards = policy.rebound_hazards(
        plan,
        selection,
        zone,
        blocker_id,
        offense_lineup,
        defense_lineup,
    )
    hazards.validate_lineups(offense_lineup, defense_lineup)
    side = _sample(
        frame,
        RandomSlot.REBOUND_SIDE,
        (
            ProbabilityOption(
                "rebound-side:OFFENSE",
                ReboundSide.OFFENSE,
                math.fsum(item.weight for item in hazards.offense),
            ),
            ProbabilityOption(
                "rebound-side:DEFENSE",
                ReboundSide.DEFENSE,
                math.fsum(item.weight for item in hazards.defense),
            ),
        ),
        trace,
    )
    selected_hazards = hazards.offense if side is ReboundSide.OFFENSE else hazards.defense
    rebounder_id = _sample(
        frame,
        RandomSlot.REBOUNDER,
        tuple(
            ProbabilityOption(f"rebounder:{item.player_id}", item.player_id, item.weight)
            for item in selected_hazards
        ),
        trace,
    )
    if side is ReboundSide.OFFENSE:
        return OffensiveRebound(rebounder_id)
    return DefensiveRebound(rebounder_id)


def _sample_assister(
    *,
    plan: OffensivePlan,
    selection: FinisherSelection,
    offense_lineup: Lineup,
    policy: SegmentProbabilityPolicy,
    frame: RandomFrame,
    trace: list[AnyNodeResult] | None,
) -> PlayerId | None:
    assist_options = policy.assist_options(plan, selection)
    if any(not isinstance(option.value, bool) for option in assist_options):
        raise ValueError("assist options must contain booleans")
    assisted = _sample(
        frame,
        RandomSlot.ASSIST_DECISION,
        assist_options,
        trace,
    )
    if not assisted:
        return None
    assister_options = policy.assister_options(plan, selection, offense_lineup)
    if any(
        option.value not in offense_lineup or option.value == selection.finisher_id
        for option in assister_options
    ):
        raise ValueError("all assister options must belong to offense and differ from finisher")
    return _sample(
        frame,
        RandomSlot.ASSISTER,
        assister_options,
        trace,
    )


def _sample_non_shooting_foul_result(
    *,
    plan: OffensivePlan,
    coverage: Coverage,
    interaction: InteractionState,
    offense_lineup: Lineup,
    defense_lineup: Lineup,
    policy: SegmentProbabilityPolicy,
    frame: RandomFrame,
    bonus_free_throws: bool,
    trace: list[AnyNodeResult] | None,
) -> SegmentSample:
    fouler_options = policy.non_shooting_fouler_options(
        plan,
        interaction,
        defense_lineup,
    )
    if any(option.value not in defense_lineup for option in fouler_options):
        raise ValueError("all non-shooting foulers must belong to defense")
    non_shooting_fouler_id = _sample(
        frame,
        RandomSlot.NON_SHOOTING_FOULER,
        fouler_options,
        trace,
    )
    offended_player_id = plan_ball_handler_id(plan)
    free_throws: list[bool] = []
    rebound: OffensiveRebound | DefensiveRebound | None = None
    if bonus_free_throws:
        for attempt_number, slot in enumerate(
            (RandomSlot.FREE_THROW_1, RandomSlot.FREE_THROW_2),
            start=1,
        ):
            options = policy.free_throw_make_options(offended_player_id, attempt_number)
            if any(not isinstance(option.value, bool) for option in options):
                raise ValueError("free throw options must contain booleans")
            free_throws.append(_sample(frame, slot, options, trace))
        if not free_throws[-1]:
            rebound = _sample_rebound(
                plan=plan,
                selection=FinisherSelection(
                    FinisherRoute.INITIATOR_SELF,
                    offended_player_id,
                ),
                zone=ShotZone.RIM,
                blocker_id=None,
                offense_lineup=offense_lineup,
                defense_lineup=defense_lineup,
                policy=policy,
                frame=frame,
                trace=trace,
            )
    result = NonShootingFoulSegmentResult(
        plan,
        coverage,
        offended_player_id,
        non_shooting_fouler_id,
        tuple(free_throws),
        rebound,
    )
    validate_action_segment_result(result, offense_lineup, defense_lineup)
    return SegmentSample(result, tuple(trace or ()))


def sample_forced_non_shooting_foul(
    *,
    plan: OffensivePlan,
    coverage: Coverage,
    interaction: InteractionState,
    offense_lineup: Lineup,
    defense_lineup: Lineup,
    policy: SegmentProbabilityPolicy,
    frame: RandomFrame,
    bonus_free_throws: bool,
    trace_mode: TraceMode = TraceMode.FULL,
) -> SegmentSample:
    """Resolve a state-selected foul while preserving formal attribution RNG slots."""
    validate_interaction_state(plan, interaction, offense_lineup, defense_lineup)
    validate_coverage(plan, coverage)
    prepared = policy.prepare_segment(
        plan,
        coverage,
        interaction,
        offense_lineup,
        defense_lineup,
    )
    trace: list[AnyNodeResult] | None = [] if trace_mode is TraceMode.FULL else None
    return _sample_non_shooting_foul_result(
        plan=plan,
        coverage=coverage,
        interaction=interaction,
        offense_lineup=offense_lineup,
        defense_lineup=defense_lineup,
        policy=prepared,
        frame=frame,
        bonus_free_throws=bonus_free_throws,
        trace=trace,
    )


def sample_action_segment(
    *,
    plan: OffensivePlan,
    coverage: Coverage,
    interaction: InteractionState,
    offense_lineup: Lineup,
    defense_lineup: Lineup,
    policy: SegmentProbabilityPolicy,
    frame: RandomFrame,
    bonus_free_throws: bool = False,
    trace_mode: TraceMode = TraceMode.FULL,
) -> SegmentSample:
    validate_interaction_state(plan, interaction, offense_lineup, defense_lineup)
    validate_coverage(plan, coverage)
    policy = policy.prepare_segment(plan, coverage, interaction, offense_lineup, defense_lineup)
    trace: list[AnyNodeResult] | None = [] if trace_mode is TraceMode.FULL else None
    non_shooting_foul_options = policy.non_shooting_foul_options(
        plan,
        coverage,
        interaction,
    )
    if non_shooting_foul_options is not None:
        if any(not isinstance(option.value, bool) for option in non_shooting_foul_options):
            raise ValueError("non-shooting foul options must contain booleans")
        non_shooting_foul = _sample(
            frame,
            RandomSlot.NON_SHOOTING_FOUL,
            non_shooting_foul_options,
            trace,
        )
        if non_shooting_foul:
            return _sample_non_shooting_foul_result(
                plan=plan,
                coverage=coverage,
                interaction=interaction,
                offense_lineup=offense_lineup,
                defense_lineup=defense_lineup,
                policy=policy,
                frame=frame,
                bonus_free_throws=bonus_free_throws,
                trace=trace,
            )
    terminal = _sample(
        frame,
        RandomSlot.TERMINAL,
        policy.terminal_options(plan, coverage, interaction),
        trace,
    )
    if isinstance(terminal, TurnoverOpportunity):
        result: ActionSegmentResult = _turnover_result(
            terminal,
            plan,
            coverage,
            interaction,
            defense_lineup,
            policy,
            frame,
            trace,
        )
        validate_action_segment_result(result, offense_lineup, defense_lineup)
        return SegmentSample(result, tuple(trace or ()))

    route_options = policy.route_options(plan, coverage, interaction)
    for route_option in route_options:
        validate_route(plan, route_option.value)
    route = _sample(
        frame,
        RandomSlot.FINISHER_ROUTE,
        route_options,
        trace,
    )
    finisher_options = policy.finisher_options(route, interaction)
    for finisher_option in finisher_options:
        select_candidate(interaction, FinisherSelection(route, finisher_option.value))
    finisher_id = _sample(
        frame,
        RandomSlot.FINISHER_PLAYER,
        finisher_options,
        trace,
    )
    selection = FinisherSelection(route, finisher_id)
    select_candidate(interaction, selection)
    zone_options = policy.zone_options(plan, selection, interaction)
    for zone_option in zone_options:
        validate_zone(route, zone_option.value)
    zone = _sample(
        frame,
        RandomSlot.SHOT_ZONE,
        zone_options,
        trace,
    )
    context = policy.contest_context(plan, coverage, selection, zone, interaction)
    validate_shot_contest_context(context, selection, zone, offense_lineup, defense_lineup)
    contest_options = policy.contest_options(context, zone)
    for contest_option in contest_options:
        validate_contest_resolution(context, contest_option.value)
    contest = _sample(
        frame,
        RandomSlot.CONTEST,
        contest_options,
        trace,
    )
    validate_contest_resolution(context, contest)
    if isinstance(contest, BlockedAttempt):
        rebound = _sample_rebound(
            plan=plan,
            selection=selection,
            zone=zone,
            blocker_id=contest.blocker_id,
            offense_lineup=offense_lineup,
            defense_lineup=defense_lineup,
            policy=policy,
            frame=frame,
            trace=trace,
        )
        result = BlockedShotSegmentResult(
            plan, coverage, selection, zone, contest.blocker_id, rebound
        )
    else:
        foul_options = policy.shooting_foul_options(context, selection, zone, contest)
        if any(not isinstance(option.value, bool) for option in foul_options):
            raise ValueError("shooting foul options must contain booleans")
        shooting_foul = _sample(
            frame,
            RandomSlot.SHOOTING_FOUL,
            foul_options,
            trace,
        )
        fouler_id: PlayerId | None = None
        if shooting_foul:
            fouler_options = policy.fouler_options(context, defense_lineup)
            if any(option.value not in defense_lineup for option in fouler_options):
                raise ValueError("all fouler options must belong to defense")
            fouler_id = _sample(
                frame,
                RandomSlot.FOULER,
                fouler_options,
                trace,
            )
        make_options = policy.make_options(plan, selection, zone, contest)
        if any(not isinstance(make_option.value, bool) for make_option in make_options):
            raise ValueError("make options must contain booleans")
        made = _sample(
            frame,
            RandomSlot.SHOT_MAKE,
            make_options,
            trace,
        )
        assister_id = (
            _sample_assister(
                plan=plan,
                selection=selection,
                offense_lineup=offense_lineup,
                policy=policy,
                frame=frame,
                trace=trace,
            )
            if made
            else None
        )
        if shooting_foul:
            if fouler_id is None:
                raise AssertionError("sampled shooting foul must have a fouler")
            free_throw_count = 1 if made else (3 if zone is ShotZone.THREE else 2)
            free_throw_slots = (
                RandomSlot.FREE_THROW_1,
                RandomSlot.FREE_THROW_2,
                RandomSlot.FREE_THROW_3,
            )
            free_throws: list[bool] = []
            for attempt_number in range(1, free_throw_count + 1):
                options = policy.free_throw_make_options(
                    selection.finisher_id,
                    attempt_number,
                )
                if any(not isinstance(option.value, bool) for option in options):
                    raise ValueError("free throw options must contain booleans")
                free_throws.append(
                    _sample(
                        frame,
                        free_throw_slots[attempt_number - 1],
                        options,
                        trace,
                    )
                )
            foul_rebound = (
                _sample_rebound(
                    plan=plan,
                    selection=selection,
                    zone=zone,
                    blocker_id=None,
                    offense_lineup=offense_lineup,
                    defense_lineup=defense_lineup,
                    policy=policy,
                    frame=frame,
                    trace=trace,
                )
                if not free_throws[-1]
                else None
            )
            result = ShootingFoulSegmentResult(
                plan,
                coverage,
                selection,
                zone,
                contest.contest_level,
                fouler_id,
                made,
                tuple(free_throws),
                foul_rebound,
                assister_id,
            )
        elif made:
            result = MadeShotSegmentResult(
                plan,
                coverage,
                selection,
                zone,
                contest.contest_level,
                assister_id,
            )
        else:
            rebound = _sample_rebound(
                plan=plan,
                selection=selection,
                zone=zone,
                blocker_id=None,
                offense_lineup=offense_lineup,
                defense_lineup=defense_lineup,
                policy=policy,
                frame=frame,
                trace=trace,
            )
            result = MissedShotSegmentResult(
                plan,
                coverage,
                selection,
                zone,
                contest.contest_level,
                rebound,
            )
    validate_action_segment_result(result, offense_lineup, defense_lineup)
    return SegmentSample(result, tuple(trace or ()))
