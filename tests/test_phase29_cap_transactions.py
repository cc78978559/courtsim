from dataclasses import replace

import pytest
from test_phase12_manager_league_adapter import league_state

from courtsim.cap_mechanics import (
    BirdRights,
    CapLedger,
    CapMechanicsRules,
)
from courtsim.career import DraftPickAsset
from courtsim.management import (
    ContractRules,
    LeagueManagementState,
    MarketAction,
    MarketActionKind,
    MarketPlan,
    PlayerContract,
    apply_market_plan,
)
from courtsim.manager_league_adapter import league_state_from_json, league_state_to_json
from courtsim.rosters import RosterSnapshot
from courtsim.trades import TradeOffer, apply_trade, audit_trade


def contract_rules(*, salary_cap: int) -> ContractRules:
    return ContractRules(
        salary_cap=salary_cap,
        minimum_salary=1_000_000,
        maximum_salary=min(40_000_000, salary_cap),
        maximum_years=5,
        maximum_roster_players=15,
    )


def test_canonical_market_entry_uses_bird_rights_for_over_cap_signing() -> None:
    rules = contract_rules(salary_cap=20_000_000)
    cap_rules = CapMechanicsRules(
        salary_cap=20_000_000,
        first_apron=25_000_000,
        second_apron=27_000_000,
    )
    state = LeagueManagementState(
        2030,
        (RosterSnapshot("A", (1, 2, 3, 4, 5)),),
        (99,),
        tuple(PlayerContract(player_id, "A", 4_000_000, 2) for player_id in range(1, 6)),
    )
    plan = MarketPlan((MarketAction(1, MarketActionKind.SIGN, 99, "A", 5_000_000, 2),))

    with pytest.raises(ValueError, match="salary cap"):
        apply_market_plan(state, plan, rules)
    with pytest.raises(ValueError, match="over-cap-without-rights"):
        apply_market_plan(
            state,
            plan,
            rules,
            cap_ledger=CapLedger(),
            cap_rules=cap_rules,
        )

    result = apply_market_plan(
        state,
        plan,
        rules,
        cap_ledger=CapLedger((BirdRights("A", 99, 3, 4_000_000),)),
        cap_rules=cap_rules,
    )
    assert result.final_state.contracts[-1].player_id == 99
    assert (
        sum(
            contract.annual_salary
            for contract in result.final_state.contracts
            if contract.team_id == "A"
        )
        == 25_000_000
    )


def trade_state() -> LeagueManagementState:
    a_players = (1, 2, 3, 4, 5)
    b_players = (11, 12, 13, 14, 15, 16)
    salaries = {
        1: 20_000_000,
        2: 20_000_000,
        3: 20_000_000,
        4: 20_000_000,
        5: 20_000_000,
        11: 10_000_000,
        12: 6_000_000,
        13: 24_000_000,
        14: 24_000_000,
        15: 25_000_000,
        16: 1_000_000,
    }
    return LeagueManagementState(
        2030,
        (RosterSnapshot("A", a_players), RosterSnapshot("B", b_players)),
        (),
        tuple(
            PlayerContract(
                player_id,
                "A" if player_id < 10 else "B",
                salaries[player_id],
                2,
            )
            for player_id in (*a_players, *b_players)
        ),
    )


def test_trade_entry_atomically_creates_consumes_and_audits_exception() -> None:
    rules = contract_rules(salary_cap=100_000_000)
    cap_rules = CapMechanicsRules(
        salary_cap=100_000_000,
        first_apron=127_000_000,
        second_apron=135_000_000,
    )
    picks = (
        DraftPickAsset(1, 1, 1, "A", "A"),
        DraftPickAsset(2, 1, 2, "B", "B"),
    )
    first = apply_trade(
        trade_state(),
        picks,
        TradeOffer(1, "A", "B", (1,), (11,)),
        rules,
        cap_ledger=CapLedger(),
        cap_rules=cap_rules,
    )
    assert first.final_cap_ledger is not None
    exception = first.final_cap_ledger.trade_exceptions[0]
    assert (exception.team_id, exception.remaining_amount) == ("A", 10_000_000)
    assert audit_trade(first).replay_verified

    second = apply_trade(
        first.final_management,
        first.final_picks,
        TradeOffer(2, "A", "B", (), (12,), (1,), ()),
        rules,
        cap_ledger=first.final_cap_ledger,
        cap_rules=cap_rules,
        exception_ids={"A": exception.exception_id},
    )
    assert second.final_cap_ledger is not None
    remaining = next(
        item
        for item in second.final_cap_ledger.trade_exceptions
        if item.exception_id == exception.exception_id
    )
    assert remaining.remaining_amount == 4_000_000
    assert audit_trade(second).replay_verified


def test_rejected_exception_trade_leaves_input_ledger_unchanged() -> None:
    rules = contract_rules(salary_cap=100_000_000)
    cap_rules = CapMechanicsRules(
        salary_cap=100_000_000,
        first_apron=127_000_000,
        second_apron=135_000_000,
    )
    ledger = CapLedger()
    with pytest.raises(ValueError, match="salary-match"):
        apply_trade(
            trade_state(),
            (),
            TradeOffer(3, "A", "B", (1,), (12,)),
            rules,
            cap_ledger=ledger,
            cap_rules=cap_rules,
        )
    assert ledger == CapLedger()


def test_over_cap_league_snapshot_round_trips_below_scaled_second_apron() -> None:
    state = league_state()
    management = replace(
        state.management,
        contracts=tuple(
            replace(contract, annual_salary=5_000_000) if contract.team_id == "A" else contract
            for contract in state.management.contracts
        ),
    )
    over_cap = replace(state, management=management)
    assert league_state_from_json(league_state_to_json(over_cap)) == over_cap
