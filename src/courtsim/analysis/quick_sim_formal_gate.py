"""Frozen, source-pinned acceptance gate for production quick simulations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.quick_sim_batch import quick_sim_batch_from_json
from courtsim.analysis.quick_sim_comparison import (
    compare_quick_sim_summaries,
    load_quick_sim_reference,
    quick_sim_report_to_json,
)
from courtsim.artifacts import sha256_file

QUICK_SIM_FORMAL_GATE_VERSION = "quick-sim-formal-gate-v1"


class QuickSimFormalGateError(ValueError):
    pass


def evaluate_quick_sim_formal_gate(
    checkpoint_path: str | Path,
    gate_path: str | Path,
) -> dict[str, object]:
    """Verify frozen inputs and eligibility before evaluating realism ranges."""
    gate_file = Path(gate_path).resolve()
    gate = _load_object(gate_file, "formal gate")
    _validate_gate(gate)
    reference_file = _resolve_input(gate_file, cast(str, gate["reference_path"]))
    reality_file = _resolve_input(gate_file, cast(str, gate["reality_path"]))
    integrity = {
        "reference": _verified_hash(reference_file, cast(str, gate["reference_sha256"])),
        "reality": _verified_hash(reality_file, cast(str, gate["reality_sha256"])),
    }
    batch = quick_sim_batch_from_json(Path(checkpoint_path).read_text(encoding="utf-8"))
    eligible = {
        "complete": batch.complete,
        "team_count": batch.spec.team_count == cast(int, gate["team_count"]),
        "minimum_seasons": batch.spec.seasons >= cast(int, gate["minimum_seasons"]),
        "unseen_master_seed": batch.spec.master_seed
        not in cast(list[int], gate["forbidden_master_seeds"]),
        "batch_id": batch.spec.batch_id.startswith(cast(str, gate["batch_id_prefix"])),
    }
    comparison_payload: dict[str, object] | None = None
    comparison_passed = False
    if all(integrity.values()) and all(eligible.values()):
        reference = load_quick_sim_reference(reference_file.read_text(encoding="utf-8"))
        if reference.reference_id != gate["reference_id"]:
            raise QuickSimFormalGateError("formal gate reference identity differs")
        report = compare_quick_sim_summaries(tuple(cell.summary for cell in batch.cells), reference)
        comparison_payload = cast(dict[str, object], json.loads(quick_sim_report_to_json(report)))
        comparison_passed = report.passed
    passed = all(integrity.values()) and all(eligible.values()) and comparison_passed
    return {
        "version": QUICK_SIM_FORMAL_GATE_VERSION,
        "gate_id": gate["gate_id"],
        "reference_id": gate["reference_id"],
        "checkpoint": {
            "batch_id": batch.spec.batch_id,
            "master_seed": batch.spec.master_seed,
            "seasons": batch.spec.seasons,
            "batch_sha256": batch.batch_sha256,
        },
        "integrity": integrity,
        "eligibility": eligible,
        "comparison": comparison_payload,
        "passed": passed,
    }


def _validate_gate(raw: dict[str, Any]) -> None:
    expected = {
        "version",
        "gate_id",
        "frozen_at",
        "reality_path",
        "reality_sha256",
        "reference_path",
        "reference_sha256",
        "reference_id",
        "team_count",
        "minimum_seasons",
        "forbidden_master_seeds",
        "batch_id_prefix",
    }
    if set(raw) != expected or raw.get("version") != QUICK_SIM_FORMAL_GATE_VERSION:
        raise QuickSimFormalGateError("formal gate schema differs")
    for field in (
        "gate_id",
        "frozen_at",
        "reality_path",
        "reference_path",
        "reference_id",
        "batch_id_prefix",
    ):
        if not isinstance(raw[field], str) or not cast(str, raw[field]).strip():
            raise QuickSimFormalGateError(f"formal gate {field} must be non-empty text")
    for field in ("reality_sha256", "reference_sha256"):
        value = raw[field]
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(item not in "0123456789abcdef" for item in value)
        ):
            raise QuickSimFormalGateError(f"formal gate {field} is invalid")
    for field in ("team_count", "minimum_seasons"):
        if not isinstance(raw[field], int) or isinstance(raw[field], bool) or raw[field] < 1:
            raise QuickSimFormalGateError(f"formal gate {field} is invalid")
    seeds = raw["forbidden_master_seeds"]
    if not isinstance(seeds, list) or any(
        not isinstance(item, int) or isinstance(item, bool) for item in seeds
    ):
        raise QuickSimFormalGateError("formal gate forbidden seeds are invalid")
    if seeds != sorted(set(seeds)):
        raise QuickSimFormalGateError("formal gate forbidden seeds must be ordered and unique")


def _resolve_input(gate_path: Path, relative: str) -> Path:
    path = (gate_path.parent / relative).resolve()
    if not path.is_file():
        raise QuickSimFormalGateError(f"formal gate input is missing: {relative}")
    return path


def _verified_hash(path: Path, expected: str) -> bool:
    return sha256_file(path) == expected


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QuickSimFormalGateError(f"cannot read {label}: {path}") from error
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise QuickSimFormalGateError(f"{label} must be an object")
    return cast(dict[str, Any], value)
