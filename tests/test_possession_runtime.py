import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from courtsim.domain.enums import PossessionEndReason
from courtsim.domain.plans import Lineup
from courtsim.domain.player import PlayerProfile
from courtsim.domain.player_serialization import player_profile_from_json
from courtsim.domain.results import NonShootingFoulSegmentResult, offense_retains_ball
from courtsim.domain.serialization import (
    SerializationError,
    possession_result_from_json,
    possession_result_to_json,
)
from courtsim.model import (
    DefensiveMatchups,
    Matchup,
    PossessionSample,
    PreparedSegmentSample,
    sample_possession,
    sample_prepared_action_segment,
)
from courtsim.model.interaction_compiler import ProfileLineup
from courtsim.parameters import load_model_parameters
from courtsim.randomness import RandomFrame, RandomFrameAddress
from courtsim.stats import StatCode, attribute_possession, attribute_segment

ROOT = Path(__file__).parents[1]
PARAMETERS = load_model_parameters(
    ROOT / "data" / "model_schema_demo_v1_3.json",
    ROOT / "data" / "model_parameters_demo_0.4.0.json",
)
COMMON_FOUL_PARAMETERS = load_model_parameters(
    ROOT / "data" / "model_schema_demo_v1_6.json",
    ROOT / "data" / "model_parameters_demo_0.8.0.json",
)
OFFENSE: Lineup = (1, 2, 3, 4, 5)
DEFENSE: Lineup = (11, 12, 13, 14, 15)
MATCHUPS = DefensiveMatchups(
    (
        Matchup(1, 11),
        Matchup(2, 12),
        Matchup(3, 13),
        Matchup(4, 14),
        Matchup(5, 15),
    )
)


def player(player_id: int) -> PlayerProfile:
    template = player_profile_from_json(
        (ROOT / "examples" / "player_profile_v1.json").read_text(encoding="utf-8")
    )
    return replace(template, player_id=player_id, name=f"Player {player_id}")


def profiles(lineup: Lineup) -> ProfileLineup:
    return cast(ProfileLineup, tuple(player(player_id) for player_id in lineup))


def sample(seed: int, max_segments: int | None = None) -> PossessionSample:
    return sample_possession(
        parameters=PARAMETERS,
        offense_lineup=OFFENSE,
        defense_lineup=DEFENSE,
        offense_profiles=profiles(OFFENSE),
        defense_profiles=profiles(DEFENSE),
        matchups=MATCHUPS,
        frame=RandomFrame(seed, RandomFrameAddress("possession", 0, 0, 0, 0)),
        max_segments=max_segments,
    )


def prepared_segment(seed: int, segment_index: int) -> PreparedSegmentSample:
    return sample_prepared_action_segment(
        parameters=PARAMETERS,
        offense_lineup=OFFENSE,
        defense_lineup=DEFENSE,
        offense_profiles=profiles(OFFENSE),
        defense_profiles=profiles(DEFENSE),
        matchups=MATCHUPS,
        frame=RandomFrame(
            seed,
            RandomFrameAddress("possession", 0, 0, 0, segment_index),
        ),
    )


def test_offensive_rebound_advances_to_a_new_addressed_segment() -> None:
    first = sample(3)
    replay = sample(3)
    assert first == replay
    assert len(first.result.segments) == 2
    assert offense_retains_ball(first.result.segments[0])
    assert not offense_retains_ball(first.result.segments[1])
    assert first.result.end_reason is PossessionEndReason.DEFENSIVE_REBOUND
    assert first.result.completed
    segment_zero = prepared_segment(3, 0)
    segment_one = prepared_segment(3, 1)
    assert first.segment_samples == (segment_zero, segment_one)


def test_segment_limit_is_explicit_and_does_not_book_a_possession() -> None:
    limited = sample(3, max_segments=1)
    assert limited.result.end_reason is PossessionEndReason.SEGMENT_LIMIT
    assert not limited.result.completed
    attribution = attribute_possession(limited.result, OFFENSE, DEFENSE)
    assert attribution.possession_delta == 0
    assert any(delta.stat is StatCode.OREB for delta in attribution.player_deltas)

    with pytest.raises(ValueError):
        sample(3, max_segments=0)
    with pytest.raises(ValueError):
        sample(3, max_segments=33)


