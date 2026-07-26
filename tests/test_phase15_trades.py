from dataclasses import fields, replace

import pytest
from test_game_runtime import player

from courtsim.career import CareerPlayer, CareerStatus, DevelopmentTraits, DraftPickAsset
from courtsim.domain.player import AbilityRatings, SizeClass
from courtsim.management import ContractRules, LeagueManagementState, PlayerContract
from courtsim.manager_ai import ManagerPolicyMode, ManagerProfile
from courtsim.manager_trade import evaluate_trade_shadow
from courtsim.rosters import RosterSnapshot
from courtsim.trades import (
    TradeOffer,
    TradeRules,
    apply_trade,
    audit_trade,
    trade_rejections,
)


def ratings(value: int) -> AbilityRatings:
    return AbilityRatings(**{item.name: value for item in fields(AbilityRatings)})


def career_player(
    player_id: int,
    ability: int,
    *,
    potential: int | None = None,
    age: int = 25,
    size: SizeClass = SizeClass.MEDIUM,
    injury_burden: int = 0,
) -> CareerPlayer:
    profile = replace(
        player(player_id),
        abilities=ratings(ability),
        size_class=size,
    )
    return CareerPlayer(
        profile,
        age,
        max(0, age - 20),
        DevelopmentTraits(),
        ratings(ability if potential is None else potential),
        CareerStatus.ACTIVE,
        injury_burden=injury_burden,
    )


def contract_rules() -> ContractRules:
    return ContractRules(
        salary_cap=120_000_000,
        minimum_salary=1_000_000,
        maximum_salary=50_000_000,
        maximum_years=5,
        maximum_roster_players=15,
    )


def management(
    *,
    salary_a: int = 12_000_000,
    salary_b: int = 10_000_000,
) -> LeagueManagementState:
    home = (1, 2, 3, 4, 5)
    away = (11, 12, 13, 14, 15)
    contracts = tuple(
        PlayerContract(
            player_id,
            "home" if player_id < 10 else "away",
            salary_a if player_id == 1 else salary_b if player_id == 11 else 2_000_000,
            2,
        )
        for player_id in (*home, *away)
    )
    return LeagueManagementState(
        2029,
        (RosterSnapshot("away", away), RosterSnapshot("home", home)),
        (),
        tuple(sorted(contracts, key=lambda item: item.player_id)),
    )


def picks() -> tuple[DraftPickAsset, ...]:
    return (
        DraftPickAsset(1, 1, 1, "home", "home"),
        DraftPickAsset(2, 1, 2, "away", "away"),
    )


def league_players(
    *,
    home_value: int = 70,
    away_value: int = 70,
    home_potential: int | None = None,
    away_potential: int | None = None,
    home_age: int = 25,
    away_age: int = 25,
) -> tuple[CareerPlayer, ...]:
    return tuple(
        career_player(
            player_id,
            home_value if player_id == 1 else away_value if player_id == 11 else 60,
            potential=(
                home_potential if player_id == 1 else away_potential if player_id == 11 else 65
            ),
            age=home_age if player_id == 1 else away_age if player_id == 11 else 25,
            size=SizeClass(player_id % 3),
        )
        for player_id in (1, 2, 3, 4, 5, 11, 12, 13, 14, 15)
    )


def test_trade_atomically_moves_players_contracts_and_picks() -> None:
    initial = management()
    offer = TradeOffer(1, "home", "away", (1,), (11,), (1,), (2,))
    result = apply_trade(initial, picks(), offer, contract_rules())
    home = next(item for item in result.final_management.rosters if item.team_id == "home")
    away = next(item for item in result.final_management.rosters if item.team_id == "away")
    assert 11 in home.player_ids and 1 not in home.player_ids
    assert 1 in away.player_ids and 11 not in away.player_ids
    contract_map = {contract.player_id: contract for contract in result.final_management.contracts}
    assert contract_map[1].team_id == "away"
    assert contract_map[1].annual_salary == 12_000_000
    assert contract_map[11].team_id == "home"
    assert tuple(pick.owner_team_id for pick in result.final_picks) == ("away", "home")
    assert initial == management()
    assert audit_trade(result).replay_verified


