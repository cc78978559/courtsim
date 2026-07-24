"""Player-aware sampling of an offensive plan and defensive response."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, TypeAlias, TypeVar, cast

from courtsim.domain.enums import Coverage, PlayFamily
from courtsim.domain.plans import (
    BallScreenPlan,
    IsolationPlan,
    Lineup,
    OffBallActionPlan,
    OffensivePlan,
    PlayerId,
    legal_coverages_for,
    validate_lineup,
)
from courtsim.domain.player import PlayerProfile
from courtsim.dynamic_roles import LineupDynamicRoles, RoleAllocation, derive_lineup_dynamic_roles
from courtsim.model.interaction_compiler import (
    DefensiveMatchups,
    ProfileLineup,
    compile_interaction_state,
)
from courtsim.model.player_aware_policy import PlayerAwareCompiledPolicy
from courtsim.model.segment_sampler import (
    SegmentSample,
    sample_action_segment,
    sample_forced_non_shooting_foul,
)
from courtsim.model.trace_mode import TraceMode
from courtsim.parameters import ModelParameters
from courtsim.player_features import centered_mix_bias, scalar_tendency_bias
from courtsim.probability import (
    ProbabilityNodeResult,
    ProbabilityOption,
    sample_probability_node,
    sample_probability_value,
)
from courtsim.randomness import RandomFrame, RandomSlot

SetupValue: TypeAlias = PlayFamily | Coverage | PlayerId | None
SetupNodeResult: TypeAlias = ProbabilityNodeResult[SetupValue]
T = TypeVar("T")


def _validated_biases(pairs: tuple[tuple[T, float], ...], field: str) -> dict[T, float]:
    result: dict[T, float] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"{field} contains a duplicate key")
        if not math.isfinite(value) or abs(value) > 2.0:
            raise ValueError(f"{field} values must be finite and within [-2, 2]")
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class TeamOffenseStrategy:
    play_family_logit_biases: tuple[tuple[PlayFamily, float], ...] = ()

    def biases(self) -> dict[PlayFamily, float]:
        return _validated_biases(self.play_family_logit_biases, "play_family_logit_biases")


@dataclass(frozen=True, slots=True)
class TeamDefenseStrategy:
    coverage_logit_biases: tuple[tuple[Coverage, float], ...] = ()

    def biases(self) -> dict[Coverage, float]:
        return _validated_biases(self.coverage_logit_biases, "coverage_logit_biases")


@dataclass(frozen=True, slots=True)
class ActionSetup:
    plan: OffensivePlan
    coverage: Coverage
    offense_roles: LineupDynamicRoles
    defense_roles: LineupDynamicRoles
    node_results: tuple[SetupNodeResult, ...]


@dataclass(frozen=True, slots=True)
class PreparedSegmentSample:
    setup: ActionSetup
    segment: SegmentSample


def _node(parameters: ModelParameters, name: str) -> Mapping[str, Any]:
    nodes = cast(Mapping[str, Any], parameters.payload["nodes"])
    return cast(Mapping[str, Any], nodes[name])


def _role_share(allocation: RoleAllocation, player_id: PlayerId) -> float:
    return next(entry.share for entry in allocation.entries if entry.player_id == player_id)


def _role_preference(profile: PlayerProfile, role: str) -> float:
    values = (
        profile.tendencies.play_role_mix.handler,
        profile.tendencies.play_role_mix.post,
        profile.tendencies.play_role_mix.spot_up,
        profile.tendencies.play_role_mix.cutter,
        profile.tendencies.play_role_mix.screener,
    )
    names = ("handler", "post", "spot_up", "cutter", "screener")
    return dict(zip(names, centered_mix_bias(values), strict=True))[role]


def _player_options(
    *,
    candidates: tuple[PlayerId, ...],
    profiles: Mapping[PlayerId, PlayerProfile],
    allocation: RoleAllocation,
    role: str,
    involvement_coefficient: float,
    role_preference_coefficient: float,
) -> tuple[ProbabilityOption[PlayerId], ...]:
    return tuple(
        ProbabilityOption(
            f"player:{player_id}",
            player_id,
            _role_share(allocation, player_id)
            * math.exp(
                involvement_coefficient
                * scalar_tendency_bias(profiles[player_id].tendencies.offensive_involvement)
                + role_preference_coefficient * _role_preference(profiles[player_id], role)
            ),
        )
        for player_id in sorted(candidates)
    )


def _sample(
    frame: RandomFrame,
    slot: RandomSlot,
    options: tuple[ProbabilityOption[T], ...],
    trace: list[SetupNodeResult] | None,
) -> T:
    if trace is None:
        return sample_probability_value(frame, slot, options)
    result = sample_probability_node(frame, slot, options)
    trace.append(cast(SetupNodeResult, result))
    return result.selected


def sample_action_setup(
    *,
    parameters: ModelParameters,
    offense_lineup: Lineup,
    defense_lineup: Lineup,
    offense_profiles: ProfileLineup,
    defense_profiles: ProfileLineup,
    frame: RandomFrame,
    offense_strategy: TeamOffenseStrategy | None = None,
    defense_strategy: TeamDefenseStrategy | None = None,
    trace_mode: TraceMode = TraceMode.FULL,
) -> ActionSetup:
    """Sample a legal setup without using spatial simulation."""
    offense_strategy = offense_strategy or TeamOffenseStrategy()
    defense_strategy = defense_strategy or TeamDefenseStrategy()
    validate_lineup(offense_lineup)
    validate_lineup(defense_lineup)
    offense = {profile.player_id: profile for profile in offense_profiles}
    defense = {profile.player_id: profile for profile in defense_profiles}
    if set(offense) != set(offense_lineup) or set(defense) != set(defense_lineup):
        raise ValueError("profiles must match their lineups")
    offense_roles = derive_lineup_dynamic_roles(offense_profiles)
    defense_roles = derive_lineup_dynamic_roles(defense_profiles)
    trace: list[SetupNodeResult] | None = [] if trace_mode is TraceMode.FULL else None

    play_parameter = _node(parameters, "play_selection")
    play_base = cast(Mapping[str, Any], play_parameter["base_probabilities"])
    play_bias = offense_strategy.biases()
    family = _sample(
        frame,
        RandomSlot.PLAY_FAMILY,
        tuple(
            ProbabilityOption(
                f"play:{play.name}",
                play,
                float(play_base[play.name]) * math.exp(play_bias.get(play, 0.0)),
            )
            for play in PlayFamily
        ),
        trace,
    )

    participant = _node(parameters, "participant_selection")
    involvement = float(participant["involvement_coefficient"])
    preference = float(participant["role_preference_coefficient"])
    initiator = _sample(
        frame,
        RandomSlot.PLAN_INITIATOR,
        _player_options(
            candidates=offense_lineup,
            profiles=offense,
            allocation=offense_roles.handler,
            role="handler",
            involvement_coefficient=involvement,
            role_preference_coefficient=preference,
        ),
        trace,
    )
    remaining = tuple(player_id for player_id in offense_lineup if player_id != initiator)
    if family is PlayFamily.BALL_SCREEN:
        partner = _sample(
            frame,
            RandomSlot.PLAN_PARTNER,
            _player_options(
                candidates=remaining,
                profiles=offense,
                allocation=offense_roles.screener,
                role="screener",
                involvement_coefficient=involvement,
                role_preference_coefficient=preference,
            ),
            trace,
        )
        plan: OffensivePlan = BallScreenPlan(initiator, partner)
    elif family is PlayFamily.ISOLATION:
        plan = IsolationPlan(initiator)
    else:
        target = _sample(
            frame,
            RandomSlot.OFFBALL_TARGET,
            _player_options(
                candidates=remaining,
                profiles=offense,
                allocation=offense_roles.spacer,
                role="spot_up",
                involvement_coefficient=involvement,
                role_preference_coefficient=preference,
            ),
            trace,
        )
        setter_candidates = tuple(player_id for player_id in remaining if player_id != target)
        no_screen_probability = float(participant["offball_no_screen_probability"])
        setter_player_options = _player_options(
            candidates=setter_candidates,
            profiles=offense,
            allocation=offense_roles.screener,
            role="screener",
            involvement_coefficient=involvement,
            role_preference_coefficient=preference,
        )
        setter_total = math.fsum(option.weight for option in setter_player_options)
        setter_options: tuple[ProbabilityOption[PlayerId | None], ...] = (
            ProbabilityOption("screen-setter:NONE", None, no_screen_probability),
            *tuple(
                ProbabilityOption[PlayerId | None](
                    option.id,
                    option.value,
                    (1.0 - no_screen_probability) * option.weight / setter_total,
                )
                for option in setter_player_options
            ),
        )
        setter: PlayerId | None = _sample(
            frame,
            RandomSlot.OFFBALL_SCREEN_SETTER,
            setter_options,
            trace,
        )
        plan = OffBallActionPlan(initiator, target, setter)

    defense_response = _node(parameters, "defense_response")
    base_by_context = cast(Mapping[str, Any], defense_response["base_probabilities"])
    context = (
        f"{family.name}|WITH_SCREEN"
        if isinstance(plan, OffBallActionPlan) and plan.screen_setter_id is not None
        else family.name
    )
    coverage_base = cast(Mapping[str, Any], base_by_context[context])
    help_effect = cast(Mapping[str, Any], defense_response["help_aggression_effect"])
    help_aggression = math.fsum(
        _role_share(defense_roles.rim_protector, player_id)
        * scalar_tendency_bias(profile.tendencies.help_aggression)
        for player_id, profile in defense.items()
    )
    coverage_bias = defense_strategy.biases()
    legal = legal_coverages_for(plan)
    coverage = _sample(
        frame,
        RandomSlot.COVERAGE,
        tuple(
            ProbabilityOption(
                f"coverage:{item.name}",
                item,
                float(coverage_base[item.name])
                * math.exp(
                    float(help_effect[item.name]) * help_aggression + coverage_bias.get(item, 0.0)
                ),
            )
            for item in Coverage
            if item in legal
        ),
        trace,
    )
    return ActionSetup(plan, coverage, offense_roles, defense_roles, tuple(trace or ()))


def sample_prepared_action_segment(
    *,
    parameters: ModelParameters,
    offense_lineup: Lineup,
    defense_lineup: Lineup,
    offense_profiles: ProfileLineup,
    defense_profiles: ProfileLineup,
    matchups: DefensiveMatchups,
    frame: RandomFrame,
    bonus_free_throws: bool = False,
    offense_strategy: TeamOffenseStrategy | None = None,
    defense_strategy: TeamDefenseStrategy | None = None,
    trace_mode: TraceMode = TraceMode.FULL,
) -> PreparedSegmentSample:
    setup = sample_action_setup(
        parameters=parameters,
        offense_lineup=offense_lineup,
        defense_lineup=defense_lineup,
        offense_profiles=offense_profiles,
        defense_profiles=defense_profiles,
        frame=frame,
        offense_strategy=offense_strategy,
        defense_strategy=defense_strategy,
        trace_mode=trace_mode,
    )
    interaction = compile_interaction_state(
        parameters=parameters,
        plan=setup.plan,
        coverage=setup.coverage,
        offense_lineup=offense_lineup,
        defense_lineup=defense_lineup,
        offense_profiles=offense_profiles,
        defense_profiles=defense_profiles,
        matchups=matchups,
    )
    policy = PlayerAwareCompiledPolicy(parameters, offense_profiles, defense_profiles)
    segment = sample_action_segment(
        plan=setup.plan,
        coverage=setup.coverage,
        interaction=interaction,
        offense_lineup=offense_lineup,
        defense_lineup=defense_lineup,
        policy=policy,
        frame=frame,
        bonus_free_throws=bonus_free_throws,
        trace_mode=trace_mode,
    )
    return PreparedSegmentSample(setup, segment)


def sample_prepared_intentional_foul_segment(
    *,
    parameters: ModelParameters,
    offense_lineup: Lineup,
    defense_lineup: Lineup,
    offense_profiles: ProfileLineup,
    defense_profiles: ProfileLineup,
    matchups: DefensiveMatchups,
    frame: RandomFrame,
    bonus_free_throws: bool,
    offense_strategy: TeamOffenseStrategy | None = None,
    defense_strategy: TeamDefenseStrategy | None = None,
    trace_mode: TraceMode = TraceMode.FULL,
) -> PreparedSegmentSample:
    """Sample normal matchup context, then force the formal bonus-foul event."""
    setup = sample_action_setup(
        parameters=parameters,
        offense_lineup=offense_lineup,
        defense_lineup=defense_lineup,
        offense_profiles=offense_profiles,
        defense_profiles=defense_profiles,
        frame=frame,
        offense_strategy=offense_strategy,
        defense_strategy=defense_strategy,
        trace_mode=trace_mode,
    )
    interaction = compile_interaction_state(
        parameters=parameters,
        plan=setup.plan,
        coverage=setup.coverage,
        offense_lineup=offense_lineup,
        defense_lineup=defense_lineup,
        offense_profiles=offense_profiles,
        defense_profiles=defense_profiles,
        matchups=matchups,
    )
    policy = PlayerAwareCompiledPolicy(parameters, offense_profiles, defense_profiles)
    segment = sample_forced_non_shooting_foul(
        plan=setup.plan,
        coverage=setup.coverage,
        interaction=interaction,
        offense_lineup=offense_lineup,
        defense_lineup=defense_lineup,
        policy=policy,
        frame=frame,
        bonus_free_throws=bonus_free_throws,
        trace_mode=trace_mode,
    )
    return PreparedSegmentSample(setup, segment)
