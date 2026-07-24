"""Multi-segment possession state machine."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, cast

from courtsim.domain.enums import PossessionEndReason
from courtsim.domain.plans import Lineup
from courtsim.domain.results import (
    ActionSegmentResult,
    PossessionResult,
    is_defensive_foul,
    possession_end_reason,
    validate_possession_result,
)
from courtsim.model.action_setup import (
    PreparedSegmentSample,
    TeamDefenseStrategy,
    TeamOffenseStrategy,
    sample_prepared_action_segment,
    sample_prepared_intentional_foul_segment,
)
from courtsim.model.interaction_compiler import DefensiveMatchups, ProfileLineup
from courtsim.model.trace_mode import TraceMode
from courtsim.parameters import ModelParameters
from courtsim.randomness import RandomFrame


@dataclass(frozen=True, slots=True)
class PossessionSample:
    result: PossessionResult
    segment_samples: tuple[PreparedSegmentSample, ...]
    defensive_fouls_committed: int
    intentional_foul_committed: bool = False


def _configured_segment_limit(parameters: ModelParameters) -> int:
    rules = cast(Mapping[str, Any], parameters.payload["rules"])
    return int(rules["max_action_segments_per_possession"])


def sample_possession(
    *,
    parameters: ModelParameters,
    offense_lineup: Lineup,
    defense_lineup: Lineup,
    offense_profiles: ProfileLineup,
    defense_profiles: ProfileLineup,
    matchups: DefensiveMatchups,
    frame: RandomFrame,
    offense_strategy: TeamOffenseStrategy | None = None,
    defense_strategy: TeamDefenseStrategy | None = None,
    max_segments: int | None = None,
    defense_team_fouls: int = 0,
    bonus_foul_threshold: int | None = None,
    force_intentional_foul: bool = False,
    trace_mode: TraceMode = TraceMode.FULL,
) -> PossessionSample:
    """Run until a natural terminal event or an explicit safety limit."""
    configured_limit = _configured_segment_limit(parameters)
    limit = configured_limit if max_segments is None else max_segments
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit < 1
        or limit > configured_limit
    ):
        raise ValueError(f"max_segments must be from 1 through {configured_limit}")
    if (
        not isinstance(defense_team_fouls, int)
        or isinstance(defense_team_fouls, bool)
        or defense_team_fouls < 0
    ):
        raise ValueError("defense_team_fouls must be a non-negative integer")
    if bonus_foul_threshold is not None and (
        not isinstance(bonus_foul_threshold, int)
        or isinstance(bonus_foul_threshold, bool)
        or bonus_foul_threshold < 1
    ):
        raise ValueError("bonus_foul_threshold must be a positive integer")
    intentional_foul_bonus = (
        bonus_foul_threshold is not None and defense_team_fouls + 1 >= bonus_foul_threshold
    )

    samples: list[PreparedSegmentSample] = []
    segment_results: list[ActionSegmentResult] = []
    end_reason: PossessionEndReason | None = None
    start_segment = frame.address.segment_index
    defensive_fouls_committed = 0
    for offset in range(limit):
        segment_frame = RandomFrame(
            frame.master_seed,
            replace(frame.address, segment_index=start_segment + offset),
        )
        if force_intentional_foul and offset == 0:
            sampled = sample_prepared_intentional_foul_segment(
                parameters=parameters,
                offense_lineup=offense_lineup,
                defense_lineup=defense_lineup,
                offense_profiles=offense_profiles,
                defense_profiles=defense_profiles,
                matchups=matchups,
                frame=segment_frame,
                bonus_free_throws=intentional_foul_bonus,
                offense_strategy=offense_strategy,
                defense_strategy=defense_strategy,
                trace_mode=trace_mode,
            )
        else:
            sampled = sample_prepared_action_segment(
                parameters=parameters,
                offense_lineup=offense_lineup,
                defense_lineup=defense_lineup,
                offense_profiles=offense_profiles,
                defense_profiles=defense_profiles,
                matchups=matchups,
                frame=segment_frame,
                bonus_free_throws=(
                    bonus_foul_threshold is not None
                    and defense_team_fouls + defensive_fouls_committed + 1 >= bonus_foul_threshold
                ),
                offense_strategy=offense_strategy,
                defense_strategy=defense_strategy,
                trace_mode=trace_mode,
            )
        segment_results.append(sampled.segment.result)
        if is_defensive_foul(sampled.segment.result):
            defensive_fouls_committed += 1
        if trace_mode is TraceMode.FULL:
            samples.append(sampled)
        end_reason = possession_end_reason(sampled.segment.result)
        if end_reason is not None:
            break
    if end_reason is None:
        end_reason = PossessionEndReason.SEGMENT_LIMIT
    result = PossessionResult(
        tuple(segment_results),
        end_reason,
    )
    validate_possession_result(result, offense_lineup, defense_lineup)
    return PossessionSample(
        result,
        tuple(samples),
        defensive_fouls_committed,
        force_intentional_foul,
    )
