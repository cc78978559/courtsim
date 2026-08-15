"""Player-aware compiled policy using node-owned feature slices exactly once."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, cast

from courtsim.domain.contest import (
    BlockedAttempt,
    ContestResolution,
    LiveAttempt,
    ShotContestContext,
)
from courtsim.domain.enums import ContestLevel, Coverage, FinisherRoute, ShotZone, TurnoverKind
from courtsim.domain.interaction import FinisherSelection, InteractionState
from courtsim.domain.plans import (
    Lineup,
    OffensivePlan,
    PlayerId,
    plan_ball_handler_id,
)
from courtsim.domain.player import PlayerProfile
from courtsim.model.compiled_policy import CompiledParameterPolicy
from courtsim.model.hazards import PlayerHazard, ReboundHazards, StealHazards
from courtsim.model.segment_sampler import (
    SegmentProbabilityPolicy,
    TerminalOpportunity,
)
from courtsim.parameters import ModelParameters
from courtsim.player_features import (
    ability_rating_to_z,
    centered_mix_bias,
    scalar_tendency_bias,
)
from courtsim.probability import ProbabilityOption

ProfileLineup = tuple[
    PlayerProfile,
    PlayerProfile,
    PlayerProfile,
    PlayerProfile,
    PlayerProfile,
]
_NBA_REAL_ROLE_TAGS = frozenset(
    {
        "PRIMARY_CREATOR",
        "SECONDARY_CREATOR",
        "RIM_FINISHER",
        "SPACER",
        "CONNECTOR",
        "BENCH_SPECIALIST",
    }
)


def _node(parameters: ModelParameters, name: str) -> Mapping[str, Any]:
    nodes = cast(Mapping[str, Any], parameters.payload["nodes"])
    return cast(Mapping[str, Any], nodes[name])


def _feature_weight(parameters: ModelParameters, node: str, feature: str, class_name: str) -> float:
    feature_weights = cast(Mapping[str, Any], _node(parameters, node)["feature_weights"])
    classes = cast(Mapping[str, Any], feature_weights[feature])
    parameter = cast(Mapping[str, Any], classes[class_name])
    return float(parameter["value"])


def _coefficient(parameters: ModelParameters, node: str, field: str) -> float:
    return float(_node(parameters, node)[field])


def _mean_route_zone_fit(
    parameters: ModelParameters,
    plan: OffensivePlan,
    route: FinisherRoute,
    profiles: tuple[PlayerProfile, ...],
) -> float:
    real_profiles = tuple(
        profile for profile in profiles if set(profile.nominal_role_tags) & _NBA_REAL_ROLE_TAGS
    )
    if not real_profiles:
        return 1.0
    table = cast(
        Mapping[str, Mapping[str, float]],
        _node(parameters, "shot_zone")["base_probabilities"],
    )
    weights = table[f"{plan.family.name}|{route.name}"]
    total = math.fsum(weights.values())
    loading = parameters.schema.zone_tendency_loading
    fits = []
    for profile in real_profiles:
        mix = profile.tendencies.shot_zone_mix
        biases = dict(
            zip(ShotZone, centered_mix_bias((mix.rim, mix.midrange, mix.three)), strict=True)
        )
        fits.append(
            math.fsum(
                weight * math.exp(loading * biases[ShotZone[zone]])
                for zone, weight in weights.items()
            )
            / total
        )
    return math.fsum(fits) / len(fits)


def _profile_map(profiles: ProfileLineup) -> dict[int, PlayerProfile]:
    ids = tuple(profile.player_id for profile in profiles)
    if len(set(ids)) != 5:
        raise ValueError("profile lineup must contain five distinct players")
    return {profile.player_id: profile for profile in profiles}


@dataclass(frozen=True, slots=True)
class PlayerAwareCompiledPolicy(SegmentProbabilityPolicy):
    parameters: ModelParameters
    offense_profiles: ProfileLineup
    defense_profiles: ProfileLineup
    steal_hazards: StealHazards | None = None
    _base_policy: CompiledParameterPolicy | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _offense_by_id: Mapping[int, PlayerProfile] | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    _defense_by_id: Mapping[int, PlayerProfile] | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if self._base_policy is None:
            object.__setattr__(self, "_base_policy", CompiledParameterPolicy(self.parameters))
        if self._offense_by_id is None:
            object.__setattr__(self, "_offense_by_id", _profile_map(self.offense_profiles))
        if self._defense_by_id is None:
            object.__setattr__(self, "_defense_by_id", _profile_map(self.defense_profiles))

    def prepare_segment(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        interaction: InteractionState,
        offense_lineup: Lineup,
        defense_lineup: Lineup,
    ) -> SegmentProbabilityPolicy:
        del plan, coverage
        offense = self._offense
        defense = self._defense
        if set(offense) != set(offense_lineup) or set(defense) != set(defense_lineup):
            raise ValueError("profile lineups must match action-segment lineups")
        eligible_ids = sorted(
            {
                defender_id
                for candidate in interaction.finisher_candidates
                for defender_id in (
                    candidate.primary_defender_id,
                    candidate.help_defender_id,
                )
                if defender_id is not None
            }
        )
        if not eligible_ids:
            eligible_ids = sorted(defense)
        skill_coefficient = _coefficient(self.parameters, "steal_hazard", "skill_coefficient")
        gamble_coefficient = _coefficient(self.parameters, "steal_hazard", "gamble_coefficient")
        log_hazards = tuple(
            (
                player_id,
                skill_coefficient * ability_rating_to_z(defense[player_id].abilities.steal_skill)
                + gamble_coefficient
                * scalar_tendency_bias(defense[player_id].tendencies.steal_gamble),
            )
            for player_id in eligible_ids
        )
        maximum = max(value for _, value in log_hazards)
        weights = tuple(
            PlayerHazard(player_id, math.exp(value - maximum)) for player_id, value in log_hazards
        )
        team_pressure = (
            maximum
            + math.log(math.fsum(math.exp(value - maximum) for _, value in log_hazards))
            - math.log(len(log_hazards))
        )
        return replace(self, steal_hazards=StealHazards(weights, team_pressure))

    @property
    def _base(self) -> CompiledParameterPolicy:
        if self._base_policy is None:
            raise AssertionError("base policy was not initialized")
        return self._base_policy

    @property
    def _offense(self) -> Mapping[int, PlayerProfile]:
        if self._offense_by_id is None:
            raise AssertionError("offense profile map was not initialized")
        return self._offense_by_id

    @property
    def _defense(self) -> Mapping[int, PlayerProfile]:
        if self._defense_by_id is None:
            raise AssertionError("defense profile map was not initialized")
        return self._defense_by_id

    def _require_prepared_steals(self) -> StealHazards:
        if self.steal_hazards is None:
            raise RuntimeError("player-aware policy must be prepared before sampling")
        return self.steal_hazards

    def terminal_options(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[TerminalOpportunity], ...]:
        base = self._base.terminal_options(plan, coverage, interaction)
        handler = self._offense[plan_ball_handler_id(plan)]
        feature_values = {
            "handler.ball_security": ability_rating_to_z(handler.abilities.ball_security),
            "handler.offensive_decision": ability_rating_to_z(handler.abilities.offensive_decision),
            "handler.pass_risk": scalar_tendency_bias(handler.tendencies.pass_risk),
            "team.steal_pressure": self._require_prepared_steals().team_pressure,
        }
        return tuple(
            ProbabilityOption(
                option.id,
                option.value,
                option.weight
                * math.exp(
                    math.fsum(
                        _feature_weight(
                            self.parameters,
                            "terminal_competing_risk",
                            feature,
                            option.id,
                        )
                        * value
                        for feature, value in feature_values.items()
                    )
                ),
            )
            for option in base
        )

    def stealer_options(
        self,
        kind: TurnoverKind,
        interaction: InteractionState,
        defense_lineup: Lineup,
    ) -> tuple[ProbabilityOption[PlayerId], ...]:
        del kind, interaction, defense_lineup
        return tuple(
            ProbabilityOption(f"stealer:{entry.player_id}", entry.player_id, entry.weight)
            for entry in self._require_prepared_steals().entries
        )

    def non_shooting_foul_options(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[bool], ...] | None:
        base = self._base.non_shooting_foul_options(plan, coverage, interaction)
        if base is None:
            return None
        node = _node(self.parameters, "non_shooting_foul")
        probability = next(option.weight for option in base if option.value)
        logit = math.log(probability / (1.0 - probability))
        handler = self._offense[plan_ball_handler_id(plan)]
        logit += float(node["foul_drawing_coefficient"]) * ability_rating_to_z(
            handler.abilities.foul_drawing
        )
        logit += float(node["contact_seek_coefficient"]) * scalar_tendency_bias(
            handler.tendencies.contact_seek
        )
        defenders = self._base.non_shooting_fouler_options(
            plan,
            interaction,
            cast(Lineup, tuple(self._defense)),
        )
        average_discipline = math.fsum(
            ability_rating_to_z(self._defense[option.value].abilities.foul_discipline)
            for option in defenders
        ) / len(defenders)
        logit -= float(node["fouler_discipline_coefficient"]) * average_discipline
        adjusted = 1.0 / (1.0 + math.exp(-logit))
        return (
            ProbabilityOption("non-shooting-foul:NO_FOUL", False, 1.0 - adjusted),
            ProbabilityOption("non-shooting-foul:FOUL", True, adjusted),
        )

    def non_shooting_fouler_options(
        self,
        plan: OffensivePlan,
        interaction: InteractionState,
        defense_lineup: Lineup,
    ) -> tuple[ProbabilityOption[PlayerId], ...]:
        base = self._base.non_shooting_fouler_options(
            plan,
            interaction,
            defense_lineup,
        )
        nodes = cast(Mapping[str, Any], self.parameters.payload["nodes"])
        if "non_shooting_foul" not in nodes:
            return base
        coefficient = float(
            cast(Mapping[str, Any], nodes["non_shooting_foul"])["fouler_discipline_coefficient"]
        )
        return tuple(
            ProbabilityOption(
                option.id,
                option.value,
                option.weight
                * math.exp(
                    -coefficient
                    * ability_rating_to_z(self._defense[option.value].abilities.foul_discipline)
                ),
            )
            for option in base
        )

    def route_options(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[FinisherRoute], ...]:
        base = self._base.route_options(plan, coverage, interaction)
        return tuple(
            ProbabilityOption(
                option.id,
                option.value,
                option.weight
                * _mean_route_zone_fit(
                    self.parameters,
                    plan,
                    option.value,
                    tuple(
                        self._offense[candidate.finisher_id]
                        for candidate in interaction.finisher_candidates
                        if candidate.route is option.value
                    ),
                ),
            )
            for option in base
        )

    def finisher_options(
        self,
        route: FinisherRoute,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[PlayerId], ...]:
        return self._base.finisher_options(route, interaction)

    def zone_options(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[ShotZone], ...]:
        base = self._base.zone_options(plan, selection, interaction)
        mix = self._offense[selection.finisher_id].tendencies.shot_zone_mix
        biases = centered_mix_bias((mix.rim, mix.midrange, mix.three))
        bias_by_zone = dict(zip(ShotZone, biases, strict=True))
        loading = self.parameters.schema.zone_tendency_loading
        return tuple(
            ProbabilityOption(
                option.id,
                option.value,
                option.weight * math.exp(loading * bias_by_zone[option.value]),
            )
            for option in base
        )

    def contest_context(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        selection: FinisherSelection,
        zone: ShotZone,
        interaction: InteractionState,
    ) -> ShotContestContext:
        return self._base.contest_context(plan, coverage, selection, zone, interaction)

    def contest_options(
        self,
        context: ShotContestContext,
        zone: ShotZone,
    ) -> tuple[ProbabilityOption[ContestResolution], ...]:
        base = self._base.contest_options(context, zone)
        defenders = self._defense
        eligible = [
            defenders[player_id]
            for player_id in context.block_candidate_ids
            if player_id in defenders
        ]
        if not eligible:
            return base
        average_rim = math.fsum(
            ability_rating_to_z(profile.abilities.rim_protection) for profile in eligible
        ) / len(eligible)
        average_chase = math.fsum(
            scalar_tendency_bias(profile.tendencies.block_chase) for profile in eligible
        ) / len(eligible)
        adjusted: list[ProbabilityOption[ContestResolution]] = []
        for option in base:
            if isinstance(option.value, BlockedAttempt):
                profile = defenders[option.value.blocker_id]
                rim_value = ability_rating_to_z(profile.abilities.rim_protection)
                chase_value = scalar_tendency_bias(profile.tendencies.block_chase)
                class_name = "BLOCK"
            elif option.value.contest_level is ContestLevel.HEAVY:
                rim_value = average_rim
                chase_value = average_chase
                class_name = "HEAVY_CONTEST"
            else:
                rim_value = average_rim
                chase_value = average_chase
                class_name = "NORMAL"
            shift = (
                _feature_weight(
                    self.parameters,
                    "contest_gate",
                    "block_candidate.rim_protection",
                    class_name,
                )
                * rim_value
                + _feature_weight(
                    self.parameters,
                    "contest_gate",
                    "block_candidate.block_chase",
                    class_name,
                )
                * chase_value
            )
            adjusted.append(
                ProbabilityOption(option.id, option.value, option.weight * math.exp(shift))
            )
        return tuple(adjusted)

    def make_options(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
        zone: ShotZone,
        live_attempt: LiveAttempt,
    ) -> tuple[ProbabilityOption[bool], ...]:
        base = self._base.make_options(plan, selection, zone, live_attempt)
        make_probability = next(option.weight for option in base if option.value)
        base_logit = math.log(make_probability / (1.0 - make_probability))
        abilities = self._offense[selection.finisher_id].abilities
        rating = {
            ShotZone.RIM: abilities.rim_finishing,
            ShotZone.MIDRANGE: abilities.midrange_shooting,
            ShotZone.THREE: abilities.three_point_shooting,
        }[zone]
        coefficient = float(
            cast(
                Mapping[str, Any],
                _node(self.parameters, "shot_make")["zone_skill_coefficient"],
            )[zone.name]
        )
        logit = base_logit + coefficient * ability_rating_to_z(rating)
        probability = 1.0 / (1.0 + math.exp(-logit))
        return (
            ProbabilityOption("shot:MISS", False, 1.0 - probability),
            ProbabilityOption("shot:MAKE", True, probability),
        )

    def shooting_foul_options(
        self,
        context: ShotContestContext,
        selection: FinisherSelection,
        zone: ShotZone,
        live_attempt: LiveAttempt,
    ) -> tuple[ProbabilityOption[bool], ...]:
        base = self._base.shooting_foul_options(
            context,
            selection,
            zone,
            live_attempt,
        )
        nodes = cast(Mapping[str, Any], self.parameters.payload["nodes"])
        if "shooting_foul" not in nodes:
            return base
        probability = next(option.weight for option in base if option.value)
        logit = math.log(probability / (1.0 - probability))
        node = cast(Mapping[str, Any], nodes["shooting_foul"])
        shooter = self._offense[selection.finisher_id]
        logit += float(node["foul_drawing_coefficient"]) * ability_rating_to_z(
            shooter.abilities.foul_drawing
        )
        logit += float(node["contact_seek_coefficient"]) * scalar_tendency_bias(
            shooter.tendencies.contact_seek
        )
        candidates = tuple(
            dict.fromkeys(
                player_id
                for player_id in (
                    context.primary_defender_id,
                    context.help_defender_id,
                    *context.block_candidate_ids,
                )
                if player_id is not None and player_id in self._defense
            )
        )
        if candidates:
            average_discipline = math.fsum(
                ability_rating_to_z(self._defense[player_id].abilities.foul_discipline)
                for player_id in candidates
            ) / len(candidates)
            logit -= float(node["fouler_discipline_coefficient"]) * average_discipline
        adjusted = 1.0 / (1.0 + math.exp(-logit))
        return (
            ProbabilityOption("foul:NO_FOUL", False, 1.0 - adjusted),
            ProbabilityOption("foul:FOUL", True, adjusted),
        )

    def fouler_options(
        self,
        context: ShotContestContext,
        defense_lineup: Lineup,
    ) -> tuple[ProbabilityOption[PlayerId], ...]:
        base = self._base.fouler_options(context, defense_lineup)
        nodes = cast(Mapping[str, Any], self.parameters.payload["nodes"])
        if "shooting_foul" not in nodes:
            return base
        coefficient = float(
            cast(Mapping[str, Any], nodes["shooting_foul"])["fouler_discipline_coefficient"]
        )
        return tuple(
            ProbabilityOption(
                option.id,
                option.value,
                option.weight
                * math.exp(
                    -coefficient
                    * ability_rating_to_z(self._defense[option.value].abilities.foul_discipline)
                ),
            )
            for option in base
        )

    def free_throw_make_options(
        self,
        shooter_id: PlayerId,
        attempt_number: int,
    ) -> tuple[ProbabilityOption[bool], ...]:
        base = self._base.free_throw_make_options(shooter_id, attempt_number)
        probability = next(option.weight for option in base if option.value)
        logit = math.log(probability / (1.0 - probability))
        coefficient = _coefficient(
            self.parameters,
            "free_throw_make",
            "shooting_coefficient",
        )
        logit += coefficient * ability_rating_to_z(
            self._offense[shooter_id].abilities.free_throw_shooting
        )
        adjusted = 1.0 / (1.0 + math.exp(-logit))
        return (
            ProbabilityOption("free-throw:MISS", False, 1.0 - adjusted),
            ProbabilityOption("free-throw:MAKE", True, adjusted),
        )

    def assist_options(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
    ) -> tuple[ProbabilityOption[bool], ...]:
        base = self._base.assist_options(plan, selection)
        if self.parameters.schema.schema_version not in {
            "demo-v1.7",
            "demo-v1.8",
            "demo-v1.9",
            "demo-v1.10",
            "demo-v1.11",
            "demo-v1.12",
        }:
            return base
        total = math.fsum(option.weight for option in base)
        assist_probability = (
            math.fsum(option.weight for option in base if option.value is True) / total
        )
        lineup = cast(Lineup, tuple(self._offense))
        passers = self.assister_options(plan, selection, lineup)
        passer_weight = math.fsum(option.weight for option in passers)
        expected_playmaking = (
            math.fsum(
                option.weight
                * ability_rating_to_z(self._offense[option.value].abilities.playmaking)
                for option in passers
            )
            / passer_weight
        )
        expected_decision = (
            math.fsum(
                option.weight
                * ability_rating_to_z(self._offense[option.value].abilities.offensive_decision)
                for option in passers
            )
            / passer_weight
        )
        logit = math.log(assist_probability / (1.0 - assist_probability))
        logit += _coefficient(
            self.parameters,
            "assist_resolution",
            "occurrence_logit_intercept",
        )
        logit += (
            _coefficient(
                self.parameters,
                "assist_resolution",
                "occurrence_playmaking_coefficient",
            )
            * expected_playmaking
        )
        logit += (
            _coefficient(
                self.parameters,
                "assist_resolution",
                "occurrence_decision_coefficient",
            )
            * expected_decision
        )
        adjusted = 1.0 / (1.0 + math.exp(-logit))
        return (
            ProbabilityOption("assist:NO_ASSIST", False, 1.0 - adjusted),
            ProbabilityOption("assist:ASSIST", True, adjusted),
        )

    def assister_options(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
        offense_lineup: Lineup,
    ) -> tuple[ProbabilityOption[PlayerId], ...]:
        base = self._base.assister_options(plan, selection, offense_lineup)
        nodes = cast(Mapping[str, Any], self.parameters.payload["nodes"])
        if "assist_resolution" not in nodes or len(base) == 1:
            return base
        playmaking = _coefficient(
            self.parameters,
            "assist_resolution",
            "assister_playmaking_coefficient",
        )
        decision = _coefficient(
            self.parameters,
            "assist_resolution",
            "assister_decision_coefficient",
        )
        offense = self._offense
        return tuple(
            ProbabilityOption(
                option.id,
                option.value,
                option.weight
                * math.exp(
                    playmaking * ability_rating_to_z(offense[option.value].abilities.playmaking)
                    + decision
                    * ability_rating_to_z(offense[option.value].abilities.offensive_decision)
                ),
            )
            for option in base
        )

    def rebound_hazards(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
        zone: ShotZone,
        blocker_id: PlayerId | None,
        offense_lineup: Lineup,
        defense_lineup: Lineup,
    ) -> ReboundHazards:
        del plan, zone
        ability_coefficient = _coefficient(self.parameters, "rebound_hazard", "ability_coefficient")
        commitment_coefficient = _coefficient(
            self.parameters, "rebound_hazard", "commitment_coefficient"
        )
        shooter_offset = _coefficient(self.parameters, "rebound_hazard", "shooter_context_offset")
        blocker_offset = _coefficient(self.parameters, "rebound_hazard", "blocker_context_offset")
        blocked_oreb_offset = _coefficient(self.parameters, "rebound_hazard", "blocked_oreb_offset")
        defense_factor = _coefficient(self.parameters, "rebound_hazard", "defense_context_factor")
        offense = self._offense
        defense = self._defense
        offense_entries = tuple(
            PlayerHazard(
                player_id,
                math.exp(
                    ability_coefficient
                    * ability_rating_to_z(offense[player_id].abilities.offensive_rebounding)
                    + commitment_coefficient
                    * scalar_tendency_bias(
                        offense[player_id].tendencies.offensive_rebound_commitment
                    )
                    + (shooter_offset if player_id == selection.finisher_id else 0.0)
                    + (blocked_oreb_offset if blocker_id is not None else 0.0)
                ),
            )
            for player_id in offense_lineup
        )
        defense_entries = tuple(
            PlayerHazard(
                player_id,
                defense_factor
                * math.exp(
                    ability_coefficient
                    * ability_rating_to_z(defense[player_id].abilities.defensive_rebounding)
                    + commitment_coefficient
                    * scalar_tendency_bias(
                        defense[player_id].tendencies.defensive_rebound_commitment
                    )
                    + (blocker_offset if player_id == blocker_id else 0.0)
                ),
            )
            for player_id in defense_lineup
        )
        return ReboundHazards(offense_entries, defense_entries)
