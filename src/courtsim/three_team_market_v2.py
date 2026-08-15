"""Contract-condition negotiation trees for the three-team market v2."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from courtsim.cap_mechanics import CapLedger, CapMechanicsRules
from courtsim.draft_assets import TradableDraftPick
from courtsim.management import ContractRules, LeagueManagementState, PlayerContract
from courtsim.three_team_trades import (
    ThreeTeamTradeOffer,
    ThreeTeamTradeResult,
    apply_three_team_trade,
)
from courtsim.trades import DEFAULT_TRADE_RULES, TradeRules

THREE_TEAM_MARKET_V2_VERSION = "three-team-market-v2"


class ContractConditionKind(IntEnum):
    MAXIMUM_ANNUAL_SALARY = 0
    MINIMUM_YEARS_REMAINING = 1
    MAXIMUM_YEARS_REMAINING = 2


@dataclass(frozen=True, slots=True)
class ThreeTeamContractCondition:
    condition_id: int
    player_id: int
    beneficiary_team_id: str
    kind: ContractConditionKind
    threshold: int

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1
            for value in (self.condition_id, self.player_id, self.threshold)
        ):
            raise ValueError("three-team contract condition values must be positive integers")
        if not self.beneficiary_team_id.strip():
            raise ValueError("contract condition beneficiary must not be blank")
        if not isinstance(self.kind, ContractConditionKind):
            raise ValueError("unsupported contract condition kind")


@dataclass(frozen=True, slots=True)
class ThreeTeamContractNegotiationNode:
    node_id: int
    parent_node_id: int | None
    round_number: int
    condition_ids: tuple[int, ...]
    status: str
    rejections: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.node_id, int)
            or isinstance(self.node_id, bool)
            or self.node_id < 1
            or not isinstance(self.round_number, int)
            or isinstance(self.round_number, bool)
            or self.round_number < 0
        ):
            raise ValueError("contract negotiation node identity is invalid")
        if self.parent_node_id is not None and self.parent_node_id >= self.node_id:
            raise ValueError("contract negotiation parent must precede child")
        if self.condition_ids != tuple(sorted(set(self.condition_ids))):
            raise ValueError("contract negotiation condition ids must be canonical")
        if self.status not in {"accepted", "countered", "rejected"}:
            raise ValueError("contract negotiation node status is invalid")
        if (self.status == "accepted") != (not self.rejections):
            raise ValueError("accepted contract node must have no rejections")


@dataclass(frozen=True, slots=True)
class ThreeTeamContractNegotiationTree:
    trade_id: int
    team_ids: tuple[str, str, str]
    offer_signature: tuple[tuple[int, str, str], ...]
    conditions: tuple[ThreeTeamContractCondition, ...]
    nodes: tuple[ThreeTeamContractNegotiationNode, ...]
    maximum_rounds: int = 4
    version: str = THREE_TEAM_MARKET_V2_VERSION

    def __post_init__(self) -> None:
        if self.version != THREE_TEAM_MARKET_V2_VERSION or not 1 <= self.maximum_rounds <= 8:
            raise ValueError("three-team contract negotiation version or rounds differ")
        condition_ids = tuple(item.condition_id for item in self.conditions)
        if condition_ids != tuple(sorted(set(condition_ids))):
            raise ValueError("three-team contract conditions must be ordered and unique")
        node_ids = tuple(item.node_id for item in self.nodes)
        if node_ids != tuple(range(1, len(self.nodes) + 1)) or not self.nodes:
            raise ValueError("contract negotiation nodes must be contiguous")
        if self.nodes[0].parent_node_id is not None or self.nodes[0].round_number != 0:
            raise ValueError("contract negotiation root is invalid")
        known_nodes = set(node_ids)
        if any(
            item.parent_node_id is not None and item.parent_node_id not in known_nodes
            for item in self.nodes
        ):
            raise ValueError("contract negotiation node references unknown parent")


def build_three_team_contract_negotiation_tree(
    offer: ThreeTeamTradeOffer,
    management: LeagueManagementState,
    conditions: tuple[ThreeTeamContractCondition, ...],
    *,
    maximum_rounds: int = 4,
) -> ThreeTeamContractNegotiationTree:
    """Build a bounded white-box tree by relaxing one failed condition per branch."""
    if (
        not isinstance(maximum_rounds, int)
        or isinstance(maximum_rounds, bool)
        or not 1 <= maximum_rounds <= 8
    ):
        raise ValueError("contract negotiation maximum_rounds must be from one through eight")
    if conditions != tuple(sorted(conditions, key=lambda item: item.condition_id)):
        raise ValueError("contract negotiation conditions must be ordered")
    condition_ids = tuple(item.condition_id for item in conditions)
    if len(condition_ids) != len(set(condition_ids)):
        raise ValueError("contract negotiation condition ids must be unique")
    if len(conditions) > 8:
        raise ValueError("contract negotiation supports at most eight conditions")
    destinations = {route.player_id: route.to_team_id for route in offer.player_routes}
    contracts = {item.player_id: item for item in management.contracts}
    for condition in conditions:
        if destinations.get(condition.player_id) != condition.beneficiary_team_id:
            raise ValueError("contract condition must benefit the routed player's destination")
        if condition.player_id not in contracts:
            raise ValueError("contract condition references a missing player contract")
    by_id = {item.condition_id: item for item in conditions}
    nodes: list[ThreeTeamContractNegotiationNode] = []
    queue: list[tuple[int | None, int, tuple[int, ...]]] = [(None, 0, condition_ids)]
    while queue:
        parent_id, round_number, active_ids = queue.pop(0)
        rejections = tuple(
            rejection
            for condition_id in active_ids
            for rejection in _condition_rejections(
                by_id[condition_id], contracts[by_id[condition_id].player_id]
            )
        )
        status = (
            "accepted"
            if not rejections
            else "rejected"
            if round_number == maximum_rounds
            else "countered"
        )
        node = ThreeTeamContractNegotiationNode(
            len(nodes) + 1,
            parent_id,
            round_number,
            active_ids,
            status,
            rejections,
        )
        nodes.append(node)
        if status != "countered":
            continue
        failed_ids = {int(rejection.split(":", 2)[1]) for rejection in rejections}
        for failed_id in sorted(failed_ids):
            queue.append(
                (
                    node.node_id,
                    round_number + 1,
                    tuple(item for item in active_ids if item != failed_id),
                )
            )
    return ThreeTeamContractNegotiationTree(
        offer.trade_id,
        offer.team_ids,
        tuple(
            (route.player_id, route.from_team_id, route.to_team_id) for route in offer.player_routes
        ),
        conditions,
        tuple(nodes),
        maximum_rounds,
    )


def execute_three_team_contract_negotiation(
    tree: ThreeTeamContractNegotiationTree,
    accepted_node_id: int,
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
    """Revalidate accepted terms and the native atomic trade immediately before execution."""
    if (
        offer.trade_id != tree.trade_id
        or offer.team_ids != tree.team_ids
        or tuple(
            (route.player_id, route.from_team_id, route.to_team_id) for route in offer.player_routes
        )
        != tree.offer_signature
    ):
        raise ValueError("contract negotiation tree differs from offer")
    node = next((item for item in tree.nodes if item.node_id == accepted_node_id), None)
    if node is None or node.status != "accepted":
        raise ValueError("contract negotiation execution requires an accepted node")
    contracts = {item.player_id: item for item in management.contracts}
    by_id = {item.condition_id: item for item in tree.conditions}
    if any(
        _condition_rejections(by_id[condition_id], contracts[by_id[condition_id].player_id])
        for condition_id in node.condition_ids
    ):
        raise ValueError("accepted contract conditions no longer match current contracts")
    return apply_three_team_trade(
        management,
        picks,
        offer,
        contract_rules,
        trade_rules,
        cap_ledger=cap_ledger,
        cap_rules=cap_rules,
        frozen_pick_ids=frozen_pick_ids,
    )


def inspect_three_team_contract_negotiation(
    tree: ThreeTeamContractNegotiationTree,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "version": tree.version,
        "trade_id": tree.trade_id,
        "teams": list(tree.team_ids),
        "conditions": len(tree.conditions),
        "nodes": len(tree.nodes),
        "accepted_nodes": [item.node_id for item in tree.nodes if item.status == "accepted"],
        "rejected_nodes": [item.node_id for item in tree.nodes if item.status == "rejected"],
        "maximum_rounds": tree.maximum_rounds,
        "tree_complete": all(
            item.status != "countered"
            or any(child.parent_node_id == item.node_id for child in tree.nodes)
            for item in tree.nodes
        ),
    }


def _condition_rejections(
    condition: ThreeTeamContractCondition,
    contract: PlayerContract,
) -> tuple[str, ...]:
    actual = (
        contract.annual_salary
        if condition.kind is ContractConditionKind.MAXIMUM_ANNUAL_SALARY
        else contract.years_remaining
    )
    passed = (
        actual <= condition.threshold
        if condition.kind
        in {
            ContractConditionKind.MAXIMUM_ANNUAL_SALARY,
            ContractConditionKind.MAXIMUM_YEARS_REMAINING,
        }
        else actual >= condition.threshold
    )
    return () if passed else (f"condition:{condition.condition_id}:{condition.kind.name}",)