def test_trade_rejects_unowned_assets_and_preserves_state() -> None:
    initial = management()
    offer = TradeOffer(2, "home", "away", (11,), (1,))
    rejected = trade_rejections(initial, picks(), offer, contract_rules(), TradeRules())
    assert "player-not-owned:home:11" in rejected
    assert "player-not-owned:away:1" in rejected
    with pytest.raises(ValueError, match="illegal trade"):
        apply_trade(initial, picks(), offer, contract_rules())
    assert initial == management()


def test_trade_rejects_roster_and_salary_matching_failures() -> None:
    initial = management(salary_a=40_000_000, salary_b=2_000_000)
    roster_offer = TradeOffer(3, "home", "away", (1, 2), (11,))
    assert "roster-minimum:home" in trade_rejections(
        initial,
        picks(),
        roster_offer,
        contract_rules(),
        TradeRules(),
    )
    salary_offer = TradeOffer(4, "home", "away", (1,), (11,))
    rejected = trade_rejections(
        initial,
        picks(),
        salary_offer,
        contract_rules(),
        TradeRules(salary_matching_threshold=0, salary_matching_buffer=0),
    )
    assert "salary-match:home" not in rejected
    assert "salary-match:away" in rejected


def test_trade_shadow_requires_both_managers_and_never_executes() -> None:
    initial = management(salary_a=5_000_000, salary_b=5_000_000)
    offer = TradeOffer(5, "home", "away", (1,), (11,))
    profiles = {
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
    players = league_players(
        home_value=66,
        away_value=84,
        home_potential=96,
        away_potential=84,
        home_age=20,
        away_age=31,
    )
    shadow = evaluate_trade_shadow(
        management=initial,
        players=players,
        picks=picks(),
        offer=offer,
        profiles=profiles,
        contract_rules=contract_rules(),
    )
    assert shadow.mode is ManagerPolicyMode.SHADOW
    assert shadow.legal
    assert shadow.approved
    assert all(item.accepted for item in shadow.approvals)
    assert all(
        item.rational_gain is not None and item.rational_gain >= 0 for item in shadow.approvals
    )
    assert tuple(record.team_id for record in shadow.ledger.records) == ("home", "away")
    assert initial == management(salary_a=5_000_000, salary_b=5_000_000)


def test_trade_shadow_one_manager_veto_blocks_approval() -> None:
    initial = management(salary_a=5_000_000, salary_b=5_000_000)
    offer = TradeOffer(6, "home", "away", (1,), (11,))
    profiles = {
        "home": ManagerProfile("home-manager", "home"),
        "away": ManagerProfile("away-manager", "away"),
    }
    shadow = evaluate_trade_shadow(
        management=initial,
        players=league_players(home_value=90, away_value=55),
        picks=picks(),
        offer=offer,
        profiles=profiles,
        contract_rules=contract_rules(),
    )
    assert not shadow.approved
    approvals = {item.team_id: item for item in shadow.approvals}
    assert not approvals["home"].accepted
    assert approvals["away"].accepted


def test_illegal_trade_is_visible_to_both_manager_traces() -> None:
    offer = TradeOffer(7, "home", "away", (1, 2), (11,))
    shadow = evaluate_trade_shadow(
        management=management(),
        players=league_players(),
        picks=picks(),
        offer=offer,
        profiles={
            "home": ManagerProfile("home-manager", "home"),
            "away": ManagerProfile("away-manager", "away"),
        },
        contract_rules=contract_rules(),
    )
    assert not shadow.legal
    assert not shadow.approved
    assert "roster-minimum:home" in shadow.hard_rejections
    for approval in shadow.approvals:
        accept = next(item for item in approval.trace.candidates if item.candidate_id == "accept")
        assert not accept.eligible
