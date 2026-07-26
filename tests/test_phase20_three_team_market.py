from dataclasses import replace

import pytest
from test_phase19_three_team_trades import (
    career_players,
    circular_offer,
    future_picks,
    profiles,
    ratings,
    rules,
    state,
)

from courtsim.career import CareerPlayer
from courtsim.manager_ai import ManagerProfile
from courtsim.three_team_market import (
    ThreeTeamMarketPlan,
    apply_three_team_market_plan,
    generate_three_team_market_shadow,
)


def timeline_players() -> tuple[CareerPlayer, ...]:
    players = []
    for item in career_players():
        if item.player_id == 1:
            players.append(
                replace(
                    item,
                    profile=replace(item.profile, abilities=ratings(60)),
                    potential=ratings(100),
                    age=20,
                    seasons_pro=0,
                )
            )
        elif item.player_id == 11:
            players.append(
                replace(
                    item,
                    profile=replace(item.profile, abilities=ratings(80)),
                    potential=ratings(80),
                    age=29,
                    seasons_pro=9,
                )
            )
        elif item.player_id == 21:
            players.append(
                replace(
                    item,
                    profile=replace(item.profile, abilities=ratings(75)),
                    potential=ratings(75),
                    age=29,
                    seasons_pro=9,
                )
            )
        else:
            players.append(item)
    return tuple(players)


def timeline_profiles() -> dict[str, ManagerProfile]:
    return {
        "A": ManagerProfile(
            "manager-A",
            "A",
            win_now=95,
            development_bias=5,
            risk_tolerance=20,
        ),
        "B": ManagerProfile(
            "manager-B",
            "B",
            win_now=5,
            development_bias=100,
            risk_tolerance=90,
        ),
        "C": ManagerProfile("manager-C", "C", win_now=80),
    }


def test_three_team_market_discovers_and_replays_positive_cycle() -> None:
    first = generate_three_team_market_shadow(
        management=state(),
        players=timeline_players(),
        picks=(),
        profiles=timeline_profiles(),
        contract_rules=rules(),
    )
    second = generate_three_team_market_shadow(
        management=state(),
        players=timeline_players(),
        picks=(),
        profiles=timeline_profiles(),
        contract_rules=rules(),
    )
    assert first == second
    assert first.plan.offers
    execution = apply_three_team_market_plan(
        state(),
        (),
        first.plan,
        rules(),
    )
    assert execution.audits
    assert all(audit.replay_verified for audit in execution.audits)


def test_three_team_market_searches_pick_compensation_with_parent_chain() -> None:
    result = generate_three_team_market_shadow(
        management=state(),
        players=career_players({1: 90, 21: 50}),
        picks=future_picks(),
        profiles=profiles(),
        contract_rules=rules(),
    )
    counters = [
        evaluation for evaluation in result.evaluations if evaluation.kind == "pick-compensation"
    ]
    assert counters
    offer_ids = {evaluation.shadow.offer.trade_id for evaluation in result.evaluations}
    assert all(evaluation.parent_trade_id in offer_ids for evaluation in counters)
    assert all(evaluation.shadow.offer.pick_routes for evaluation in counters)


def test_three_team_market_respects_per_trio_candidate_budget() -> None:
    result = generate_three_team_market_shadow(
        management=state(),
        players=career_players({1: 90, 21: 50}),
        picks=future_picks(),
        profiles=profiles(),
        contract_rules=rules(),
    )
    assert len(result.evaluations) <= 64
    assert len(result.ledger.records) == len(result.evaluations) * 3


def test_three_team_market_filters_zero_surplus_churn() -> None:
    result = generate_three_team_market_shadow(
        management=state(),
        players=career_players(),
        picks=(),
        profiles=profiles(),
        contract_rules=rules(),
    )
    assert result.plan.offers == ()
    assert any(evaluation.shadow.approved for evaluation in result.evaluations)


def test_three_team_market_plan_rejects_team_conflicts() -> None:
    first = circular_offer()
    second = replace(first, trade_id=41)
    with pytest.raises(ValueError, match="reuse"):
        ThreeTeamMarketPlan((first, second))
