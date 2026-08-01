from dataclasses import replace

from courtsim.draft_assets import DraftAssetLedger, FutureDraftPickAsset, seed_future_draft_picks
from courtsim.draft_obligations import (
    build_draft_obligation_ledger_v3,
    draft_obligation_ledger_v3_from_dict,
    draft_obligation_ledger_v3_to_dict,
    inspect_draft_obligation_ledger_v3,
)


def _assets() -> DraftAssetLedger:
    ledger = seed_future_draft_picks(
        DraftAssetLedger(),
        team_ids=("A", "B"),
        draft_years=tuple(range(2029, 2036)),
        rounds=1,
    )
    picks = list(ledger.picks)
    picks[0] = replace(
        picks[0],
        owner_team_id="B",
        protected_top_n=4,
        deferrals_remaining=2,
    )
    return replace(ledger, picks=tuple(picks))


def test_v3_derives_conservative_freezes_and_round_trips() -> None:
    ledger = build_draft_obligation_ledger_v3(
        _assets(),
        as_of_year=2029,
        source_asset_sha256="a" * 64,
    )
    assert len(ledger.obligations) == 1
    obligation = ledger.obligations[0]
    assert (obligation.earliest_year, obligation.latest_year) == (2029, 2031)
    assert tuple(item.draft_year for item in ledger.freezes) == (2030, 2031, 2032)
    assert (
        draft_obligation_ledger_v3_from_dict(draft_obligation_ledger_v3_to_dict(ledger)) == ledger
    )


def test_v3_audit_requires_hash_and_complete_seven_year_horizon() -> None:
    assets = _assets()
    ledger = build_draft_obligation_ledger_v3(
        assets,
        as_of_year=2029,
        source_asset_sha256="a" * 64,
    )
    passed = inspect_draft_obligation_ledger_v3(
        ledger,
        assets,
        actual_asset_sha256="a" * 64,
    )
    assert passed["ready"] is True
    assert passed["blocked_trade_assets"] == [3, 5, 7]
    failed = inspect_draft_obligation_ledger_v3(
        ledger,
        replace(assets, picks=assets.picks[:-1]),
        actual_asset_sha256="b" * 64,
    )
    assert failed["ready"] is False
    assert failed["source_verified"] is False
    assert failed["missing_seven_year_firsts"]


def test_distinct_consecutive_outgoing_firsts_are_stepien_risk() -> None:
    assets = DraftAssetLedger(
        (
            FutureDraftPickAsset(1, 2029, 1, "A", "B"),
            FutureDraftPickAsset(2, 2030, 1, "A", "B"),
        ),
        next_asset_id=3,
    )
    ledger = build_draft_obligation_ledger_v3(
        assets,
        as_of_year=2029,
        source_asset_sha256="a" * 64,
    )
    audit = inspect_draft_obligation_ledger_v3(
        ledger,
        assets,
        actual_asset_sha256="a" * 64,
    )
    assert audit["stepien_risk_pairs"] == [
        {"team_id": "A", "first_year": 2029, "second_year": 2030}
    ]