def test_possession_ledger_is_the_sum_of_its_canonical_segments() -> None:
    result = sample(3).result
    attribution = attribute_possession(result, OFFENSE, DEFENSE)
    segment_attributions = tuple(attribute_segment(segment) for segment in result.segments)
    assert attribution.score_delta == sum(item.score_delta for item in segment_attributions)
    assert attribution.possession_delta == 1

    expected: dict[tuple[int, StatCode], int] = {}
    for item in segment_attributions:
        for delta in item.player_deltas:
            key = (delta.player_id, delta.stat)
            expected[key] = expected.get(key, 0) + delta.amount
    actual = {(delta.player_id, delta.stat): delta.amount for delta in attribution.player_deltas}
    assert actual == expected


def test_possession_serialization_round_trip_and_rejects_false_endings() -> None:
    result = sample(3).result
    payload = possession_result_to_json(result)
    assert possession_result_from_json(payload) == result

    invalid = json.loads(payload)
    invalid["end_reason"] = int(PossessionEndReason.TURNOVER)
    with pytest.raises(SerializationError):
        possession_result_from_json(json.dumps(invalid))


def test_v16_common_foul_uses_bonus_state_and_formal_policy() -> None:
    sampled = sample_possession(
        parameters=COMMON_FOUL_PARAMETERS,
        offense_lineup=OFFENSE,
        defense_lineup=DEFENSE,
        offense_profiles=profiles(OFFENSE),
        defense_profiles=profiles(DEFENSE),
        matchups=MATCHUPS,
        frame=RandomFrame(14, RandomFrameAddress("possession", 0, 0, 0, 0)),
        bonus_foul_threshold=1,
    )

    assert sampled.defensive_fouls_committed == 1
    assert len(sampled.result.segments) == 1
    result = sampled.result.segments[0]
    assert isinstance(result, NonShootingFoulSegmentResult)
    assert result.in_bonus
    assert len(result.free_throws) == 2


def test_forced_intentional_foul_reuses_bonus_foul_chain() -> None:
    frame = RandomFrame(14, RandomFrameAddress("intentional-foul", 0, 0, 0, 0))
    sampled = sample_possession(
        parameters=COMMON_FOUL_PARAMETERS,
        offense_lineup=OFFENSE,
        defense_lineup=DEFENSE,
        offense_profiles=profiles(OFFENSE),
        defense_profiles=profiles(DEFENSE),
        matchups=MATCHUPS,
        frame=frame,
        defense_team_fouls=4,
        bonus_foul_threshold=5,
        force_intentional_foul=True,
    )

    assert sampled.intentional_foul_committed
    assert sampled.defensive_fouls_committed == 1
    assert len(sampled.result.segments) == 1
    result = sampled.result.segments[0]
    assert isinstance(result, NonShootingFoulSegmentResult)
    assert result.in_bonus
    assert len(result.free_throws) == 2
    attribution = attribute_possession(sampled.result, OFFENSE, DEFENSE)
    personal_fouls = sum(
        delta.amount for delta in attribution.player_deltas if delta.stat is StatCode.PF
    )
    free_throw_attempts = sum(
        delta.amount for delta in attribution.player_deltas if delta.stat is StatCode.FTA
    )
    assert personal_fouls == 1
    assert free_throw_attempts == 2


def test_forced_non_bonus_intentional_foul_continues_same_possession() -> None:
    sampled = sample_possession(
        parameters=COMMON_FOUL_PARAMETERS,
        offense_lineup=OFFENSE,
        defense_lineup=DEFENSE,
        offense_profiles=profiles(OFFENSE),
        defense_profiles=profiles(DEFENSE),
        matchups=MATCHUPS,
        frame=RandomFrame(14, RandomFrameAddress("intentional-foul", 0, 0, 0, 0)),
        defense_team_fouls=3,
        bonus_foul_threshold=5,
        force_intentional_foul=True,
    )

    assert sampled.intentional_foul_committed
    assert len(sampled.result.segments) >= 2
    first = sampled.result.segments[0]
    assert isinstance(first, NonShootingFoulSegmentResult)
    assert not first.in_bonus
    assert offense_retains_ball(first)
    assert sampled.result.completed
