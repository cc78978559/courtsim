"""Automatic three-team discovery, pick compensation, and conflict-free clearing."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import combinations, product

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
from courtsim.three_team_trades import (
    THREE_TEAM_TRADE_VERSION,
    PickTradeRoute,
    PlayerTradeRoute,
    ThreeTeamTradeAudit,
    ThreeTeamTradeOffer,
    ThreeTeamTradeShadowResult,
    apply_three_team_trade,
    audit_three_team_trade,
    evaluate_three_team_trade_shadow,
)
from courtsim.trades import DEFAULT_TRADE_RULES, TradeRules

THREE_TEAM_MARKET_VERSION = "three-team-market-v1"


@dataclass(frozen=True, slots=True)
class ThreeTeamMarketRules:
    maximum_candidates_per_trio: int = 64
    minimum_combined_rational_gain: float = 0.001
    search_pick_compensation: bool = True
    version: str = THREE_TEAM_MARKET_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.maximum_candidates_per_trio, int)
            or isinstance(self.maximum_candidates_per_trio, bool)
            or self.maximum_candidates_per_trio < 1
        ):
            raise ValueError("three-team candidate limit must be a positive integer")
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

    def __post_init__(self) -> None:
        if self.kind not in {"cyclic", "pick-compensation"}:
            raise ValueError("unsupported three-team market candidate kind")
        if self.kind == "cyclic" and self.parent_trade_id is not None:
            raise ValueError("cyclic offer cannot reference a parent")
        if self.kind == "pick-compensation" and self.parent_trade_id is None:
            raise ValueError("pick compensation must reference its parent")


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
) -> ThreeTeamMarketShadowResult:
    team_ids = tuple(roster.team_id for roster in management.rosters)
    if set(profiles) != set(team_ids):
        raise ValueError("three-team market profiles must cover every league team")
    rosters = {roster.team_id: roster.player_ids for roster in management.rosters}
    evaluations: list[ThreeTeamMarketEvaluation] = []
    ledger_records: list[ManagerDecisionRecord] = []
    next_trade_id = 1
    for trio in combinations(tuple(sorted(team_ids)), 3):
        trio_evaluations = 0
        for routes in _cyclic_routes(trio, rosters):
            if trio_evaluations >= market_rules.maximum_candidates_per_trio:
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
            )
            evaluations.append(ThreeTeamMarketEvaluation("cyclic", None, shadow))
            _append_ledger(ledger_records, shadow)
            trio_evaluations += 1
            if (
                market_rules.search_pick_compensation
                and not shadow.approved
                and trio_evaluations < market_rules.maximum_candidates_per_trio
            ):
                compensation = _compensation_offer(
                    next_trade_id,
                    shadow,
                    picks,
                )
                if compensation is not None:
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
                    )
                    evaluations.append(
                        ThreeTeamMarketEvaluation(
                            "pick-compensation",
                            offer.trade_id,
                            counter,
                        )
                    )
                    _append_ledger(ledger_records, counter)
                    trio_evaluations += 1

    approved = [
        evaluation
        for evaluation in evaluations
        if evaluation.shadow.approved
        and three_team_shadow_gain(evaluation.shadow) >= market_rules.minimum_combined_rational_gain
    ]
    approved.sort(
        key=lambda evaluation: (
            -three_team_shadow_gain(evaluation.shadow),
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
    return ThreeTeamMarketShadowResult(
        ThreeTeamMarketPlan(tuple(selected)),
        tuple(evaluations),
        ManagerDecisionLedger(tuple(ledger_records)),
    )


def apply_three_team_market_plan(
    management: LeagueManagementState,
    picks: tuple[TradableDraftPick, ...],
    plan: ThreeTeamMarketPlan,
    contract_rules: ContractRules,
    trade_rules: TradeRules = DEFAULT_TRADE_RULES,
) -> ThreeTeamMarketExecution:
    final_management = management
    final_picks = picks
    audits: list[ThreeTeamTradeAudit] = []
    for offer in plan.offers:
        result = apply_three_team_trade(
            final_management,
            final_picks,
            offer,
            contract_rules,
            trade_rules,
        )
        audits.append(audit_three_team_trade(result))
        final_management = result.final_management
        final_picks = result.final_picks
    return ThreeTeamMarketExecution(
        plan,
        management,
        picks,
        final_management,
        final_picks,
        tuple(audits),
    )


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


def _compensation_offer(
    trade_id: int,
    parent: ThreeTeamTradeShadowResult,
    picks: tuple[TradableDraftPick, ...],
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
    if not available:
        return None
    route = PickTradeRoute(
        available[0].selection_number,
        donor.team_id,
        recipient.team_id,
    )
    return ThreeTeamTradeOffer(
        trade_id,
        parent.offer.team_ids,
        parent.offer.player_routes,
        tuple(
            sorted(
                (*parent.offer.pick_routes, route),
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


def _offer_signature(offer: ThreeTeamTradeOffer) -> tuple[object, ...]:
    return (
        offer.team_ids,
        tuple(_player_route_key(route) for route in offer.player_routes),
        tuple((route.from_team_id, route.to_team_id, route.pick_id) for route in offer.pick_routes),
        offer.trade_id,
    )
