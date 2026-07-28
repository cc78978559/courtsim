from dataclasses import replace

import pytest
from test_phase15_trades import contract_rules, management

from courtsim.draft_assets import (
    DraftAssetLedger,
    DraftPickSwapRight,
    FutureDraftPickAsset,
    draft_asset_ledger_from_dict,
    draft_asset_ledger_to_dict,
    seed_future_draft_picks,
    settle_draft_assets,
)
from courtsim.trades import TradeOffer, apply_trade


def test_seeded_future_picks_have_stable_unique_identity_and_round_trip() -> None:
    ledger = seed_future_draft_picks(
        DraftAssetLedger(),
        team_ids=("A", "B"),
        draft_years=(2029, 2030),
        rounds=2,
    )
    assert len(ledger.picks) == 8
    assert tuple(pick.asset_id for pick in ledger.picks) == tuple(range(1, 9))
    assert ledger.next_asset_id == 9
    assert (
        seed_future_draft_picks(
            ledger,
            team_ids=("A", "B"),
            draft_years=(2029, 2030),
            rounds=2,
        )
        == ledger
    )
    assert draft_asset_ledger_from_dict(draft_asset_ledger_to_dict(ledger)) == ledger


def test_future_pick_trade_changes_owner_without_changing_native_identity() -> None:
    ledger = DraftAssetLedger(
        (
            FutureDraftPickAsset(1, 2030, 1, "home", "home"),
            FutureDraftPickAsset(2, 2030, 1, "away", "away"),
        ),
        next_asset_id=3,
    )
    result = apply_trade(
        management(),
        ledger.picks,
        TradeOffer(20, "home", "away", picks_from_a=(1,), picks_from_b=(2,)),
        contract_rules(),
    )
    first, second = result.final_picks
    assert isinstance(first, FutureDraftPickAsset)
    assert isinstance(second, FutureDraftPickAsset)
    assert (first.asset_id, first.original_team_id, first.owner_team_id) == (
        1,
        "home",
        "away",
    )
    assert (second.asset_id, second.original_team_id, second.owner_team_id) == (
        2,
        "away",
        "home",
    )


def test_top_protection_keeps_current_pick_and_rolls_obligation() -> None:
    ledger = DraftAssetLedger(
        (
            FutureDraftPickAsset(1, 2029, 1, "A", "B", 2, 1),
            FutureDraftPickAsset(2, 2029, 1, "B", "B"),
            FutureDraftPickAsset(3, 2030, 1, "A", "A"),
            FutureDraftPickAsset(4, 2030, 1, "B", "B"),
        ),
        next_asset_id=5,
    )
    settlement = settle_draft_assets(
        ledger,
        draft_year=2029,
        original_team_order=("A", "B"),
    )
    current_a = next(pick for pick in settlement.picks if pick.original_team_id == "A")
    rolled_a = next(
        pick
        for pick in settlement.final_ledger.picks
        if pick.draft_year == 2030 and pick.original_team_id == "A"
    )
    assert current_a.owner_team_id == "A"
    assert settlement.protected_asset_ids == (1,)
    assert settlement.rolled_asset_ids == (1,)
    assert rolled_a.asset_id == 3
    assert rolled_a.owner_team_id == "B"
    assert rolled_a.protected_top_n == 0
    assert rolled_a.deferrals_remaining == 0


def test_protection_does_not_block_conveyance_outside_protected_slots() -> None:
    ledger = DraftAssetLedger(
        (
            FutureDraftPickAsset(1, 2029, 1, "A", "B", 1, 1),
            FutureDraftPickAsset(2, 2029, 1, "B", "B"),
        ),
        next_asset_id=3,
    )
    settlement = settle_draft_assets(
        ledger,
        draft_year=2029,
        original_team_order=("B", "A"),
    )
    pick = next(item for item in settlement.picks if item.original_team_id == "A")
    assert pick.round_pick == 2
    assert pick.owner_team_id == "B"
    assert settlement.protected_asset_ids == ()
    assert settlement.final_ledger.picks == ()


def test_swap_executes_only_when_controller_receives_better_slot() -> None:
    ledger = DraftAssetLedger(
        (
            FutureDraftPickAsset(1, 2029, 1, "A", "A"),
            FutureDraftPickAsset(2, 2029, 1, "B", "B"),
            FutureDraftPickAsset(3, 2029, 1, "C", "C"),
        ),
        (DraftPickSwapRight(1, 2029, 1, "A", "B"),),
        4,
    )
    exercised = settle_draft_assets(
        ledger,
        draft_year=2029,
        original_team_order=("B", "C", "A"),
    )
    owners = {pick.original_team_id: pick.owner_team_id for pick in exercised.picks}
    assert owners == {"A": "B", "B": "A", "C": "C"}
    assert exercised.exercised_swap_ids == (1,)
    assert exercised.final_ledger.swaps == ()

    not_exercised = settle_draft_assets(
        replace(
            ledger,
            swaps=(DraftPickSwapRight(2, 2029, 1, "A", "B"),),
        ),
        draft_year=2029,
        original_team_order=("A", "C", "B"),
    )
    owners = {pick.original_team_id: pick.owner_team_id for pick in not_exercised.picks}
    assert owners == {"A": "A", "B": "B", "C": "C"}
    assert not_exercised.exercised_swap_ids == ()


def test_ledger_rejects_duplicate_native_pick_and_strict_json_keys() -> None:
    with pytest.raises(ValueError, match="one ownership"):
        DraftAssetLedger(
            (
                FutureDraftPickAsset(1, 2029, 1, "A", "A"),
                FutureDraftPickAsset(2, 2029, 1, "A", "B"),
            ),
            next_asset_id=3,
        )
    payload = draft_asset_ledger_to_dict(DraftAssetLedger())
    payload["extra"] = True
    with pytest.raises(ValueError, match="keys"):
        draft_asset_ledger_from_dict(payload)
