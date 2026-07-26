"""Persistent future draft-pick ownership, protections, swaps, and annual settlement."""

from __future__ import annotations

from dataclasses import dataclass, replace

from courtsim.career import DraftPickAsset

DRAFT_ASSET_VERSION = "draft-asset-v1"
DRAFT_ASSET_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class FutureDraftPickAsset:
    asset_id: int
    draft_year: int
    round_number: int
    original_team_id: str
    owner_team_id: str
    protected_top_n: int = 0
    deferrals_remaining: int = 0
    version: str = DRAFT_ASSET_VERSION

    def __post_init__(self) -> None:
        values = (
            self.asset_id,
            self.draft_year,
            self.round_number,
            self.protected_top_n,
            self.deferrals_remaining,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise ValueError("future draft-pick values must be integers")
        if self.asset_id < 1 or self.draft_year < 1 or self.round_number < 1:
            raise ValueError("future draft-pick identity values must be positive")
        if self.protected_top_n < 0 or self.deferrals_remaining < 0:
            raise ValueError("future draft-pick protection values must be non-negative")
        if self.protected_top_n == 0 and self.deferrals_remaining != 0:
            raise ValueError("an unprotected pick cannot carry deferrals")
        if not self.original_team_id.strip() or not self.owner_team_id.strip():
            raise ValueError("future draft-pick team ids must not be blank")
        if self.version != DRAFT_ASSET_VERSION:
            raise ValueError(f"unsupported draft asset version: {self.version}")

    @property
    def selection_number(self) -> int:
        """Stable trade identifier shared with current DraftPickAsset."""
        return self.asset_id


TradableDraftPick = DraftPickAsset | FutureDraftPickAsset


@dataclass(frozen=True, slots=True)
class DraftPickSwapRight:
    swap_id: int
    draft_year: int
    round_number: int
    controller_team_id: str
    target_original_team_id: str
    version: str = DRAFT_ASSET_VERSION

    def __post_init__(self) -> None:
        values = (self.swap_id, self.draft_year, self.round_number)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in values
        ):
            raise ValueError("draft swap identity values must be positive integers")
        if not self.controller_team_id.strip() or not self.target_original_team_id.strip():
            raise ValueError("draft swap team ids must not be blank")
        if self.controller_team_id == self.target_original_team_id:
            raise ValueError("draft swap teams must be distinct")
        if self.version != DRAFT_ASSET_VERSION:
            raise ValueError(f"unsupported draft asset version: {self.version}")


@dataclass(frozen=True, slots=True)
class DraftAssetLedger:
    picks: tuple[FutureDraftPickAsset, ...] = ()
    swaps: tuple[DraftPickSwapRight, ...] = ()
    next_asset_id: int = 1
    version: str = DRAFT_ASSET_VERSION

    def __post_init__(self) -> None:
        if self.version != DRAFT_ASSET_VERSION:
            raise ValueError("unsupported draft asset ledger version")
        if (
            not isinstance(self.next_asset_id, int)
            or isinstance(self.next_asset_id, bool)
            or self.next_asset_id < 1
        ):
            raise ValueError("next_asset_id must be a positive integer")
        if self.picks != tuple(sorted(self.picks, key=lambda item: item.asset_id)):
            raise ValueError("future draft picks must be ordered by asset_id")
        asset_ids = tuple(pick.asset_id for pick in self.picks)
        if len(asset_ids) != len(set(asset_ids)):
            raise ValueError("future draft-pick asset ids must be unique")
        keys = tuple(
            (pick.draft_year, pick.round_number, pick.original_team_id) for pick in self.picks
        )
        if len(keys) != len(set(keys)):
            raise ValueError("a native future pick can have only one ownership record")
        if asset_ids and self.next_asset_id <= max(asset_ids):
            raise ValueError("next_asset_id must exceed every existing pick asset id")
        if self.swaps != tuple(sorted(self.swaps, key=lambda item: item.swap_id)):
            raise ValueError("draft swap rights must be ordered by swap_id")
        swap_ids = tuple(swap.swap_id for swap in self.swaps)
        if len(swap_ids) != len(set(swap_ids)):
            raise ValueError("draft swap ids must be unique")


@dataclass(frozen=True, slots=True)
class DraftAssetSettlement:
    draft_year: int
    picks: tuple[DraftPickAsset, ...]
    final_ledger: DraftAssetLedger
    protected_asset_ids: tuple[int, ...]
    rolled_asset_ids: tuple[int, ...]
    exercised_swap_ids: tuple[int, ...]
    version: str = DRAFT_ASSET_VERSION


