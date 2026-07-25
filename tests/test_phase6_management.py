import json
from dataclasses import replace

import pytest

from courtsim.domain.serialization import SerializationError
from courtsim.management import (
    ContractRules,
    LeagueManagementState,
    MarketAction,
    MarketActionKind,
    MarketPlan,
    PlayerContract,
    advance_contract_year,
    apply_market_plan,
    audit_contract_year,
    audit_market,
    market_result_from_json,
    market_result_to_json,
    validate_management_state,
)
from courtsim.rosters import RosterSnapshot


def rules(**changes: int) -> ContractRules:
    return ContractRules(
        salary_cap=changes.get("salary_cap", 10_000_000),
        minimum_salary=changes.get("minimum_salary", 1_000_000),
        maximum_salary=changes.get("maximum_salary", 5_000_000),
        maximum_years=changes.get("maximum_years", 3),
        maximum_roster_players=changes.get("maximum_roster_players", 5),
    )


def state() -> LeagueManagementState:
    return LeagueManagementState(
        2026,
        (
            RosterSnapshot("home", (1, 2)),
            RosterSnapshot("away", (11, 12)),
        ),
        (20, 21),
        (
            PlayerContract(1, "home", 2_000_000, 1),
            PlayerContract(2, "home", 2_000_000, 2),
            PlayerContract(11, "away", 2_000_000, 2),
            PlayerContract(12, "away", 2_000_000, 3),
        ),
    )


def canonical_state() -> LeagueManagementState:
    original = state()
    return replace(original, rosters=tuple(sorted(original.rosters, key=lambda item: item.team_id)))


def market_plan() -> MarketPlan:
    return MarketPlan(
        (
            MarketAction(1, MarketActionKind.WAIVE, 1, "home"),
            MarketAction(
                2,
                MarketActionKind.SIGN,
                20,
                "home",
                3_000_000,
                2,
            ),
        )
    )


def test_contract_rules_and_canonical_state_validation() -> None:
    with pytest.raises(ValueError, match="minimum_salary"):
        ContractRules(minimum_salary=2, maximum_salary=1)
    with pytest.raises(ValueError, match="five"):
        ContractRules(maximum_roster_players=4)
    with pytest.raises(ValueError, match="ordered"):
        validate_management_state(state(), rules())
    validate_management_state(canonical_state(), rules())


def test_management_state_rejects_ownership_contract_and_cap_errors() -> None:
    base = canonical_state()
    with pytest.raises(ValueError, match="rostered and a free agent"):
        validate_management_state(replace(base, free_agent_ids=(1, 20, 21)), rules())
    with pytest.raises(ValueError, match="exactly one active"):
        validate_management_state(replace(base, contracts=base.contracts[:-1]), rules())
    bad_owner = replace(base.contracts[0], team_id="away")
    with pytest.raises(ValueError, match="match roster"):
        validate_management_state(
            replace(base, contracts=(bad_owner, *base.contracts[1:])),
            rules(),
        )
    expensive = replace(base.contracts[0], annual_salary=5_000_000)
    with pytest.raises(ValueError, match="salary cap"):
        validate_management_state(
            replace(base, contracts=(expensive, *base.contracts[1:])),
            rules(salary_cap=6_000_000),
        )


def test_contract_year_advancement_expires_players_deterministically() -> None:
    base = canonical_state()
    first = advance_contract_year(base, rules())
    second = advance_contract_year(base, rules())
    assert first == second
    assert first.initial_year == 2026
    assert first.final_state.season_year == 2027
    assert first.expired_player_ids == (1,)
    assert first.final_state.free_agent_ids == (1, 20, 21)
    assert 1 not in next(
        roster.player_ids for roster in first.final_state.rosters if roster.team_id == "home"
    )
    assert (
        next(
            contract.years_remaining
            for contract in first.final_state.contracts
            if contract.player_id == 2
        )
        == 1
    )


