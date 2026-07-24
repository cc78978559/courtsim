"""Integrity-checked coverage report for heterogeneous team-style targets."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.matrix_ranking import (
    MatrixRankingError,
    assess_matrix_candidate,
)
from courtsim.artifacts import sha256_file, write_json


class MatrixStyleCoverageError(ValueError):
    pass


def _load_object(path: Path, context: str) -> dict[str, Any]:
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise MatrixStyleCoverageError(f"cannot load {context}: {path}") from error
    if not isinstance(raw, dict):
        raise MatrixStyleCoverageError(f"{context} must contain an object")
    return cast(dict[str, Any], raw)


def _metric_row(raw: object, context: str) -> dict[str, object]:
    if not isinstance(raw, dict):
        raise MatrixStyleCoverageError(f"{context} must be an object")
    required = {
        "metric",
        "value",
        "lower",
        "target",
        "upper",
        "required",
        "direction",
        "normalized_distance",
    }
    if not required <= set(raw):
        raise MatrixStyleCoverageError(f"{context} is incomplete")
    metric = raw["metric"]
    direction = raw["direction"]
    required_flag = raw["required"]
    if (
        not isinstance(metric, str)
        or direction not in {"IN_RANGE", "LOW", "HIGH"}
        or not isinstance(required_flag, bool)
    ):
        raise MatrixStyleCoverageError(f"{context} has invalid labels")
    numbers: dict[str, float] = {}
    for field in ("value", "lower", "target", "upper", "normalized_distance"):
        value = raw[field]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise MatrixStyleCoverageError(f"{context}.{field} is invalid")
        numbers[field] = float(value)
    return {
        "metric": metric,
        **numbers,
        "required": required_flag,
        "direction": direction,
    }


def build_matrix_style_coverage(
    *,
    matrix_report_path: str | Path,
    output_path: str | Path,
) -> Path:
    report_path = Path(matrix_report_path).resolve()
    report = _load_object(report_path, "matrix report")
    if report.get("kind") != "courtsim-experiment-matrix":
        raise MatrixStyleCoverageError("unsupported matrix report kind")
    raw_cells = report.get("cells")
    if not isinstance(raw_cells, list):
        raise MatrixStyleCoverageError("matrix report cells must be a list")

    cells: list[dict[str, object]] = []
    values_by_metric: dict[str, list[float]] = {}
    integrity_checked = 0
    total_metrics = 0
    total_in_range = 0
    for index, raw_row in enumerate(raw_cells):
        if not isinstance(raw_row, dict):
            raise MatrixStyleCoverageError(f"matrix cell row {index} is invalid")
        row = cast(dict[str, Any], raw_row)
        if row.get("status") != "completed":
            continue
        try:
            assessment = assess_matrix_candidate(report_path.parent, row)
        except MatrixRankingError as error:
            raise MatrixStyleCoverageError(str(error)) from error
        integrity_checked += 1
        result_path = report_path.parent / assessment.result_path
        result = _load_object(result_path, f"cell {assessment.cell_id} result")
        raw_targets = result.get("targets")
        if not isinstance(raw_targets, list):
            raise MatrixStyleCoverageError(f"cell {assessment.cell_id} targets must be a list")
        target_rows: list[dict[str, object]] = []
        for target_index, raw_target in enumerate(raw_targets):
            if not isinstance(raw_target, dict):
                raise MatrixStyleCoverageError(
                    f"cell {assessment.cell_id} target {target_index} is invalid"
                )
            score_path = result_path.parent / str(raw_target.get("path"))
            score = _load_object(
                score_path,
                f"cell {assessment.cell_id} target score {target_index}",
            )
            raw_metrics = score.get("metric_results")
            if not isinstance(raw_metrics, list):
                raise MatrixStyleCoverageError(
                    f"cell {assessment.cell_id} score metrics must be a list"
                )
            metrics = [
                _metric_row(
                    metric,
                    f"cell {assessment.cell_id} metric {metric_index}",
                )
                for metric_index, metric in enumerate(raw_metrics)
            ]
            for metric in metrics:
                metric_name = cast(str, metric["metric"])
                values_by_metric.setdefault(metric_name, []).append(cast(float, metric["value"]))
            in_range = sum(metric["direction"] == "IN_RANGE" for metric in metrics)
            total_metrics += len(metrics)
            total_in_range += in_range
            target_rows.append(
                {
                    "target_set_id": score.get("target_set_id"),
                    "gate_passed": score.get("gate_passed"),
                    "required_failures": score.get("required_failures"),
                    "weighted_rmse": score.get("weighted_rmse"),
                    "metrics_in_range": in_range,
                    "metrics_evaluated": len(metrics),
                    "metrics": metrics,
                }
            )
        cells.append(
            {
                "cell_id": assessment.cell_id,
                "audit_sha256": assessment.audit_sha256,
                "targets": target_rows,
            }
        )

    constants = [
        {
            "metric": metric,
            "value": values[0],
            "cells_observed": len(values),
        }
        for metric, values in sorted(values_by_metric.items())
        if len(values) >= 2 and max(values) - min(values) <= 1e-12
    ]
    output = Path(output_path)
    write_json(
        output,
        {
            "format_version": 1,
            "kind": "courtsim-matrix-style-coverage",
            "source": {
                "matrix_report": str(report_path),
                "matrix_report_sha256": sha256_file(report_path),
                "matrix_id": report.get("matrix_id"),
            },
            "policy": {
                "purpose": "coverage audit across heterogeneous team-style targets",
                "cross_cell_ranking": False,
                "automatic_promotion": False,
            },
            "summary": {
                "cells": len(cells),
                "integrity_checked": integrity_checked,
                "metrics_evaluated": total_metrics,
                "metrics_in_range": total_in_range,
                "coverage_rate": (total_in_range / total_metrics if total_metrics else None),
                "constant_metrics": len(constants),
            },
            "constant_metrics": constants,
            "cells": cells,
        },
    )
    return output
