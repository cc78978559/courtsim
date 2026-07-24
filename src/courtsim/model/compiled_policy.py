"""Compilation of validated demo-v1 numbers into a runnable segment policy."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from courtsim.domain.contest import (
    BlockedAttempt,
    ContestResolution,
    LiveAttempt,
    ShotContestContext,
)
from courtsim.domain.enums import (
    ContestLevel,
    Coverage,
    FinisherRoute,
    ShotZone,
    TurnoverKind,
)
from courtsim.domain.interaction import (
    FinisherSelection,
    InteractionState,
    select_candidate,
)
from courtsim.domain.plans import (
    Lineup,
    OffensivePlan,
    PlayerId,
    creation_mode_for,
    last_passer_for,
    plan_ball_handler_id,
)
from courtsim.model.hazards import PlayerHazard, ReboundHazards
from courtsim.model.segment_sampler import (
    SegmentProbabilityPolicy,
    ShotOpportunity,
    TerminalOpportunity,
    TurnoverOpportunity,
)
from courtsim.parameters import TERMINAL_CLASSES, ModelParameters
from courtsim.probability import ProbabilityOption


def _nodes(parameters: ModelParameters) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], parameters.payload["nodes"])


def _table(parameters: ModelParameters, node: str, field: str) -> Mapping[str, Any]:
    node_payload = cast(Mapping[str, Any], _nodes(parameters)[node])
    return cast(Mapping[str, Any], node_payload[field])


def _sigmoid(logit: float) -> float:
    if logit >= 0:
        return 1.0 / (1.0 + math.exp(-logit))
    exponential = math.exp(logit)
    return exponential / (1.0 + exponential)


def _non_shooting_foul_defenders(
    plan: OffensivePlan,
    interaction: InteractionState,
    defense_lineup: Lineup,
) -> tuple[PlayerId, ...]:
    handler_id = plan_ball_handler_id(plan)
    candidates = tuple(
        dict.fromkeys(
            defender_id
            for profile in interaction.finisher_candidates
            if profile.finisher_id == handler_id
            for defender_id in (
                profile.primary_defender_id,
                profile.help_defender_id,
            )
            if defender_id is not None
        )
    )
    return candidates or defense_lineup


@dataclass(frozen=True, slots=True)
class CompiledParameterPolicy(SegmentProbabilityPolicy):
    parameters: ModelParameters

    def prepare_segment(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        interaction: InteractionState,
        offense_lineup: Lineup,
        defense_lineup: Lineup,
    ) -> SegmentProbabilityPolicy:
        del plan, coverage, interaction, offense_lineup, defense_lineup
        return self

    def terminal_options(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[TerminalOpportunity], ...]:
        del coverage
        base = cast(
            Mapping[str, float],
            _table(self.parameters, "terminal_competing_risk", "base_probabilities")[
                plan.family.name
            ],
        )
        feature_values = {
            "interaction.ball_pressure": interaction.ball_pressure,
            "interaction.pass_release": interaction.pass_release,
        }
        raw_weights = _table(self.parameters, "terminal_competing_risk", "feature_weights")
        options: list[ProbabilityOption[TerminalOpportunity]] = []
        for class_name in TERMINAL_CLASSES:
            shift = math.fsum(
                cast(
                    Mapping[str, Any],
                    cast(Mapping[str, Any], class_weights)[class_name],
                )["value"]
                * feature_values[feature]
                for feature, class_weights in raw_weights.items()
                if feature in feature_values
            )
            value: TerminalOpportunity
            if class_name == "SHOT_OPPORTUNITY":
                value = ShotOpportunity()
            else:
                value = TurnoverOpportunity(TurnoverKind[class_name.removeprefix("TO_")])
            options.append(ProbabilityOption(class_name, value, base[class_name] * math.exp(shift)))
        return tuple(options)

    def non_shooting_foul_options(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[bool], ...] | None:
        del coverage
        nodes = _nodes(self.parameters)
        if "non_shooting_foul" not in nodes:
            return None
        node = cast(Mapping[str, Any], nodes["non_shooting_foul"])
        bases = cast(Mapping[str, Any], node["base_probability_by_play_family"])
        base = float(bases[plan.family.name])
        logit = math.log(base / (1.0 - base))
        logit += float(node["ball_pressure_coefficient"]) * interaction.ball_pressure
        probability = _sigmoid(logit)
        return (
            ProbabilityOption("non-shooting-foul:NO_FOUL", False, 1.0 - probability),
            ProbabilityOption("non-shooting-foul:FOUL", True, probability),
        )

    def non_shooting_fouler_options(
        self,
        plan: OffensivePlan,
        interaction: InteractionState,
        defense_lineup: Lineup,
    ) -> tuple[ProbabilityOption[PlayerId], ...]:
        return tuple(
            ProbabilityOption(f"non-shooting-fouler:{player_id}", player_id, 1.0)
            for player_id in _non_shooting_foul_defenders(
                plan,
                interaction,
                defense_lineup,
            )
        )

    def stealer_options(
        self,
        kind: TurnoverKind,
        interaction: InteractionState,
        defense_lineup: Lineup,
    ) -> tuple[ProbabilityOption[PlayerId], ...]:
        del kind
        candidates = {
            defender
            for profile in interaction.finisher_candidates
            for defender in (profile.primary_defender_id, profile.help_defender_id)
            if defender is not None
        }
        eligible = sorted(candidates) if candidates else list(defense_lineup)
        return tuple(
            ProbabilityOption(f"stealer:{player_id}", player_id, 1.0) for player_id in eligible
        )

    def route_options(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[FinisherRoute], ...]:
        del coverage, interaction
        base = cast(
            Mapping[str, float],
            _table(self.parameters, "finisher_route", "base_probabilities")[plan.family.name],
        )
        return tuple(
            ProbabilityOption(f"route:{route.name}", route, base[route.name])
            for route in FinisherRoute
            if route.name in base
        )

    def finisher_options(
        self,
        route: FinisherRoute,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[PlayerId], ...]:
        profiles = sorted(
            (profile for profile in interaction.finisher_candidates if profile.route is route),
            key=lambda profile: profile.finisher_id,
        )
        loading = self.parameters.schema.finisher_availability_loading
        maximum = max(profile.availability * loading for profile in profiles)
        return tuple(
            ProbabilityOption(
                f"finisher:{profile.finisher_id}",
                profile.finisher_id,
                math.exp(profile.availability * loading - maximum),
            )
            for profile in profiles
        )

    def zone_options(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
        interaction: InteractionState,
    ) -> tuple[ProbabilityOption[ShotZone], ...]:
        del interaction
        context = f"{plan.family.name}|{selection.route.name}"
        base = cast(
            Mapping[str, float],
            _table(self.parameters, "shot_zone", "base_probabilities")[context],
        )
        return tuple(
            ProbabilityOption(f"zone:{zone.name}", zone, base[zone.name])
            for zone in ShotZone
            if zone.name in base
        )

    def contest_context(
        self,
        plan: OffensivePlan,
        coverage: Coverage,
        selection: FinisherSelection,
        zone: ShotZone,
        interaction: InteractionState,
    ) -> ShotContestContext:
        del plan, coverage
        profile = select_candidate(interaction, selection)
        ordered = (
            (profile.help_defender_id, profile.primary_defender_id)
            if zone is ShotZone.RIM
            else (profile.primary_defender_id, profile.help_defender_id)
        )
        block_candidates = tuple(
            dict.fromkeys(player_id for player_id in ordered if player_id is not None)
        )
        return ShotContestContext(
            profile.primary_contest,
            profile.help_contest,
            profile.primary_defender_id,
            profile.help_defender_id,
            block_candidates,
        )

    def contest_options(
        self,
        context: ShotContestContext,
        zone: ShotZone,
    ) -> tuple[ProbabilityOption[ContestResolution], ...]:
        base = cast(
            Mapping[str, float],
            _table(self.parameters, "contest_gate", "base_probabilities")[zone.name],
        )
        options: list[ProbabilityOption[ContestResolution]] = []
        if context.block_candidate_ids:
            per_blocker = base["BLOCK"] / len(context.block_candidate_ids)
            options.extend(
                ProbabilityOption(
                    f"contest:BLOCK:{blocker_id}",
                    BlockedAttempt(blocker_id),
                    per_blocker,
                )
                for blocker_id in context.block_candidate_ids
            )
        options.extend(
            (
                ProbabilityOption(
                    "contest:HEAVY_CONTEST",
                    LiveAttempt(ContestLevel.HEAVY),
                    base["HEAVY_CONTEST"],
                ),
                ProbabilityOption(
                    "contest:NORMAL",
                    LiveAttempt(ContestLevel.NORMAL),
                    base["NORMAL"],
                ),
            )
        )
        return tuple(options)

    def make_options(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
        zone: ShotZone,
        live_attempt: LiveAttempt,
    ) -> tuple[ProbabilityOption[bool], ...]:
        del plan, selection
        base = _number_from_table(self.parameters, "shot_make", "base_make_probability", zone.name)
        logit = math.log(base / (1.0 - base))
        if live_attempt.contest_level is ContestLevel.HEAVY:
            logit += _number_from_table(
                self.parameters, "shot_make", "heavy_contest_offset", zone.name
            )
        make_probability = _sigmoid(logit)
        return (
            ProbabilityOption("shot:MISS", False, 1.0 - make_probability),
            ProbabilityOption("shot:MAKE", True, make_probability),
        )

    def shooting_foul_options(
        self,
        context: ShotContestContext,
        selection: FinisherSelection,
        zone: ShotZone,
        live_attempt: LiveAttempt,
    ) -> tuple[ProbabilityOption[bool], ...]:
        del context, selection
        nodes = _nodes(self.parameters)
        if "shooting_foul" not in nodes:
            return (ProbabilityOption("foul:LEGACY:NO_FOUL", False, 1.0),)
        node = cast(Mapping[str, Any], nodes["shooting_foul"])
        bases = cast(Mapping[str, Any], node["base_probability_by_zone"])
        base = float(bases[zone.name])
        logit = math.log(base / (1.0 - base))
        if live_attempt.contest_level is ContestLevel.HEAVY:
            logit += float(node["heavy_contest_logit_offset"])
        probability = _sigmoid(logit)
        return (
            ProbabilityOption("foul:NO_FOUL", False, 1.0 - probability),
            ProbabilityOption("foul:FOUL", True, probability),
        )

    def fouler_options(
        self,
        context: ShotContestContext,
        defense_lineup: Lineup,
    ) -> tuple[ProbabilityOption[PlayerId], ...]:
        candidates = tuple(
            dict.fromkeys(
                player_id
                for player_id in (
                    context.primary_defender_id,
                    context.help_defender_id,
                    *context.block_candidate_ids,
                )
                if player_id is not None
            )
        )
        eligible = candidates or defense_lineup
        return tuple(
            ProbabilityOption(f"fouler:{player_id}", player_id, 1.0) for player_id in eligible
        )

    def free_throw_make_options(
        self,
        shooter_id: PlayerId,
        attempt_number: int,
    ) -> tuple[ProbabilityOption[bool], ...]:
        del shooter_id, attempt_number
        nodes = _nodes(self.parameters)
        if "free_throw_make" not in nodes:
            raise ValueError("legacy parameters cannot resolve free throws")
        node = cast(Mapping[str, Any], nodes["free_throw_make"])
        probability = float(node["base_make_probability"])
        return (
            ProbabilityOption("free-throw:MISS", False, 1.0 - probability),
            ProbabilityOption("free-throw:MAKE", True, probability),
        )

    def assist_options(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
    ) -> tuple[ProbabilityOption[bool], ...]:
        nodes = _nodes(self.parameters)
        if "assist_resolution" not in nodes:
            legacy_assisted = last_passer_for(plan, selection.route) is not None
            return (
                ProbabilityOption(
                    f"assist:LEGACY:{legacy_assisted}",
                    legacy_assisted,
                    1.0,
                ),
            )
        node = cast(Mapping[str, Any], nodes["assist_resolution"])
        bases = cast(Mapping[str, Any], node["base_probability_by_creation_mode"])
        probability = float(bases[creation_mode_for(selection.route).name])
        return (
            ProbabilityOption("assist:NO_ASSIST", False, 1.0 - probability),
            ProbabilityOption("assist:ASSIST", True, probability),
        )

    def assister_options(
        self,
        plan: OffensivePlan,
        selection: FinisherSelection,
        offense_lineup: Lineup,
    ) -> tuple[ProbabilityOption[PlayerId], ...]:
        fixed = last_passer_for(plan, selection.route)
        if fixed is not None:
            return (ProbabilityOption(f"assister:{fixed}", fixed, 1.0),)
        return tuple(
            ProbabilityOption(f"assister:{player_id}", player_id, 1.0)
            for player_id in offense_lineup
            if player_id != selection.finisher_id
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
        del plan, selection, zone, blocker_id
        rebound_node = cast(Mapping[str, Any], _nodes(self.parameters)["rebound_side"])
        oreb = float(rebound_node["neutral_oreb_probability"])
        return ReboundHazards(
            offense=tuple(
                PlayerHazard(player_id, oreb / len(offense_lineup)) for player_id in offense_lineup
            ),
            defense=tuple(
                PlayerHazard(player_id, (1.0 - oreb) / len(defense_lineup))
                for player_id in defense_lineup
            ),
        )


def _number_from_table(parameters: ModelParameters, node: str, field: str, key: str) -> float:
    return float(_table(parameters, node, field)[key])