def seed_future_draft_picks(
    ledger: DraftAssetLedger,
    *,
    team_ids: tuple[str, ...],
    draft_years: tuple[int, ...],
    rounds: int,
) -> DraftAssetLedger:
    if team_ids != tuple(sorted(set(team_ids))) or not team_ids:
        raise ValueError("team_ids must be sorted unique and non-empty")
    if draft_years != tuple(sorted(set(draft_years))) or any(year < 1 for year in draft_years):
        raise ValueError("draft_years must be sorted unique positive integers")
    if not isinstance(rounds, int) or isinstance(rounds, bool) or rounds < 1:
        raise ValueError("rounds must be a positive integer")
    picks = list(ledger.picks)
    existing = {(pick.draft_year, pick.round_number, pick.original_team_id) for pick in picks}
    next_id = ledger.next_asset_id
    for draft_year in draft_years:
        for round_number in range(1, rounds + 1):
            for team_id in team_ids:
                key = (draft_year, round_number, team_id)
                if key in existing:
                    continue
                picks.append(
                    FutureDraftPickAsset(
                        next_id,
                        draft_year,
                        round_number,
                        team_id,
                        team_id,
                    )
                )
                existing.add(key)
                next_id += 1
    return DraftAssetLedger(
        tuple(sorted(picks, key=lambda item: item.asset_id)),
        ledger.swaps,
        next_id,
    )


def settle_draft_assets(
    ledger: DraftAssetLedger,
    *,
    draft_year: int,
    original_team_order: tuple[str, ...],
) -> DraftAssetSettlement:
    """Resolve protections and swaps from worst-to-best original-team order."""
    if original_team_order != tuple(dict.fromkeys(original_team_order)):
        raise ValueError("original_team_order must contain unique teams")
    due = tuple(pick for pick in ledger.picks if pick.draft_year == draft_year)
    future = [pick for pick in ledger.picks if pick.draft_year != draft_year]
    order = {team_id: index + 1 for index, team_id in enumerate(original_team_order)}
    if any(pick.original_team_id not in order for pick in due):
        raise ValueError("draft order does not cover every due original team")
    protected: list[int] = []
    rolled: list[int] = []
    current: list[tuple[FutureDraftPickAsset, str]] = []
    next_id_cursor = ledger.next_asset_id
    for pick in due:
        round_pick = order[pick.original_team_id]
        owner = pick.owner_team_id
        if (
            owner != pick.original_team_id
            and pick.protected_top_n
            and round_pick <= pick.protected_top_n
        ):
            owner = pick.original_team_id
            protected.append(pick.asset_id)
            if pick.deferrals_remaining:
                future, next_id_cursor = _roll_obligation(
                    future,
                    pick,
                    next_id_cursor,
                )
                rolled.append(pick.asset_id)
        current.append((pick, owner))

    current.sort(
        key=lambda item: (
            item[0].round_number,
            order[item[0].original_team_id],
            item[0].asset_id,
        )
    )
    picks = [
        DraftPickAsset(
            index,
            pick.round_number,
            order[pick.original_team_id],
            pick.original_team_id,
            owner,
        )
        for index, (pick, owner) in enumerate(current, start=1)
    ]
    exercised: list[int] = []
    for swap in ledger.swaps:
        if swap.draft_year != draft_year:
            continue
        controller = next(
            (
                pick
                for pick in picks
                if pick.round_number == swap.round_number
                and pick.original_team_id == swap.controller_team_id
            ),
            None,
        )
        target = next(
            (
                pick
                for pick in picks
                if pick.round_number == swap.round_number
                and pick.original_team_id == swap.target_original_team_id
            ),
            None,
        )
        if controller is None or target is None:
            raise ValueError("draft swap references a missing current pick")
        if controller.owner_team_id != swap.controller_team_id:
            raise ValueError("draft swap controller no longer owns its native pick")
        if target.round_pick < controller.round_pick:
            controller_index = picks.index(controller)
            target_index = picks.index(target)
            picks[controller_index] = replace(
                controller,
                owner_team_id=target.owner_team_id,
            )
            picks[target_index] = replace(
                target,
                owner_team_id=swap.controller_team_id,
            )
            exercised.append(swap.swap_id)

    next_id = max(
        ledger.next_asset_id,
        next_id_cursor,
        max((pick.asset_id for pick in future), default=0) + 1,
    )
    remaining_swaps = tuple(swap for swap in ledger.swaps if swap.draft_year != draft_year)
    final_ledger = DraftAssetLedger(
        tuple(sorted(future, key=lambda item: item.asset_id)),
        remaining_swaps,
        next_id,
    )
    return DraftAssetSettlement(
        draft_year,
        tuple(picks),
        final_ledger,
        tuple(protected),
        tuple(rolled),
        tuple(exercised),
    )


