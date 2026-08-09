"""Conservative conditional-pick obligation and freeze ledger v3."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from courtsim.artifacts import sha256_file
from courtsim.draft_assets import (
    DraftAssetLedger,
    draft_asset_ledger_from_dict,
    draft_asset_ledger_to_dict,
)

DRAFT_OBLIGATION_LEDGER_VERSION = "draft-obligation-ledger-v3"
DRAFT_OBLIGATION_SCHEMA_VERSION = 3


class DraftObligationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class DraftObligation:
    obligation_id: int
    source_asset_id: int
    debtor_team_id: str
    creditor_team_id: str
    earliest_year: int
    latest_year: int
    possible_rounds: tuple[int, ...]

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1
            for value in (
                self.obligation_id,
                self.source_asset_id,
                self.earliest_year,
                self.latest_year,
                *self.possible_rounds,
            )
        ):
            raise ValueError("draft obligation values must be positive integers")
        if self.latest_year < self.earliest_year or self.possible_rounds != tuple(
            sorted(set(self.possible_rounds))
        ):
            raise ValueError("draft obligation window or rounds are invalid")
        if not self.debtor_team_id.strip() or not self.creditor_team_id.strip():
            raise ValueError("draft obligation teams must not be blank")
        if self.debtor_team_id == self.creditor_team_id:
            raise ValueError("draft obligation teams must be distinct")


@dataclass(frozen=True, slots=True)
class DraftPickFreeze:
    asset_id: int
    team_id: str
    draft_year: int
    round_number: int
    obligation_ids: tuple[int, ...]
    reason: str = "unresolved-first-round-obligation"

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1
            for value in (self.asset_id, self.draft_year, self.round_number, *self.obligation_ids)
        ):
            raise ValueError("draft freeze values must be positive integers")
        if self.obligation_ids != tuple(sorted(set(self.obligation_ids))):
            raise ValueError("draft freeze obligation ids must be canonical")
        if not self.team_id.strip() or not self.reason.strip():
            raise ValueError("draft freeze identity must not be blank")


@dataclass(frozen=True, slots=True)
class DraftObligationLedgerV3:
    as_of_year: int
    source_asset_sha256: str
    obligations: tuple[DraftObligation, ...]
    freezes: tuple[DraftPickFreeze, ...]
    horizon_years: int = 7
    version: str = DRAFT_OBLIGATION_LEDGER_VERSION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.as_of_year, int)
            or isinstance(self.as_of_year, bool)
            or self.as_of_year < 1
            or self.horizon_years != 7
            or self.version != DRAFT_OBLIGATION_LEDGER_VERSION
        ):
            raise ValueError("draft obligation ledger identity is invalid")
        if len(self.source_asset_sha256) != 64 or any(
            value not in "0123456789abcdef" for value in self.source_asset_sha256
        ):
            raise ValueError("draft obligation source hash is invalid")
        if self.obligations != tuple(sorted(self.obligations, key=lambda item: item.obligation_id)):
            raise ValueError("draft obligations must be ordered")
        obligation_ids = tuple(item.obligation_id for item in self.obligations)
        if len(obligation_ids) != len(set(obligation_ids)):
            raise ValueError("draft obligation ids must be unique")
        if self.freezes != tuple(sorted(self.freezes, key=lambda item: item.asset_id)):
            raise ValueError("draft freezes must be ordered")
        freeze_ids = tuple(item.asset_id for item in self.freezes)
        if len(freeze_ids) != len(set(freeze_ids)):
            raise ValueError("a draft asset can have only one freeze record")
        if any(set(item.obligation_ids) - set(obligation_ids) for item in self.freezes):
            raise ValueError("draft freeze references an unknown obligation")


def build_draft_obligation_ledger_v3(
    assets: DraftAssetLedger,
    *,
    as_of_year: int,
    source_asset_sha256: str,
) -> DraftObligationLedgerV3:
    """Derive conservative freezes from every outstanding outgoing pick."""
    obligations: list[DraftObligation] = []
    for pick in assets.picks:
        if pick.owner_team_id == pick.original_team_id or pick.draft_year < as_of_year:
            continue
        possible_rounds = {pick.round_number}
        possible_rounds.update(
            condition.conversion_round_number
            for condition in pick.conditions
            if condition.outcome == "convert"
        )
        obligations.append(
            DraftObligation(
                len(obligations) + 1,
                pick.asset_id,
                pick.original_team_id,
                pick.owner_team_id,
                pick.draft_year,
                pick.draft_year + pick.deferrals_remaining,
                tuple(sorted(possible_rounds)),
            )
        )
    freeze_reasons: dict[int, list[int]] = {}
    picks_by_id = {item.asset_id: item for item in assets.picks}
    horizon_end = as_of_year + 6
    for obligation in obligations:
        if 1 not in obligation.possible_rounds:
            continue
        for pick in assets.picks:
            if (
                pick.original_team_id == obligation.debtor_team_id
                and pick.owner_team_id == pick.original_team_id
                and pick.round_number == 1
                and obligation.earliest_year
                <= pick.draft_year
                <= min(horizon_end, obligation.latest_year + 1)
            ):
                freeze_reasons.setdefault(pick.asset_id, []).append(obligation.obligation_id)
    freezes = tuple(
        DraftPickFreeze(
            asset_id,
            picks_by_id[asset_id].original_team_id,
            picks_by_id[asset_id].draft_year,
            picks_by_id[asset_id].round_number,
            tuple(sorted(obligation_ids)),
        )
        for asset_id, obligation_ids in sorted(freeze_reasons.items())
    )
    return DraftObligationLedgerV3(
        as_of_year,
        source_asset_sha256,
        tuple(obligations),
        freezes,
    )


def derive_draft_obligation_ledger_v3(
    assets: DraftAssetLedger,
    *,
    as_of_year: int,
) -> DraftObligationLedgerV3:
    """Build a source-bound runtime ledger from canonical in-memory draft assets."""
    canonical = json.dumps(
        draft_asset_ledger_to_dict(assets),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return build_draft_obligation_ledger_v3(
        assets,
        as_of_year=as_of_year,
        source_asset_sha256=hashlib.sha256(canonical).hexdigest(),
    )


def inspect_draft_obligation_ledger_v3(
    ledger: DraftObligationLedgerV3,
    assets: DraftAssetLedger,
    *,
    actual_asset_sha256: str,
) -> dict[str, object]:
    """Read-only integrity, horizon, freeze, and worst-case Stepien audit."""
    asset_by_id = {item.asset_id: item for item in assets.picks}
    orphan_obligations = sorted(
        item.obligation_id for item in ledger.obligations if item.source_asset_id not in asset_by_id
    )
    orphan_freezes = sorted(
        item.asset_id for item in ledger.freezes if item.asset_id not in asset_by_id
    )
    freeze_identity_mismatches = sorted(
        item.asset_id
        for item in ledger.freezes
        if item.asset_id in asset_by_id
        and (
            item.team_id,
            item.draft_year,
            item.round_number,
        )
        != (
            asset_by_id[item.asset_id].original_team_id,
            asset_by_id[item.asset_id].draft_year,
            asset_by_id[item.asset_id].round_number,
        )
    )
    teams = tuple(sorted({item.original_team_id for item in assets.picks}))
    years = tuple(range(ledger.as_of_year, ledger.as_of_year + ledger.horizon_years))
    native_firsts = {
        (item.original_team_id, item.draft_year) for item in assets.picks if item.round_number == 1
    }
    missing_horizon = [
        {"team_id": team_id, "draft_year": year}
        for team_id in teams
        for year in years
        if (team_id, year) not in native_firsts
    ]
    possible_outgoing: dict[str, dict[int, set[int]]] = {}
    for item in ledger.obligations:
        if 1 in item.possible_rounds:
            by_year = possible_outgoing.setdefault(item.debtor_team_id, {})
            for year in range(item.earliest_year, item.latest_year + 1):
                by_year.setdefault(year, set()).add(item.obligation_id)
    stepien_risk_pairs = [
        {"team_id": team_id, "first_year": year, "second_year": year + 1}
        for team_id, by_year in sorted(possible_outgoing.items())
        for year in sorted(by_year)
        if year + 1 in by_year
        and any(first != second for first in by_year[year] for second in by_year[year + 1])
    ]
    source_verified = ledger.source_asset_sha256 == actual_asset_sha256
    ready = (
        source_verified
        and not orphan_obligations
        and not orphan_freezes
        and not freeze_identity_mismatches
        and not missing_horizon
        and not stepien_risk_pairs
    )
    return {
        "schema_version": 1,
        "version": "draft-obligation-audit-v1",
        "ledger_version": ledger.version,
        "as_of_year": ledger.as_of_year,
        "horizon_years": ledger.horizon_years,
        "source_verified": source_verified,
        "ready": ready,
        "counts": {
            "assets": len(assets.picks),
            "obligations": len(ledger.obligations),
            "freezes": len(ledger.freezes),
            "teams": len(teams),
        },
        "blocked_trade_assets": [item.asset_id for item in ledger.freezes],
        "orphan_obligations": orphan_obligations,
        "orphan_freezes": orphan_freezes,
        "freeze_identity_mismatches": freeze_identity_mismatches,
        "missing_seven_year_firsts": missing_horizon,
        "stepien_risk_pairs": stepien_risk_pairs,
    }


def draft_obligation_ledger_v3_to_dict(
    ledger: DraftObligationLedgerV3,
) -> dict[str, object]:
    return {
        "schema_version": DRAFT_OBLIGATION_SCHEMA_VERSION,
        "version": ledger.version,
        "as_of_year": ledger.as_of_year,
        "horizon_years": ledger.horizon_years,
        "source_asset_sha256": ledger.source_asset_sha256,
        "obligations": [
            {
                "obligation_id": item.obligation_id,
                "source_asset_id": item.source_asset_id,
                "debtor_team_id": item.debtor_team_id,
                "creditor_team_id": item.creditor_team_id,
                "earliest_year": item.earliest_year,
                "latest_year": item.latest_year,
                "possible_rounds": list(item.possible_rounds),
            }
            for item in ledger.obligations
        ],
        "freezes": [
            {
                "asset_id": item.asset_id,
                "team_id": item.team_id,
                "draft_year": item.draft_year,
                "round_number": item.round_number,
                "obligation_ids": list(item.obligation_ids),
                "reason": item.reason,
            }
            for item in ledger.freezes
        ],
    }


def draft_obligation_ledger_v3_from_dict(value: object) -> DraftObligationLedgerV3:
    root = _object(value, "draft obligation ledger")
    if (
        set(root)
        != {
            "schema_version",
            "version",
            "as_of_year",
            "horizon_years",
            "source_asset_sha256",
            "obligations",
            "freezes",
        }
        or root.get("schema_version") != DRAFT_OBLIGATION_SCHEMA_VERSION
    ):
        raise DraftObligationError("draft obligation ledger schema differs")
    raw_obligations = root["obligations"]
    raw_freezes = root["freezes"]
    if not isinstance(raw_obligations, list) or not isinstance(raw_freezes, list):
        raise DraftObligationError("draft obligation collections must be lists")
    try:
        return DraftObligationLedgerV3(
            _integer(root["as_of_year"], "as_of_year"),
            _text(root["source_asset_sha256"], "source_asset_sha256"),
            tuple(_obligation(item) for item in raw_obligations),
            tuple(_freeze(item) for item in raw_freezes),
            _integer(root["horizon_years"], "horizon_years"),
            _text(root["version"], "version"),
        )
    except ValueError as error:
        raise DraftObligationError(str(error)) from error


def inspect_draft_obligation_files(
    ledger_path: str | Path, asset_path: str | Path
) -> dict[str, object]:
    ledger_file = Path(ledger_path).resolve()
    asset_file = Path(asset_path).resolve()
    ledger = draft_obligation_ledger_v3_from_dict(_load_json(ledger_file))
    try:
        assets = draft_asset_ledger_from_dict(_load_json(asset_file))
    except ValueError as error:
        raise DraftObligationError(str(error)) from error
    return inspect_draft_obligation_ledger_v3(
        ledger,
        assets,
        actual_asset_sha256=sha256_file(asset_file),
    )


def _obligation(value: object) -> DraftObligation:
    raw = _object(value, "draft obligation")
    expected = {
        "obligation_id",
        "source_asset_id",
        "debtor_team_id",
        "creditor_team_id",
        "earliest_year",
        "latest_year",
        "possible_rounds",
    }
    if set(raw) != expected or not isinstance(raw["possible_rounds"], list):
        raise DraftObligationError("draft obligation row is invalid")
    return DraftObligation(
        _integer(raw["obligation_id"], "obligation_id"),
        _integer(raw["source_asset_id"], "source_asset_id"),
        _text(raw["debtor_team_id"], "debtor_team_id"),
        _text(raw["creditor_team_id"], "creditor_team_id"),
        _integer(raw["earliest_year"], "earliest_year"),
        _integer(raw["latest_year"], "latest_year"),
        tuple(_integer(item, "possible_round") for item in raw["possible_rounds"]),
    )


def _freeze(value: object) -> DraftPickFreeze:
    raw = _object(value, "draft freeze")
    expected = {
        "asset_id",
        "team_id",
        "draft_year",
        "round_number",
        "obligation_ids",
        "reason",
    }
    if set(raw) != expected or not isinstance(raw["obligation_ids"], list):
        raise DraftObligationError("draft freeze row is invalid")
    return DraftPickFreeze(
        _integer(raw["asset_id"], "asset_id"),
        _text(raw["team_id"], "team_id"),
        _integer(raw["draft_year"], "draft_year"),
        _integer(raw["round_number"], "round_number"),
        tuple(_integer(item, "obligation_id") for item in raw["obligation_ids"]),
        _text(raw["reason"], "reason"),
    )


def _load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DraftObligationError(f"cannot read draft ledger: {path}") from error


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise DraftObligationError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _integer(value: object, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise DraftObligationError(f"{field} must be an integer")
    return value


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DraftObligationError(f"{field} must be non-empty text")
    return value.strip()
