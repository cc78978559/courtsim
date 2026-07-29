"""Reconcile locally reduced NBA event and possession datasets with pinned totals."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.nba_reference import (
    calculate_nba_core_totals,
    calculate_nba_reference_totals,
)
from courtsim.artifacts import sha256_file

NBA_DATA_AUDIT_VERSION = 1
_EVENT_TOTALS = (
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
_EVENT_DERIVED = {
    "field_goal_percentage": ("field_goals_made", "field_goal_attempts"),
    "three_point_percentage": ("three_points_made", "three_point_attempts"),
    "free_throw_percentage": ("free_throws_made", "free_throw_attempts"),
    "turnovers_per_game": ("turnovers", "games"),
}
_POSSESSION_METRICS = (
    "teams",
    "games",
    "possessions",
    "two_points_made",
    "two_point_attempts",
    "three_points_made",
    "three_point_attempts",
    "turnovers",
    "offensive_rebounds",
    "combined_possessions_per_game",
    "two_point_percentage",
    "three_point_percentage",
    "turnover_per_possession",
)
_SHOT_METRICS = (
    "teams",
    "games",
    "field_goals_made",
    "field_goal_attempts",
    "three_points_made",
    "three_point_attempts",
    "field_goal_percentage",
    "three_point_percentage",
)


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
    """Build a compact audit for play-by-play events and traditional team totals."""
    _validate_thresholds(tolerance, warning_multiplier)
    summary_file, summary, metrics, source = _load_summary(summary_path, "NBA event summary")
    core_file = Path(core_snapshot_path).resolve()
    free_throw_file = Path(free_throw_snapshot_path).resolve()
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
    compared = (*_EVENT_TOTALS, *_EVENT_DERIVED)
    comparisons, passed, warnings, rejected = _compare(
        metrics,
        reference_values,
        compared,
        "event_value",
        tolerance,
        warning_multiplier,
    )
    direct_promotable = [metric for metric in _EVENT_TOTALS if metric in passed]
    derived_promotable = [
        metric
        for metric, requirements in _EVENT_DERIVED.items()
        if metric in passed and all(requirement in passed for requirement in requirements)
    ]
    return {
        "schema_version": NBA_DATA_AUDIT_VERSION,
        "audit_id": f"{_text(summary.get('dataset_id'), 'summary.dataset_id')}-source-audit-v1",
        "season": _text(summary.get("season"), "summary.season"),
        "status": _overall_status(passed, warnings, rejected),
        "thresholds": _threshold_payload(tolerance, warning_multiplier),
        "sources": {
            "event_summary": _summary_source(summary_file, source),
            "core_snapshot": _file_source(core_file),
            "free_throw_snapshot": _file_source(free_throw_file),
        },
        "comparisons": comparisons,
        "promotion": {
            "direct_metrics": direct_promotable,
            "derived_metrics": derived_promotable,
            "warning_metrics": warnings,
            "rejected_metrics": rejected,
            "unmatched_event_metrics": sorted(set(metrics) - set(compared)),
        },
        "summary": _summary_counts(comparisons, warnings, rejected),
    }


def build_nba_possession_audit(
    summary_path: str | Path,
    core_snapshot_path: str | Path,
    *,
    tolerance: float = 0.001,
    warning_multiplier: float = 5.0,
) -> dict[str, object]:
    """Audit deduplicated possession aggregates without conflating POSS semantics."""
    _validate_thresholds(tolerance, warning_multiplier)
    summary_file, summary, metrics, source = _load_summary(summary_path, "NBA possession summary")
    core_file = Path(core_snapshot_path).resolve()
    reference = calculate_nba_core_totals(core_file)
    two_points_made = reference["field_goals_made"] - reference["three_points_made"]
    two_point_attempts = reference["field_goal_attempts"] - reference["three_point_attempts"]
    reference_values: dict[str, float | int] = {
        "teams": reference["teams"],
        "games": reference["games"],
        "possessions": reference["possessions"],
        "two_points_made": two_points_made,
        "two_point_attempts": two_point_attempts,
        "three_points_made": reference["three_points_made"],
        "three_point_attempts": reference["three_point_attempts"],
        "turnovers": reference["turnovers"],
        "offensive_rebounds": reference["offensive_rebounds"],
        "combined_possessions_per_game": reference["possessions"] / reference["games"],
        "two_point_percentage": two_points_made / two_point_attempts,
        "three_point_percentage": (
            reference["three_points_made"] / reference["three_point_attempts"]
        ),
        "turnover_per_possession": reference["turnovers"] / reference["possessions"],
    }
    comparisons, passed, warnings, rejected = _compare(
        metrics,
        reference_values,
        _POSSESSION_METRICS,
        "possession_value",
        tolerance,
        warning_multiplier,
    )
    return {
        "schema_version": NBA_DATA_AUDIT_VERSION,
        "audit_id": f"{_text(summary.get('dataset_id'), 'summary.dataset_id')}-audit-v1",
        "season": _text(summary.get("season"), "summary.season"),
        "status": _overall_status(passed, warnings, rejected),
        "notes": (
            "Pinned NBA POSS is a team aggregate while pbpstats possessions are event-boundary "
            "groups. A failed possession count marks a semantic boundary and does not invalidate "
            "source-only duration metrics."
        ),
        "thresholds": _threshold_payload(tolerance, warning_multiplier),
        "sources": {
            "possession_summary": _summary_source(summary_file, source),
            "core_snapshot": _file_source(core_file),
        },
        "comparisons": comparisons,
        "promotion": {
            "reconciled_metrics": passed,
            "warning_metrics": warnings,
            "rejected_metrics": rejected,
            "source_only_metrics": sorted(set(metrics) - set(_POSSESSION_METRICS)),
        },
        "summary": _summary_counts(comparisons, warnings, rejected),
    }


def build_nba_shot_audit(
    summary_path: str | Path,
    core_snapshot_path: str | Path,
    *,
    tolerance: float = 0.001,
    warning_multiplier: float = 5.0,
) -> dict[str, object]:
    """Reconcile shot-detail totals while retaining zones as source-only targets."""
    _validate_thresholds(tolerance, warning_multiplier)
    summary_file, summary, metrics, source = _load_summary(summary_path, "NBA shot summary")
    core_file = Path(core_snapshot_path).resolve()
    reference = calculate_nba_core_totals(core_file)
    reference_values: dict[str, float | int] = {
        "teams": reference["teams"],
        "games": reference["games"],
        "field_goals_made": reference["field_goals_made"],
        "field_goal_attempts": reference["field_goal_attempts"],
        "three_points_made": reference["three_points_made"],
        "three_point_attempts": reference["three_point_attempts"],
        "field_goal_percentage": (reference["field_goals_made"] / reference["field_goal_attempts"]),
        "three_point_percentage": (
            reference["three_points_made"] / reference["three_point_attempts"]
        ),
    }
    comparisons, passed, warnings, rejected = _compare(
        metrics,
        reference_values,
        _SHOT_METRICS,
        "shot_value",
        tolerance,
        warning_multiplier,
    )
    return {
        "schema_version": NBA_DATA_AUDIT_VERSION,
        "audit_id": f"{_text(summary.get('dataset_id'), 'summary.dataset_id')}-audit-v1",
        "season": _text(summary.get("season"), "summary.season"),
        "status": _overall_status(passed, warnings, rejected),
        "notes": (
            "Shot totals are reconciled with pinned NBA team aggregates. Zone metrics have no "
            "independent pinned counterpart and remain source-only calibration targets."
        ),
        "thresholds": _threshold_payload(tolerance, warning_multiplier),
        "sources": {
            "shot_summary": _summary_source(summary_file, source),
            "core_snapshot": _file_source(core_file),
        },
        "comparisons": comparisons,
        "promotion": {
            "reconciled_metrics": passed,
            "warning_metrics": warnings,
            "rejected_metrics": rejected,
            "source_only_metrics": sorted(set(metrics) - set(_SHOT_METRICS)),
        },
        "summary": _summary_counts(comparisons, warnings, rejected),
    }


def _compare(
    metrics: dict[str, Any],
    reference: dict[str, float | int],
    order: tuple[str, ...],
    value_field: str,
    tolerance: float,
    warning_multiplier: float,
) -> tuple[list[dict[str, object]], list[str], list[str], list[str]]:
    comparisons: list[dict[str, object]] = []
    passed: list[str] = []
    warnings: list[str] = []
    rejected: list[str] = []
    for metric in order:
        observed = _metric_number(metrics.get(metric), metric)
        expected = reference[metric]
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
        target = passed if status == "pass" else warnings if status == "warning" else rejected
        target.append(metric)
        comparisons.append(
            {
                "metric": metric,
                value_field: observed,
                "reference_value": expected,
                "absolute_difference": round(absolute_difference, 12),
                "relative_difference": round(relative_difference, 12),
                "status": status,
            }
        )
    return comparisons, passed, warnings, rejected


def _load_summary(
    path: str | Path,
    label: str,
) -> tuple[Path, dict[str, Any], dict[str, Any], dict[str, Any]]:
    summary_file = Path(path).resolve()
    summary = _load_object(summary_file, label)
    if summary.get("schema_version") != 1:
        raise NbaDataAuditError(f"{label} schema_version must be 1")
    metrics = _mapping(summary.get("metrics"), "summary.metrics")
    source = _mapping(summary.get("source"), "summary.source")
    _sha256_text(source.get("sha256"), "summary.source.sha256")
    raw_bytes = source.get("bytes")
    if not isinstance(raw_bytes, int) or raw_bytes <= 0:
        raise NbaDataAuditError("summary.source.bytes must be a positive integer")
    return summary_file, summary, metrics, source


def _summary_source(path: Path, source: dict[str, Any]) -> dict[str, object]:
    return {
        "path": path.name,
        "sha256": sha256_file(path),
        "raw_source_sha256": _sha256_text(source.get("sha256"), "summary.source.sha256"),
        "raw_source_bytes": cast(int, source["bytes"]),
    }


def _file_source(path: Path) -> dict[str, object]:
    return {"path": path.name, "sha256": sha256_file(path)}


def _overall_status(passed: list[str], warnings: list[str], rejected: list[str]) -> str:
    if rejected:
        return "partial" if passed else "rejected"
    return "warning" if warnings else "passed"


def _summary_counts(
    comparisons: list[dict[str, object]],
    warnings: list[str],
    rejected: list[str],
) -> dict[str, int]:
    return {
        "compared": len(comparisons),
        "passed": len(comparisons) - len(warnings) - len(rejected),
        "warnings": len(warnings),
        "rejected": len(rejected),
    }


def _threshold_payload(tolerance: float, warning_multiplier: float) -> dict[str, float]:
    return {
        "pass_relative_difference": tolerance,
        "warning_relative_difference": tolerance * warning_multiplier,
    }


def _validate_thresholds(tolerance: float, warning_multiplier: float) -> None:
    if not math.isfinite(tolerance) or not 0.0 <= tolerance < 1.0:
        raise NbaDataAuditError("tolerance must be finite and between 0 and 1")
    if not math.isfinite(warning_multiplier) or warning_multiplier <= 1.0:
        raise NbaDataAuditError("warning_multiplier must be finite and greater than 1")


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
