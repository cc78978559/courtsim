"""Deterministic weighted draft lottery with a complete draw ledger."""

from __future__ import annotations

from dataclasses import dataclass

from courtsim.randomness import derive_seed

DRAFT_LOTTERY_VERSION = "draft-lottery-v1"


@dataclass(frozen=True, slots=True)
class DraftLotteryRules:
    drawn_slots: int = 2
    weight_bps: tuple[int, ...] = (4000, 3000, 2000, 1000)
    version: str = DRAFT_LOTTERY_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.drawn_slots, int)
            or isinstance(self.drawn_slots, bool)
            or not 1 <= self.drawn_slots < len(self.weight_bps)
        ):
            raise ValueError("drawn_slots must be below the lottery team count")
        if (
            any(
                not isinstance(weight, int) or isinstance(weight, bool) or weight < 1
                for weight in self.weight_bps
            )
            or sum(self.weight_bps) != 10_000
        ):
            raise ValueError("lottery weights must be positive basis points summing to 10000")
        if self.version != DRAFT_LOTTERY_VERSION:
            raise ValueError(f"unsupported draft lottery version: {self.version}")


DEFAULT_DRAFT_LOTTERY_RULES = DraftLotteryRules()


@dataclass(frozen=True, slots=True)
class DraftLotteryDraw:
    slot: int
    roll: int
    total_weight: int
    selected_team_id: str
    candidates: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class DraftLotteryResult:
    draft_year: int
    master_seed: int
    base_order: tuple[str, ...]
    final_order: tuple[str, ...]
    draws: tuple[DraftLotteryDraw, ...]
    rules: DraftLotteryRules
    version: str = DRAFT_LOTTERY_VERSION


def resolve_draft_lottery(
    *,
    draft_year: int,
    master_seed: int,
    base_order: tuple[str, ...],
    rules: DraftLotteryRules = DEFAULT_DRAFT_LOTTERY_RULES,
) -> DraftLotteryResult:
    """Draw top slots without replacement; all randomness is draw-addressed."""
    if not isinstance(draft_year, int) or isinstance(draft_year, bool) or draft_year < 1:
        raise ValueError("draft_year must be a positive integer")
    if not isinstance(master_seed, int) or isinstance(master_seed, bool) or master_seed < 0:
        raise ValueError("master_seed must be a non-negative integer")
    if (
        len(base_order) != len(rules.weight_bps)
        or base_order != tuple(dict.fromkeys(base_order))
        or any(not team_id.strip() for team_id in base_order)
    ):
        raise ValueError("base_order must uniquely cover the configured lottery teams")
    weights = dict(zip(base_order, rules.weight_bps, strict=True))
    remaining = list(base_order)
    winners: list[str] = []
    draws: list[DraftLotteryDraw] = []
    for slot in range(1, rules.drawn_slots + 1):
        candidates = tuple((team_id, weights[team_id]) for team_id in remaining)
        total_weight = sum(weight for _, weight in candidates)
        roll = (
            derive_seed(
                master_seed,
                DRAFT_LOTTERY_VERSION,
                draft_year,
                "slot",
                slot,
            )
            % total_weight
        )
        cursor = 0
        selected = remaining[-1]
        for team_id, weight in candidates:
            cursor += weight
            if roll < cursor:
                selected = team_id
                break
        winners.append(selected)
        remaining.remove(selected)
        draws.append(DraftLotteryDraw(slot, roll, total_weight, selected, candidates))
    final_order = (*winners, *remaining)
    return DraftLotteryResult(
        draft_year,
        master_seed,
        base_order,
        final_order,
        tuple(draws),
        rules,
    )
