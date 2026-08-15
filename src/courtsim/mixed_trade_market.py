"""Deterministic conflict clearing across bilateral and three-team markets."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite

from courtsim.three_team_market import (
    ThreeTeamMarketPlan,
    ThreeTeamMarketShadowResult,
    three_team_shadow_gain,
)
from courtsim.trade_market import TradeMarketPlan, TradeMarketShadowResult

MIXED_TRADE_CLEARING_VERSION = "mixed-trade-clearing-v1"


@dataclass(frozen=True, slots=True)
class MixedTradeCandidate:
    source: str
    trade_id: int
    team_ids: tuple[str, ...]
    player_ids: tuple[int, ...]
    pick_ids: tuple[int, ...]
    combined_gain: float

    def __post_init__(self) -> None:
        if self.source not in {"bilateral", "three-team"}:
            raise ValueError("mixed trade source is unsupported")
        if self.trade_id < 0 or not isfinite(self.combined_gain):
            raise ValueError("mixed trade identity or gain is invalid")
        if len(self.team_ids) != len(set(self.team_ids)):
            raise ValueError("mixed trade candidate repeats a team")
        if len(self.player_ids) != len(set(self.player_ids)):
            raise ValueError("mixed trade candidate repeats a player")
        if len(self.pick_ids) != len(set(self.pick_ids)):
            raise ValueError("mixed trade candidate repeats a pick")


@dataclass(frozen=True, slots=True)
class MixedTradeMarketClearing:
    bilateral_plan: TradeMarketPlan
    three_team_plan: ThreeTeamMarketPlan
    selections: tuple[MixedTradeCandidate, ...]
    version: str = MIXED_TRADE_CLEARING_VERSION

    @property
    def choice(self) -> str:
        bilateral = bool(self.bilateral_plan.offers)
        three_team = bool(self.three_team_plan.offers)
        if bilateral and three_team:
            return "mixed"
        if bilateral:
            return "bilateral"
        if three_team:
            return "three-team"
        return "none"


def select_mixed_trade_candidates(
    candidates: tuple[MixedTradeCandidate, ...],
) -> tuple[MixedTradeCandidate, ...]:
    """Greedily maximize approved gain while locking every touched identity."""
    selected: list[MixedTradeCandidate] = []
    locked_teams: set[str] = set()
    locked_players: set[int] = set()
    locked_picks: set[int] = set()
    for candidate in sorted(
        candidates,
        key=lambda item: (-item.combined_gain, item.source, item.trade_id),
    ):
        if (
            set(candidate.team_ids) & locked_teams
            or set(candidate.player_ids) & locked_players
            or set(candidate.pick_ids) & locked_picks
        ):
            continue
        selected.append(candidate)
        locked_teams.update(candidate.team_ids)
        locked_players.update(candidate.player_ids)
        locked_picks.update(candidate.pick_ids)
    return tuple(sorted(selected, key=lambda item: (item.source, item.trade_id)))


def clear_mixed_trade_markets(
    bilateral: TradeMarketShadowResult,
    three_team: ThreeTeamMarketShadowResult,
) -> MixedTradeMarketClearing:
    bilateral_gains = {
        evaluation.shadow.offer.trade_id: sum(
            approval.rational_gain or 0.0 for approval in evaluation.shadow.approvals
        )
        for evaluation in bilateral.evaluations
    }
    three_team_gains = {
        evaluation.shadow.offer.trade_id: three_team_shadow_gain(evaluation.shadow)
        for evaluation in three_team.evaluations
    }
    candidates = [
        MixedTradeCandidate(
            "bilateral",
            offer.trade_id,
            (offer.team_a_id, offer.team_b_id),
            (*offer.players_from_a, *offer.players_from_b),
            (*offer.picks_from_a, *offer.picks_from_b),
            bilateral_gains.get(offer.trade_id, 0.0),
        )
        for offer in bilateral.plan.offers
    ]
    candidates.extend(
        MixedTradeCandidate(
            "three-team",
            offer.trade_id,
            offer.team_ids,
            tuple(route.player_id for route in offer.player_routes),
            tuple(route.pick_id for route in offer.pick_routes),
            three_team_gains.get(offer.trade_id, 0.0),
        )
        for offer in three_team.plan.offers
    )
    selections = select_mixed_trade_candidates(tuple(candidates))
    bilateral_ids = {item.trade_id for item in selections if item.source == "bilateral"}
    three_team_ids = {item.trade_id for item in selections if item.source == "three-team"}
    return MixedTradeMarketClearing(
        TradeMarketPlan(
            tuple(offer for offer in bilateral.plan.offers if offer.trade_id in bilateral_ids)
        ),
        ThreeTeamMarketPlan(
            tuple(offer for offer in three_team.plan.offers if offer.trade_id in three_team_ids)
        ),
        selections,
    )
