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
    run_manifest_path: str | Path,
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
    checkpoint_file = Path(checkpoint_path).resolve()
    batch = quick_sim_batch_from_json(checkpoint_file.read_text(encoding="utf-8"))
    run_manifest = _load_object(Path(run_manifest_path).resolve(), "quick-sim run manifest")
    run_version, run_configuration = _run_configuration(run_manifest, checkpoint_file)
    required_inputs = cast(dict[str, str], gate["required_input_sha256"])
    observed_inputs = cast(dict[str, dict[str, object]], run_configuration["inputs"])
    eligible = {
        "complete": batch.complete,
        "team_count": batch.spec.team_count == cast(int, gate["team_count"]),
        "minimum_seasons": batch.spec.seasons >= cast(int, gate["minimum_seasons"]),
        "unseen_master_seed": batch.spec.master_seed
        not in cast(list[int], gate["forbidden_master_seeds"]),
        "batch_id": batch.spec.batch_id.startswith(cast(str, gate["batch_id_prefix"])),
        "executor_version": run_configuration.get("executor_version")
        == gate["required_executor_version"],
        "runner_version": run_version == gate["required_runner_version"],
        "game_config": run_configuration.get("game_config") == gate["required_game_config"],
        "inputs": set(observed_inputs) == set(required_inputs)
        and all(
            observed_inputs[role].get("sha256") == digest
            for role, digest in required_inputs.items()
        ),
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
        "required_executor_version",
        "required_runner_version",
        "required_game_config",
        "required_input_sha256",
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
        "required_executor_version",
        "required_runner_version",
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
    required_game = raw["required_game_config"]
    required_inputs = raw["required_input_sha256"]
    if not isinstance(required_game, dict) or not isinstance(required_inputs, dict):
        raise QuickSimFormalGateError("formal gate run requirements are invalid")
    if any(
        not isinstance(role, str)
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        for role, digest in required_inputs.items()
    ):
        raise QuickSimFormalGateError("formal gate required input hashes are invalid")


def _run_configuration(
    manifest: dict[str, Any], checkpoint_path: Path
) -> tuple[str, dict[str, Any]]:
    version = manifest.get("version")
    if not isinstance(version, str) or not version.strip():
        raise QuickSimFormalGateError("formal gate run manifest version is invalid")
    checkpoint = manifest.get("checkpoint")
    configuration = manifest.get("configuration")
    if not isinstance(checkpoint, dict) or not isinstance(configuration, dict):
        raise QuickSimFormalGateError("quick-sim run manifest schema differs")
    if checkpoint.get("sha256") != sha256_file(checkpoint_path):
        raise QuickSimFormalGateError("run manifest checkpoint hash differs")
    inputs = configuration.get("inputs")
    if not isinstance(inputs, dict) or any(
        not isinstance(value, dict) for value in inputs.values()
    ):
        raise QuickSimFormalGateError("quick-sim run manifest inputs differ")
    return version, cast(dict[str, Any], configuration)


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
