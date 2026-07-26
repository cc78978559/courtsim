"""Canonical bilateral trades with atomic player, contract, and pick ownership updates."""

from __future__ import annotations

from dataclasses import dataclass, replace

from courtsim.draft_assets import TradableDraftPick
from courtsim.management import (
    ContractRules,
    LeagueManagementState,
    validate_management_state,
)
from courtsim.rosters import RosterSnapshot

TRADE_VERSION = "trade-v1"


@dataclass(frozen=True, slots=True)
class TradeRules:
    minimum_roster_players: int = 5
    salary_matching_threshold: int = 100_000_000
    maximum_incoming_salary_bps: int = 12_500
    salary_matching_buffer: int = 250_000
    version: str = TRADE_VERSION

    def __post_init__(self) -> None:
        values = (
            self.minimum_roster_players,
            self.salary_matching_threshold,
            self.maximum_incoming_salary_bps,
            self.salary_matching_buffer,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise ValueError("trade rule values must be integers")
        if self.minimum_roster_players < 5:
            raise ValueError("minimum_roster_players cannot be below five")
        if self.salary_matching_threshold < 0 or self.salary_matching_buffer < 0:
            raise ValueError("salary matching values must be non-negative")
        if self.maximum_incoming_salary_bps < 10_000:
            raise ValueError("maximum incoming salary cannot be below outgoing salary")
        if self.version != TRADE_VERSION:
            raise ValueError(f"unsupported trade version: {self.version}")


DEFAULT_TRADE_RULES = TradeRules()


@dataclass(frozen=True, slots=True)
class TradeOffer:
    trade_id: int
    team_a_id: str
    team_b_id: str
    players_from_a: tuple[int, ...] = ()
    players_from_b: tuple[int, ...] = ()
    picks_from_a: tuple[int, ...] = ()
    picks_from_b: tuple[int, ...] = ()
    version: str = TRADE_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.trade_id, int)
            or isinstance(self.trade_id, bool)
            or self.trade_id < 0
        ):
            raise ValueError("trade_id must be a non-negative integer")
        if not self.team_a_id.strip() or not self.team_b_id.strip():
            raise ValueError("trade team ids must not be blank")
        if self.team_a_id == self.team_b_id:
            raise ValueError("trade teams must be distinct")
        asset_groups = (
            self.players_from_a,
            self.players_from_b,
            self.picks_from_a,
            self.picks_from_b,
        )
        if any(
            any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in group
            )
            or len(group) != len(set(group))
            or group != tuple(sorted(group))
            for group in asset_groups
        ):
            raise ValueError("trade asset ids must be sorted unique non-negative integers")
        if set(self.players_from_a) & set(self.players_from_b):
            raise ValueError("a player cannot be sent by both teams")
        if set(self.picks_from_a) & set(self.picks_from_b):
            raise ValueError("a pick cannot be sent by both teams")
        if not (self.players_from_a or self.picks_from_a):
            raise ValueError("team A must send at least one asset")
        if not (self.players_from_b or self.picks_from_b):
            raise ValueError("team B must send at least one asset")
        if self.version != TRADE_VERSION:
            raise ValueError(f"unsupported trade version: {self.version}")


@dataclass(frozen=True, slots=True)
class TradeResult:
    rules: TradeRules
    contract_rules: ContractRules
    offer: TradeOffer
    initial_management: LeagueManagementState
    initial_picks: tuple[TradableDraftPick, ...]
    final_management: LeagueManagementState
    final_picks: tuple[TradableDraftPick, ...]
    version: str = TRADE_VERSION

    def __post_init__(self) -> None:
        if self.version != TRADE_VERSION:
            raise ValueError("unsupported trade result version")


@dataclass(frozen=True, slots=True)
class TradeAudit:
    trade_id: int
    players_moved: int
    picks_moved: int
    salary_to_a: int
    salary_to_b: int
    replay_verified: bool


