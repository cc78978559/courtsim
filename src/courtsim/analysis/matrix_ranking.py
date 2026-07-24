"""Integrity-checked ranking of completed experiment-matrix cells."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.audit_gates import load_distribution_audit
from courtsim.analysis.realism_targets import (
    load_realism_target_set,
    realism_score_report_to_json,
    score_audit_against_realism_targets,
)
from courtsim.artifacts import sha256_file, write_json
from courtsim.verification import verify_manifest


class MatrixRankingError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class CandidateAssessment:
    cell_id: str
    eligible: bool
    active_targets: int
    failed_active_targets: int
    required_failures: int
    center_weighted_rmse: float | None
    result_path: str
    plan_sha256: str
    audit_sha256: str

    @property
    def ranking_key(self) -> tuple[bool, int, int, float]:
        return (
            not self.eligible,
            self.required_failures,
            self.failed_active_targets,
            (self.center_weighted_rmse if self.center_weighted_rmse is not None else math.inf),
        )


def _load_object(path: Path, context: str) -> dict[str, Any]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MatrixRankingError(f"cannot load {context}: {path}") from error
    if not isinstance(raw, dict):
        raise MatrixRankingError(f"{context} must contain an object")
    return cast(dict[str, Any], raw)


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verify_hashed_path(raw: object, context: str) -> Path:
    if not isinstance(raw, dict):
        raise MatrixRankingError(f"{context} must be an object")
    path = raw.get("path")
    expected = raw.get("sha256")
    if not isinstance(path, str) or not isinstance(expected, str):
        raise MatrixRankingError(f"{context} requires path and sha256 strings")
    resolved = Path(path)
    if not resolved.is_file() or sha256_file(resolved) != expected:
        raise MatrixRankingError(f"{context} file is missing or changed: {resolved}")
    return resolved


def center_error_components(score: dict[str, Any], context: str) -> tuple[float, float]:
    metrics = score.get("metric_results")
    if not isinstance(metrics, list):
        raise MatrixRankingError(f"{context}.metric_results must be a list")
    weighted_squared = 0.0
    total_weight = 0.0
    for index, metric in enumerate(metrics):
        if not isinstance(metric, dict):
            raise MatrixRankingError(f"{context}.metric_results[{index}] must be an object")
        try:
            value = float(metric["value"])
            target = float(metric["target"])
            lower = float(metric["lower"])
            upper = float(metric["upper"])
            weight = float(metric["weight"])
        except (KeyError, TypeError, ValueError) as error:
            raise MatrixRankingError(
                f"{context}.metric_results[{index}] has invalid numerics"
            ) from error
        if (
            not all(math.isfinite(item) for item in (value, target, lower, upper, weight))
            or lower > target
            or target > upper
            or weight <= 0
        ):
            raise MatrixRankingError(f"{context}.metric_results[{index}] is invalid")
        scale = max(upper - lower, abs(target) * 0.05, 1e-12)
        distance = (value - target) / scale
        weighted_squared += weight * distance * distance
        total_weight += weight
    return weighted_squared, total_weight


def assess_matrix_candidate(
    report_directory: Path,
    row: dict[str, Any],
) -> CandidateAssessment:
    cell_id = row.get("cell_id")
    raw_result_path = row.get("result")
    if not isinstance(cell_id, str) or not isinstance(raw_result_path, str):
        raise MatrixRankingError("matrix cell row requires cell_id and result")
    result_path = report_directory / raw_result_path
    result = _load_object(result_path, f"cell {cell_id} result")
    if result.get("status") != "completed":
        raise MatrixRankingError(f"completed matrix row has non-completed result: {cell_id}")
    plan = result.get("plan")
    plan_sha256 = result.get("plan_sha256")
    if (
        not isinstance(plan, dict)
        or not isinstance(plan_sha256, str)
        or _canonical_hash(plan) != plan_sha256
        or row.get("plan_sha256") != plan_sha256
    ):
        raise MatrixRankingError(f"cell {cell_id} plan hash mismatch")
    inputs = plan.get("inputs")
    target_sources = plan.get("targets")
    if not isinstance(inputs, dict) or not isinstance(target_sources, list):
        raise MatrixRankingError(f"cell {cell_id} plan provenance is invalid")
    for name in ("schema", "parameters", "profile"):
        _verify_hashed_path(inputs.get(name), f"cell {cell_id} input {name}")
    if "opponent_profile" in inputs:
        _verify_hashed_path(
            inputs.get("opponent_profile"),
            f"cell {cell_id} input opponent_profile",
        )
    verified_target_sources = tuple(
        _verify_hashed_path(target, f"cell {cell_id} target source {index}")
        for index, target in enumerate(target_sources)
    )

    raw_manifest = result.get("manifest")
    raw_audit = result.get("audit")
    expected_audit = result.get("audit_sha256")
    if not all(isinstance(item, str) for item in (raw_manifest, raw_audit, expected_audit)):
        raise MatrixRankingError(f"cell {cell_id} artifact paths are invalid")
    manifest_path = result_path.parent / cast(str, raw_manifest)
    audit_path = result_path.parent / cast(str, raw_audit)
    verification = verify_manifest(manifest_path)
    if not verification.ok:
        raise MatrixRankingError(f"cell {cell_id} manifest verification failed")
    if not audit_path.is_file() or sha256_file(audit_path) != expected_audit:
        raise MatrixRankingError(f"cell {cell_id} audit hash mismatch")
    audit = load_distribution_audit(audit_path)

    raw_targets = result.get("targets")
    if not isinstance(raw_targets, list):
        raise MatrixRankingError(f"cell {cell_id} targets must be a list")
    if len(raw_targets) != len(verified_target_sources):
        raise MatrixRankingError(f"cell {cell_id} target count mismatch")
    active_targets = 0
    failed_active_targets = 0
    required_failures = 0
    weighted_squared = 0.0
    total_weight = 0.0
    for index, target in enumerate(raw_targets):
        if not isinstance(target, dict):
            raise MatrixRankingError(f"cell {cell_id} target {index} is invalid")
        score_path = _verify_hashed_path(
            {
                "path": str(result_path.parent / str(target.get("path"))),
                "sha256": target.get("sha256"),
            },
            f"cell {cell_id} target report {index}",
        )
        score = _load_object(score_path, f"cell {cell_id} target report {index}")
        expected_score = json.loads(
            realism_score_report_to_json(
                score_audit_against_realism_targets(
                    audit,
                    load_realism_target_set(verified_target_sources[index]),
                )
            )
        )
        if score != expected_score:
            raise MatrixRankingError(f"cell {cell_id} target report {index} is stale")
        if score.get("target_set_id") != target.get("target_set_id"):
            raise MatrixRankingError(f"cell {cell_id} target id mismatch")
        gate_passed = score.get("gate_passed")
        if gate_passed is not None and not isinstance(gate_passed, bool):
            raise MatrixRankingError(f"cell {cell_id} target gate is invalid")
        if isinstance(gate_passed, bool):
            active_targets += 1
            failed_active_targets += not gate_passed
        failures = score.get("required_failures")
        if not isinstance(failures, int) or isinstance(failures, bool) or failures < 0:
            raise MatrixRankingError(f"cell {cell_id} target failures are invalid")
        required_failures += failures
        squared, weight = center_error_components(score, f"cell {cell_id} target {index}")
        weighted_squared += squared
        total_weight += weight
    center_rmse = math.sqrt(weighted_squared / total_weight) if total_weight else None
    eligible = active_targets > 0 and failed_active_targets == 0 and required_failures == 0
    return CandidateAssessment(
        cell_id,
        eligible,
        active_targets,
        failed_active_targets,
        required_failures,
        center_rmse,
        raw_result_path,
        plan_sha256,
        cast(str, expected_audit),
    )


def rank_candidate_assessments(
    candidates: tuple[CandidateAssessment, ...],
) -> tuple[tuple[CandidateAssessment, ...], str, tuple[str, ...]]:
    ordered = tuple(sorted(candidates, key=lambda item: (*item.ranking_key, item.cell_id)))
    eligible = tuple(item for item in ordered if item.eligible)
    if not eligible:
        return ordered, "no-eligible-candidate", ()
    best_key = eligible[0].ranking_key
    best = tuple(item.cell_id for item in eligible if item.ranking_key == best_key)
    return ordered, ("single-candidate" if len(best) == 1 else "tie"), best


def _target_signature(report_directory: Path, row: dict[str, Any]) -> tuple[str, ...]:
    result = _load_object(
        report_directory / cast(str, row["result"]),
        f"cell {row['cell_id']} result",
    )
    plan = result.get("plan")
    if not isinstance(plan, dict):
        raise MatrixRankingError(f"cell {row['cell_id']} plan is invalid")
    targets = plan.get("targets")
    if not isinstance(targets, list):
        raise MatrixRankingError(f"cell {row['cell_id']} targets are invalid")
    signature: list[str] = []
    for index, target in enumerate(targets):
        if not isinstance(target, dict):
            raise MatrixRankingError(f"cell {row['cell_id']} target {index} is invalid")
        path = target.get("path")
        digest = target.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str):
            raise MatrixRankingError(f"cell {row['cell_id']} target {index} provenance is invalid")
        signature.append(f"{path}\0{digest}")
    return tuple(signature)


def rank_experiment_matrix(
    *,
    matrix_report_path: str | Path,
    output_path: str | Path,
) -> Path:
    report_path = Path(matrix_report_path).resolve()
    report = _load_object(report_path, "matrix report")
    if report.get("kind") != "courtsim-experiment-matrix":
        raise MatrixRankingError("unsupported matrix report kind")
    raw_spec = report.get("spec_path")
    expected_spec = report.get("spec_sha256")
    if (
        not isinstance(raw_spec, str)
        or not isinstance(expected_spec, str)
        or not Path(raw_spec).is_file()
        or sha256_file(raw_spec) != expected_spec
    ):
        raise MatrixRankingError("matrix spec is missing or changed")
    raw_cells = report.get("cells")
    if not isinstance(raw_cells, list):
        raise MatrixRankingError("matrix report cells must be a list")
    completed_rows: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    for index, row in enumerate(raw_cells):
        if not isinstance(row, dict):
            raise MatrixRankingError(f"matrix cell row {index} must be an object")
        row = cast(dict[str, Any], row)
        if row.get("status") == "completed":
            completed_rows.append(row)
        else:
            excluded.append(
                {
                    "cell_id": str(row.get("cell_id")),
                    "reason": "matrix-cell-not-completed",
                }
            )
    candidates = tuple(assess_matrix_candidate(report_path.parent, row) for row in completed_rows)
    target_signatures = {_target_signature(report_path.parent, row) for row in completed_rows}
    if len(target_signatures) > 1:
        raise MatrixRankingError(
            "heterogeneous per-cell target sets cannot be ranked; use matrix-style-coverage"
        )
    ordered, recommendation_status, recommended = rank_candidate_assessments(candidates)
    ranking_rows = [
        {
            "rank": index,
            **asdict(candidate),
        }
        for index, candidate in enumerate(ordered, start=1)
    ]
    output = Path(output_path)
    write_json(
        output,
        {
            "format_version": 1,
            "kind": "courtsim-matrix-candidate-ranking",
            "source": {
                "matrix_report": str(report_path),
                "matrix_report_sha256": sha256_file(report_path),
                "matrix_id": report.get("matrix_id"),
            },
            "policy": {
                "eligibility": (
                    "at least one active target; all active gates pass; "
                    "zero required metric failures"
                ),
                "ordering": [
                    "eligible candidates first",
                    "fewer required metric failures",
                    "fewer failed active targets",
                    "lower target-center weighted RMSE",
                    "cell_id for deterministic display only",
                ],
                "automatic_promotion": False,
            },
            "recommendation": {
                "status": recommendation_status,
                "candidate_cell_ids": list(recommended),
                "automatic_promotion": False,
            },
            "summary": {
                "matrix_cells": len(raw_cells),
                "ranked_candidates": len(ordered),
                "eligible_candidates": sum(item.eligible for item in ordered),
                "excluded_cells": len(excluded),
            },
            "ranking": ranking_rows,
            "excluded": excluded,
        },
    )
    return output
