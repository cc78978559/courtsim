"""Paired-seed counterfactual gates for completed experiment matrices."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.audit_gates import audit_metric_map, load_distribution_audit
from courtsim.analysis.experiment_matrix import CELL_ID_PATTERN
from courtsim.analysis.matrix_ranking import (
    MatrixRankingError,
    assess_matrix_candidate,
)
from courtsim.artifacts import sha256_file, write_json


class MatrixContrastError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ContrastGate:
    metric: str
    minimum_delta: float
    maximum_delta: float


@dataclass(frozen=True, slots=True)
class ContrastDefinition:
    contrast_id: str
    baseline_cell_id: str
    candidate_cell_id: str
    gates: tuple[ContrastGate, ...]


@dataclass(frozen=True, slots=True)
class MatrixContrastSpec:
    contrast_set_id: str
    comparisons: tuple[ContrastDefinition, ...]


def _load_object(path: Path, context: str) -> dict[str, Any]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MatrixContrastError(f"cannot load {context}: {path}") from error
    if not isinstance(raw, dict):
        raise MatrixContrastError(f"{context} must contain an object")
    return cast(dict[str, Any], raw)


def _exact_keys(raw: dict[str, Any], expected: set[str], context: str) -> None:
    if set(raw) != expected:
        raise MatrixContrastError(f"{context} keys must be exactly {sorted(expected)}")


def _identifier(value: object, context: str) -> str:
    if not isinstance(value, str) or not CELL_ID_PATTERN.fullmatch(value):
        raise MatrixContrastError(f"{context} must be a lowercase ASCII identifier")
    return value


def _number(value: object, context: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise MatrixContrastError(f"{context} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise MatrixContrastError(f"{context} must be finite")
    return result


def load_matrix_contrast_spec(path: str | Path) -> MatrixContrastSpec:
    source = Path(path)
    raw = _load_object(source, "matrix contrast spec")
    _exact_keys(
        raw,
        {"format_version", "kind", "contrast_set_id", "comparisons"},
        "contrast spec",
    )
    if raw["format_version"] != 1 or raw["kind"] != "courtsim-matrix-contrast-spec":
        raise MatrixContrastError("unsupported matrix contrast spec")
    contrast_set_id = _identifier(raw["contrast_set_id"], "contrast_set_id")
    raw_comparisons = raw["comparisons"]
    if not isinstance(raw_comparisons, list) or not raw_comparisons:
        raise MatrixContrastError("comparisons must be a non-empty list")
    comparisons: list[ContrastDefinition] = []
    for comparison_index, raw_comparison in enumerate(raw_comparisons):
        if not isinstance(raw_comparison, dict):
            raise MatrixContrastError(f"comparisons[{comparison_index}] must be an object")
        comparison = cast(dict[str, Any], raw_comparison)
        _exact_keys(
            comparison,
            {
                "contrast_id",
                "baseline_cell_id",
                "candidate_cell_id",
                "gates",
            },
            f"comparisons[{comparison_index}]",
        )
        contrast_id = _identifier(
            comparison["contrast_id"],
            f"comparisons[{comparison_index}].contrast_id",
        )
        baseline_id = _identifier(
            comparison["baseline_cell_id"],
            f"comparisons[{comparison_index}].baseline_cell_id",
        )
        candidate_id = _identifier(
            comparison["candidate_cell_id"],
            f"comparisons[{comparison_index}].candidate_cell_id",
        )
        if baseline_id == candidate_id:
            raise MatrixContrastError(
                f"comparisons[{comparison_index}] must use two different cells"
            )
        raw_gates = comparison["gates"]
        if not isinstance(raw_gates, list) or not raw_gates:
            raise MatrixContrastError(f"comparisons[{comparison_index}].gates must be non-empty")
        gates: list[ContrastGate] = []
        for gate_index, raw_gate in enumerate(raw_gates):
            if not isinstance(raw_gate, dict):
                raise MatrixContrastError(
                    f"comparisons[{comparison_index}].gates[{gate_index}] is invalid"
                )
            gate = cast(dict[str, Any], raw_gate)
            _exact_keys(
                gate,
                {"metric", "minimum_delta", "maximum_delta"},
                f"comparisons[{comparison_index}].gates[{gate_index}]",
            )
            metric = gate["metric"]
            if not isinstance(metric, str) or not metric:
                raise MatrixContrastError(
                    f"comparisons[{comparison_index}].gates[{gate_index}].metric is invalid"
                )
            minimum = _number(
                gate["minimum_delta"],
                f"comparisons[{comparison_index}].gates[{gate_index}].minimum_delta",
            )
            maximum = _number(
                gate["maximum_delta"],
                f"comparisons[{comparison_index}].gates[{gate_index}].maximum_delta",
            )
            if minimum > maximum:
                raise MatrixContrastError(
                    f"comparisons[{comparison_index}].gates[{gate_index}] has inverted bounds"
                )
            gates.append(ContrastGate(metric, minimum, maximum))
        if len({gate.metric for gate in gates}) != len(gates):
            raise MatrixContrastError(
                f"comparisons[{comparison_index}] gate metrics must be unique"
            )
        comparisons.append(
            ContrastDefinition(
                contrast_id,
                baseline_id,
                candidate_id,
                tuple(gates),
            )
        )
    if len({comparison.contrast_id for comparison in comparisons}) != len(comparisons):
        raise MatrixContrastError("contrast_id values must be unique")
    return MatrixContrastSpec(contrast_set_id, tuple(comparisons))


def _cell_artifacts(
    *,
    matrix_directory: Path,
    ranking_row: dict[str, Any],
) -> tuple[dict[str, Any], Path]:
    raw_result_path = ranking_row.get("result_path")
    if not isinstance(raw_result_path, str):
        raise MatrixContrastError("ranking result path is invalid")
    result_path = matrix_directory / raw_result_path
    result = _load_object(result_path, "matrix cell result")
    raw_audit = result.get("audit")
    expected_audit_hash = result.get("audit_sha256")
    if not isinstance(raw_audit, str) or not isinstance(expected_audit_hash, str):
        raise MatrixContrastError("matrix cell audit provenance is invalid")
    audit_path = result_path.parent / raw_audit
    if not audit_path.is_file() or sha256_file(audit_path) != expected_audit_hash:
        raise MatrixContrastError(f"matrix cell audit is missing or changed: {audit_path}")
    return result, audit_path


def _paired_plan_error(
    baseline_plan: object,
    candidate_plan: object,
) -> str | None:
    if not isinstance(baseline_plan, dict) or not isinstance(candidate_plan, dict):
        return "cell plans are invalid"
    if baseline_plan.get("seed") != candidate_plan.get("seed"):
        return "cells do not share a paired seed; assign the same seed_group"
    for field in ("games", "start_index", "clock"):
        if baseline_plan.get(field) != candidate_plan.get(field):
            return f"cell plans differ in {field}"
    return None


def run_matrix_contrasts(
    *,
    matrix_report_path: str | Path,
    spec_path: str | Path,
    output_directory: str | Path,
) -> Path:
    matrix_report = Path(matrix_report_path).resolve()
    contrast_spec_path = Path(spec_path).resolve()
    destination = Path(output_directory)
    report_path = destination / "contrast-report.json"
    if report_path.exists():
        raise MatrixContrastError(f"contrast report already exists: {report_path}")
    spec = load_matrix_contrast_spec(contrast_spec_path)
    matrix_payload = _load_object(matrix_report, "matrix report")
    raw_cells = matrix_payload.get("cells")
    if matrix_payload.get("kind") != "courtsim-experiment-matrix" or not isinstance(
        raw_cells, list
    ):
        raise MatrixContrastError("source matrix report is invalid")
    raw_ranking: list[dict[str, Any]] = []
    try:
        for index, raw_cell in enumerate(raw_cells):
            if not isinstance(raw_cell, dict):
                raise MatrixContrastError(f"matrix cell row {index} is invalid")
            if raw_cell.get("status") == "completed":
                raw_ranking.append(
                    asdict(
                        assess_matrix_candidate(
                            matrix_report.parent,
                            cast(dict[str, Any], raw_cell),
                        )
                    )
                )
    except MatrixRankingError as error:
        raise MatrixContrastError(str(error)) from error
    source_ranking_path = destination / "source-integrity-index.json"
    write_json(
        source_ranking_path,
        {
            "format_version": 1,
            "kind": "courtsim-matrix-contrast-integrity-index",
            "matrix_report": str(matrix_report),
            "matrix_report_sha256": sha256_file(matrix_report),
            "ranking": raw_ranking,
            "cross_cell_ranking": False,
        },
    )
    candidates = {
        str(row.get("cell_id")): row
        for row in raw_ranking
        if isinstance(row, dict) and isinstance(row.get("cell_id"), str)
    }

    comparison_rows: list[dict[str, Any]] = []
    for comparison in spec.comparisons:
        try:
            baseline_row = candidates[comparison.baseline_cell_id]
            candidate_row = candidates[comparison.candidate_cell_id]
            baseline_result, baseline_audit_path = _cell_artifacts(
                matrix_directory=matrix_report.parent,
                ranking_row=baseline_row,
            )
            candidate_result, candidate_audit_path = _cell_artifacts(
                matrix_directory=matrix_report.parent,
                ranking_row=candidate_row,
            )
            plan_error = _paired_plan_error(
                baseline_result.get("plan"),
                candidate_result.get("plan"),
            )
            if plan_error is not None:
                raise MatrixContrastError(plan_error)
            baseline_metrics = audit_metric_map(load_distribution_audit(baseline_audit_path))
            candidate_metrics = audit_metric_map(load_distribution_audit(candidate_audit_path))
            if set(baseline_metrics) != set(candidate_metrics):
                raise MatrixContrastError("cell audit metric sets differ")
            unknown = sorted(
                gate.metric for gate in comparison.gates if gate.metric not in baseline_metrics
            )
            if unknown:
                raise MatrixContrastError(f"unknown contrast metrics: {unknown}")
            gate_rows = []
            for gate in comparison.gates:
                baseline_value = baseline_metrics[gate.metric]
                candidate_value = candidate_metrics[gate.metric]
                delta = candidate_value - baseline_value
                gate_passed = gate.minimum_delta <= delta <= gate.maximum_delta
                gate_rows.append(
                    {
                        "metric": gate.metric,
                        "baseline": baseline_value,
                        "candidate": candidate_value,
                        "delta": delta,
                        "minimum_delta": gate.minimum_delta,
                        "maximum_delta": gate.maximum_delta,
                        "passed": gate_passed,
                    }
                )
            failures = sum(not row["passed"] for row in gate_rows)
            comparison_rows.append(
                {
                    "contrast_id": comparison.contrast_id,
                    "status": "completed",
                    "passed": failures == 0,
                    "baseline_cell_id": comparison.baseline_cell_id,
                    "candidate_cell_id": comparison.candidate_cell_id,
                    "shared_seed": baseline_result["plan"]["seed"],
                    "baseline_audit": str(baseline_audit_path.resolve()),
                    "baseline_audit_sha256": sha256_file(baseline_audit_path),
                    "candidate_audit": str(candidate_audit_path.resolve()),
                    "candidate_audit_sha256": sha256_file(candidate_audit_path),
                    "checked": len(gate_rows),
                    "failures": failures,
                    "gates": gate_rows,
                }
            )
        except (KeyError, ValueError) as error:
            comparison_rows.append(
                {
                    "contrast_id": comparison.contrast_id,
                    "status": "failed",
                    "passed": False,
                    "baseline_cell_id": comparison.baseline_cell_id,
                    "candidate_cell_id": comparison.candidate_cell_id,
                    "error_type": type(error).__name__,
                    "error": str(error),
                }
            )
    completed = [row for row in comparison_rows if row["status"] == "completed"]
    passed_comparisons = [row for row in completed if row["passed"]]
    failed = len(comparison_rows) - len(completed)
    gate_failures = sum(int(row["failures"]) for row in completed)
    write_json(
        report_path,
        {
            "format_version": 1,
            "kind": "courtsim-matrix-contrast-report",
            "contrast_set_id": spec.contrast_set_id,
            "source": {
                "matrix_report": str(matrix_report),
                "matrix_report_sha256": sha256_file(matrix_report),
                "contrast_spec": str(contrast_spec_path),
                "contrast_spec_sha256": sha256_file(contrast_spec_path),
                "source_ranking": source_ranking_path.name,
                "source_ranking_sha256": sha256_file(source_ranking_path),
            },
            "policy": {
                "delta": "candidate minus baseline",
                "paired_seed_required": True,
                "automatic_promotion": False,
            },
            "status": ("passed" if len(passed_comparisons) == len(comparison_rows) else "failed"),
            "summary": {
                "comparisons": len(comparison_rows),
                "completed": len(completed),
                "execution_failures": failed,
                "passed": len(passed_comparisons),
                "failed_gates": gate_failures,
            },
            "comparisons": comparison_rows,
        },
    )
    return report_path
