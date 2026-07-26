import json
from dataclasses import replace

import pytest
from test_phase12_manager_league_adapter import (
    TEAM_IDS,
    adapter,
    league_state,
    request,
)
from test_phase15_trades import (
    contract_rules,
    league_players,
    management,
    picks,
    ratings,
)

from courtsim.manager_ai import ManagerPolicyMode, ManagerProfile
from courtsim.manager_experiment import ManagerExperimentArm
from courtsim.manager_league_adapter import league_state_to_json
from courtsim.trade_market import (
    TradeMarketPlan,
    apply_trade_market_plan,
    generate_trade_market_shadow,
)
from courtsim.trades import TradeOffer


def timeline_profiles() -> dict[str, ManagerProfile]:
    return {
        "home": ManagerProfile(
            "contender",
            "home",
            win_now=95,
            development_bias=5,
            risk_tolerance=20,
            star_preference=80,
        ),
        "away": ManagerProfile(
            "builder",
            "away",
            win_now=5,
            development_bias=95,
            risk_tolerance=80,
            star_preference=20,
        ),
    }


def test_market_finds_and_replays_mutually_beneficial_trade() -> None:
    initial = management(salary_a=5_000_000, salary_b=5_000_000)
    players = league_players(
        home_value=66,
        away_value=84,
        home_potential=96,
        away_potential=84,
        home_age=20,
        away_age=31,
    )
    first = generate_trade_market_shadow(
        management=initial,
        players=players,
        picks=(),
        profiles=timeline_profiles(),
        contract_rules=contract_rules(),
    )
    second = generate_trade_market_shadow(
        management=initial,
        players=players,
        picks=(),
        profiles=timeline_profiles(),
        contract_rules=contract_rules(),
    )
    assert first == second
    assert first.mode is ManagerPolicyMode.SHADOW
    assert len(first.plan.offers) == 1
    selected = first.plan.offers[0]
    assert {selected.team_a_id, selected.team_b_id} == {"home", "away"}
    execution = apply_trade_market_plan(
        initial,
        (),
        first.plan,
        contract_rules(),
    )
    assert len(execution.audits) == 1
    assert execution.audits[0].replay_verified
    assert execution.final_management != initial
    assert initial == management(salary_a=5_000_000, salary_b=5_000_000)


def test_market_generates_pick_counteroffers_with_parent_links() -> None:
    result = generate_trade_market_shadow(
        management=management(salary_a=5_000_000, salary_b=5_000_000),
        players=league_players(home_value=80, away_value=70),
        picks=picks(),
        profiles={
            "home": ManagerProfile("home-manager", "home"),
            "away": ManagerProfile("away-manager", "away"),
        },
        contract_rules=contract_rules(),
    )
    counters = [item for item in result.evaluations if item.kind == "pick-counter"]
    assert counters
    assert all(item.parent_trade_id is not None for item in counters)
    offer_ids = {item.shadow.offer.trade_id for item in result.evaluations}
    assert all(item.parent_trade_id in offer_ids for item in counters)


def test_market_plan_rejects_team_reuse_before_execution() -> None:
    with pytest.raises(ValueError, match="reuse"):
        TradeMarketPlan(
            (
                TradeOffer(1, "A", "B", (1,), (11,)),
                TradeOffer(2, "A", "C", (2,), (21,)),
            )
        )


def test_market_does_not_clear_zero_surplus_churn() -> None:
    result = generate_trade_market_shadow(
        management=management(salary_a=5_000_000, salary_b=5_000_000),
        players=league_players(home_value=70, away_value=70),
        picks=(),
        profiles={
            "home": ManagerProfile("home-manager", "home"),
            "away": ManagerProfile("away-manager", "away"),
        },
        contract_rules=contract_rules(),
    )
    assert result.plan.offers == ()
    assert any(item.shadow.approved for item in result.evaluations)


def test_market_plan_is_stable_when_input_player_order_changes() -> None:
    players = league_players(
        home_value=66,
        away_value=84,
        home_potential=96,
        away_potential=84,
        home_age=20,
        away_age=31,
    )
    baseline = generate_trade_market_shadow(
        management=management(salary_a=5_000_000, salary_b=5_000_000),
        players=players,
        picks=(),
        profiles=timeline_profiles(),
        contract_rules=contract_rules(),
    )
    reordered = generate_trade_market_shadow(
        management=management(salary_a=5_000_000, salary_b=5_000_000),
        players=tuple(reversed(players)),
        picks=(),
        profiles=timeline_profiles(),
        contract_rules=contract_rules(),
    )
    assert reordered.plan == baseline.plan
    assert replace(reordered, evaluations=()) == replace(baseline, evaluations=())


def test_real_league_shadow_executes_selected_preseason_market() -> None:
    state = league_state()
    revised_players = tuple(
        replace(
            item,
            profile=replace(item.profile, abilities=ratings(66)),
            potential=ratings(96),
            age=20,
            seasons_pro=0,
        )
        if item.player_id == 1
        else replace(
            item,
            profile=replace(item.profile, abilities=ratings(84)),
            potential=ratings(84),
            age=31,
            seasons_pro=11,
        )
        if item.player_id == 6
        else item
        for item in state.players
    )
    revised = replace(state, players=revised_players)
    profiles = (
        ManagerProfile(
            "manager-A",
            "A",
            win_now=95,
            development_bias=5,
            risk_tolerance=20,
        ),
        ManagerProfile(
            "manager-B",
            "B",
            win_now=5,
            development_bias=95,
            risk_tolerance=80,
        ),
        *(ManagerProfile(f"manager-{team_id}", team_id) for team_id in TEAM_IDS[2:]),
    )
    execution = replace(adapter(), manager_profiles=profiles)(
        replace(
            request(ManagerExperimentArm.SHADOW),
            state_payload=league_state_to_json(revised),
        )
    )
    audit = json.loads(execution.audit_payload)
    assert audit["trade_clearing_choice"] in {"bilateral", "three-team"}
    selected_market = (
        audit["trade_market"]
        if audit["trade_clearing_choice"] == "bilateral"
        else audit["three_team_market"]
    )
    assert selected_market["selected_offers"]
    assert selected_market["execution_audits"]
    assert all(item["replay_verified"] for item in selected_market["execution_audits"])
