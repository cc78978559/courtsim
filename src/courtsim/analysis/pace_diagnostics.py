"""White-box clock decomposition and leakage-safe pace experiments."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from statistics import fmean
from typing import Any, cast

from courtsim.artifacts import sha256_file
from courtsim.domain.game import GameClockConfig, GameResult
from courtsim.domain.game_serialization import game_result_from_dict
from courtsim.domain.results import (
    NonShootingFoulSegmentResult,
    OffensiveRebound,
    ShootingFoulSegmentResult,
    TechnicalFoulSegmentResult,
)
from courtsim.verification import verify_manifest

PACE_DIAGNOSTIC_VERSION = "pace-diagnostic-v1"
PACE_EXPERIMENT_VERSION = "pace-single-factor-experiment-v1"


class PaceDiagnosticError(ValueError):
    pass


def build_pace_audit_from_bundle(manifest_path: str | Path) -> dict[str, object]:
    """Read a verified full-trace model bundle and attach source receipts."""
    manifest_file = Path(manifest_path).resolve()
    verification = verify_manifest(manifest_file)
    if not verification.ok:
        raise PaceDiagnosticError("pace audit bundle verification failed")
    try:
        manifest = _mapping(
            json.loads(manifest_file.read_text(encoding="utf-8")), "model-audit manifest"
        )
    except (OSError, json.JSONDecodeError) as error:
        raise PaceDiagnosticError("cannot read model-audit manifest") from error
    outputs = manifest.get("outputs")
    if not isinstance(outputs, list):
        raise PaceDiagnosticError("model-audit outputs are invalid")
    games_record = next(
        (
            _mapping(item, "model-audit output")
            for item in outputs
            if isinstance(item, dict) and item.get("path") == "games.jsonl"
        ),
        None,
    )
    if games_record is None:
        raise PaceDiagnosticError("pace audit requires full-trace games.jsonl")
    games_file = manifest_file.parent / "games.jsonl"
    clock_raw = _mapping(manifest.get("clock"), "clock")
    clock = GameClockConfig(
        int(clock_raw["regulation_periods"]),
        int(clock_raw["period_seconds"]),
        int(clock_raw["possession_seconds"]),
        int(clock_raw.get("overtime_seconds", 300)),
        int(clock_raw.get("max_overtimes", 8)),
        bool(clock_raw.get("overtime_enabled", False)),
    )
    results = []
    try:
        rows = [
            _mapping(json.loads(line), "model-audit game row")
            for line in games_file.read_text(encoding="utf-8").splitlines()
        ]
        allowed_seconds = tuple(
            sorted(
                {
                    int(possession["clock_start_seconds"]) - int(possession["clock_end_seconds"])
                    for row in rows
                    for possession in cast(dict[str, Any], row["result"])["possessions"]
                }
            )
        )
        for row in rows:
            results.append(game_result_from_dict(row["result"], clock, allowed_seconds))
    except (OSError, json.JSONDecodeError, KeyError, ValueError) as error:
        raise PaceDiagnosticError("cannot read model-audit games") from error
    report = audit_pace_clock(results)
    report["sources"] = {
        "manifest": {"path": manifest_file.name, "sha256": sha256_file(manifest_file)},
        "games": {"path": games_file.name, "sha256": sha256_file(games_file)},
    }
    return report


def audit_pace_clock(results: Iterable[GameResult]) -> dict[str, object]:
    """Decompose modeled clock use by observable possession continuation context."""
    games = tuple(results)
    if not games or any(not game.completed for game in games):
        raise PaceDiagnosticError("pace audit requires completed games")
    durations: dict[str, list[int]] = defaultdict(list)
    continuation_counts: Counter[str] = Counter()
    total_segments = 0
    for game in games:
        for possession in game.possessions:
            duration = possession.clock_start_seconds - possession.clock_end_seconds
            flags: set[str] = set()
            for segment in possession.result.segments:
                total_segments += 1
                rebound = getattr(segment, "rebound", None)
                if isinstance(rebound, OffensiveRebound):
                    flags.add("offensive-rebound-continuation")
                    continuation_counts["offensive_rebounds"] += 1
                if isinstance(segment, (ShootingFoulSegmentResult, NonShootingFoulSegmentResult)):
                    if segment.free_throws:
                        flags.add("free-throw-sequence")
                        continuation_counts["free_throw_attempts"] += len(segment.free_throws)
                    elif isinstance(segment, NonShootingFoulSegmentResult):
                        flags.add("dead-ball-inbound-continuation")
                        continuation_counts["dead_ball_inbounds"] += 1
                if isinstance(segment, TechnicalFoulSegmentResult):
                    flags.add("technical-free-throw")
                    continuation_counts["technical_free_throws"] += len(segment.free_throws)
                    if segment.offense_retains_possession:
                        flags.add("dead-ball-inbound-continuation")
                        continuation_counts["dead_ball_inbounds"] += 1
            category = "standard" if not flags else "+".join(sorted(flags))
            durations[category].append(duration)
            continuation_counts["retained_segments"] += max(0, len(possession.result.segments) - 1)
    all_durations = [value for values in durations.values() for value in values]
    regulation_seconds = sum(
        sum(record.clock_start_seconds - record.clock_end_seconds for record in game.possessions)
        for game in games
    )
    possessions = len(all_durations)
    return {
        "schema_version": 1,
        "version": PACE_DIAGNOSTIC_VERSION,
        "games": len(games),
        "possessions": possessions,
        "segments": total_segments,
        "mean_team_possessions": possessions / (2 * len(games)),
        "mean_modeled_seconds_per_possession": fmean(all_durations),
        "modeled_clock_seconds": regulation_seconds,
        "continuations": dict(sorted(continuation_counts.items())),
        "contexts": [
            {
                "context": context,
                "possessions": len(values),
                "share": len(values) / possessions,
                "mean_seconds": fmean(values),
                "p10_seconds": _percentile(values, 0.10),
                "p50_seconds": _percentile(values, 0.50),
                "p90_seconds": _percentile(values, 0.90),
            }
            for context, values in sorted(durations.items())
        ],
        "clock_semantics": {
            "live_ball_duration_modeled": True,
            "free_throw_dead_ball_clock_seconds": 0,
            "inbound_dead_ball_clock_seconds": 0,
            "warning": (
                "The current engine assigns one live-clock duration to the complete possession; "
                "retained segments do not receive independent clock samples."
            ),
        },
    }


def build_single_factor_pace_experiment(
    *,
    experiment_id: str,
    factor_path: tuple[str, ...],
    baseline_value: float,
    candidate_values: tuple[float, ...],
    development_observations: Mapping[float, tuple[float, ...]],
    target_minimum: float,
    target_maximum: float,
    development_seeds: tuple[int, ...],
    holdout_seeds: tuple[int, ...],
) -> dict[str, object]:
    """Select and freeze one factor using development seeds only."""
    if not experiment_id.strip() or not factor_path or not candidate_values:
        raise PaceDiagnosticError("pace experiment identity is invalid")
    if set(development_seeds) & set(holdout_seeds):
        raise PaceDiagnosticError("development and holdout seeds must be disjoint")
    if (
        tuple(sorted(set(development_seeds))) != development_seeds
        or tuple(sorted(set(holdout_seeds))) != holdout_seeds
    ):
        raise PaceDiagnosticError("pace experiment seeds must be canonical and unique")
    if set(development_observations) != set(candidate_values):
        raise PaceDiagnosticError("development observations must cover every candidate")
    rows = []
    for candidate in candidate_values:
        observations = development_observations[candidate]
        if len(observations) != len(development_seeds) or any(
            not math.isfinite(value) for value in observations
        ):
            raise PaceDiagnosticError("development observation shape is invalid")
        mean = fmean(observations)
        distance = (
            0.0
            if target_minimum <= mean <= target_maximum
            else min(abs(mean - target_minimum), abs(mean - target_maximum))
        )
        rows.append((distance, abs(candidate - baseline_value), candidate, mean))
    _, _, selected, selected_mean = min(rows)
    frozen = {
        "schema_version": 1,
        "version": PACE_EXPERIMENT_VERSION,
        "experiment_id": experiment_id,
        "factor_path": list(factor_path),
        "baseline_value": baseline_value,
        "selected_value": selected,
        "target": {"minimum": target_minimum, "maximum": target_maximum},
        "development_seeds": list(development_seeds),
        "holdout_seeds_sha256": _digest(list(holdout_seeds)),
        "development": [
            {
                "candidate": candidate,
                "mean_pace": mean,
                "distance_to_gate": distance,
            }
            for distance, _change, candidate, mean in sorted(rows, key=lambda row: row[2])
        ],
        "selection": {
            "selected_value": selected,
            "development_mean_pace": selected_mean,
            "rule": "minimum distance to target, then minimum change from baseline",
        },
    }
    frozen["freeze_sha256"] = _digest(frozen)
    return frozen


def evaluate_pace_holdout(
    frozen: Mapping[str, object],
    *,
    holdout_seeds: tuple[int, ...],
    observations: tuple[float, ...],
) -> dict[str, object]:
    """Evaluate a frozen candidate without exposing holdout values during selection."""
    if frozen.get("version") != PACE_EXPERIMENT_VERSION:
        raise PaceDiagnosticError("pace freeze version differs")
    freeze_payload = dict(frozen)
    freeze_hash = freeze_payload.pop("freeze_sha256", None)
    if freeze_hash != _digest(freeze_payload):
        raise PaceDiagnosticError("pace freeze hash differs")
    if frozen.get("holdout_seeds_sha256") != _digest(list(holdout_seeds)):
        raise PaceDiagnosticError("holdout seed receipt differs")
    if len(observations) != len(holdout_seeds) or not observations:
        raise PaceDiagnosticError("holdout observation shape differs")
    target = _mapping(frozen.get("target"), "target")
    minimum = _number(target.get("minimum"), "target.minimum")
    maximum = _number(target.get("maximum"), "target.maximum")
    mean = fmean(observations)
    return {
        "schema_version": 1,
        "version": "pace-holdout-evaluation-v1",
        "experiment_id": frozen["experiment_id"],
        "freeze_sha256": freeze_hash,
        "holdout_seeds_sha256": _digest(list(holdout_seeds)),
        "seeds": len(holdout_seeds),
        "mean_pace": mean,
        "minimum_pace": min(observations),
        "maximum_pace": max(observations),
        "target": {"minimum": minimum, "maximum": maximum},
        "passed": minimum <= mean <= maximum,
    }


def _percentile(values: list[int], quantile: float) -> float:
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return float(ordered[lower])
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def _digest(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _mapping(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise PaceDiagnosticError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _number(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise PaceDiagnosticError(f"{field} must be finite numeric data")
    return float(value)
