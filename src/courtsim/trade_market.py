"""Deterministic offer generation, counteroffers, and conflict-free trade clearing."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import combinations

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
    TradeShadowResult,
    evaluate_trade_shadow,
)
from courtsim.trades import (
    DEFAULT_TRADE_RULES,
    TRADE_VERSION,
    TradeAudit,
    TradeOffer,
    TradeRules,
    apply_trade,
    audit_trade,
)

TRADE_MARKET_VERSION = "trade-market-v1"


@dataclass(frozen=True, slots=True)
class TradeMarketRules:
    maximum_candidates_per_pair: int = 96
    maximum_trades_per_team: int = 1
    minimum_combined_rational_gain: float = 0.001
    generate_pick_counteroffers: bool = True
    generate_player_for_pick_offers: bool = True
    generate_two_for_one_offers: bool = True
    maximum_negotiation_rounds: int = 3
    maximum_round_three_candidates: int = 32
    generate_round_three_counteroffers: bool = True
    version: str = TRADE_MARKET_VERSION

    def __post_init__(self) -> None:
        values = (
            self.maximum_candidates_per_pair,
            self.maximum_trades_per_team,
            self.maximum_negotiation_rounds,
            self.maximum_round_three_candidates,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in values
        ):
            raise ValueError("trade market limits must be positive integers")
        if self.maximum_trades_per_team != 1:
            raise ValueError("trade-market-v1 permits one cleared trade per team")
        if self.maximum_negotiation_rounds != 3:
            raise ValueError("trade-market-v1 supports exactly three negotiation rounds")
        if self.minimum_combined_rational_gain <= 0:
            raise ValueError("minimum combined rational gain must be positive")
        if self.version != TRADE_MARKET_VERSION:
            raise ValueError(f"unsupported trade market version: {self.version}")


DEFAULT_TRADE_MARKET_RULES = TradeMarketRules()


@dataclass(frozen=True, slots=True)
class TradeMarketEvaluation:
    kind: str
    parent_trade_id: int | None
    negotiation_id: int
    round_number: int
    shadow: TradeShadowResult

    def __post_init__(self) -> None:
        if self.kind not in {
            "direct",
            "pick-counter",
            "player-for-pick",
            "multi-player",
            "round-three-counter",
        }:
            raise ValueError("unsupported trade market candidate kind")
        if self.kind == "direct" and self.parent_trade_id is not None:
            raise ValueError("a direct offer cannot reference a parent")
        if self.kind != "direct" and self.parent_trade_id is None:
            raise ValueError("a counteroffer must reference its parent")
        if self.negotiation_id < 1 or not 1 <= self.round_number <= 3:
            raise ValueError("trade negotiation identity or round is invalid")
        if self.kind == "direct" and (
            self.negotiation_id != self.shadow.offer.trade_id or self.round_number != 1
        ):
            raise ValueError("direct offers must open their negotiation")
        if self.kind != "direct" and self.round_number == 1:
            raise ValueError("counteroffers cannot use negotiation round one")


@dataclass(frozen=True, slots=True)
class TradeNegotiation:
    negotiation_id: int
    team_a_id: str
    team_b_id: str
    offer_ids: tuple[int, ...]
    rounds_completed: int
    accepted_trade_id: int | None
    terminal_reason: str

    def __post_init__(self) -> None:
        if self.negotiation_id < 1 or not self.team_a_id.strip() or not self.team_b_id.strip():
            raise ValueError("trade negotiation identity is invalid")
        if not self.offer_ids or self.offer_ids != tuple(sorted(set(self.offer_ids))):
            raise ValueError("trade negotiation offers must be ordered and unique")
        if not 1 <= self.rounds_completed <= 3:
            raise ValueError("trade negotiation rounds are invalid")
        if self.accepted_trade_id is not None and self.accepted_trade_id not in self.offer_ids:
            raise ValueError("accepted trade must belong to its negotiation")
        if self.terminal_reason not in {"accepted", "round-limit", "no-counter"}:
            raise ValueError("unsupported trade negotiation terminal reason")
        if (self.terminal_reason == "accepted") != (self.accepted_trade_id is not None):
            raise ValueError("accepted negotiation terminal state is inconsistent")


@dataclass(frozen=True, slots=True)
class TradeMarketPlan:
    offers: tuple[TradeOffer, ...]
    version: str = TRADE_MARKET_VERSION

    def __post_init__(self) -> None:
        if self.version != TRADE_MARKET_VERSION:
            raise ValueError("unsupported trade market plan version")
        ids = tuple(offer.trade_id for offer in self.offers)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("trade market plan offer ids must be ordered and unique")
        teams = [team_id for offer in self.offers for team_id in (offer.team_a_id, offer.team_b_id)]
        if len(teams) != len(set(teams)):
            raise ValueError("trade market plan cannot reuse a participating team")


@dataclass(frozen=True, slots=True)
class TradeMarketShadowResult:
    plan: TradeMarketPlan
    evaluations: tuple[TradeMarketEvaluation, ...]
    ledger: ManagerDecisionLedger
    negotiations: tuple[TradeNegotiation, ...] = ()
    mode: ManagerPolicyMode = ManagerPolicyMode.SHADOW
    version: str = TRADE_MARKET_VERSION


@dataclass(frozen=True, slots=True)
class TradeMarketExecution:
    plan: TradeMarketPlan
    initial_management: LeagueManagementState
    initial_picks: tuple[TradableDraftPick, ...]
    final_management: LeagueManagementState
    final_picks: tuple[TradableDraftPick, ...]
    audits: tuple[TradeAudit, ...]
    initial_cap_ledger: CapLedger | None = None
    final_cap_ledger: CapLedger | None = None
    trade_version: str = TRADE_VERSION
    version: str = TRADE_MARKET_VERSION


@dataclass(frozen=True, slots=True)
class _RawOffer:
    team_a_id: str
    team_b_id: str
    players_from_a: tuple[int, ...]
    players_from_b: tuple[int, ...]
    picks_from_a: tuple[int, ...]
    picks_from_b: tuple[int, ...]
    kind: str
    parent_index: int | None


def generate_trade_market_shadow(
    *,
    management: LeagueManagementState,
    players: Sequence[CareerPlayer],
    picks: tuple[TradableDraftPick, ...],
    profiles: Mapping[str, ManagerProfile],
    contract_rules: ContractRules,
    trade_rules: TradeRules = DEFAULT_TRADE_RULES,
    manager_rules: ManagerTradeRules = DEFAULT_MANAGER_TRADE_RULES,
    market_rules: TradeMarketRules = DEFAULT_TRADE_MARKET_RULES,
    cap_ledger: CapLedger | None = None,
    cap_rules: CapMechanicsRules | None = None,
) -> TradeMarketShadowResult:
    """Generate and independently approve a bounded, deterministic offer market."""
    team_ids = tuple(roster.team_id for roster in management.rosters)
    if set(profiles) != set(team_ids):
        raise ValueError("trade market profiles must cover every team exactly")
    if any(team_id != profile.team_id for team_id, profile in profiles.items()):
        raise ValueError("trade market profile keys must match profile team ids")
    raw_offers = _candidate_offers(management, picks, market_rules)
    evaluations: list[TradeMarketEvaluation] = []
    ledger_records: list[ManagerDecisionRecord] = []
    direct_ids: dict[int, int] = {}
    for index, raw in enumerate(raw_offers, start=1):
        offer = TradeOffer(
            index,
            raw.team_a_id,
            raw.team_b_id,
            raw.players_from_a,
            raw.players_from_b,
            raw.picks_from_a,
            raw.picks_from_b,
        )
        if raw.kind == "direct":
            direct_ids[index - 1] = index
        parent_trade_id = direct_ids[raw.parent_index] if raw.parent_index is not None else None
        shadow = evaluate_trade_shadow(
            management=management,
            players=players,
            picks=picks,
            offer=offer,
            profiles={
                offer.team_a_id: profiles[offer.team_a_id],
                offer.team_b_id: profiles[offer.team_b_id],
            },
            contract_rules=contract_rules,
            trade_rules=trade_rules,
            manager_rules=manager_rules,
            cap_ledger=cap_ledger,
            cap_rules=cap_rules,
        )
        negotiation_id = offer.trade_id if parent_trade_id is None else parent_trade_id
        evaluations.append(
            TradeMarketEvaluation(
                raw.kind,
                parent_trade_id,
                negotiation_id,
                1 if raw.kind == "direct" else 2,
                shadow,
            )
        )
        for record in shadow.ledger.records:
            ledger_records.append(replace(record, sequence=len(ledger_records) + 1))

    next_trade_id = len(evaluations) + 1
    for parent, offer in _round_three_counteroffers(
        tuple(evaluations),
        picks,
        start_trade_id=next_trade_id,
        rules=market_rules,
    ):
        shadow = evaluate_trade_shadow(
            management=management,
            players=players,
            picks=picks,
            offer=offer,
            profiles={
                offer.team_a_id: profiles[offer.team_a_id],
                offer.team_b_id: profiles[offer.team_b_id],
            },
            contract_rules=contract_rules,
            trade_rules=trade_rules,
            manager_rules=manager_rules,
            cap_ledger=cap_ledger,
            cap_rules=cap_rules,
        )
        evaluations.append(
            TradeMarketEvaluation(
                "round-three-counter",
                parent.shadow.offer.trade_id,
                parent.negotiation_id,
                3,
                shadow,
            )
        )
        for record in shadow.ledger.records:
            ledger_records.append(replace(record, sequence=len(ledger_records) + 1))

    approved = [
        evaluation
        for evaluation in evaluations
        if evaluation.shadow.approved
        and _combined_gain(evaluation.shadow) >= market_rules.minimum_combined_rational_gain
    ]
    approved.sort(
        key=lambda evaluation: (
            -_combined_gain(evaluation.shadow),
            _offer_signature(evaluation.shadow.offer),
        )
    )
    selected: list[TradeOffer] = []
    locked_teams: set[str] = set()
    locked_players: set[int] = set()
    locked_picks: set[int] = set()
    for evaluation in approved:
        offer = evaluation.shadow.offer
        teams = {offer.team_a_id, offer.team_b_id}
        player_ids = set((*offer.players_from_a, *offer.players_from_b))
        pick_ids = set((*offer.picks_from_a, *offer.picks_from_b))
        if teams & locked_teams or player_ids & locked_players or pick_ids & locked_picks:
            continue
        selected.append(offer)
        locked_teams.update(teams)
        locked_players.update(player_ids)
        locked_picks.update(pick_ids)
    selected.sort(key=lambda offer: offer.trade_id)
    return TradeMarketShadowResult(
        TradeMarketPlan(tuple(selected)),
        tuple(evaluations),
        ManagerDecisionLedger(tuple(ledger_records)),
        _negotiation_summaries(tuple(evaluations), market_rules),
    )


def apply_trade_market_plan(
    management: LeagueManagementState,
    picks: tuple[TradableDraftPick, ...],
    plan: TradeMarketPlan,
    contract_rules: ContractRules,
    trade_rules: TradeRules = DEFAULT_TRADE_RULES,
    *,
    cap_ledger: CapLedger | None = None,
    cap_rules: CapMechanicsRules | None = None,
    exception_ids: Mapping[int, Mapping[str, int]] | None = None,
) -> TradeMarketExecution:
    """Replay a conflict-free approved plan through the canonical trade engine."""
    final_management = management
    final_picks = picks
    final_cap_ledger = cap_ledger
    audits: list[TradeAudit] = []
    for offer in plan.offers:
        result = apply_trade(
            final_management,
            final_picks,
            offer,
            contract_rules,
            trade_rules,
            cap_ledger=final_cap_ledger,
            cap_rules=cap_rules,
            exception_ids=(exception_ids or {}).get(offer.trade_id),
        )
        audits.append(audit_trade(result))
        final_management = result.final_management
        final_picks = result.final_picks
        final_cap_ledger = result.final_cap_ledger
    return TradeMarketExecution(
        plan,
        management,
        picks,
        final_management,
        final_picks,
        tuple(audits),
        cap_ledger,
        final_cap_ledger,
    )


def _candidate_offers(
    management: LeagueManagementState,
    picks: tuple[TradableDraftPick, ...],
    rules: TradeMarketRules,
) -> tuple[_RawOffer, ...]:
    rosters = {roster.team_id: roster.player_ids for roster in management.rosters}
    picks_by_team: dict[str, list[int]] = {team_id: [] for team_id in rosters}
    for pick in picks:
        if pick.owner_team_id in picks_by_team:
            picks_by_team[pick.owner_team_id].append(pick.selection_number)
    result: list[_RawOffer] = []
    team_ids = tuple(sorted(rosters))
    for first_index, team_a_id in enumerate(team_ids):
        for team_b_id in team_ids[first_index + 1 :]:
            pair: list[_RawOffer] = []
            direct_indices: dict[tuple[int, int], int] = {}
            for player_a in rosters[team_a_id]:
                for player_b in rosters[team_b_id]:
                    direct_index = len(result) + len(pair)
                    direct_indices[(player_a, player_b)] = direct_index
                    pair.append(
                        _RawOffer(
                            team_a_id,
                            team_b_id,
                            (player_a,),
                            (player_b,),
                            (),
                            (),
                            "direct",
                            None,
                        )
                    )
            if rules.generate_two_for_one_offers:
                for first_a, second_a in combinations(rosters[team_a_id], 2):
                    for player_b in rosters[team_b_id]:
                        pair.append(
                            _RawOffer(
                                team_a_id,
                                team_b_id,
                                (first_a, second_a),
                                (player_b,),
                                (),
                                (),
                                "multi-player",
                                direct_indices[(first_a, player_b)],
                            )
                        )
                for player_a in rosters[team_a_id]:
                    for first_b, second_b in combinations(rosters[team_b_id], 2):
                        pair.append(
                            _RawOffer(
                                team_a_id,
                                team_b_id,
                                (player_a,),
                                (first_b, second_b),
                                (),
                                (),
                                "multi-player",
                                direct_indices[(player_a, first_b)],
                            )
                        )
            if rules.generate_pick_counteroffers:
                for player_a in rosters[team_a_id]:
                    for player_b in rosters[team_b_id]:
                        direct_index = direct_indices[(player_a, player_b)]
                        pair.extend(
                            _RawOffer(
                                team_a_id,
                                team_b_id,
                                (player_a,),
                                (player_b,),
                                (pick_id,),
                                (),
                                "pick-counter",
                                direct_index,
                            )
                            for pick_id in picks_by_team[team_a_id]
                        )
                        pair.extend(
                            _RawOffer(
                                team_a_id,
                                team_b_id,
                                (player_a,),
                                (player_b,),
                                (),
                                (pick_id,),
                                "pick-counter",
                                direct_index,
                            )
                            for pick_id in picks_by_team[team_b_id]
                        )
            if rules.generate_player_for_pick_offers:
                for player_a in rosters[team_a_id]:
                    pair.extend(
                        _RawOffer(
                            team_a_id,
                            team_b_id,
                            (player_a,),
                            (),
                            (),
                            (pick_id,),
                            "player-for-pick",
                            _nearest_direct_index(result, pair),
                        )
                        for pick_id in picks_by_team[team_b_id]
                    )
                for player_b in rosters[team_b_id]:
                    pair.extend(
                        _RawOffer(
                            team_a_id,
                            team_b_id,
                            (),
                            (player_b,),
                            (pick_id,),
                            (),
                            "player-for-pick",
                            _nearest_direct_index(result, pair),
                        )
                        for pick_id in picks_by_team[team_a_id]
                    )
            result.extend(
                _bounded_candidate_mix(
                    pair,
                    rules.maximum_candidates_per_pair,
                )
            )
    return tuple(result)


def _bounded_candidate_mix(
    candidates: list[_RawOffer],
    limit: int,
) -> list[_RawOffer]:
    direct = [candidate for candidate in candidates if candidate.kind == "direct"]
    selected = direct[:limit]
    if len(selected) == limit or len(selected) != len(direct):
        return selected
    queues = [
        [candidate for candidate in candidates if candidate.kind == kind]
        for kind in ("multi-player", "pick-counter", "player-for-pick")
    ]
    indexes = [0] * len(queues)
    while len(selected) < limit:
        progressed = False
        for queue_index, queue in enumerate(queues):
            if indexes[queue_index] >= len(queue):
                continue
            selected.append(queue[indexes[queue_index]])
            indexes[queue_index] += 1
            progressed = True
            if len(selected) == limit:
                break
        if not progressed:
            break
    return selected


def _nearest_direct_index(existing: list[_RawOffer], pair: list[_RawOffer]) -> int:
    for offset in range(len(pair) - 1, -1, -1):
        if pair[offset].kind == "direct":
            return len(existing) + offset
    raise ValueError("player-for-pick generation requires a direct parent")


def _round_three_counteroffers(
    evaluations: tuple[TradeMarketEvaluation, ...],
    picks: tuple[TradableDraftPick, ...],
    *,
    start_trade_id: int,
    rules: TradeMarketRules,
) -> tuple[tuple[TradeMarketEvaluation, TradeOffer], ...]:
    if not rules.generate_round_three_counteroffers:
        return ()
    accepted_negotiations = {
        evaluation.negotiation_id for evaluation in evaluations if evaluation.shadow.approved
    }
    picks_by_team: dict[str, tuple[int, ...]] = {}
    for team_id in sorted({pick.owner_team_id for pick in picks}):
        picks_by_team[team_id] = tuple(
            sorted(pick.selection_number for pick in picks if pick.owner_team_id == team_id)
        )
    result: list[tuple[TradeMarketEvaluation, TradeOffer]] = []
    signatures: set[tuple[object, ...]] = set()
    next_trade_id = start_trade_id
    for evaluation in evaluations:
        if (
            evaluation.round_number != 2
            or not evaluation.shadow.legal
            or evaluation.negotiation_id in accepted_negotiations
        ):
            continue
        rejectors = tuple(
            approval.team_id for approval in evaluation.shadow.approvals if not approval.accepted
        )
        if len(rejectors) != 1:
            continue
        offer = evaluation.shadow.offer
        rejecting_team = rejectors[0]
        sender = offer.team_b_id if rejecting_team == offer.team_a_id else offer.team_a_id
        existing_picks = offer.picks_from_a if sender == offer.team_a_id else offer.picks_from_b
        for pick_id in picks_by_team.get(sender, ()):
            if pick_id in existing_picks:
                continue
            counter = replace(
                offer,
                trade_id=next_trade_id,
                picks_from_a=(
                    tuple(sorted((*offer.picks_from_a, pick_id)))
                    if sender == offer.team_a_id
                    else offer.picks_from_a
                ),
                picks_from_b=(
                    tuple(sorted((*offer.picks_from_b, pick_id)))
                    if sender == offer.team_b_id
                    else offer.picks_from_b
                ),
            )
            signature = _offer_signature(counter)[:-1]
            if signature in signatures:
                continue
            signatures.add(signature)
            result.append((evaluation, counter))
            next_trade_id += 1
            if len(result) == rules.maximum_round_three_candidates:
                return tuple(result)
    return tuple(result)


def _negotiation_summaries(
    evaluations: tuple[TradeMarketEvaluation, ...],
    rules: TradeMarketRules,
) -> tuple[TradeNegotiation, ...]:
    grouped: dict[int, list[TradeMarketEvaluation]] = {}
    for evaluation in evaluations:
        grouped.setdefault(evaluation.negotiation_id, []).append(evaluation)
    result: list[TradeNegotiation] = []
    for negotiation_id, candidates in sorted(grouped.items()):
        ordered = sorted(
            candidates,
            key=lambda item: (item.round_number, item.shadow.offer.trade_id),
        )
        accepted = next(
            (item.shadow.offer.trade_id for item in ordered if item.shadow.approved),
            None,
        )
        rounds_completed = max(item.round_number for item in ordered)
        terminal_reason = (
            "accepted"
            if accepted is not None
            else "round-limit"
            if rounds_completed == rules.maximum_negotiation_rounds
            else "no-counter"
        )
        opening = ordered[0].shadow.offer
        result.append(
            TradeNegotiation(
                negotiation_id,
                opening.team_a_id,
                opening.team_b_id,
                tuple(sorted(item.shadow.offer.trade_id for item in ordered)),
                rounds_completed,
                accepted,
                terminal_reason,
            )
        )
    return tuple(result)


def _combined_gain(shadow: TradeShadowResult) -> float:
    return sum(approval.rational_gain or 0.0 for approval in shadow.approvals)


def _offer_signature(offer: TradeOffer) -> tuple[object, ...]:
    return (
        offer.team_a_id,
        offer.team_b_id,
        offer.players_from_a,
        offer.players_from_b,
        offer.picks_from_a,
        offer.picks_from_b,
        offer.trade_id,
    )
