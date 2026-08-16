from dataclasses import fields, replace

import pytest
from test_game_runtime import player

from courtsim.career import CareerPlayer, CareerStatus, DevelopmentTraits
from courtsim.domain.player import AbilityRatings
from courtsim.draft_assets import FutureDraftPickAsset
from courtsim.management import ContractRules, LeagueManagementState, PlayerContract
from courtsim.manager_ai import REALITY_BASELINE_POLICY, ManagerPolicyMode, ManagerProfile
from courtsim.rosters import RosterSnapshot
from courtsim.three_team_trades import (
    PickTradeRoute,
    PlayerTradeRoute,
    ThreeTeamTradeOffer,
    ThreeTeamTradeShadowResult,
    apply_three_team_trade,
    audit_three_team_trade,
    evaluate_three_team_trade_shadow,
    three_team_trade_rejections,
)


def ratings(value: int) -> AbilityRatings:
    return AbilityRatings(**{item.name: value for item in fields(AbilityRatings)})


def rules() -> ContractRules:
    return ContractRules(
        salary_cap=100_000_000,
        minimum_salary=1_000_000,
        maximum_salary=40_000_000,
        maximum_years=5,
        maximum_roster_players=15,
    )


def state() -> LeagueManagementState:
    rosters = (
        RosterSnapshot("A", (1, 2, 3, 4, 5)),
        RosterSnapshot("B", (11, 12, 13, 14, 15)),
        RosterSnapshot("C", (21, 22, 23, 24, 25)),
    )
    contracts = tuple(
        PlayerContract(player_id, roster.team_id, 5_000_000, 2)
        for roster in rosters
        for player_id in roster.player_ids
    )
    return LeagueManagementState(2029, rosters, (), contracts)


def career_players(
    values: dict[int, int] | None = None,
) -> tuple[CareerPlayer, ...]:
    overrides = values or {}
    return tuple(
        CareerPlayer(
            replace(
                player(player_id),
                abilities=ratings(overrides.get(player_id, 70)),
            ),
            25,
            5,
            DevelopmentTraits(),
            ratings(overrides.get(player_id, 70)),
            CareerStatus.ACTIVE,
        )
        for player_id in (1, 2, 3, 4, 5, 11, 12, 13, 14, 15, 21, 22, 23, 24, 25)
    )


def future_picks() -> tuple[FutureDraftPickAsset, ...]:
    return (
        FutureDraftPickAsset(101, 2030, 1, "A", "A"),
        FutureDraftPickAsset(102, 2030, 1, "B", "B"),
        FutureDraftPickAsset(103, 2030, 1, "C", "C"),
    )


def circular_offer(*, with_picks: bool = False) -> ThreeTeamTradeOffer:
    return ThreeTeamTradeOffer(
        40,
        ("A", "B", "C"),
        (
            PlayerTradeRoute(1, "A", "B"),
            PlayerTradeRoute(11, "B", "C"),
            PlayerTradeRoute(21, "C", "A"),
        ),
        (
            (
                PickTradeRoute(101, "A", "C"),
                PickTradeRoute(102, "B", "A"),
                PickTradeRoute(103, "C", "B"),
            )
            if with_picks
            else ()
        ),
    )


def profiles() -> dict[str, ManagerProfile]:
    return {team_id: ManagerProfile(f"manager-{team_id}", team_id) for team_id in ("A", "B", "C")}


def test_reality_baseline_three_team_trade_does_not_read_hidden_potential() -> None:
    baseline_profiles = profiles()
    policies = {team_id: REALITY_BASELINE_POLICY for team_id in baseline_profiles}
    original = career_players()
    changed = tuple(
        replace(item, potential=ratings(100 if item.player_id in {1, 11, 21} else 70))
        for item in original
    )

    def evaluate(players: tuple[CareerPlayer, ...]) -> ThreeTeamTradeShadowResult:
        return evaluate_three_team_trade_shadow(
            management=state(),
            players=players,
            picks=future_picks(),
            offer=circular_offer(),
            profiles=baseline_profiles,
            contract_rules=rules(),
            front_office_policies=policies,
        )

    first = evaluate(original)
    second = evaluate(changed)
    assert tuple(item.accepted for item in first.approvals) == tuple(
        item.accepted for item in second.approvals
    )
    assert tuple(item.rational_gain for item in first.approvals) == tuple(
        item.rational_gain for item in second.approvals
    )
    assert tuple(item.trace for item in first.approvals) == tuple(
        item.trace for item in second.approvals
    )
    with pytest.raises(ValueError, match="policies must cover"):
        evaluate_three_team_trade_shadow(
            management=state(),
            players=original,
            picks=future_picks(),
            offer=circular_offer(),
            profiles=baseline_profiles,
            contract_rules=rules(),
            front_office_policies={"A": REALITY_BASELINE_POLICY},
        )