def draft_asset_ledger_to_dict(ledger: DraftAssetLedger) -> dict[str, object]:
    return {
        "schema_version": DRAFT_ASSET_SCHEMA_VERSION,
        "version": ledger.version,
        "next_asset_id": ledger.next_asset_id,
        "picks": [
            {
                "asset_id": pick.asset_id,
                "draft_year": pick.draft_year,
                "round_number": pick.round_number,
                "original_team_id": pick.original_team_id,
                "owner_team_id": pick.owner_team_id,
                "protected_top_n": pick.protected_top_n,
                "deferrals_remaining": pick.deferrals_remaining,
                "version": pick.version,
            }
            for pick in ledger.picks
        ],
        "swaps": [
            {
                "swap_id": swap.swap_id,
                "draft_year": swap.draft_year,
                "round_number": swap.round_number,
                "controller_team_id": swap.controller_team_id,
                "target_original_team_id": swap.target_original_team_id,
                "version": swap.version,
            }
            for swap in ledger.swaps
        ],
    }


def draft_asset_ledger_from_dict(value: object) -> DraftAssetLedger:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "version",
        "next_asset_id",
        "picks",
        "swaps",
    }:
        raise ValueError("invalid draft asset ledger keys")
    if (
        value["schema_version"] != DRAFT_ASSET_SCHEMA_VERSION
        or value["version"] != DRAFT_ASSET_VERSION
    ):
        raise ValueError("unsupported draft asset ledger")
    raw_picks = value["picks"]
    raw_swaps = value["swaps"]
    if not isinstance(raw_picks, list) or not isinstance(raw_swaps, list):
        raise ValueError("draft asset picks and swaps must be lists")
    picks = tuple(_pick_from_dict(item) for item in raw_picks)
    swaps = tuple(_swap_from_dict(item) for item in raw_swaps)
    return DraftAssetLedger(picks, swaps, _integer(value["next_asset_id"], "next_asset_id"))


def _roll_obligation(
    future: list[FutureDraftPickAsset],
    pick: FutureDraftPickAsset,
    next_asset_id: int,
) -> tuple[list[FutureDraftPickAsset], int]:
    key = (pick.draft_year + 1, pick.round_number, pick.original_team_id)
    existing = next(
        (
            candidate
            for candidate in future
            if (candidate.draft_year, candidate.round_number, candidate.original_team_id) == key
        ),
        None,
    )
    replacement = FutureDraftPickAsset(
        existing.asset_id if existing else next_asset_id,
        pick.draft_year + 1,
        pick.round_number,
        pick.original_team_id,
        pick.owner_team_id,
        pick.protected_top_n if pick.deferrals_remaining > 1 else 0,
        max(0, pick.deferrals_remaining - 1),
    )
    if existing is not None and existing.owner_team_id != existing.original_team_id:
        raise ValueError("protected pick cannot roll onto an already traded native pick")
    updated = [
        *(candidate for candidate in future if candidate is not existing),
        replacement,
    ]
    return updated, next_asset_id if existing else next_asset_id + 1


def _pick_from_dict(value: object) -> FutureDraftPickAsset:
    if not isinstance(value, dict) or set(value) != {
        "asset_id",
        "draft_year",
        "round_number",
        "original_team_id",
        "owner_team_id",
        "protected_top_n",
        "deferrals_remaining",
        "version",
    }:
        raise ValueError("invalid future draft-pick keys")
    return FutureDraftPickAsset(
        _integer(value["asset_id"], "asset_id"),
        _integer(value["draft_year"], "draft_year"),
        _integer(value["round_number"], "round_number"),
        _text(value["original_team_id"], "original_team_id"),
        _text(value["owner_team_id"], "owner_team_id"),
        _integer(value["protected_top_n"], "protected_top_n"),
        _integer(value["deferrals_remaining"], "deferrals_remaining"),
        _text(value["version"], "version"),
    )


def _swap_from_dict(value: object) -> DraftPickSwapRight:
    if not isinstance(value, dict) or set(value) != {
        "swap_id",
        "draft_year",
        "round_number",
        "controller_team_id",
        "target_original_team_id",
        "version",
    }:
        raise ValueError("invalid draft swap keys")
    return DraftPickSwapRight(
        _integer(value["swap_id"], "swap_id"),
        _integer(value["draft_year"], "draft_year"),
        _integer(value["round_number"], "round_number"),
        _text(value["controller_team_id"], "controller_team_id"),
        _text(value["target_original_team_id"], "target_original_team_id"),
        _text(value["version"], "version"),
    )


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{label} must be an integer")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    return value