def test_market_plan_requires_unique_ordered_actions_and_valid_terms() -> None:
    action = MarketAction(1, MarketActionKind.WAIVE, 1, "home")
    with pytest.raises(ValueError, match="unique"):
        MarketPlan((action, replace(action, team_id="away")))
    with pytest.raises(ValueError, match="ordered"):
        MarketPlan((replace(action, action_id=2), action))
    with pytest.raises(ValueError, match="cannot contain"):
        MarketAction(1, MarketActionKind.WAIVE, 1, "home", 1, 1)
    with pytest.raises(ValueError, match="positive"):
        MarketAction(1, MarketActionKind.SIGN, 20, "home")


def test_waive_and_sign_plan_updates_ownership_and_contracts() -> None:
    base = canonical_state()
    result = apply_market_plan(base, market_plan(), rules())
    assert result.initial_state == base
    assert base == canonical_state()
    home = next(
        roster.player_ids for roster in result.final_state.rosters if roster.team_id == "home"
    )
    assert home == (2, 20)
    assert result.final_state.free_agent_ids == (1, 21)
    signed = next(contract for contract in result.final_state.contracts if contract.player_id == 20)
    assert signed.team_id == "home"
    assert signed.annual_salary == 3_000_000
    assert signed.years_remaining == 2


def test_invalid_market_plan_fails_without_mutating_initial_state() -> None:
    base = canonical_state()
    invalid = MarketPlan(
        (
            MarketAction(1, MarketActionKind.WAIVE, 1, "home"),
            MarketAction(2, MarketActionKind.SIGN, 99, "home", 1_000_000, 1),
        )
    )
    with pytest.raises(ValueError, match="not a free agent"):
        apply_market_plan(base, invalid, rules())
    assert base == canonical_state()
    with pytest.raises(ValueError, match="does not own"):
        apply_market_plan(
            base,
            MarketPlan((MarketAction(1, MarketActionKind.WAIVE, 1, "away"),)),
            rules(),
        )


def test_signing_enforces_roster_capacity_and_salary_cap() -> None:
    base = canonical_state()
    signing = MarketPlan((MarketAction(1, MarketActionKind.SIGN, 20, "home", 1_000_000, 1),))
    home = next(roster for roster in base.rosters if roster.team_id == "home")
    full = replace(
        base,
        rosters=tuple(
            RosterSnapshot("home", (1, 2, 3, 4, 5)) if roster.team_id == "home" else roster
            for roster in base.rosters
        ),
        contracts=tuple(
            sorted(
                (
                    *base.contracts,
                    PlayerContract(3, "home", 1_000_000, 1),
                    PlayerContract(4, "home", 1_000_000, 1),
                    PlayerContract(5, "home", 1_000_000, 1),
                ),
                key=lambda item: item.player_id,
            )
        ),
    )
    assert home.player_ids == (1, 2)
    with pytest.raises(ValueError, match="maximum roster"):
        apply_market_plan(full, signing, rules())
    expensive = MarketPlan((MarketAction(1, MarketActionKind.SIGN, 20, "home", 5_000_000, 1),))
    with pytest.raises(ValueError, match="salary cap"):
        apply_market_plan(base, expensive, rules(salary_cap=8_000_000))


def test_management_json_round_trip_and_strict_tamper_detection() -> None:
    result = apply_market_plan(canonical_state(), market_plan(), rules())
    payload = market_result_to_json(result)
    assert market_result_from_json(payload) == result
    raw = json.loads(payload)
    raw["final_state"]["free_agent_ids"].append(20)
    with pytest.raises(
        SerializationError,
        match=r"free_agent_ids|rostered and a free agent",
    ):
        market_result_from_json(json.dumps(raw))
    raw = json.loads(payload)
    raw["extra"] = True
    with pytest.raises(SerializationError, match="keys"):
        market_result_from_json(json.dumps(raw))


def test_management_audits_payroll_actions_and_expirations() -> None:
    market = audit_market(apply_market_plan(canonical_state(), market_plan(), rules()))
    assert market.teams == 2
    assert market.rostered_players == 4
    assert market.free_agents == 2
    assert market.total_payroll == 9_000_000
    assert market.maximum_team_payroll == 5_000_000
    assert market.signings == 1
    assert market.waivers == 1
    year = audit_contract_year(
        advance_contract_year(canonical_state(), rules()),
        rules(),
    )
    assert year.expirations == 1
    assert year.free_agents == 3
