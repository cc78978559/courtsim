"""Bilateral white-box manager approval for canonical basketball trades."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, fields
from typing import cast

from courtsim.career import CareerPlayer
from courtsim.domain.player import AbilityRatings, SizeClass
from courtsim.draft_assets import TradableDraftPick
from courtsim.management import ContractRules, LeagueManagementState
from courtsim.manager_ai import (
    DecisionContribution,
    ManagerCandidate,
    ManagerDecisionLedger,
    ManagerDecisionTrace,
    ManagerPolicyMode,
    ManagerProfile,
    evaluate_manager_decision,
)
from courtsim.trades import (
    DEFAULT_TRADE_RULES,
    TRADE_VERSION,
    TradeOffer,
    TradeRules,
    trade_rejections,
)

MANAGER_TRADE_VERSION = "manager-trade-v1"


@dataclass(frozen=True, slots=True)
class ManagerTradeRules:
    reasonable_band: float = 0.08
    style_contribution_limit: float = 0.04
    minimum_rational_gain: float = 0.0
    version: str = MANAGER_TRADE_VERSION

    def __post_init__(self) -> None:
        if (
            self.reasonable_band < 0
            or self.style_contribution_limit < 0
            or self.minimum_rational_gain < 0
        ):
            raise ValueError("manager trade decision bounds must be non-negative")
        if self.version != MANAGER_TRADE_VERSION:
            raise ValueError(f"unsupported manager trade version: {self.version}")


DEFAULT_MANAGER_TRADE_RULES = ManagerTradeRules()


@dataclass(frozen=True, slots=True)
class TradeManagerApproval:
    team_id: str
    manager_id: str
    accepted: bool
    rational_gain: float | None
    trace: ManagerDecisionTrace


@dataclass(frozen=True, slots=True)
class TradeShadowResult:
    offer: TradeOffer
    legal: bool
    approved: bool
    hard_rejections: tuple[str, ...]
    approvals: tuple[TradeManagerApproval, TradeManagerApproval]
    ledger: ManagerDecisionLedger
    mode: ManagerPolicyMode = ManagerPolicyMode.SHADOW
    trade_version: str = TRADE_VERSION
    version: str = MANAGER_TRADE_VERSION


def evaluate_trade_shadow(
    *,
    management: LeagueManagementState,
    players: Sequence[CareerPlayer],
    picks: tuple[TradableDraftPick, ...],
    offer: TradeOffer,
    profiles: Mapping[str, ManagerProfile],
    contract_rules: ContractRules,
    trade_rules: TradeRules = DEFAULT_TRADE_RULES,
    manager_rules: ManagerTradeRules = DEFAULT_MANAGER_TRADE_RULES,
) -> TradeShadowResult:
    """Evaluate both managers independently; this function never executes the trade."""
    if set(profiles) != {offer.team_a_id, offer.team_b_id}:
        raise ValueError("trade profiles must cover both participating teams exactly")
    if any(team_id != profile.team_id for team_id, profile in profiles.items()):
        raise ValueError("trade profile keys must match profile team ids")
    player_map = {player.player_id: player for player in players}
    if len(player_map) != len(players):
        raise ValueError("career player ids must be unique")
    rejected = trade_rejections(management, picks, offer, contract_rules, trade_rules)
    approvals: list[TradeManagerApproval] = []
    ledger = ManagerDecisionLedger()
    for (
        team_id,
        other_team_id,
        outgoing_players,
        incoming_players,
        outgoing_picks,
        incoming_picks,
    ) in (
        (
            offer.team_a_id,
            offer.team_b_id,
            offer.players_from_a,
            offer.players_from_b,
            offer.picks_from_a,
            offer.picks_from_b,
        ),
        (
            offer.team_b_id,
            offer.team_a_id,
            offer.players_from_b,
            offer.players_from_a,
            offer.picks_from_b,
            offer.picks_from_a,
        ),
    ):
        profile = profiles[team_id]
        approval = evaluate_trade_team_approval(
            management=management,
            player_map=player_map,
            picks=picks,
            team_id=team_id,
            profile=profile,
            outgoing_players=outgoing_players,
            incoming_players=incoming_players,
            outgoing_picks=outgoing_picks,
            incoming_picks=incoming_picks,
            hard_rejections=rejected,
            contract_rules=contract_rules,
            manager_rules=manager_rules,
            decision_id=f"trade:{offer.trade_id}:{team_id}:{other_team_id}",
        )
        approvals.append(approval)
        ledger = ledger.add(trace=approval.trace, stage="trade", profile=profile)
    pair = cast(
        tuple[TradeManagerApproval, TradeManagerApproval],
        tuple(approvals),
    )
    return TradeShadowResult(
        offer,
        not rejected,
        not rejected and all(approval.accepted for approval in pair),
        rejected,
        pair,
        ledger,
    )


def evaluate_trade_team_approval(
    *,
    management: LeagueManagementState,
    player_map: Mapping[int, CareerPlayer],
    picks: tuple[TradableDraftPick, ...],
    team_id: str,
    profile: ManagerProfile,
    outgoing_players: tuple[int, ...],
    incoming_players: tuple[int, ...],
    outgoing_picks: tuple[int, ...],
    incoming_picks: tuple[int, ...],
    hard_rejections: tuple[str, ...],
    contract_rules: ContractRules,
    decision_id: str,
    manager_rules: ManagerTradeRules = DEFAULT_MANAGER_TRADE_RULES,
) -> TradeManagerApproval:
    """Evaluate one team's accept/reject choice for any routed trade structure."""
    contributions = _trade_contributions(
        management,
        player_map,
        picks,
        team_id,
        outgoing_players,
        incoming_players,
        outgoing_picks,
        incoming_picks,
        profile,
        contract_rules,
    )
    style = _trade_style(
        player_map,
        outgoing_players,
        incoming_players,
        profile,
    )
    trace = evaluate_manager_decision(
        decision_id=decision_id,
        candidates=(
            ManagerCandidate(
                "accept",
                hard_rejections,
                contributions,
                style,
            ),
            ManagerCandidate(
                "reject",
                (),
                (
                    DecisionContribution(
                        "status-quo",
                        "continuity",
                        "competence",
                        0.0,
                        "retain current assets and contracts",
                    ),
                ),
            ),
        ),
        reasonable_band=manager_rules.reasonable_band,
        style_contribution_limit=manager_rules.style_contribution_limit,
        incumbent="reject",
    )
    accept_candidate = next(
        candidate for candidate in trace.candidates if candidate.candidate_id == "accept"
    )
    rational_gain = accept_candidate.rational_score
    accepted = (
        trace.selected == "accept"
        and rational_gain is not None
        and rational_gain >= manager_rules.minimum_rational_gain
    )
    return TradeManagerApproval(
        team_id,
        profile.manager_id,
        accepted,
        rational_gain,
        trace,
    )


