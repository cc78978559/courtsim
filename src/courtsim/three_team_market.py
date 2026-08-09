"""Automatic three-team discovery, pick compensation, and conflict-free clearing."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from heapq import nsmallest
from itertools import combinations, permutations, product

from courtsim.cap_mechanics import CapLedger, CapMechanicsRules
from courtsim.career import CareerPlayer
from courtsim.draft_assets import TradableDraftPick
from courtsim.management import ContractRules, LeagueManagementState
from courtsim.manager_ai import (
    ManagerDecisionLedger,
    ManagerDecisionRecord,
    ManagerPolicyMode,
    ManagerProfile,
)
from courtsim.manager_trade import (
    DEFAULT_MANAGER_TRADE_RULES,
    ManagerTradeRules,
)
from courtsim.three_team_market_v2 import (
    ContractConditionKind,
    ThreeTeamContractCondition,
    ThreeTeamContractNegotiationTree,
    build_three_team_contract_negotiation_tree,
    execute_three_team_contract_negotiation,
)
from courtsim.three_team_trades import (
    THREE_TEAM_TRADE_VERSION,
    PickTradeRoute,
    PlayerTradeRoute,
    ThreeTeamTradeAudit,
    ThreeTeamTradeOffer,
    ThreeTeamTradeShadowResult,
    audit_three_team_trade,
    evaluate_three_team_trade_shadow,
)
from courtsim.trades import DEFAULT_TRADE_RULES, TradeRules

THREE_TEAM_MARKET_VERSION = "three-team-market-v1"


@dataclass(frozen=True, slots=True)
class ThreeTeamMarketRules:
    maximum_candidates_per_trio: int = 64
    maximum_cyclic_candidates_per_trio: int = 32
    maximum_hub_candidates_per_trio: int = 32
    minimum_combined_rational_gain: float = 0.001
    search_pick_compensation: bool = True
    maximum_compensation_picks: int = 2
    salary_aware_hub_ordering: bool = True
    maximum_contract_negotiation_rounds: int = 4
    version: str = THREE_TEAM_MARKET_VERSION

    def __post_init__(self) -> None:
        limits = (
            self.maximum_candidates_per_trio,
            self.maximum_cyclic_candidates_per_trio,
            self.maximum_hub_candidates_per_trio,
            self.maximum_compensation_picks,
            self.maximum_contract_negotiation_rounds,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in limits
        ):
            raise ValueError("three-team candidate limit must be a positive integer")
        if (
            self.maximum_cyclic_candidates_per_trio + self.maximum_hub_candidates_per_trio
            > self.maximum_candidates_per_trio
        ):
            raise ValueError("three-team candidate family budgets exceed the trio limit")
        if self.maximum_compensation_picks > 2:
            raise ValueError("three-team-market-v1 supports at most two compensation picks")
        if not 4 <= self.maximum_contract_negotiation_rounds <= 8:
            raise ValueError("three-team market requires four through eight contract rounds")
        if self.minimum_combined_rational_gain <= 0:
            raise ValueError("three-team minimum combined gain must be positive")
        if self.version != THREE_TEAM_MARKET_VERSION:
            raise ValueError(f"unsupported three-team market version: {self.version}")


DEFAULT_THREE_TEAM_MARKET_RULES = ThreeTeamMarketRules()


@dataclass(frozen=True, slots=True)
class ThreeTeamMarketEvaluation:
    kind: str
    parent_trade_id: int | None
    shadow: ThreeTeamTradeShadowResult
    salary_imbalance: int = 0

    def __post_init__(self) -> None:
        if self.kind not in {
            "cyclic",
            "hub",
            "pick-compensation",
            "multi-pick-compensation",
        }:
            raise ValueError("unsupported three-team market candidate kind")
        if self.kind in {"cyclic", "hub"} and self.parent_trade_id is not None:
            raise ValueError("base three-team offer cannot reference a parent")
        if self.kind in {"pick-compensation", "multi-pick-compensation"} and (
            self.parent_trade_id is None
        ):
            raise ValueError("pick compensation must reference its parent")
        if (
            not isinstance(self.salary_imbalance, int)
            or isinstance(self.salary_imbalance, bool)
            or self.salary_imbalance < 0
        ):
            raise ValueError("salary imbalance must be a non-negative integer")

    @property
    def negotiation_round(self) -> int:
        return {
            "cyclic": 0,
            "hub": 0,
            "pick-compensation": 1,
            "multi-pick-compensation": 2,
        }[self.kind]


@dataclass(frozen=True, slots=True)
class ThreeTeamMarketPlan:
    offers: tuple[ThreeTeamTradeOffer, ...]
    version: str = THREE_TEAM_MARKET_VERSION

    def __post_init__(self) -> None:
        if self.version != THREE_TEAM_MARKET_VERSION:
            raise ValueError("unsupported three-team market plan version")
        ids = tuple(offer.trade_id for offer in self.offers)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("three-team market offer ids must be ordered and unique")
        team_ids = [team_id for offer in self.offers for team_id in offer.team_ids]
        if len(team_ids) != len(set(team_ids)):
            raise ValueError("three-team market plan cannot reuse a team")


@dataclass(frozen=True, slots=True)
class ThreeTeamMarketShadowResult:
    plan: ThreeTeamMarketPlan
    evaluations: tuple[ThreeTeamMarketEvaluation, ...]
    ledger: ManagerDecisionLedger
    negotiations: tuple[ThreeTeamContractNegotiationTree, ...] = ()
    mode: ManagerPolicyMode = ManagerPolicyMode.SHADOW
    version: str = THREE_TEAM_MARKET_VERSION


@dataclass(frozen=True, slots=True)
class ThreeTeamMarketExecution:
    plan: ThreeTeamMarketPlan
    initial_management: LeagueManagementState
    initial_picks: tuple[TradableDraftPick, ...]
    final_management: LeagueManagementState
    final_picks: tuple[TradableDraftPick, ...]
    audits: tuple[ThreeTeamTradeAudit, ...]
    negotiations: tuple[ThreeTeamContractNegotiationTree, ...] = ()
    accepted_node_ids: tuple[int, ...] = ()
    initial_cap_ledger: CapLedger | None = None
    final_cap_ledger: CapLedger | None = None
    three_team_trade_version: str = THREE_TEAM_TRADE_VERSION
    version: str = THREE_TEAM_MARKET_VERSION


def generate_three_team_market_shadow(
    *,
    management: LeagueManagementState,
    players: Sequence[CareerPlayer],
    picks: tuple[TradableDraftPick, ...],
    profiles: Mapping[str, ManagerProfile],
    contract_rules: ContractRules,
    trade_rules: TradeRules = DEFAULT_TRADE_RULES,
    manager_rules: ManagerTradeRules = DEFAULT_MANAGER_TRADE_RULES,
    market_rules: ThreeTeamMarketRules = DEFAULT_THREE_TEAM_MARKET_RULES,
    cap_ledger: CapLedger | None = None,
    cap_rules: CapMechanicsRules | None = None,
    frozen_pick_ids: frozenset[int] = frozenset(),
) -> ThreeTeamMarketShadowResult:
    team_ids = tuple(roster.team_id for roster in management.rosters)
    if set(profiles) != set(team_ids):
        raise ValueError("three-team market profiles must cover every league team")
    rosters = {roster.team_id: roster.player_ids for roster in management.rosters}
    salaries = {contract.player_id: contract.annual_salary for contract in management.contracts}
    evaluations: list[ThreeTeamMarketEvaluation] = []
    ledger_records: list[ManagerDecisionRecord] = []
    next_trade_id = 1
    for trio in combinations(tuple(sorted(team_ids)), 3):
        trio_evaluations = 0
        families = (
            (
                "cyclic",
                _cyclic_routes(trio, rosters),
                market_rules.maximum_cyclic_candidates_per_trio,
            ),
            (
                "hub",
                _hub_routes(
                    trio,
                    rosters,
                    salaries,
                    market_rules.maximum_hub_candidates_per_trio,
                    market_rules.salary_aware_hub_ordering,
                ),
                market_rules.maximum_hub_candidates_per_trio,
            ),
        )
        for base_kind, route_candidates, family_budget in families:
            family_evaluations = 0
            for routes in route_candidates:
                if (
                    trio_evaluations >= market_rules.maximum_candidates_per_trio
                    or family_evaluations >= family_budget
                ):
                    break
                offer = ThreeTeamTradeOffer(
                    next_trade_id,
                    trio,
                    routes,
                )
                next_trade_id += 1
                shadow = evaluate_three_team_trade_shadow(
                    management=management,
                    players=players,
                    picks=picks,
                    offer=offer,
                    profiles={team_id: profiles[team_id] for team_id in trio},
                    contract_rules=contract_rules,
                    trade_rules=trade_rules,
                    manager_rules=manager_rules,
                    cap_ledger=cap_ledger,
                    cap_rules=cap_rules,
                    frozen_pick_ids=frozen_pick_ids,
                )
                salary_imbalance = _salary_imbalance(routes, salaries)
                evaluations.append(
                    ThreeTeamMarketEvaluation(
                        base_kind,
                        None,
                        shadow,
                        salary_imbalance,
                    )
                )
                _append_ledger(ledger_records, shadow)
                trio_evaluations += 1
                family_evaluations += 1
                if not market_rules.search_pick_compensation or not shadow.legal:
                    continue
                parent_trade_id = offer.trade_id
                previous_shadow = shadow
                for pick_count in range(1, market_rules.maximum_compensation_picks + 1):
                    if (
                        previous_shadow.approved
                        or trio_evaluations >= market_rules.maximum_candidates_per_trio
                        or family_evaluations >= family_budget
                    ):
                        break
                    compensation = _compensation_offer(
                        next_trade_id,
                        shadow,
                        picks,
                        pick_count,
                    )
                    if compensation is None:
                        break
                    next_trade_id += 1
                    counter = evaluate_three_team_trade_shadow(
                        management=management,
                        players=players,
                        picks=picks,
                        offer=compensation,
                        profiles={team_id: profiles[team_id] for team_id in trio},
                        contract_rules=contract_rules,
                        trade_rules=trade_rules,
                        manager_rules=manager_rules,
                        cap_ledger=cap_ledger,
                        cap_rules=cap_rules,
                        frozen_pick_ids=frozen_pick_ids,
                    )
                    evaluations.append(
                        ThreeTeamMarketEvaluation(
                            ("pick-compensation" if pick_count == 1 else "multi-pick-compensation"),
                            parent_trade_id,
                            counter,
                            salary_imbalance,
                        )
                    )
                    _append_ledger(ledger_records, counter)
                    trio_evaluations += 1
                    family_evaluations += 1
                    parent_trade_id = compensation.trade_id
                    previous_shadow = counter

    approved = [
        evaluation
        for evaluation in evaluations
        if evaluation.shadow.approved
        and three_team_shadow_gain(evaluation.shadow) >= market_rules.minimum_combined_rational_gain
    ]
    approved.sort(
        key=lambda evaluation: (
            -three_team_shadow_gain(evaluation.shadow),
            evaluation.salary_imbalance,
            _offer_signature(evaluation.shadow.offer),
        )
    )
    selected: list[ThreeTeamTradeOffer] = []
    locked_teams: set[str] = set()
    for evaluation in approved:
        offer = evaluation.shadow.offer
        if set(offer.team_ids) & locked_teams:
            continue
        selected.append(offer)
        locked_teams.update(offer.team_ids)
    selected.sort(key=lambda offer: offer.trade_id)
    negotiations = tuple(
        build_three_team_contract_negotiation_tree(
            offer,
            management,
            _contract_conditions(offer, management),
            maximum_rounds=market_rules.maximum_contract_negotiation_rounds,
        )
        for offer in selected
    )
    return ThreeTeamMarketShadowResult(
        ThreeTeamMarketPlan(tuple(selected)),
        tuple(evaluations),
        ManagerDecisionLedger(tuple(ledger_records)),
        negotiations,
    )


def apply_three_team_market_plan(
    management: LeagueManagementState,
    picks: tuple[TradableDraftPick, ...],
    plan: ThreeTeamMarketPlan,
    contract_rules: ContractRules,
    trade_rules: TradeRules = DEFAULT_TRADE_RULES,
    *,
    cap_ledger: CapLedger | None = None,
    cap_rules: CapMechanicsRules | None = None,
    frozen_pick_ids: frozenset[int] = frozenset(),
    negotiations: tuple[ThreeTeamContractNegotiationTree, ...] = (),
) -> ThreeTeamMarketExecution:
    if plan.offers and not negotiations:
        negotiations = tuple(
            build_three_team_contract_negotiation_tree(
                offer,
                management,
                _contract_conditions(offer, management),
            )
            for offer in plan.offers
        )
    trees = {tree.trade_id: tree for tree in negotiations}
    if set(trees) != {offer.trade_id for offer in plan.offers} and (plan.offers or negotiations):
        raise ValueError("three-team market negotiations must exactly cover the plan")
    final_management = management
    final_picks = picks
    final_cap_ledger = cap_ledger
    audits: list[ThreeTeamTradeAudit] = []
    accepted_node_ids: list[int] = []
    for offer in plan.offers:
        tree = trees[offer.trade_id]
        accepted = next((node for node in tree.nodes if node.status == "accepted"), None)
        if accepted is None:
            raise ValueError("three-team market negotiation has no accepted terms")
        result = execute_three_team_contract_negotiation(
            tree,
            accepted.node_id,
            final_management,
            final_picks,
            offer,
            contract_rules,
            trade_rules,
            cap_ledger=final_cap_ledger,
            cap_rules=cap_rules,
            frozen_pick_ids=frozen_pick_ids,
        )
        accepted_node_ids.append(accepted.node_id)
        audits.append(audit_three_team_trade(result))
        final_management = result.final_management
        final_picks = result.final_picks
        final_cap_ledger = result.final_cap_ledger
    return ThreeTeamMarketExecution(
        plan,
        management,
        picks,
        final_management,
        final_picks,
        tuple(audits),
        negotiations,
        tuple(accepted_node_ids),
        cap_ledger,
        final_cap_ledger,
    )


def _contract_conditions(
    offer: ThreeTeamTradeOffer,
    management: LeagueManagementState,
) -> tuple[ThreeTeamContractCondition, ...]:
    contracts = {contract.player_id: contract for contract in management.contracts}
    conditions: list[ThreeTeamContractCondition] = []
    for route in offer.player_routes:
        contract = contracts[route.player_id]
        conditions.extend(
            (
                ThreeTeamContractCondition(
                    len(conditions) + 1,
                    route.player_id,
                    route.to_team_id,
                    ContractConditionKind.MAXIMUM_ANNUAL_SALARY,
                    contract.annual_salary,
                ),
                ThreeTeamContractCondition(
                    len(conditions) + 2,
                    route.player_id,
                    route.to_team_id,
                    ContractConditionKind.MINIMUM_YEARS_REMAINING,
                    contract.years_remaining,
                ),
            )
        )
    return tuple(conditions)


def three_team_shadow_gain(shadow: ThreeTeamTradeShadowResult) -> float:
    return sum(approval.rational_gain or 0.0 for approval in shadow.approvals)


def _cyclic_routes(
    trio: tuple[str, str, str],
    rosters: Mapping[str, tuple[int, ...]],
) -> Iterator[tuple[PlayerTradeRoute, ...]]:
    first, second, third = trio
    for first_player, second_player, third_player in product(
        rosters[first],
        rosters[second],
        rosters[third],
    ):
        clockwise = (
            PlayerTradeRoute(first_player, first, second),
            PlayerTradeRoute(second_player, second, third),
            PlayerTradeRoute(third_player, third, first),
        )
        counterclockwise = (
            PlayerTradeRoute(first_player, first, third),
            PlayerTradeRoute(second_player, second, first),
            PlayerTradeRoute(third_player, third, second),
        )
        yield tuple(sorted(clockwise, key=_player_route_key))
        yield tuple(sorted(counterclockwise, key=_player_route_key))


def _hub_routes(
    trio: tuple[str, str, str],
    rosters: Mapping[str, tuple[int, ...]],
    salaries: Mapping[int, int],
    candidate_limit: int,
    salary_aware: bool,
) -> Iterator[tuple[PlayerTradeRoute, ...]]:
    per_hub_limit = max(1, (candidate_limit + len(trio) - 1) // len(trio))
    candidates_by_hub = []
    for hub in trio:
        candidates = _hub_routes_for_team(trio, hub, rosters)
        if salary_aware:
            ordered = nsmallest(
                per_hub_limit,
                candidates,
                key=lambda routes: (
                    _salary_imbalance(routes, salaries),
                    tuple(_player_route_key(route) for route in routes),
                ),
            )
        else:
            ordered = list(_take(candidates, per_hub_limit))
        candidates_by_hub.append(iter(ordered))
    iterators = tuple(candidates_by_hub)
    active = list(iterators)
    while active:
        remaining: list[Iterator[tuple[PlayerTradeRoute, ...]]] = []
        for candidates in active:
            try:
                yield next(candidates)
                remaining.append(candidates)
            except StopIteration:
                pass
        active = remaining


def _take(
    candidates: Iterator[tuple[PlayerTradeRoute, ...]],
    limit: int,
) -> Iterator[tuple[PlayerTradeRoute, ...]]:
    for index, candidate in enumerate(candidates):
        if index >= limit:
            break
        yield candidate


def _hub_routes_for_team(
    trio: tuple[str, str, str],
    hub: str,
    rosters: Mapping[str, tuple[int, ...]],
) -> Iterator[tuple[PlayerTradeRoute, ...]]:
    first_spoke, second_spoke = tuple(team_id for team_id in trio if team_id != hub)
    for hub_players in permutations(rosters[hub], 2):
        for first_player, second_player in product(
            rosters[first_spoke],
            rosters[second_spoke],
        ):
            routes = (
                PlayerTradeRoute(hub_players[0], hub, first_spoke),
                PlayerTradeRoute(hub_players[1], hub, second_spoke),
                PlayerTradeRoute(first_player, first_spoke, hub),
                PlayerTradeRoute(second_player, second_spoke, hub),
            )
            yield tuple(sorted(routes, key=_player_route_key))


def _compensation_offer(
    trade_id: int,
    parent: ThreeTeamTradeShadowResult,
    picks: tuple[TradableDraftPick, ...],
    pick_count: int,
) -> ThreeTeamTradeOffer | None:
    ordered = sorted(
        parent.approvals,
        key=lambda approval: (
            approval.rational_gain is None,
            approval.rational_gain or 0.0,
            approval.team_id,
        ),
    )
    recipient = ordered[0]
    donor = max(
        parent.approvals,
        key=lambda approval: (
            approval.rational_gain or 0.0,
            approval.team_id,
        ),
    )
    if recipient.team_id == donor.team_id:
        return None
    available = sorted(
        (
            pick
            for pick in picks
            if pick.owner_team_id == donor.team_id
            and pick.selection_number not in {route.pick_id for route in parent.offer.pick_routes}
        ),
        key=lambda pick: (
            -getattr(pick, "round_number", 1),
            -getattr(pick, "draft_year", 0),
            pick.selection_number,
        ),
    )
    if len(available) < pick_count:
        return None
    routes = tuple(
        PickTradeRoute(
            pick.selection_number,
            donor.team_id,
            recipient.team_id,
        )
        for pick in available[:pick_count]
    )
    return ThreeTeamTradeOffer(
        trade_id,
        parent.offer.team_ids,
        parent.offer.player_routes,
        tuple(
            sorted(
                (*parent.offer.pick_routes, *routes),
                key=lambda item: (
                    item.from_team_id,
                    item.to_team_id,
                    item.pick_id,
                ),
            )
        ),
    )


def _append_ledger(
    records: list[ManagerDecisionRecord],
    shadow: ThreeTeamTradeShadowResult,
) -> None:
    for record in shadow.ledger.records:
        records.append(replace(record, sequence=len(records) + 1))


def _player_route_key(route: PlayerTradeRoute) -> tuple[str, str, int]:
    return route.from_team_id, route.to_team_id, route.player_id


def _salary_imbalance(
    routes: Sequence[PlayerTradeRoute],
    salaries: Mapping[int, int],
) -> int:
    deltas: dict[str, int] = {}
    for route in routes:
        salary = salaries[route.player_id]
        deltas[route.from_team_id] = deltas.get(route.from_team_id, 0) - salary
        deltas[route.to_team_id] = deltas.get(route.to_team_id, 0) + salary
    return sum(abs(delta) for delta in deltas.values())


def _offer_signature(offer: ThreeTeamTradeOffer) -> tuple[object, ...]:
    return (
        offer.team_ids,
        tuple(_player_route_key(route) for route in offer.player_routes),
        tuple((route.from_team_id, route.to_team_id, route.pick_id) for route in offer.pick_routes),
        offer.trade_id,
    )
