"""Deterministic player/profile compilation into the frozen InteractionState."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from courtsim.domain.enums import Coverage, FinisherRoute, PlayFamily
from courtsim.domain.interaction import FinisherCandidateProfile, InteractionState
from courtsim.domain.plans import (
    LEGAL_ROUTES_BY_PLAY,
    BallScreenPlan,
    IsolationPlan,
    Lineup,
    OffBallActionPlan,
    OffensivePlan,
    PlayerId,
    expected_fixed_finisher,
    plan_ball_handler_id,
    plan_participants,
    validate_coverage,
    validate_plan,
)
from courtsim.domain.player import PlayerProfile
from courtsim.parameters import ModelParameters
from courtsim.player_features import ability_rating_to_z, scalar_tendency_bias

ProfileLineup = tuple[
    PlayerProfile,
    PlayerProfile,
    PlayerProfile,
    PlayerProfile,
    PlayerProfile,
]


@dataclass(frozen=True, slots=True)
class Matchup:
    offender_id: PlayerId
    defender_id: PlayerId

    def __post_init__(self) -> None:
        if self.offender_id < 0 or self.defender_id < 0:
            raise ValueError("matchup player ids must be non-negative")


@dataclass(frozen=True, slots=True)
class DefensiveMatchups:
    assignments: tuple[Matchup, Matchup, Matchup, Matchup, Matchup]

    def as_map(self, offense_lineup: Lineup, defense_lineup: Lineup) -> dict[PlayerId, PlayerId]:
        offenders = tuple(item.offender_id for item in self.assignments)
        defenders = tuple(item.defender_id for item in self.assignments)
        if set(offenders) != set(offense_lineup):
            raise ValueError("matchups must cover every offensive player exactly once")
        if set(defenders) != set(defense_lineup):
            raise ValueError("matchups must cover every defensive player exactly once")
        return {item.offender_id: item.defender_id for item in self.assignments}


def _profiles(
    profiles: ProfileLineup, expected_lineup: Lineup, field: str
) -> dict[PlayerId, PlayerProfile]:
    result = {profile.player_id: profile for profile in profiles}
    if len(result) != 5 or set(result) != set(expected_lineup):
        raise ValueError(f"{field} profiles must match its lineup")
    return result


def _interaction_parameters(parameters: ModelParameters) -> Mapping[str, Any]:
    nodes = cast(Mapping[str, Any], parameters.payload["nodes"])
    return cast(Mapping[str, Any], nodes["interaction"])


def _coefficient(parameters: Mapping[str, Any], field: str) -> float:
    coefficients = cast(Mapping[str, Any], parameters["coefficients"])
    return float(coefficients[field])


def _coverage_delta(
    parameters: Mapping[str, Any],
    play: PlayFamily,
    coverage: Coverage,
    dimension: str,
) -> float:
    table = cast(Mapping[str, Any], parameters["coverage_deltas"])
    context = cast(Mapping[str, Any], table[f"{play.name}|{coverage.name}"])
    return float(context[dimension])


def _choose_help_defender(
    defense: Mapping[PlayerId, PlayerProfile],
    excluded: frozenset[PlayerId],
) -> PlayerId:
    eligible = [profile for player_id, profile in defense.items() if player_id not in excluded]
    if not eligible:
        raise ValueError("at least one help defender must remain eligible")
    return min(
        eligible,
        key=lambda profile: (
            -(
                ability_rating_to_z(profile.abilities.defensive_awareness)
                + 0.25 * scalar_tendency_bias(profile.tendencies.help_aggression)
            ),
            profile.player_id,
        ),
    ).player_id


def compile_interaction_state(
    *,
    parameters: ModelParameters,
    plan: OffensivePlan,
    coverage: Coverage,
    offense_lineup: Lineup,
    defense_lineup: Lineup,
    offense_profiles: ProfileLineup,
    defense_profiles: ProfileLineup,
    matchups: DefensiveMatchups,
) -> InteractionState:
    validate_plan(plan, offense_lineup)
    validate_coverage(plan, coverage)
    offense = _profiles(offense_profiles, offense_lineup, "offense")
    defense = _profiles(defense_profiles, defense_lineup, "defense")
    matchup = matchups.as_map(offense_lineup, defense_lineup)
    parameter = _interaction_parameters(parameters)
    handler_id = plan_ball_handler_id(plan)
    handler = offense[handler_id]
    handler_primary_id = matchup[handler_id]
    effective_matchup = dict(matchup)

    if coverage is Coverage.SWITCH:
        if isinstance(plan, BallScreenPlan):
            effective_matchup[plan.handler_id], effective_matchup[plan.screener_id] = (
                matchup[plan.screener_id],
                matchup[plan.handler_id],
            )
        elif isinstance(plan, OffBallActionPlan) and plan.screen_setter_id is not None:
            effective_matchup[plan.target_id], effective_matchup[plan.screen_setter_id] = (
                matchup[plan.screen_setter_id],
                matchup[plan.target_id],
            )
        handler_primary_id = effective_matchup[handler_id]

    if isinstance(plan, BallScreenPlan) and coverage in {
        Coverage.DROP,
        Coverage.BLITZ,
    }:
        help_defender_id = matchup[plan.screener_id]
    else:
        help_defender_id = _choose_help_defender(defense, frozenset({handler_primary_id}))

    primary = defense[handler_primary_id]
    helper = defense[help_defender_id]
    creator_edge = 0.0
    target_movement_z = 0.0
    screen_setting_z = 0.0
    if isinstance(plan, BallScreenPlan):
        screen_setting_z = ability_rating_to_z(offense[plan.screener_id].abilities.screen_setting)
        creator_edge = (
            _coefficient(parameter, "ball_screen_creator")
            * ability_rating_to_z(handler.abilities.perimeter_creation)
            + _coefficient(parameter, "ball_screen_screen") * screen_setting_z
            + _coefficient(parameter, "ball_screen_primary_defense")
            * ability_rating_to_z(primary.abilities.point_of_attack_defense)
        )
    elif isinstance(plan, IsolationPlan):
        creator_edge = _coefficient(parameter, "isolation_creator") * ability_rating_to_z(
            handler.abilities.perimeter_creation
        ) + _coefficient(parameter, "isolation_primary_defense") * ability_rating_to_z(
            primary.abilities.point_of_attack_defense
        )
    else:
        target = offense[plan.target_id]
        target_defender = defense[effective_matchup[plan.target_id]]
        target_movement_z = ability_rating_to_z(target.abilities.off_ball_movement)
        creator_edge = (
            _coefficient(parameter, "offball_playmaking")
            * ability_rating_to_z(handler.abilities.playmaking)
            + _coefficient(parameter, "offball_target_movement") * target_movement_z
            + _coefficient(parameter, "offball_target_awareness")
            * ability_rating_to_z(target_defender.abilities.defensive_awareness)
        )

    if coverage is Coverage.SWITCH:
        size_delta = int(handler.size_class) - int(primary.size_class)
        if size_delta > 0:
            creator_edge += float(parameter["favorable_switch_creator_delta"])
        elif size_delta < 0:
            creator_edge += float(parameter["unfavorable_switch_creator_delta"])

    helper_awareness_z = ability_rating_to_z(helper.abilities.defensive_awareness)
    primary_poa_z = ability_rating_to_z(primary.abilities.point_of_attack_defense)
    eligible_weakside = sorted(set(offense_lineup) - set(plan_participants(plan)))
    average_weakside_movement = (
        sum(
            ability_rating_to_z(offense[player_id].abilities.off_ball_movement)
            for player_id in eligible_weakside
        )
        / len(eligible_weakside)
        if eligible_weakside
        else target_movement_z
    )
    ball_pressure = _coefficient(parameter, "ball_pressure_primary_defense") * primary_poa_z
    pass_release = (
        _coefficient(parameter, "pass_release_playmaking")
        * ability_rating_to_z(handler.abilities.playmaking)
        + _coefficient(parameter, "pass_release_target_movement") * average_weakside_movement
        + _coefficient(parameter, "pass_release_help_awareness") * helper_awareness_z
    )
    rim_access = (
        _coefficient(parameter, "rim_access_creator")
        * ability_rating_to_z(handler.abilities.perimeter_creation)
        + _coefficient(parameter, "rim_access_screen") * screen_setting_z
        + _coefficient(parameter, "rim_access_primary_defense") * primary_poa_z
        + _coefficient(parameter, "rim_access_help_awareness") * helper_awareness_z
    )
    rim_help = _coefficient(parameter, "rim_help_awareness") * helper_awareness_z

    for dimension in (
        "creator_edge",
        "ball_pressure",
        "pass_release",
        "rim_access",
        "rim_help",
    ):
        delta = _coverage_delta(parameter, plan.family, coverage, dimension)
        if dimension == "creator_edge":
            creator_edge += delta
        elif dimension == "ball_pressure":
            ball_pressure += delta
        elif dimension == "pass_release":
            pass_release += delta
        elif dimension == "rim_access":
            rim_access += delta
        else:
            rim_help += delta

    candidates: list[FinisherCandidateProfile] = []
    for route in sorted(LEGAL_ROUTES_BY_PLAY[plan.family], key=int):
        fixed = expected_fixed_finisher(plan, route)
        finisher_ids = (fixed,) if fixed is not None else tuple(eligible_weakside)
        for finisher_id in finisher_ids:
            if finisher_id is None:
                raise AssertionError("fixed route must identify a finisher")
            finisher = offense[finisher_id]
            primary_defender_id = effective_matchup[finisher_id]
            finisher_defender = defense[primary_defender_id]
            finisher_move = ability_rating_to_z(finisher.abilities.off_ball_movement)
            defender_awareness = ability_rating_to_z(
                finisher_defender.abilities.defensive_awareness
            )
            if route in {
                FinisherRoute.INITIATOR_SELF,
                FinisherRoute.INITIATOR_BAILOUT,
            }:
                availability = creator_edge
            elif route is FinisherRoute.SCREENER_ROLL:
                availability = pass_release + rim_access
            elif route is FinisherRoute.SCREENER_POP:
                availability = pass_release
            elif route is FinisherRoute.HELP_RELEASE:
                availability = (
                    pass_release
                    + _coefficient(parameter, "help_candidate_movement") * finisher_move
                    + _coefficient(parameter, "help_candidate_awareness") * defender_awareness
                )
            else:
                availability = creator_edge + pass_release
            candidates.append(
                FinisherCandidateProfile(
                    route=route,
                    finisher_id=finisher_id,
                    availability=availability,
                    primary_contest=(
                        _coefficient(parameter, "primary_contest_defense")
                        * ability_rating_to_z(finisher_defender.abilities.point_of_attack_defense)
                        + _coefficient(parameter, "primary_contest_creator_edge") * creator_edge
                    ),
                    help_contest=rim_help,
                    rim_access=rim_access,
                    primary_defender_id=primary_defender_id,
                    help_defender_id=(
                        help_defender_id if help_defender_id != primary_defender_id else None
                    ),
                )
            )
    return InteractionState(ball_pressure, pass_release, tuple(candidates))
