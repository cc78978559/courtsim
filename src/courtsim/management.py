"""Canonical contracts, free agency, and deterministic market actions."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from enum import IntEnum
from typing import Any, NoReturn, cast

from courtsim.cap_mechanics import (
    CapLedger,
    CapMechanicsRules,
    evaluate_signing_salary,
    record_bird_rights_signing,
    remove_bird_rights,
)
from courtsim.domain.serialization import SerializationError
from courtsim.rosters import RosterSnapshot

CONTRACT_VERSION = "contract-v1"
FREE_AGENCY_VERSION = "free-agency-v1"
MANAGEMENT_SCHEMA_VERSION = 1


class MarketActionKind(IntEnum):
    WAIVE = 0
    SIGN = 1


@dataclass(frozen=True, slots=True)
class ContractRules:
    salary_cap: int = 140_000_000
    minimum_salary: int = 1_000_000
    maximum_salary: int = 60_000_000
    maximum_years: int = 5
    maximum_roster_players: int = 15
    version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        values = (
            self.salary_cap,
            self.minimum_salary,
            self.maximum_salary,
            self.maximum_years,
            self.maximum_roster_players,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in values
        ):
            raise ValueError("contract rule values must be positive integers")
        if self.minimum_salary > self.maximum_salary:
            raise ValueError("minimum_salary cannot exceed maximum_salary")
        if self.maximum_salary > self.salary_cap:
            raise ValueError("maximum_salary cannot exceed salary_cap")
        if self.maximum_roster_players < 5:
            raise ValueError("maximum_roster_players cannot be below five")
        if self.version != CONTRACT_VERSION:
            raise ValueError(f"unsupported contract version: {self.version}")


@dataclass(frozen=True, slots=True)
class PlayerContract:
    player_id: int
    team_id: str
    annual_salary: int
    years_remaining: int

    def __post_init__(self) -> None:
        values = (self.player_id, self.annual_salary, self.years_remaining)
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise ValueError("contract values must be integers")
        if self.player_id < 0 or self.annual_salary < 1 or self.years_remaining < 1:
            raise ValueError("contract player id must be non-negative and terms positive")
        if not self.team_id.strip():
            raise ValueError("contract team_id must not be blank")


@dataclass(frozen=True, slots=True)
class LeagueManagementState:
    season_year: int
    rosters: tuple[RosterSnapshot, ...]
    free_agent_ids: tuple[int, ...]
    contracts: tuple[PlayerContract, ...]
    contract_version: str = CONTRACT_VERSION
    free_agency_version: str = FREE_AGENCY_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.season_year, int)
            or isinstance(self.season_year, bool)
            or self.season_year < 1
        ):
            raise ValueError("season_year must be a positive integer")
        if self.contract_version != CONTRACT_VERSION:
            raise ValueError("unsupported contract version")
        if self.free_agency_version != FREE_AGENCY_VERSION:
            raise ValueError("unsupported free-agency version")


@dataclass(frozen=True, slots=True)
class ContractYearResult:
    initial_year: int
    final_state: LeagueManagementState
    expired_player_ids: tuple[int, ...]
    version: str = CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.version != CONTRACT_VERSION:
            raise ValueError("unsupported contract-year result version")


@dataclass(frozen=True, slots=True)
class MarketAction:
    action_id: int
    kind: MarketActionKind
    player_id: int
    team_id: str
    annual_salary: int = 0
    years: int = 0

    def __post_init__(self) -> None:
        values = (self.action_id, self.player_id, self.annual_salary, self.years)
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise ValueError("market action values must be integers")
        if self.action_id < 0 or self.player_id < 0 or not self.team_id.strip():
            raise ValueError("market action ids must be non-negative and team_id non-blank")
        if not isinstance(self.kind, MarketActionKind):
            raise ValueError("kind must be MarketActionKind")
        if self.kind is MarketActionKind.WAIVE:
            if self.annual_salary != 0 or self.years != 0:
                raise ValueError("waivers cannot contain contract terms")
        elif self.annual_salary < 1 or self.years < 1:
            raise ValueError("signings require positive contract terms")


@dataclass(frozen=True, slots=True)
class MarketPlan:
    actions: tuple[MarketAction, ...]
    version: str = FREE_AGENCY_VERSION

    def __post_init__(self) -> None:
        if self.version != FREE_AGENCY_VERSION:
            raise ValueError("unsupported market plan version")
        action_ids = tuple(action.action_id for action in self.actions)
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("market action ids must be unique")
        if action_ids != tuple(sorted(action_ids)):
            raise ValueError("market actions must be ordered by action_id")


@dataclass(frozen=True, slots=True)
class MarketResult:
    rules: ContractRules
    initial_state: LeagueManagementState
    actions: tuple[MarketAction, ...]
    final_state: LeagueManagementState
    initial_cap_ledger: CapLedger | None = None
    final_cap_ledger: CapLedger | None = None
    cap_rules: CapMechanicsRules | None = None
    version: str = FREE_AGENCY_VERSION

    def __post_init__(self) -> None:
        if self.version != FREE_AGENCY_VERSION:
            raise ValueError("unsupported market result version")


@dataclass(frozen=True, slots=True)
class ManagementAudit:
    teams: int
    rostered_players: int
    free_agents: int
    total_payroll: int
    maximum_team_payroll: int
    signings: int
    waivers: int
    expirations: int


def _owner_map(state: LeagueManagementState) -> dict[int, str]:
    return {
        player_id: roster.team_id for roster in state.rosters for player_id in roster.player_ids
    }


def _payrolls(state: LeagueManagementState) -> dict[str, int]:
    payrolls = {roster.team_id: 0 for roster in state.rosters}
    for contract in state.contracts:
        payrolls[contract.team_id] += contract.annual_salary
    return payrolls


def validate_management_state(
    state: LeagueManagementState,
    rules: ContractRules,
    *,
    maximum_payroll: int | None = None,
) -> None:
    if state.rosters != tuple(sorted(state.rosters, key=lambda item: item.team_id)):
        raise ValueError("rosters must be ordered by team_id")
    team_ids = tuple(roster.team_id for roster in state.rosters)
    if not team_ids or len(team_ids) != len(set(team_ids)):
        raise ValueError("management state must contain unique teams")
    rostered = [player_id for roster in state.rosters for player_id in roster.player_ids]
    if len(rostered) != len(set(rostered)):
        raise ValueError("rostered players must have exactly one owner")
    if any(len(roster.player_ids) > rules.maximum_roster_players for roster in state.rosters):
        raise ValueError("team exceeds maximum roster size")
    if any(
        not isinstance(player_id, int) or isinstance(player_id, bool) or player_id < 0
        for player_id in state.free_agent_ids
    ) or state.free_agent_ids != tuple(sorted(set(state.free_agent_ids))):
        raise ValueError("free_agent_ids must be sorted unique non-negative integers")
    if set(rostered) & set(state.free_agent_ids):
        raise ValueError("a player cannot be rostered and a free agent")
    if state.contracts != tuple(sorted(state.contracts, key=lambda item: item.player_id)):
        raise ValueError("contracts must be ordered by player_id")
    contract_ids = tuple(contract.player_id for contract in state.contracts)
    if len(contract_ids) != len(set(contract_ids)) or set(contract_ids) != set(rostered):
        raise ValueError("every rostered player must have exactly one active contract")
    owners = _owner_map(state)
    for contract in state.contracts:
        if owners[contract.player_id] != contract.team_id:
            raise ValueError("contract team must match roster ownership")
        if not rules.minimum_salary <= contract.annual_salary <= rules.maximum_salary:
            raise ValueError("contract salary is outside configured bounds")
        if contract.years_remaining > rules.maximum_years:
            raise ValueError("contract term exceeds configured maximum")
    payroll_ceiling = rules.salary_cap if maximum_payroll is None else maximum_payroll
    if payroll_ceiling < rules.salary_cap:
        raise ValueError("maximum payroll cannot be below the contract salary cap")
    if any(payroll > payroll_ceiling for payroll in _payrolls(state).values()):
        raise ValueError("team payroll exceeds salary cap")


def advance_contract_year(
    state: LeagueManagementState,
    rules: ContractRules,
    *,
    maximum_payroll: int | None = None,
) -> ContractYearResult:
    validate_management_state(state, rules, maximum_payroll=maximum_payroll)
    expired = tuple(
        contract.player_id for contract in state.contracts if contract.years_remaining == 1
    )
    expired_set = set(expired)
    final = LeagueManagementState(
        state.season_year + 1,
        tuple(
            RosterSnapshot(
                roster.team_id,
                tuple(player_id for player_id in roster.player_ids if player_id not in expired_set),
            )
            for roster in state.rosters
        ),
        tuple(sorted((*state.free_agent_ids, *expired))),
        tuple(
            replace(contract, years_remaining=contract.years_remaining - 1)
            for contract in state.contracts
            if contract.player_id not in expired_set
        ),
    )
    validate_management_state(final, rules, maximum_payroll=maximum_payroll)
    return ContractYearResult(state.season_year, final, expired)


def _replace_roster(
    state: LeagueManagementState,
    team_id: str,
    player_ids: tuple[int, ...],
) -> tuple[RosterSnapshot, ...]:
    if team_id not in {roster.team_id for roster in state.rosters}:
        raise ValueError("market action references an unknown team")
    return tuple(
        RosterSnapshot(roster.team_id, player_ids) if roster.team_id == team_id else roster
        for roster in state.rosters
    )


def _apply_action(
    state: LeagueManagementState,
    action: MarketAction,
    rules: ContractRules,
    cap_ledger: CapLedger | None = None,
    cap_rules: CapMechanicsRules | None = None,
    maximum_payroll: int | None = None,
) -> LeagueManagementState:
    owners = _owner_map(state)
    if action.kind is MarketActionKind.WAIVE:
        if owners.get(action.player_id) != action.team_id:
            raise ValueError("waiver team does not own player")
        roster = next(item for item in state.rosters if item.team_id == action.team_id)
        updated = LeagueManagementState(
            state.season_year,
            _replace_roster(
                state,
                action.team_id,
                tuple(
                    player_id for player_id in roster.player_ids if player_id != action.player_id
                ),
            ),
            tuple(sorted((*state.free_agent_ids, action.player_id))),
            tuple(
                contract for contract in state.contracts if contract.player_id != action.player_id
            ),
        )
    else:
        if action.player_id not in state.free_agent_ids:
            raise ValueError("signing player is not a free agent")
        if action.team_id not in {roster.team_id for roster in state.rosters}:
            raise ValueError("market action references an unknown team")
        roster = next(item for item in state.rosters if item.team_id == action.team_id)
        if len(roster.player_ids) >= rules.maximum_roster_players:
            raise ValueError("signing would exceed maximum roster size")
        if cap_ledger is not None:
            active_cap_rules = cap_rules or CapMechanicsRules()
            decision = evaluate_signing_salary(
                team_id=action.team_id,
                player_id=action.player_id,
                team_payroll=_payrolls(state)[action.team_id],
                annual_salary=action.annual_salary,
                ledger=cap_ledger,
                rules=active_cap_rules,
                minimum_salary=rules.minimum_salary,
            )
            if not decision.allowed:
                raise ValueError("illegal signing: " + ", ".join(decision.rejections))
        contract = PlayerContract(
            action.player_id,
            action.team_id,
            action.annual_salary,
            action.years,
        )
        updated = LeagueManagementState(
            state.season_year,
            _replace_roster(
                state,
                action.team_id,
                (*roster.player_ids, action.player_id),
            ),
            tuple(player_id for player_id in state.free_agent_ids if player_id != action.player_id),
            tuple(sorted((*state.contracts, contract), key=lambda item: item.player_id)),
        )
    validate_management_state(
        updated,
        rules,
        maximum_payroll=(
            max(cap_rules.second_apron, maximum_payroll or 0)
            if cap_ledger is not None and cap_rules
            else maximum_payroll
        ),
    )
    return updated


def apply_market_plan(
    state: LeagueManagementState,
    plan: MarketPlan,
    rules: ContractRules,
    *,
    cap_ledger: CapLedger | None = None,
    cap_rules: CapMechanicsRules | None = None,
    maximum_payroll: int | None = None,
) -> MarketResult:
    if cap_ledger is not None and cap_rules is None:
        cap_rules = CapMechanicsRules()
    payroll_ceiling = (
        max(cap_rules.second_apron, maximum_payroll or 0)
        if cap_rules is not None
        else maximum_payroll
    )
    validate_management_state(
        state,
        rules,
        maximum_payroll=payroll_ceiling,
    )
    final = state
    final_cap_ledger = cap_ledger
    for action in plan.actions:
        final = _apply_action(
            final,
            action,
            rules,
            final_cap_ledger,
            cap_rules,
            maximum_payroll,
        )
        if final_cap_ledger is not None:
            final_cap_ledger = (
                remove_bird_rights(final_cap_ledger, frozenset({action.player_id}))
                if action.kind is MarketActionKind.WAIVE
                else record_bird_rights_signing(
                    final_cap_ledger,
                    team_id=action.team_id,
                    player_id=action.player_id,
                    annual_salary=action.annual_salary,
                )
            )
    return MarketResult(
        rules,
        state,
        plan.actions,
        final,
        cap_ledger,
        final_cap_ledger,
        cap_rules,
    )


def audit_market(
    result: MarketResult,
    *,
    maximum_payroll: int | None = None,
) -> ManagementAudit:
    validate_management_state(
        result.initial_state,
        result.rules,
        maximum_payroll=maximum_payroll,
    )
    validate_management_state(
        result.final_state,
        result.rules,
        maximum_payroll=maximum_payroll,
    )
    replayed = apply_market_plan(
        result.initial_state,
        MarketPlan(result.actions),
        result.rules,
        cap_ledger=result.initial_cap_ledger,
        cap_rules=result.cap_rules,
        maximum_payroll=maximum_payroll,
    )
    if (
        replayed.final_state != result.final_state
        or replayed.final_cap_ledger != result.final_cap_ledger
    ):
        raise ValueError("final management state does not derive from action ledger")
    payrolls = _payrolls(result.final_state)
    return ManagementAudit(
        len(result.final_state.rosters),
        sum(len(roster.player_ids) for roster in result.final_state.rosters),
        len(result.final_state.free_agent_ids),
        sum(payrolls.values()),
        max(payrolls.values(), default=0),
        sum(action.kind is MarketActionKind.SIGN for action in result.actions),
        sum(action.kind is MarketActionKind.WAIVE for action in result.actions),
        0,
    )


def audit_contract_year(
    result: ContractYearResult,
    rules: ContractRules,
) -> ManagementAudit:
    validate_management_state(result.final_state, rules)
    payrolls = _payrolls(result.final_state)
    return ManagementAudit(
        len(result.final_state.rosters),
        sum(len(roster.player_ids) for roster in result.final_state.rosters),
        len(result.final_state.free_agent_ids),
        sum(payrolls.values()),
        max(payrolls.values(), default=0),
        0,
        0,
        len(result.expired_player_ids),
    )


def _state_to_dict(state: LeagueManagementState) -> dict[str, object]:
    return {
        "season_year": state.season_year,
        "contract_version": state.contract_version,
        "free_agency_version": state.free_agency_version,
        "rosters": [
            {"team_id": roster.team_id, "player_ids": list(roster.player_ids)}
            for roster in state.rosters
        ],
        "free_agent_ids": list(state.free_agent_ids),
        "contracts": [
            {
                "player_id": contract.player_id,
                "team_id": contract.team_id,
                "annual_salary": contract.annual_salary,
                "years_remaining": contract.years_remaining,
            }
            for contract in state.contracts
        ],
    }


def market_result_to_dict(result: MarketResult) -> dict[str, object]:
    return {
        "schema_version": MANAGEMENT_SCHEMA_VERSION,
        "version": result.version,
        "rules": {
            "version": result.rules.version,
            "salary_cap": result.rules.salary_cap,
            "minimum_salary": result.rules.minimum_salary,
            "maximum_salary": result.rules.maximum_salary,
            "maximum_years": result.rules.maximum_years,
            "maximum_roster_players": result.rules.maximum_roster_players,
        },
        "initial_state": _state_to_dict(result.initial_state),
        "actions": [
            {
                "action_id": action.action_id,
                "kind": action.kind.name,
                "player_id": action.player_id,
                "team_id": action.team_id,
                "annual_salary": action.annual_salary,
                "years": action.years,
            }
            for action in result.actions
        ],
        "final_state": _state_to_dict(result.final_state),
    }


def _fail(message: str) -> NoReturn:
    raise SerializationError(message)


def _object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _fail(f"{field} must be an object")
    return cast(Mapping[str, Any], value)


def _exact(value: Mapping[str, Any], keys: set[str], field: str) -> None:
    if set(value) != keys:
        _fail(f"{field} keys must be exactly {sorted(keys)}")


def _integer(value: Mapping[str, Any], key: str) -> int:
    raw = value[key]
    if not isinstance(raw, int) or isinstance(raw, bool):
        _fail(f"{key} must be an integer")
    return raw


def _string(value: Mapping[str, Any], key: str) -> str:
    raw = value[key]
    if not isinstance(raw, str) or not raw:
        _fail(f"{key} must be a non-empty string")
    return raw


def _integer_tuple(value: object, field: str) -> tuple[int, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, int) or isinstance(item, bool) for item in value
    ):
        _fail(f"{field} must be an integer list")
    return tuple(value)


def _state_from_dict(value: object) -> LeagueManagementState:
    raw = _object(value, "management state")
    _exact(
        raw,
        {
            "season_year",
            "contract_version",
            "free_agency_version",
            "rosters",
            "free_agent_ids",
            "contracts",
        },
        "management state",
    )
    rosters_raw = raw["rosters"]
    if not isinstance(rosters_raw, list):
        _fail("rosters must be a list")
    rosters: list[RosterSnapshot] = []
    for roster_raw in rosters_raw:
        item = _object(roster_raw, "roster")
        _exact(item, {"team_id", "player_ids"}, "roster")
        rosters.append(
            RosterSnapshot(
                _string(item, "team_id"),
                _integer_tuple(item["player_ids"], "player_ids"),
            )
        )
    contracts_raw = raw["contracts"]
    if not isinstance(contracts_raw, list):
        _fail("contracts must be a list")
    contracts: list[PlayerContract] = []
    for contract_raw in contracts_raw:
        item = _object(contract_raw, "contract")
        _exact(
            item,
            {"player_id", "team_id", "annual_salary", "years_remaining"},
            "contract",
        )
        contracts.append(
            PlayerContract(
                _integer(item, "player_id"),
                _string(item, "team_id"),
                _integer(item, "annual_salary"),
                _integer(item, "years_remaining"),
            )
        )
    return LeagueManagementState(
        _integer(raw, "season_year"),
        tuple(rosters),
        _integer_tuple(raw["free_agent_ids"], "free_agent_ids"),
        tuple(contracts),
        _string(raw, "contract_version"),
        _string(raw, "free_agency_version"),
    )


def market_result_from_dict(
    value: object,
    *,
    maximum_payroll: int | None = None,
) -> MarketResult:
    raw = _object(value, "market result")
    _exact(
        raw,
        {"schema_version", "version", "rules", "initial_state", "actions", "final_state"},
        "market result",
    )
    if _integer(raw, "schema_version") != MANAGEMENT_SCHEMA_VERSION:
        _fail("unsupported management schema_version")
    rules_raw = _object(raw["rules"], "contract rules")
    _exact(
        rules_raw,
        {
            "version",
            "salary_cap",
            "minimum_salary",
            "maximum_salary",
            "maximum_years",
            "maximum_roster_players",
        },
        "contract rules",
    )
    rules = ContractRules(
        _integer(rules_raw, "salary_cap"),
        _integer(rules_raw, "minimum_salary"),
        _integer(rules_raw, "maximum_salary"),
        _integer(rules_raw, "maximum_years"),
        _integer(rules_raw, "maximum_roster_players"),
        _string(rules_raw, "version"),
    )
    actions_raw = raw["actions"]
    if not isinstance(actions_raw, list):
        _fail("actions must be a list")
    actions: list[MarketAction] = []
    for action_raw in actions_raw:
        item = _object(action_raw, "market action")
        _exact(
            item,
            {"action_id", "kind", "player_id", "team_id", "annual_salary", "years"},
            "market action",
        )
        kind_name = _string(item, "kind")
        try:
            kind = MarketActionKind[kind_name]
        except KeyError as error:
            raise SerializationError("unknown market action kind") from error
        actions.append(
            MarketAction(
                _integer(item, "action_id"),
                kind,
                _integer(item, "player_id"),
                _string(item, "team_id"),
                _integer(item, "annual_salary"),
                _integer(item, "years"),
            )
        )
    result = MarketResult(
        rules,
        _state_from_dict(raw["initial_state"]),
        tuple(actions),
        _state_from_dict(raw["final_state"]),
        version=_string(raw, "version"),
    )
    if result.version != FREE_AGENCY_VERSION:
        _fail("unsupported market result version")
    try:
        audit_market(result, maximum_payroll=maximum_payroll)
    except ValueError as error:
        raise SerializationError(str(error)) from error
    return result


def market_result_to_json(result: MarketResult) -> str:
    return json.dumps(
        market_result_to_dict(result),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def market_result_from_json(payload: str) -> MarketResult:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as error:
        raise SerializationError(f"invalid management JSON: {error.msg}") from error
    return market_result_from_dict(value)