def test_three_team_trade_atomically_routes_players_contracts_and_picks() -> None:
    initial = state()
    result = apply_three_team_trade(
        initial,
        future_picks(),
        circular_offer(with_picks=True),
        rules(),
    )
    rosters = {roster.team_id: roster.player_ids for roster in result.final_management.rosters}
    assert 21 in rosters["A"] and 1 not in rosters["A"]
    assert 1 in rosters["B"] and 11 not in rosters["B"]
    assert 11 in rosters["C"] and 21 not in rosters["C"]
    contracts = {
        contract.player_id: contract.team_id for contract in result.final_management.contracts
    }
    assert (contracts[1], contracts[11], contracts[21]) == ("B", "C", "A")
    assert tuple(pick.owner_team_id for pick in result.final_picks) == ("C", "A", "B")
    assert audit_three_team_trade(result).replay_verified
    assert initial == state()


def test_three_team_trade_rejects_wrong_route_owner_without_partial_state() -> None:
    offer = ThreeTeamTradeOffer(
        41,
        ("A", "B", "C"),
        (
            PlayerTradeRoute(11, "A", "B"),
            PlayerTradeRoute(21, "B", "C"),
            PlayerTradeRoute(1, "C", "A"),
        ),
    )
    rejected = three_team_trade_rejections(state(), (), offer, rules())
    assert "player-not-owned:A:11" in rejected
    with pytest.raises(ValueError, match="illegal three-team trade"):
        apply_three_team_trade(state(), (), offer, rules())


def test_three_team_trade_rejects_draft_obligation_frozen_pick() -> None:
    offer = circular_offer(with_picks=True)
    rejected = three_team_trade_rejections(
        state(),
        future_picks(),
        offer,
        rules(),
        frozen_pick_ids=frozenset({101}),
    )
    assert "draft-obligation-frozen:101" in rejected
    with pytest.raises(ValueError, match="draft-obligation-frozen:101"):
        apply_three_team_trade(
            state(),
            future_picks(),
            offer,
            rules(),
            frozen_pick_ids=frozenset({101}),
        )


def test_three_team_offer_requires_every_team_to_send_and_receive() -> None:
    with pytest.raises(ValueError, match="send and receive"):
        ThreeTeamTradeOffer(
            42,
            ("A", "B", "C"),
            (
                PlayerTradeRoute(1, "A", "B"),
                PlayerTradeRoute(11, "B", "A"),
            ),
        )


def test_three_manager_shadow_requires_unanimous_approval() -> None:
    result = evaluate_three_team_trade_shadow(
        management=state(),
        players=career_players(),
        picks=(),
        offer=circular_offer(),
        profiles=profiles(),
        contract_rules=rules(),
    )
    assert result.mode is ManagerPolicyMode.SHADOW
    assert result.legal
    assert result.approved
    assert all(approval.accepted for approval in result.approvals)
    assert tuple(record.team_id for record in result.ledger.records) == ("A", "B", "C")


def test_one_manager_veto_blocks_three_team_trade() -> None:
    result = evaluate_three_team_trade_shadow(
        management=state(),
        players=career_players({1: 90, 21: 50}),
        picks=(),
        offer=circular_offer(),
        profiles=profiles(),
        contract_rules=rules(),
    )
    approvals = {approval.team_id: approval for approval in result.approvals}
    assert not approvals["A"].accepted
    assert not result.approved


def test_illegal_route_is_visible_to_all_three_manager_traces() -> None:
    offer = ThreeTeamTradeOffer(
        43,
        ("A", "B", "C"),
        (
            PlayerTradeRoute(11, "A", "B"),
            PlayerTradeRoute(21, "B", "C"),
            PlayerTradeRoute(1, "C", "A"),
        ),
    )
    result = evaluate_three_team_trade_shadow(
        management=state(),
        players=career_players(),
        picks=(),
        offer=offer,
        profiles=profiles(),
        contract_rules=rules(),
    )
    assert not result.legal
    assert not result.approved
    for approval in result.approvals:
        accept = next(
            candidate
            for candidate in approval.trace.candidates
            if candidate.candidate_id == "accept"
        )
        assert not accept.eligible
