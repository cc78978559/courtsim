import pytest
from test_phase19_three_team_trades import (
    career_players,
    profiles,
    rules,
    state,
)

from courtsim.draft_assets import FutureDraftPickAsset
from courtsim.three_team_market import (
    ThreeTeamMarketRules,
    generate_three_team_market_shadow,
)


def second_round_picks() -> tuple[FutureDraftPickAsset, ...]:
    return tuple(
        FutureDraftPickAsset(
            asset_id,
            2030 + offset,
            2,
            team_id,
            team_id,
        )
        for team_index, team_id in enumerate(("A", "B", "C"))
        for offset, asset_id in enumerate((201 + team_index * 10, 202 + team_index * 10))
    )


def test_hub_candidates_are_balanced_and_rotate_across_hubs() -> None:
    result = generate_three_team_market_shadow(
        management=state(),
        players=career_players(),
        picks=(),
        profiles=profiles(),
        contract_rules=rules(),
        market_rules=ThreeTeamMarketRules(
            maximum_candidates_per_trio=8,
            maximum_cyclic_candidates_per_trio=2,
            maximum_hub_candidates_per_trio=6,
        ),
    )
    hubs = [evaluation for evaluation in result.evaluations if evaluation.kind == "hub"]
    assert len(hubs) == 6
    identified_hubs = []
    for evaluation in hubs:
        routes = evaluation.shadow.offer.player_routes
        assert len(routes) == 4
        sent = {
            team_id: sum(route.from_team_id == team_id for route in routes)
            for team_id in ("A", "B", "C")
        }
        received = {
            team_id: sum(route.to_team_id == team_id for route in routes)
            for team_id in ("A", "B", "C")
        }
        hub = next(team_id for team_id, count in sent.items() if count == 2)
        assert received[hub] == 2
        assert all(sent[team_id] == received[team_id] == 1 for team_id in sent if team_id != hub)
        identified_hubs.append(hub)
    assert set(identified_hubs) == {"A", "B", "C"}


def test_rejected_offer_escalates_through_two_pick_counteroffer_chain() -> None:
    result = generate_three_team_market_shadow(
        management=state(),
        players=career_players({1: 90, 21: 50}),
        picks=second_round_picks(),
        profiles=profiles(),
        contract_rules=rules(),
    )
    by_id = {evaluation.shadow.offer.trade_id: evaluation for evaluation in result.evaluations}
    multi_pick = next(
        evaluation
        for evaluation in result.evaluations
        if evaluation.kind == "multi-pick-compensation"
    )
    assert multi_pick.negotiation_round == 2
    assert len(multi_pick.shadow.offer.pick_routes) == 2
    assert multi_pick.parent_trade_id is not None
    single_pick = by_id[multi_pick.parent_trade_id]
    assert single_pick.kind == "pick-compensation"
    assert single_pick.negotiation_round == 1
    assert len(single_pick.shadow.offer.pick_routes) == 1
    assert single_pick.parent_trade_id is not None
    base = by_id[single_pick.parent_trade_id]
    assert base.kind in {"cyclic", "hub"}
    assert base.negotiation_round == 0
    assert base.parent_trade_id is None


def test_mixed_candidate_search_is_deterministic_and_bounded() -> None:
    market_rules = ThreeTeamMarketRules(
        maximum_candidates_per_trio=12,
        maximum_cyclic_candidates_per_trio=6,
        maximum_hub_candidates_per_trio=6,
    )
    first = generate_three_team_market_shadow(
        management=state(),
        players=career_players({1: 90, 21: 50}),
        picks=second_round_picks(),
        profiles=profiles(),
        contract_rules=rules(),
        market_rules=market_rules,
    )
    second = generate_three_team_market_shadow(
        management=state(),
        players=career_players({1: 90, 21: 50}),
        picks=second_round_picks(),
        profiles=profiles(),
        contract_rules=rules(),
        market_rules=market_rules,
    )
    assert first == second
    assert len(first.evaluations) <= market_rules.maximum_candidates_per_trio
    assert {"cyclic", "hub"} <= {evaluation.kind for evaluation in first.evaluations}


def test_candidate_family_budgets_must_fit_inside_trio_limit() -> None:
    with pytest.raises(ValueError, match="budgets exceed"):
        ThreeTeamMarketRules(
            maximum_candidates_per_trio=8,
            maximum_cyclic_candidates_per_trio=5,
            maximum_hub_candidates_per_trio=4,
        )
    with pytest.raises(ValueError, match="at most two"):
        ThreeTeamMarketRules(maximum_compensation_picks=3)
