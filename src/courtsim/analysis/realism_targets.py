"""Provenance-aware realism targets, separate from regression gates."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Any, Literal, cast

from courtsim.analysis.audit_gates import audit_metric_map
from courtsim.analysis.distribution import DistributionAudit

TargetStatus = Literal["draft", "active"]
MetricDirection = Literal["IN_RANGE", "LOW", "HIGH"]


class RealismTargetError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TargetSource:
    source_id: str
    label: str
    origin: str
    artifact_path: str
    retrieved_on: str
    content_sha256: str


@dataclass(frozen=True, slots=True)
class RealismMetricTarget:
    metric: str
    lower: float
    target: float
    upper: float
    weight: float
    required: bool
    source_id: str


@dataclass(frozen=True, slots=True)
class RealismTargetSet:
    target_set_id: str
    status: TargetStatus
    population: str
    season: str
    notes: str
    sources: tuple[TargetSource, ...]
    metrics: tuple[RealismMetricTarget, ...]
    planned_metrics: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RealismMetricResult:
    metric: str
    value: float
    lower: float
    target: float
    upper: float
    weight: float
    required: bool
    direction: MetricDirection
    normalized_distance: float


@dataclass(frozen=True, slots=True)
class RealismScoreReport:
    target_set_id: str
    target_status: TargetStatus
    metrics_evaluated: int
    weighted_rmse: float | None
    required_failures: int
    gate_passed: bool | None
    metric_results: tuple[RealismMetricResult, ...]


def _load_object(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    try:
        value: object = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RealismTargetError(f"cannot load {source}") from error
    if not isinstance(value, dict):
        raise RealismTargetError("realism target root must be an object")
    return cast(dict[str, Any], value)


def _number(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise RealismTargetError(f"{field} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise RealismTargetError(f"{field} must be finite")
    return result


def _nonempty(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RealismTargetError(f"{field} must be a non-empty string")
    return value.strip()


def load_realism_target_set(path: str | Path) -> RealismTargetSet:
    source_path = Path(path)
    raw = _load_object(source_path)
    expected = {
        "format_version",
        "target_set_id",
        "status",
        "population",
        "season",
        "notes",
        "sources",
        "metrics",
        "planned_metrics",
    }
    if set(raw) != expected or raw["format_version"] != 1:
        raise RealismTargetError("realism target file does not match the v1 contract")
    status = raw["status"]
    if status not in {"draft", "active"}:
        raise RealismTargetError("status must be draft or active")
    raw_sources = raw["sources"]
    raw_metrics = raw["metrics"]
    raw_planned = raw["planned_metrics"]
    if (
        not isinstance(raw_sources, list)
        or not isinstance(raw_metrics, list)
        or not isinstance(raw_planned, list)
        or not all(isinstance(item, str) and item for item in raw_planned)
    ):
        raise RealismTargetError("sources, metrics and planned_metrics must be lists")

    sources: list[TargetSource] = []
    for index, item in enumerate(raw_sources):
        if not isinstance(item, dict) or set(item) != {
            "source_id",
            "label",
            "origin",
            "artifact_path",
            "retrieved_on",
            "content_sha256",
        }:
            raise RealismTargetError(f"sources[{index}] is invalid")
        retrieved_on = _nonempty(item["retrieved_on"], f"sources[{index}].retrieved_on")
        try:
            date.fromisoformat(retrieved_on)
        except ValueError as error:
            raise RealismTargetError(f"sources[{index}].retrieved_on is invalid") from error
        digest = _nonempty(item["content_sha256"], f"sources[{index}].content_sha256")
        if len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
            raise RealismTargetError(f"sources[{index}].content_sha256 is invalid")
        artifact_name = _nonempty(item["artifact_path"], f"sources[{index}].artifact_path")
        artifact_relative = Path(artifact_name)
        if artifact_relative.is_absolute() or ".." in artifact_relative.parts:
            raise RealismTargetError(f"sources[{index}].artifact_path must be portable")
        artifact = source_path.parent / artifact_relative
        try:
            actual_digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        except OSError as error:
            raise RealismTargetError(
                f"sources[{index}] artifact cannot be read: {artifact}"
            ) from error
        if actual_digest != digest:
            raise RealismTargetError(f"sources[{index}] artifact hash mismatch")
        sources.append(
            TargetSource(
                _nonempty(item["source_id"], f"sources[{index}].source_id"),
                _nonempty(item["label"], f"sources[{index}].label"),
                _nonempty(item["origin"], f"sources[{index}].origin"),
                artifact_name,
                retrieved_on,
                digest,
            )
        )
    if len({source.source_id for source in sources}) != len(sources):
        raise RealismTargetError("source ids must be unique")

    metrics: list[RealismMetricTarget] = []
    for index, item in enumerate(raw_metrics):
        if not isinstance(item, dict) or set(item) != {
            "metric",
            "lower",
            "target",
            "upper",
            "weight",
            "required",
            "source_id",
        }:
            raise RealismTargetError(f"metrics[{index}] is invalid")
        lower = _number(item["lower"], f"metrics[{index}].lower")
        target = _number(item["target"], f"metrics[{index}].target")
        upper = _number(item["upper"], f"metrics[{index}].upper")
        weight = _number(item["weight"], f"metrics[{index}].weight")
        if not lower <= target <= upper:
            raise RealismTargetError(f"metrics[{index}] requires lower <= target <= upper")
        if weight <= 0.0:
            raise RealismTargetError(f"metrics[{index}].weight must be positive")
        if not isinstance(item["required"], bool):
            raise RealismTargetError(f"metrics[{index}].required must be boolean")
        metrics.append(
            RealismMetricTarget(
                _nonempty(item["metric"], f"metrics[{index}].metric"),
                lower,
                target,
                upper,
                weight,
                item["required"],
                _nonempty(item["source_id"], f"metrics[{index}].source_id"),
            )
        )
    if len({metric.metric for metric in metrics}) != len(metrics):
        raise RealismTargetError("target metrics must be unique")
    source_ids = {source.source_id for source in sources}
    unknown_sources = sorted(
        metric.source_id for metric in metrics if metric.source_id not in source_ids
    )
    if unknown_sources:
        raise RealismTargetError(f"metrics reference unknown sources: {unknown_sources}")
    if len(set(raw_planned)) != len(raw_planned):
        raise RealismTargetError("planned metrics must be unique")
    if set(raw_planned) & {metric.metric for metric in metrics}:
        raise RealismTargetError("a metric cannot be both planned and active")
    if status == "active" and (not sources or not metrics or raw_planned):
        raise RealismTargetError(
            "active targets require sources and metrics with no planned metrics"
        )
    return RealismTargetSet(
        _nonempty(raw["target_set_id"], "target_set_id"),
        status,
        _nonempty(raw["population"], "population"),
        _nonempty(raw["season"], "season"),
        _nonempty(raw["notes"], "notes"),
        tuple(sources),
        tuple(metrics),
        tuple(raw_planned),
    )


def score_audit_against_realism_targets(
    audit: DistributionAudit,
    targets: RealismTargetSet,
) -> RealismScoreReport:
    if not targets.metrics:
        return RealismScoreReport(
            targets.target_set_id,
            targets.status,
            0,
            None,
            0,
            None,
            (),
        )
    values = audit_metric_map(audit)
    unknown = sorted(metric.metric for metric in targets.metrics if metric.metric not in values)
    if unknown:
        raise RealismTargetError(f"unknown audit metrics: {unknown}")
    results: list[RealismMetricResult] = []
    weighted_squared = 0.0
    total_weight = 0.0
    for metric in targets.metrics:
        value = values[metric.metric]
        scale = max(metric.upper - metric.lower, abs(metric.target) * 0.05, 1e-12)
        if value < metric.lower:
            direction: MetricDirection = "LOW"
            distance = (metric.lower - value) / scale
        elif value > metric.upper:
            direction = "HIGH"
            distance = (value - metric.upper) / scale
        else:
            direction = "IN_RANGE"
            distance = 0.0
        results.append(
            RealismMetricResult(
                metric.metric,
                value,
                metric.lower,
                metric.target,
                metric.upper,
                metric.weight,
                metric.required,
                direction,
                distance,
            )
        )
        weighted_squared += metric.weight * distance * distance
        total_weight += metric.weight
    ordered = tuple(
        sorted(
            results,
            key=lambda item: (-item.normalized_distance, item.metric),
        )
    )
    required_failures = sum(item.required and item.direction != "IN_RANGE" for item in ordered)
    return RealismScoreReport(
        targets.target_set_id,
        targets.status,
        len(ordered),
        math.sqrt(weighted_squared / total_weight),
        required_failures,
        required_failures == 0 if targets.status == "active" else None,
        ordered,
    )


def realism_score_report_to_json(report: RealismScoreReport) -> str:
    return json.dumps(
        asdict(report),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
