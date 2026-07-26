import json
from dataclasses import replace

from test_phase12_manager_league_adapter import adapter, league_state, request

from courtsim.domain.game import GameClockConfig
from courtsim.manager_experiment import ManagerExperimentArm
from courtsim.manager_league_adapter import _opponent_observation, league_state_to_json


def test_opponent_observation_normalizes_efficiency_pace_and_shot_zones() -> None:
    observation = _opponent_observation(
        "B",
        [2, 220, 180, 200, 190, 160, 64, 80],
        GameClockConfig(4, 750, 15),
    )
    assert observation.offense_strength == 55
    assert observation.defense_strength == 53
    assert observation.pace == 50
    assert observation.three_point_rate == 40
    assert observation.rim_rate == 50


def test_real_game_events_feed_opponent_shot_profile_and_next_season_tactics() -> None:
    first = adapter()(request(ManagerExperimentArm.INCUMBENT))
    first_audit = json.loads(first.audit_payload)
    memories = [
        opponent for state in first_audit["manager_learning"] for opponent in state["opponents"]
    ]
    assert memories
    assert any(
        opponent["three_point_rate"] != 50 or opponent["rim_rate"] != 50 for opponent in memories
    )
    assert all(0 <= opponent["pace"] <= 100 for opponent in memories)

    second = adapter()(
        replace(
            request(ManagerExperimentArm.INCUMBENT),
            season_year=2029,
            state_payload=first.next_state_payload,
        )
    )
    second_audit = json.loads(second.audit_payload)
    tactics = [
        matchup["tactics"]
        for team in second_audit["rotations"].values()
        for matchup in team["opponents"].values()
        if matchup["tactics"] is not None
    ]
    assert tactics
    assert all(
        -100 <= tactic["matchup_net_rating"] <= 100
        and 7_500 <= tactic["response_multiplier_bps"] <= 12_500
        for tactic in tactics
    )
    assert any(
        any(value != 0 for value in tactic["coverage_logit_biases"].values()) for tactic in tactics
    )


def test_learning_remains_replay_stable_from_identical_state() -> None:
    initial = league_state()
    payload = league_state_to_json(initial)
    season_request = replace(
        request(ManagerExperimentArm.INCUMBENT),
        state_payload=payload,
    )
    assert adapter()(season_request) == adapter()(season_request)