def _trade_contributions(
    management: LeagueManagementState,
    player_map: Mapping[int, CareerPlayer],
    picks: tuple[TradableDraftPick, ...],
    team_id: str,
    outgoing_players: tuple[int, ...],
    incoming_players: tuple[int, ...],
    outgoing_picks: tuple[int, ...],
    incoming_picks: tuple[int, ...],
    profile: ManagerProfile,
    contract_rules: ContractRules,
) -> tuple[DecisionContribution, ...]:
    roster = next(item.player_ids for item in management.rosters if item.team_id == team_id)
    contracts = {contract.player_id: contract for contract in management.contracts}
    for player_id in (*outgoing_players, *incoming_players):
        if player_id not in player_map:
            raise ValueError(f"trade player {player_id} has no career record")
    outgoing_player_value = sum(
        _player_value(
            player_map[player_id], contracts[player_id].annual_salary, profile, contract_rules
        )
        for player_id in outgoing_players
    )
    incoming_player_value = sum(
        _player_value(
            player_map[player_id], contracts[player_id].annual_salary, profile, contract_rules
        )
        for player_id in incoming_players
    )
    pick_map = {pick.selection_number: pick for pick in picks}
    outgoing_pick_value = sum(_pick_value(pick_map[number], profile) for number in outgoing_picks)
    incoming_pick_value = sum(_pick_value(pick_map[number], profile) for number in incoming_picks)
    before_balance = _roster_balance(roster, player_map)
    after_ids = tuple(sorted((set(roster) - set(outgoing_players)) | set(incoming_players)))
    after_balance = _roster_balance(after_ids, player_map)
    outgoing_salary = sum(contracts[player_id].annual_salary for player_id in outgoing_players)
    incoming_salary = sum(contracts[player_id].annual_salary for player_id in incoming_players)
    cap_flex = (
        (outgoing_salary - incoming_salary)
        / contract_rules.salary_cap
        * (0.04 + profile.cap_discipline / 100 * 0.08)
    )
    return (
        _contribution(
            "player-assets",
            "talent",
            incoming_player_value - outgoing_player_value,
            "manager-specific value of incoming versus outgoing players",
        ),
        _contribution(
            "draft-assets",
            "development",
            incoming_pick_value - outgoing_pick_value,
            "manager-specific value of incoming versus outgoing draft picks",
        ),
        _contribution(
            "roster-balance",
            "roster",
            (after_balance - before_balance) * 0.12,
            "change in size-class roster coverage",
        ),
        _contribution(
            "cap-flexibility",
            "economics",
            cap_flex,
            "change in salary-cap flexibility",
        ),
    )


