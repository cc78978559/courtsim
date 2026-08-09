from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import courtsim.draft_obligations as obligation_module
from courtsim.draft_assets import DraftAssetLedger, FutureDraftPickAsset, seed_future_draft_picks
from courtsim.draft_obligations import (
    DraftObligation,
    DraftObligationError,
    DraftPickFreeze,
    build_draft_obligation_ledger_v3,
    derive_draft_obligation_ledger_v3,
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


def test_runtime_v3_refreshes_source_hash_and_unfreezes_after_settlement() -> None:
    assets = _assets()
    first = derive_draft_obligation_ledger_v3(assets, as_of_year=2029)
    assert tuple(item.asset_id for item in first.freezes) == (3, 5, 7)
    assert first == derive_draft_obligation_ledger_v3(assets, as_of_year=2029)
    settled = replace(
        assets,
        picks=tuple(pick for pick in assets.picks if pick.owner_team_id == pick.original_team_id),
    )
    refreshed = derive_draft_obligation_ledger_v3(settled, as_of_year=2030)
    assert refreshed.source_asset_sha256 != first.source_asset_sha256
    assert refreshed.obligations == ()
    assert refreshed.freezes == ()


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


def test_v3_value_objects_reject_invalid_obligation_and_freeze_identity() -> None:
    obligation = DraftObligation(1, 1, "A", "B", 2029, 2031, (1, 2))
    invalid_obligations = (
        ({"obligation_id": 0}, "positive integers"),
        ({"latest_year": 2028}, "window or rounds"),
        ({"possible_rounds": (2, 1)}, "window or rounds"),
        ({"debtor_team_id": ""}, "must not be blank"),
        ({"creditor_team_id": "A"}, "must be distinct"),
    )
    for changes, message in invalid_obligations:
        with pytest.raises(ValueError, match=message):
            replace(obligation, **changes)

    freeze = DraftPickFreeze(2, "A", 2030, 1, (1,))
    with pytest.raises(ValueError, match="positive integers"):
        replace(freeze, asset_id=0)
    with pytest.raises(ValueError, match="canonical"):
        replace(freeze, obligation_ids=(2, 1))
    with pytest.raises(ValueError, match="must not be blank"):
        replace(freeze, reason="")


def test_v3_ledger_rejects_hash_order_duplicates_and_unknown_references() -> None:
    ledger = build_draft_obligation_ledger_v3(
        _assets(), as_of_year=2029, source_asset_sha256="a" * 64
    )
    first = ledger.obligations[0]
    second = replace(first, obligation_id=2, source_asset_id=2)
    with pytest.raises(ValueError, match="identity is invalid"):
        replace(ledger, horizon_years=6)
    with pytest.raises(ValueError, match="source hash"):
        replace(ledger, source_asset_sha256="bad")
    with pytest.raises(ValueError, match="must be ordered"):
        replace(ledger, obligations=(second, first))
    with pytest.raises(ValueError, match="ids must be unique"):
        replace(ledger, obligations=(first, replace(second, obligation_id=1)))
    with pytest.raises(ValueError, match="unknown obligation"):
        replace(
            ledger,
            freezes=(replace(ledger.freezes[0], obligation_ids=(999,)), *ledger.freezes[1:]),
        )


def test_v3_payload_parser_rejects_schema_collection_and_row_drift() -> None:
    ledger = build_draft_obligation_ledger_v3(
        _assets(), as_of_year=2029, source_asset_sha256="a" * 64
    )
    base = draft_obligation_ledger_v3_to_dict(ledger)
    mutations: tuple[tuple[Callable[[dict[str, Any]], object], str], ...] = (
        (lambda payload: payload.__setitem__("schema_version", 2), "schema differs"),
        (lambda payload: payload.__setitem__("obligations", {}), "must be lists"),
        (
            lambda payload: payload["obligations"][0].__setitem__("extra", 1),
            "obligation row is invalid",
        ),
        (
            lambda payload: payload["freezes"][0].__setitem__("extra", 1),
            "freeze row is invalid",
        ),
        (lambda payload: payload.__setitem__("as_of_year", True), "must be an integer"),
    )
    for mutation, message in mutations:
        payload = deepcopy(base)
        mutation(payload)
        with pytest.raises(DraftObligationError, match=message):
            draft_obligation_ledger_v3_from_dict(payload)


def test_v3_private_json_and_scalar_guards_wrap_bad_inputs(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    with pytest.raises(DraftObligationError, match="cannot read"):
        obligation_module._load_json(path)
    with pytest.raises(DraftObligationError, match="must be an object"):
        obligation_module._object([], "ledger")
    with pytest.raises(DraftObligationError, match="non-empty text"):
        obligation_module._text("", "team")
