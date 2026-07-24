from dataclasses import replace
from pathlib import Path

import pytest

from courtsim.domain.enums import Coverage, PlayFamily
from courtsim.domain.plans import Lineup, OffBallActionPlan, legal_coverages_for, plan_participants
from courtsim.domain.player import PlayerProfile
from courtsim.domain.player_serialization import player_profile_from_json
from courtsim.model import (
    ActionSetup,
    DefensiveMatchups,
    Matchup,
    PreparedSegmentSample,
    TeamDefenseStrategy,
    TeamOffenseStrategy,
    sample_action_setup,
    sample_prepared_action_segment,
)
from courtsim.model.interaction_compiler import ProfileLineup
from courtsim.parameters import load_model_parameters
from courtsim.randomness import RandomFrame, RandomFrameAddress, RandomSlot

ROOT = Path(__file__).parents[1]
PARAMETERS = load_model_parameters(
    ROOT / "data" / "model_schema_demo_v1_3.json",
    ROOT / "data" / "model_parameters_demo_0.4.0.json",
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
    return tuple(player(player_id) for player_id in lineup)  # type: ignore[return-value]


def frame(seed: int, segment: int = 0) -> RandomFrame:
    return RandomFrame(seed, RandomFrameAddress("setup", 0, 0, 0, segment))


def setup(seed: int, segment: int = 0) -> ActionSetup:
    return sample_action_setup(
        parameters=PARAMETERS,
        offense_lineup=OFFENSE,
        defense_lineup=DEFENSE,
        offense_profiles=profiles(OFFENSE),
        defense_profiles=profiles(DEFENSE),
        frame=frame(seed, segment),
    )


def prepared(seed: int) -> PreparedSegmentSample:
    return sample_prepared_action_segment(
        parameters=PARAMETERS,
        offense_lineup=OFFENSE,
        defense_lineup=DEFENSE,
        offense_profiles=profiles(OFFENSE),
        defense_profiles=profiles(DEFENSE),
        matchups=MATCHUPS,
        frame=frame(seed),
    )


def test_setup_is_reproducible_legal_and_has_stable_candidate_order() -> None:
    first = setup(123)
    assert first == setup(123)
    assert set(plan_participants(first.plan)) <= set(OFFENSE)
    assert first.coverage in legal_coverages_for(first.plan)
    for node in first.node_results:
        player_ids = [
            option.value
            for option in node.options
            if isinstance(option.value, int)
            and not isinstance(option.value, (PlayFamily, Coverage))
        ]
        assert player_ids == sorted(player_ids)


def test_all_families_and_conditional_coverage_shapes_are_reachable() -> None:
    observed_families = set()
    observed_offball_shapes = set()
    for seed in range(300):
        sampled = setup(seed)
        observed_families.add(sampled.plan.family)
        if isinstance(sampled.plan, OffBallActionPlan):
            observed_offball_shapes.add(sampled.plan.screen_setter_id is not None)
            if sampled.plan.screen_setter_id is None:
                assert sampled.coverage is Coverage.BASE
    assert observed_families == set(PlayFamily)
    assert observed_offball_shapes == {False, True}


def test_strategies_change_logits_without_bypassing_legality() -> None:
    offense_strategy = TeamOffenseStrategy(((PlayFamily.ISOLATION, 2.0),))
    defense_strategy = TeamDefenseStrategy(((Coverage.BLITZ, 2.0),))
    sampled = sample_action_setup(
        parameters=PARAMETERS,
        offense_lineup=OFFENSE,
        defense_lineup=DEFENSE,
        offense_profiles=profiles(OFFENSE),
        defense_profiles=profiles(DEFENSE),
        frame=frame(45),
        offense_strategy=offense_strategy,
        defense_strategy=defense_strategy,
    )
    play_node = next(node for node in sampled.node_results if node.slot is RandomSlot.PLAY_FAMILY)
    isolation_probability = play_node.probabilities[list(PlayFamily).index(PlayFamily.ISOLATION)]
    assert isolation_probability > 0.5
    assert sampled.coverage in legal_coverages_for(sampled.plan)

    with pytest.raises(ValueError):
        TeamOffenseStrategy(((PlayFamily.ISOLATION, 3.0),)).biases()
    with pytest.raises(ValueError):
        TeamDefenseStrategy(((Coverage.BASE, 0.1), (Coverage.BASE, 0.2))).biases()


def test_full_setup_interaction_and_outcome_pipeline_replays() -> None:
    sampled = prepared(901)
    replay = prepared(901)
    assert sampled == replay
    assert sampled.segment.result.plan == sampled.setup.plan
    assert sampled.segment.result.coverage is sampled.setup.coverage