def _player_value(
    player: CareerPlayer,
    salary: int,
    profile: ManagerProfile,
    contract_rules: ContractRules,
) -> float:
    ability = _rating_mean(player.profile.abilities) / 100
    potential = _rating_mean(player.potential) / 100
    upside = max(0.0, potential - ability)
    age_value = max(0.0, min(1.0, (34 - player.age) / 16))
    availability = 1 - player.injury_burden / 100
    current_weight = 0.42 + profile.win_now / 100 * 0.18
    future_weight = 0.10 + profile.development_bias / 100 * 0.13
    upside_weight = 0.06 + profile.risk_tolerance / 100 * 0.08
    salary_efficiency = max(0.0, ability - salary / contract_rules.salary_cap)
    return (
        ability * current_weight
        + potential * future_weight
        + upside * upside_weight
        + age_value * 0.04
        + availability * 0.05
        + salary_efficiency * profile.cap_discipline / 100 * 0.08
    )


def _pick_value(pick: TradableDraftPick, profile: ManagerProfile) -> float:
    base = 0.42 if pick.round_number == 1 else 0.15 / max(1, pick.round_number - 1)
    development = 0.75 + profile.development_bias / 100 * 0.35
    risk = 0.9 + profile.risk_tolerance / 100 * 0.2
    return base * development * risk


def _roster_balance(
    player_ids: Sequence[int],
    player_map: Mapping[int, CareerPlayer],
) -> float:
    counts = {size: 0 for size in SizeClass}
    for player_id in player_ids:
        player = player_map.get(player_id)
        if player is not None:
            counts[player.profile.size_class] += 1
    total = sum(counts.values())
    if total == 0:
        return 0.0
    represented = sum(count > 0 for count in counts.values()) / len(counts)
    concentration = max(counts.values()) / total
    return represented * 0.7 + (1 - concentration) * 0.3


def _trade_style(
    player_map: Mapping[int, CareerPlayer],
    outgoing_players: tuple[int, ...],
    incoming_players: tuple[int, ...],
    profile: ManagerProfile,
) -> tuple[DecisionContribution, ...]:
    outgoing_ability = sum(
        _rating_mean(player_map[item].profile.abilities) for item in outgoing_players
    )
    incoming_ability = sum(
        _rating_mean(player_map[item].profile.abilities) for item in incoming_players
    )
    star_change = (incoming_ability - outgoing_ability) / 100
    return (
        _contribution(
            "star-preference",
            "style",
            star_change * (profile.star_preference - 50) / 50 * 0.015,
            "manager preference for concentrated current talent",
            source="personality",
        ),
        _contribution(
            "continuity",
            "style",
            -len(outgoing_players) * (profile.continuity - 50) / 50 * 0.006,
            "manager preference for roster continuity",
            source="personality",
        ),
    )


def _rating_mean(ratings: AbilityRatings) -> float:
    values = tuple(cast(int, getattr(ratings, item.name)) for item in fields(AbilityRatings))
    return sum(values) / len(values)


def _contribution(
    contribution_id: str,
    group: str,
    value: float,
    reason: str,
    *,
    source: str = "competence",
) -> DecisionContribution:
    return DecisionContribution(contribution_id, group, source, round(value, 6), reason)
