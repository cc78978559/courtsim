"""Native three-team trades with routed assets and unanimous manager approval."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import cast

from courtsim.cap_mechanics import CapLedger, CapMechanicsRules, evaluate_trade_salary
from courtsim.career import CareerPlayer
from courtsim.draft_assets import TradableDraftPick
from courtsim.management import (
    ContractRules,
    LeagueManagementState,
    validate_management_state,
)
from courtsim.manager_ai import ManagerDecisionLedger, ManagerPolicyMode, ManagerProfile
from courtsim.manager_trade import (
    DEFAULT_MANAGER_TRADE_RULES,
    MANAGER_TRADE_VERSION,
    ManagerTradeRules,
    TradeManagerApproval,
    evaluate_trade_team_approval,
)
from courtsim.rosters import RosterSnapshot
from courtsim.trades import (
    DEFAULT_TRADE_RULES,
    TradeRules,
    stepien_rejections,
)

THREE_TEAM_TRADE_VERSION = "three-team-trade-v1"


@dataclass(frozen=True, slots=True)
class PlayerTradeRoute:
    player_id: int
    from_team_id: str
    to_team_id: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.player_id, int)
            or isinstance(self.player_id, bool)
            or self.player_id < 0
        ):
            raise ValueError("routed player id must be a non-negative integer")
        _validate_route_teams(self.from_team_id, self.to_team_id)


@dataclass(frozen=True, slots=True)
class PickTradeRoute:
    pick_id: int
    from_team_id: str
    to_team_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.pick_id, int) or isinstance(self.pick_id, bool) or self.pick_id < 0:
            raise ValueError("routed pick id must be a non-negative integer")
        _validate_route_teams(self.from_team_id, self.to_team_id)


@dataclass(frozen=True, slots=True)
class ThreeTeamTradeOffer:
    trade_id: int
    team_ids: tuple[str, str, str]
    player_routes: tuple[PlayerTradeRoute, ...] = ()
    pick_routes: tuple[PickTradeRoute, ...] = ()
    version: str = THREE_TEAM_TRADE_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.trade_id, int)
            or isinstance(self.trade_id, bool)
            or self.trade_id < 0
        ):
            raise ValueError("three-team trade_id must be a non-negative integer")
        if self.team_ids != tuple(sorted(set(self.team_ids))) or any(
            not team_id.strip() for team_id in self.team_ids
        ):
            raise ValueError("three-team offer must contain three ordered unique teams")
        if self.player_routes != tuple(
            sorted(
                self.player_routes,
                key=lambda route: (
                    route.from_team_id,
                    route.to_team_id,
                    route.player_id,
                ),
            )
        ):
            raise ValueError("player routes must use canonical order")
        if self.pick_routes != tuple(
            sorted(
                self.pick_routes,
                key=lambda route: (
                    route.from_team_id,
                    route.to_team_id,
                    route.pick_id,
                ),
            )
        ):
            raise ValueError("pick routes must use canonical order")
        player_ids = tuple(route.player_id for route in self.player_routes)
        pick_ids = tuple(route.pick_id for route in self.pick_routes)
        if len(player_ids) != len(set(player_ids)) or len(pick_ids) != len(set(pick_ids)):
            raise ValueError("a routed asset may appear only once")
        if not self.player_routes and not self.pick_routes:
            raise ValueError("three-team offer must route at least one asset")
        participants = set(self.team_ids)
        if any(
            route.from_team_id not in participants or route.to_team_id not in participants
            for route in self.player_routes
        ) or any(
            route.from_team_id not in participants or route.to_team_id not in participants
            for route in self.pick_routes
        ):
            raise ValueError("every route must stay inside the three participating teams")
        for team_id in self.team_ids:
            sends = any(route.from_team_id == team_id for route in self.player_routes) or any(
                route.from_team_id == team_id for route in self.pick_routes
            )
            receives = any(route.to_team_id == team_id for route in self.player_routes) or any(
                route.to_team_id == team_id for route in self.pick_routes
            )
            if not sends or not receives:
                raise ValueError("every participating team must send and receive an asset")
        if self.version != THREE_TEAM_TRADE_VERSION:
            raise ValueError(f"unsupported three-team trade version: {self.version}")


@dataclass(frozen=True, slots=True)
class ThreeTeamTradeResult:
    offer: ThreeTeamTradeOffer
    trade_rules: TradeRules
    contract_rules: ContractRules
    initial_management: LeagueManagementState
    initial_picks: tuple[TradableDraftPick, ...]
    final_management: LeagueManagementState
    final_picks: tuple[TradableDraftPick, ...]
    initial_cap_ledger: CapLedger | None = None
    final_cap_ledger: CapLedger | None = None
    cap_rules: CapMechanicsRules | None = None
    frozen_pick_ids: tuple[int, ...] = ()
    version: str = THREE_TEAM_TRADE_VERSION


@dataclass(frozen=True, slots=True)
class ThreeTeamTradeAudit:
    trade_id: int
    teams: tuple[str, str, str]
    players_moved: int
    picks_moved: int
    replay_verified: bool


@dataclass(frozen=True, slots=True)
class ThreeTeamTradeShadowResult:
    offer: ThreeTeamTradeOffer
    legal: bool
    approved: bool
    hard_rejections: tuple[str, ...]
    approvals: tuple[TradeManagerApproval, TradeManagerApproval, TradeManagerApproval]
    ledger: ManagerDecisionLedger
    mode: ManagerPolicyMode = ManagerPolicyMode.SHADOW
    manager_trade_version: str = MANAGER_TRADE_VERSION
    version: str = THREE_TEAM_TRADE_VERSION


def three_team_trade_rejections(
    management: LeagueManagementState,
    picks: tuple[TradableDraftPick, ...],
    offer: ThreeTeamTradeOffer,
    contract_rules: ContractRules,
    trade_rules: TradeRules = DEFAULT_TRADE_RULES,
    *,
    cap_ledger: CapLedger | None = None,
    cap_rules: CapMechanicsRules | None = None,
    frozen_pick_ids: frozenset[int] = frozenset(),
) -> tuple[str, ...]:
    rejected: list[str] = []
    if cap_ledger is not None and cap_rules is None:
        cap_rules = CapMechanicsRules()
    try:
        validate_management_state(
            management,
            contract_rules,
            maximum_payroll=cap_rules.second_apron if cap_rules is not None else None,
        )
    except ValueError as error:
        return (f"invalid-management:{error}",)
    rosters = {roster.team_id: roster for roster in management.rosters}
    if not set(offer.team_ids) <= set(rosters):
        return ("unknown-team",)
    owners = {
        player_id: roster.team_id
        for roster in management.rosters
        for player_id in roster.player_ids
    }
    pick_map = {pick.selection_number: pick for pick in picks}
    if len(pick_map) != len(picks):
        rejected.append("duplicate-pick-selection")
    for player_route in offer.player_routes:
        if owners.get(player_route.player_id) != player_route.from_team_id:
            rejected.append(
                f"player-not-owned:{player_route.from_team_id}:{player_route.player_id}"
            )
    for pick_route in offer.pick_routes:
        if pick_route.pick_id in frozen_pick_ids:
            rejected.append(f"draft-obligation-frozen:{pick_route.pick_id}")
        pick = pick_map.get(pick_route.pick_id)
        if pick is None or pick.owner_team_id != pick_route.from_team_id:
            rejected.append(f"pick-not-owned:{pick_route.from_team_id}:{pick_route.pick_id}")

    salaries = {contract.player_id: contract.annual_salary for contract in management.contracts}
    payrolls = {team_id: 0 for team_id in rosters}
    for contract in management.contracts:
        payrolls[contract.team_id] += contract.annual_salary
    for team_id in offer.team_ids:
        outgoing_players = tuple(
            route.player_id for route in offer.player_routes if route.from_team_id == team_id
        )
        incoming_players = tuple(
            route.player_id for route in offer.player_routes if route.to_team_id == team_id
        )
        final_size = (
            len(rosters[team_id].player_ids) - len(outgoing_players) + len(incoming_players)
        )
        if final_size < trade_rules.minimum_roster_players:
            rejected.append(f"roster-minimum:{team_id}")
        if final_size > contract_rules.maximum_roster_players:
            rejected.append(f"roster-maximum:{team_id}")
        outgoing_salary = sum(salaries.get(player_id, 0) for player_id in outgoing_players)
        incoming_salary = sum(salaries.get(player_id, 0) for player_id in incoming_players)
        if cap_ledger is not None:
            cap_result = evaluate_trade_salary(
                team_id=team_id,
                team_payroll=payrolls[team_id],
                outgoing_salary=outgoing_salary,
                incoming_salary=incoming_salary,
                season_year=management.season_year,
                ledger=cap_ledger,
                rules=cap_rules,
            )
            rejected.extend(
                f"cap-mechanics:{team_id}:{reason}" for reason in cap_result.decision.rejections
            )
        elif payrolls[team_id] - outgoing_salary + incoming_salary > contract_rules.salary_cap:
            rejected.append(f"salary-cap:{team_id}")
        if cap_ledger is None and payrolls[team_id] >= trade_rules.salary_matching_threshold:
            maximum = (
                outgoing_salary * trade_rules.maximum_incoming_salary_bps // 10_000
                + trade_rules.salary_matching_buffer
            )
            if incoming_salary > maximum:
                rejected.append(f"salary-match:{team_id}")
    if trade_rules.enforce_stepien_rule:
        destinations = {route.pick_id: route.to_team_id for route in offer.pick_routes}
        rejected.extend(
            stepien_rejections(
                picks,
                final_pick_owners={
                    pick.selection_number: destinations.get(
                        pick.selection_number,
                        pick.owner_team_id,
                    )
                    for pick in picks
                },
                team_ids=offer.team_ids,
                rules=trade_rules,
            )
        )
    return tuple(rejected)


def apply_three_team_trade(
    management: LeagueManagementState,
    picks: tuple[TradableDraftPick, ...],
    offer: ThreeTeamTradeOffer,
    contract_rules: ContractRules,
    trade_rules: TradeRules = DEFAULT_TRADE_RULES,
    *,
    cap_ledger: CapLedger | None = None,
    cap_rules: CapMechanicsRules | None = None,
    frozen_pick_ids: frozenset[int] = frozenset(),
) -> ThreeTeamTradeResult:
    if cap_ledger is not None and cap_rules is None:
        cap_rules = CapMechanicsRules()
    rejected = three_team_trade_rejections(
        management,
        picks,
        offer,
        contract_rules,
        trade_rules,
        cap_ledger=cap_ledger,
        cap_rules=cap_rules,
        frozen_pick_ids=frozen_pick_ids,
    )
    if rejected:
        raise ValueError("illegal three-team trade: " + ", ".join(rejected))
    player_destinations = {route.player_id: route.to_team_id for route in offer.player_routes}
    outgoing_by_team = {
        team_id: {route.player_id for route in offer.player_routes if route.from_team_id == team_id}
        for team_id in offer.team_ids
    }
    incoming_by_team = {
        team_id: {route.player_id for route in offer.player_routes if route.to_team_id == team_id}
        for team_id in offer.team_ids
    }
    final_rosters = tuple(
        RosterSnapshot(
            roster.team_id,
            tuple(
                sorted(
                    (set(roster.player_ids) - outgoing_by_team[roster.team_id])
                    | incoming_by_team[roster.team_id]
                )
            ),
        )
        if roster.team_id in offer.team_ids
        else roster
        for roster in management.rosters
    )
    final_contracts = tuple(
        replace(
            contract,
            team_id=player_destinations.get(contract.player_id, contract.team_id),
        )
        for contract in management.contracts
    )
    pick_destinations = {route.pick_id: route.to_team_id for route in offer.pick_routes}
    final_picks = tuple(
        replace(
            pick,
            owner_team_id=pick_destinations.get(
                pick.selection_number,
                pick.owner_team_id,
            ),
        )
        for pick in picks
    )
    final_management = replace(
        management,
        rosters=final_rosters,
        contracts=final_contracts,
    )
    final_cap_ledger = cap_ledger
    if cap_ledger is not None and cap_rules is not None:
        salaries = {contract.player_id: contract.annual_salary for contract in management.contracts}
        payrolls = {roster.team_id: 0 for roster in management.rosters}
        for contract in management.contracts:
            payrolls[contract.team_id] += contract.annual_salary
        for team_id in offer.team_ids:
            assert final_cap_ledger is not None
            outgoing = (
                route.player_id for route in offer.player_routes if route.from_team_id == team_id
            )
            incoming = (
                route.player_id for route in offer.player_routes if route.to_team_id == team_id
            )
            cap_result = evaluate_trade_salary(
                team_id=team_id,
                team_payroll=payrolls[team_id],
                outgoing_salary=sum(salaries[player_id] for player_id in outgoing),
                incoming_salary=sum(salaries[player_id] for player_id in incoming),
                season_year=management.season_year,
                ledger=final_cap_ledger,
                rules=cap_rules,
            )
            final_cap_ledger = cap_result.final_ledger
    validate_management_state(
        final_management,
        contract_rules,
        maximum_payroll=cap_rules.second_apron if cap_rules is not None else None,
    )
    return ThreeTeamTradeResult(
        offer,
        trade_rules,
        contract_rules,
        management,
        picks,
        final_management,
        final_picks,
        cap_ledger,
        final_cap_ledger,
        cap_rules,
        tuple(sorted(frozen_pick_ids)),
    )


def audit_three_team_trade(result: ThreeTeamTradeResult) -> ThreeTeamTradeAudit:
    replayed = apply_three_team_trade(
        result.initial_management,
        result.initial_picks,
        result.offer,
        result.contract_rules,
        result.trade_rules,
        cap_ledger=result.initial_cap_ledger,
        cap_rules=result.cap_rules,
        frozen_pick_ids=frozenset(result.frozen_pick_ids),
    )
    if (
        replayed.final_management != result.final_management
        or replayed.final_picks != result.final_picks
        or replayed.final_cap_ledger != result.final_cap_ledger
    ):
        raise ValueError("three-team trade result does not derive from its routed ledger")
    return ThreeTeamTradeAudit(
        result.offer.trade_id,
        result.offer.team_ids,
        len(result.offer.player_routes),
        len(result.offer.pick_routes),
        True,
    )


def evaluate_three_team_trade_shadow(
    *,
    management: LeagueManagementState,
    players: Sequence[CareerPlayer],
    picks: tuple[TradableDraftPick, ...],
    offer: ThreeTeamTradeOffer,
    profiles: Mapping[str, ManagerProfile],
    contract_rules: ContractRules,
    trade_rules: TradeRules = DEFAULT_TRADE_RULES,
    manager_rules: ManagerTradeRules = DEFAULT_MANAGER_TRADE_RULES,
    cap_ledger: CapLedger | None = None,
    cap_rules: CapMechanicsRules | None = None,
    frozen_pick_ids: frozenset[int] = frozenset(),
) -> ThreeTeamTradeShadowResult:
    if set(profiles) != set(offer.team_ids):
        raise ValueError("three-team profiles must cover every participant exactly")
    if any(team_id != profile.team_id for team_id, profile in profiles.items()):
        raise ValueError("three-team profile keys must match profile team ids")
    player_map = {player.player_id: player for player in players}
    if len(player_map) != len(players):
        raise ValueError("career player ids must be unique")
    rejected = three_team_trade_rejections(
        management,
        picks,
        offer,
        contract_rules,
        trade_rules,
        cap_ledger=cap_ledger,
        cap_rules=cap_rules,
        frozen_pick_ids=frozen_pick_ids,
    )
    approvals: list[TradeManagerApproval] = []
    ledger = ManagerDecisionLedger()
    for team_id in offer.team_ids:
        profile = profiles[team_id]
        approval = evaluate_trade_team_approval(
            management=management,
            player_map=player_map,
            picks=picks,
            team_id=team_id,
            profile=profile,
            outgoing_players=tuple(
                route.player_id for route in offer.player_routes if route.from_team_id == team_id
            ),
            incoming_players=tuple(
                route.player_id for route in offer.player_routes if route.to_team_id == team_id
            ),
            outgoing_picks=tuple(
                route.pick_id for route in offer.pick_routes if route.from_team_id == team_id
            ),
            incoming_picks=tuple(
                route.pick_id for route in offer.pick_routes if route.to_team_id == team_id
            ),
            hard_rejections=rejected,
            contract_rules=contract_rules,
            manager_rules=manager_rules,
            decision_id=f"three-team-trade:{offer.trade_id}:{team_id}",
        )
        approvals.append(approval)
        ledger = ledger.add(trace=approval.trace, stage="three-team-trade", profile=profile)
    approval_tuple = cast(
        tuple[TradeManagerApproval, TradeManagerApproval, TradeManagerApproval],
        tuple(approvals),
    )
    return ThreeTeamTradeShadowResult(
        offer,
        not rejected,
        not rejected and all(approval.accepted for approval in approval_tuple),
        rejected,
        approval_tuple,
        ledger,
    )


def _validate_route_teams(from_team_id: str, to_team_id: str) -> None:
    if not from_team_id.strip() or not to_team_id.strip():
        raise ValueError("route team ids must not be blank")
    if from_team_id == to_team_id:
        raise ValueError("route teams must be distinct")
