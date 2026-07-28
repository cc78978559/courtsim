from dataclasses import replace

import pytest
from test_phase19_three_team_trades import career_players, profiles, rules, state

from courtsim.management import LeagueManagementState
from courtsim.three_team_market import (
    ThreeTeamMarketEvaluation,
    ThreeTeamMarketRules,
    generate_three_team_market_shadow,
)


def varied_salary_state() -> LeagueManagementState:
    salaries = {
        1: 1_000_000,
        2: 5_000_000,
        3: 10_000_000,
        4: 20_000_000,
        5: 30_000_000,
        11: 2_000_000,
        12: 6_000_000,
        13: 11_000_000,
        14: 21_000_000,
        15: 31_000_000,
        21: 3_000_000,
        22: 7_000_000,
        23: 12_000_000,
        24: 22_000_000,
        25: 32_000_000,
    }
    initial = state()
    return replace(
        initial,
        contracts=tuple(
            replace(contract, annual_salary=salaries[contract.player_id])
            for contract in initial.contracts
        ),
    )


def _hub_team(evaluation: ThreeTeamMarketEvaluation) -> str:
    routes = evaluation.shadow.offer.player_routes
    return next(
        team_id
        for team_id in evaluation.shadow.offer.team_ids
        if sum(route.from_team_id == team_id for route in routes) == 2
    )


def test_hub_candidates_are_salary_sorted_within_each_round_robin_lane() -> None:
    result = generate_three_team_market_shadow(
        management=varied_salary_state(),
        players=career_players(),
        picks=(),
        profiles=profiles(),
        contract_rules=rules(),
        market_rules=ThreeTeamMarketRules(
            maximum_candidates_per_trio=11,
            maximum_cyclic_candidates_per_trio=2,
            maximum_hub_candidates_per_trio=9,
        ),
    )
    hubs = [evaluation for evaluation in result.evaluations if evaluation.kind == "hub"]
    assert len(hubs) == 9
    for team_id in ("A", "B", "C"):
        imbalances = [
            evaluation.salary_imbalance for evaluation in hubs if _hub_team(evaluation) == team_id
        ]
        assert imbalances == sorted(imbalances)


def test_salary_aware_ordering_beats_lexical_first_hub_packages() -> None:
    aware = generate_three_team_market_shadow(
        management=varied_salary_state(),
        players=career_players(),
        picks=(),
        profiles=profiles(),
        contract_rules=rules(),
        market_rules=ThreeTeamMarketRules(
            maximum_candidates_per_trio=5,
            maximum_cyclic_candidates_per_trio=2,
            maximum_hub_candidates_per_trio=3,
        ),
    )
    lexical = generate_three_team_market_shadow(
        management=varied_salary_state(),
        players=career_players(),
        picks=(),
        profiles=profiles(),
        contract_rules=rules(),
        market_rules=ThreeTeamMarketRules(
            maximum_candidates_per_trio=5,
            maximum_cyclic_candidates_per_trio=2,
            maximum_hub_candidates_per_trio=3,
            salary_aware_hub_ordering=False,
        ),
    )
    aware_by_hub = {
        _hub_team(evaluation): evaluation.salary_imbalance
        for evaluation in aware.evaluations
        if evaluation.kind == "hub"
    }
    lexical_by_hub = {
        _hub_team(evaluation): evaluation.salary_imbalance
        for evaluation in lexical.evaluations
        if evaluation.kind == "hub"
    }
    assert all(aware_by_hub[team_id] <= lexical_by_hub[team_id] for team_id in aware_by_hub)
    assert any(aware_by_hub[team_id] < lexical_by_hub[team_id] for team_id in aware_by_hub)


def test_salary_imbalance_is_validated_and_deterministic() -> None:
    result = generate_three_team_market_shadow(
        management=varied_salary_state(),
        players=career_players(),
        picks=(),
        profiles=profiles(),
        contract_rules=rules(),
    )
    assert result == generate_three_team_market_shadow(
        management=varied_salary_state(),
        players=career_players(),
        picks=(),
        profiles=profiles(),
        contract_rules=rules(),
    )
    assert all(evaluation.salary_imbalance >= 0 for evaluation in result.evaluations)
    with pytest.raises(ValueError, match="salary imbalance"):
        replace(result.evaluations[0], salary_imbalance=-1)