def trade_rejections(
    management: LeagueManagementState,
    picks: tuple[TradableDraftPick, ...],
    offer: TradeOffer,
    contract_rules: ContractRules,
    trade_rules: TradeRules,
) -> tuple[str, ...]:
    """Return deterministic legality failures without mutating league state."""
    rejected: list[str] = []
    try:
        validate_management_state(management, contract_rules)
    except ValueError as error:
        return (f"invalid-management:{error}",)
    teams = {roster.team_id: roster for roster in management.rosters}
    if offer.team_a_id not in teams or offer.team_b_id not in teams:
        return ("unknown-team",)
    owners = {
        player_id: roster.team_id
        for roster in management.rosters
        for player_id in roster.player_ids
    }
    for player_id in offer.players_from_a:
        if owners.get(player_id) != offer.team_a_id:
            rejected.append(f"player-not-owned:{offer.team_a_id}:{player_id}")
    for player_id in offer.players_from_b:
        if owners.get(player_id) != offer.team_b_id:
            rejected.append(f"player-not-owned:{offer.team_b_id}:{player_id}")
    pick_map = {pick.selection_number: pick for pick in picks}
    if len(pick_map) != len(picks):
        rejected.append("duplicate-pick-selection")
    for selection_number in offer.picks_from_a:
        pick = pick_map.get(selection_number)
        if pick is None or pick.owner_team_id != offer.team_a_id:
            rejected.append(f"pick-not-owned:{offer.team_a_id}:{selection_number}")
    for selection_number in offer.picks_from_b:
        pick = pick_map.get(selection_number)
        if pick is None or pick.owner_team_id != offer.team_b_id:
            rejected.append(f"pick-not-owned:{offer.team_b_id}:{selection_number}")

    final_a = (
        len(teams[offer.team_a_id].player_ids)
        - len(offer.players_from_a)
        + len(offer.players_from_b)
    )
    final_b = (
        len(teams[offer.team_b_id].player_ids)
        - len(offer.players_from_b)
        + len(offer.players_from_a)
    )
    for team_id, size in ((offer.team_a_id, final_a), (offer.team_b_id, final_b)):
        if size < trade_rules.minimum_roster_players:
            rejected.append(f"roster-minimum:{team_id}")
        if size > contract_rules.maximum_roster_players:
            rejected.append(f"roster-maximum:{team_id}")

    salaries = {contract.player_id: contract.annual_salary for contract in management.contracts}
    payrolls = {team_id: 0 for team_id in teams}
    for contract in management.contracts:
        payrolls[contract.team_id] += contract.annual_salary
    outgoing_a = sum(salaries.get(player_id, 0) for player_id in offer.players_from_a)
    outgoing_b = sum(salaries.get(player_id, 0) for player_id in offer.players_from_b)
    incoming_a = outgoing_b
    incoming_b = outgoing_a
    for team_id, outgoing, incoming in (
        (offer.team_a_id, outgoing_a, incoming_a),
        (offer.team_b_id, outgoing_b, incoming_b),
    ):
        final_payroll = payrolls[team_id] - outgoing + incoming
        if final_payroll > contract_rules.salary_cap:
            rejected.append(f"salary-cap:{team_id}")
        if payrolls[team_id] >= trade_rules.salary_matching_threshold:
            maximum = (
                outgoing * trade_rules.maximum_incoming_salary_bps // 10_000
                + trade_rules.salary_matching_buffer
            )
            if incoming > maximum:
                rejected.append(f"salary-match:{team_id}")
    return tuple(rejected)


def apply_trade(
    management: LeagueManagementState,
    picks: tuple[TradableDraftPick, ...],
    offer: TradeOffer,
    contract_rules: ContractRules,
    trade_rules: TradeRules = DEFAULT_TRADE_RULES,
) -> TradeResult:
    """Apply a legal bilateral trade as one atomic state transition."""
    rejected = trade_rejections(management, picks, offer, contract_rules, trade_rules)
    if rejected:
        raise ValueError("illegal trade: " + ", ".join(rejected))
    a_out = set(offer.players_from_a)
    b_out = set(offer.players_from_b)
    final_rosters = tuple(
        RosterSnapshot(
            roster.team_id,
            tuple(
                sorted(
                    (
                        set(roster.player_ids)
                        - (a_out if roster.team_id == offer.team_a_id else b_out)
                    )
                    | (b_out if roster.team_id == offer.team_a_id else a_out)
                )
            )
            if roster.team_id in {offer.team_a_id, offer.team_b_id}
            else roster.player_ids,
        )
        for roster in management.rosters
    )
    final_contracts = tuple(
        sorted(
            (
                replace(contract, team_id=offer.team_b_id)
                if contract.player_id in a_out
                else replace(contract, team_id=offer.team_a_id)
                if contract.player_id in b_out
                else contract
                for contract in management.contracts
            ),
            key=lambda contract: contract.player_id,
        )
    )
    a_picks = set(offer.picks_from_a)
    b_picks = set(offer.picks_from_b)
    final_picks = tuple(
        replace(pick, owner_team_id=offer.team_b_id)
        if pick.selection_number in a_picks
        else replace(pick, owner_team_id=offer.team_a_id)
        if pick.selection_number in b_picks
        else pick
        for pick in picks
    )
    final_management = replace(
        management,
        rosters=final_rosters,
        contracts=final_contracts,
    )
    validate_management_state(final_management, contract_rules)
    return TradeResult(
        trade_rules,
        contract_rules,
        offer,
        management,
        picks,
        final_management,
        final_picks,
    )


def audit_trade(result: TradeResult) -> TradeAudit:
    replayed = apply_trade(
        result.initial_management,
        result.initial_picks,
        result.offer,
        result.contract_rules,
        result.rules,
    )
    if (
        replayed.final_management != result.final_management
        or replayed.final_picks != result.final_picks
    ):
        raise ValueError("trade result does not derive from its offer ledger")
    salaries = {
        contract.player_id: contract.annual_salary
        for contract in result.initial_management.contracts
    }
    return TradeAudit(
        result.offer.trade_id,
        len(result.offer.players_from_a) + len(result.offer.players_from_b),
        len(result.offer.picks_from_a) + len(result.offer.picks_from_b),
        sum(salaries[player_id] for player_id in result.offer.players_from_b),
        sum(salaries[player_id] for player_id in result.offer.players_from_a),
        True,
    )
