"""Reconcile a locally reduced event dataset against pinned NBA team totals."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.nba_reference import calculate_nba_reference_totals
from courtsim.artifacts import sha256_file

NBA_DATA_AUDIT_VERSION = 1
_COMPARISON_ORDER = (
    "teams",
    "games",
    "field_goals_made",
    "field_goal_attempts",
    "three_points_made",
    "three_point_attempts",
    "free_throws_made",
    "free_throw_attempts",
    "turnovers",
    "rebounds",
)
_DERIVED_REQUIREMENTS = {
    "field_goal_percentage": ("field_goals_made", "field_goal_attempts"),
    "three_point_percentage": ("three_points_made", "three_point_attempts"),
    "free_throw_percentage": ("free_throws_made", "free_throw_attempts"),
    "turnovers_per_game": ("turnovers", "games"),
}


class NbaDataAuditError(ValueError):
    """Raised when an NBA source audit cannot be trusted."""


def build_nba_data_audit(
    summary_path: str | Path,
    core_snapshot_path: str | Path,
    free_throw_snapshot_path: str | Path,
    *,
    tolerance: float = 0.001,
    warning_multiplier: float = 5.0,
) -> dict[str, object]:
    """Build a compact pass/warning/rejected report for overlapping metrics."""
    if not math.isfinite(tolerance) or not 0.0 <= tolerance < 1.0:
        raise NbaDataAuditError("tolerance must be finite and between 0 and 1")
    if not math.isfinite(warning_multiplier) or warning_multiplier <= 1.0:
        raise NbaDataAuditError("warning_multiplier must be finite and greater than 1")
    summary_file = Path(summary_path).resolve()
    core_file = Path(core_snapshot_path).resolve()
    free_throw_file = Path(free_throw_snapshot_path).resolve()
    summary = _load_object(summary_file, "NBA event summary")
    if summary.get("schema_version") != 1:
        raise NbaDataAuditError("NBA event summary schema_version must be 1")
    season = _text(summary.get("season"), "summary.season")
    metrics = _mapping(summary.get("metrics"), "summary.metrics")
    source = _mapping(summary.get("source"), "summary.source")
    source_hash = _sha256_text(source.get("sha256"), "summary.source.sha256")
    raw_bytes = source.get("bytes")
    if not isinstance(raw_bytes, int) or raw_bytes <= 0:
        raise NbaDataAuditError("summary.source.bytes must be a positive integer")
    reference = calculate_nba_reference_totals(core_file, free_throw_file)
    reference_values: dict[str, float | int] = {
        **reference,
        "field_goal_percentage": (reference["field_goals_made"] / reference["field_goal_attempts"]),
        "three_point_percentage": (
            reference["three_points_made"] / reference["three_point_attempts"]
        ),
        "free_throw_percentage": (reference["free_throws_made"] / reference["free_throw_attempts"]),
        "turnovers_per_game": reference["turnovers"] / reference["games"],
    }
    comparisons: list[dict[str, object]] = []
    status_by_metric: dict[str, str] = {}
    compared_metrics = (*_COMPARISON_ORDER, *_DERIVED_REQUIREMENTS)
    for metric in compared_metrics:
        observed = _metric_number(metrics.get(metric), metric)
        expected = reference_values[metric]
        absolute_difference = abs(observed - expected)
        denominator = abs(float(expected)) if expected != 0 else 1.0
        relative_difference = absolute_difference / denominator
        status = (
            "pass"
            if relative_difference <= tolerance
            else "warning"
            if relative_difference <= tolerance * warning_multiplier
            else "rejected"
        )
        status_by_metric[metric] = status
        comparisons.append(
            {
                "metric": metric,
                "event_value": observed,
                "reference_value": expected,
                "absolute_difference": round(absolute_difference, 12),
                "relative_difference": round(relative_difference, 12),
                "status": status,
            }
        )
    direct_promotable = [
        metric for metric in _COMPARISON_ORDER if status_by_metric[metric] == "pass"
    ]
    derived_promotable = [
        metric
        for metric, requirements in _DERIVED_REQUIREMENTS.items()
        if status_by_metric[metric] == "pass"
        and all(status_by_metric[requirement] == "pass" for requirement in requirements)
    ]
    rejected = [metric for metric in compared_metrics if status_by_metric[metric] == "rejected"]
    warnings = [metric for metric in compared_metrics if status_by_metric[metric] == "warning"]
    unmatched = sorted(set(metrics) - set(_COMPARISON_ORDER) - set(_DERIVED_REQUIREMENTS))
    return {
        "schema_version": NBA_DATA_AUDIT_VERSION,
        "audit_id": f"{_text(summary.get('dataset_id'), 'summary.dataset_id')}-source-audit-v1",
        "season": season,
        "status": (
            "partial"
            if rejected and (direct_promotable or derived_promotable)
            else "rejected"
            if rejected
            else "warning"
            if warnings
            else "passed"
        ),
        "thresholds": {
            "pass_relative_difference": tolerance,
            "warning_relative_difference": tolerance * warning_multiplier,
        },
        "sources": {
            "event_summary": {
                "path": summary_file.name,
                "sha256": sha256_file(summary_file),
                "raw_source_sha256": source_hash,
                "raw_source_bytes": raw_bytes,
            },
            "core_snapshot": {
                "path": core_file.name,
                "sha256": sha256_file(core_file),
            },
            "free_throw_snapshot": {
                "path": free_throw_file.name,
                "sha256": sha256_file(free_throw_file),
            },
        },
        "comparisons": comparisons,
        "promotion": {
            "direct_metrics": direct_promotable,
            "derived_metrics": derived_promotable,
            "warning_metrics": warnings,
            "rejected_metrics": rejected,
            "unmatched_event_metrics": unmatched,
        },
        "summary": {
            "compared": len(comparisons),
            "passed": len(comparisons) - len(warnings) - len(rejected),
            "warnings": len(warnings),
            "rejected": len(rejected),
        },
    }


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NbaDataAuditError(f"cannot load {label}: {path}") from error
    if not isinstance(value, dict):
        raise NbaDataAuditError(f"{label} root must be an object")
    return cast(dict[str, Any], value)


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise NbaDataAuditError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NbaDataAuditError(f"{field} must be a non-empty string")
    return value.strip()


def _sha256_text(value: object, field: str) -> str:
    digest = _text(value, field).lower()
    if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
        raise NbaDataAuditError(f"{field} must be a SHA-256 digest")
    return digest


def _metric_number(value: object, metric: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise NbaDataAuditError(f"summary metric {metric} must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise NbaDataAuditError(f"summary metric {metric} must be finite and non-negative")
    return value
