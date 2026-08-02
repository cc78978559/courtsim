"""Paired aggregate/full-engine consistency and sensitivity reports."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from statistics import fmean

from courtsim.analysis.nba_aggregate_quick_sim import build_nba_aggregate_quick_sim_executor
from courtsim.analysis.quick_sim_batch import quick_sim_batch_from_json
from courtsim.analysis.quick_sim_comparison import QUICK_SIM_METRICS, QuickSimSeasonSummary

QUICK_SIM_CONSISTENCY_VERSION = "quick-sim-consistency-v1"


class QuickSimConsistencyError(ValueError):
    pass


def compare_quick_sim_engines(
    aggregate: Mapping[int, QuickSimSeasonSummary],
    full_engine: Mapping[int, QuickSimSeasonSummary],
) -> dict[str, object]:
    """Compare paired seeds; partial resumable batches are valid but explicitly not promotable."""
    seeds = tuple(sorted(set(aggregate) & set(full_engine)))
    if not seeds:
        raise QuickSimConsistencyError("consistency comparison has no paired seeds")
    metrics = []
    for metric in QUICK_SIM_METRICS:
        pairs = [
            (_metric(aggregate[seed], metric), _metric(full_engine[seed], metric)) for seed in seeds
        ]
        errors = [left - right for left, right in pairs]
        metrics.append(
            {
                "metric": metric,
                "aggregate_mean": fmean(left for left, _right in pairs),
                "full_engine_mean": fmean(right for _left, right in pairs),
                "mean_error": fmean(errors),
                "mae": fmean(abs(value) for value in errors),
                "rmse": math.sqrt(fmean(value * value for value in errors)),
            }
        )
    sample_ready = len(seeds) >= 3
    return {
        "schema_version": 1,
        "version": QUICK_SIM_CONSISTENCY_VERSION,
        "paired_seeds": list(seeds),
        "paired_seasons": len(seeds),
        "requested_minimum_seasons": 3,
        "sample_ready": sample_ready,
        # Accuracy tolerances must be frozen before a new holdout batch. The first
        # diagnostic batch deliberately cannot promote itself after its errors are seen.
        "accuracy_gate": {"configured": False, "passed": None},
        "promotion_ready": False,
        "metrics": metrics,
    }


def build_aggregate_sensitivity_report(
    baseline: Mapping[int, QuickSimSeasonSummary],
    variants: Mapping[str, Mapping[int, QuickSimSeasonSummary]],
    *,
    changed_factors: Mapping[str, tuple[str, float]],
) -> dict[str, object]:
    if set(variants) != set(changed_factors) or not variants:
        raise QuickSimConsistencyError("sensitivity variants and factors differ")
    rows = []
    for variant_id in sorted(variants):
        candidate = variants[variant_id]
        seeds = tuple(sorted(set(baseline) & set(candidate)))
        if set(seeds) != set(baseline) or set(seeds) != set(candidate):
            raise QuickSimConsistencyError("sensitivity analysis requires paired complete seeds")
        factor, value = changed_factors[variant_id]
        rows.append(
            {
                "variant_id": variant_id,
                "factor": factor,
                "value": value,
                "seeds": len(seeds),
                "metric_deltas": {
                    metric: fmean(
                        _metric(candidate[seed], metric) - _metric(baseline[seed], metric)
                        for seed in seeds
                    )
                    for metric in QUICK_SIM_METRICS
                },
            }
        )
    return {
        "schema_version": 1,
        "version": "aggregate-sensitivity-v1",
        "single_factor_required": True,
        "variants": rows,
    }


def run_aggregate_sensitivity(
    parameter_path: str | Path,
    strength_path: str | Path,
    baseline_checkpoint_path: str | Path,
) -> dict[str, object]:
    """Run paired, one-at-a-time sensitivity around the declared aggregate baseline."""
    batch = quick_sim_batch_from_json(Path(baseline_checkpoint_path).read_text(encoding="utf-8"))
    if not batch.complete:
        raise QuickSimConsistencyError("aggregate sensitivity requires a complete checkpoint")
    executor = build_nba_aggregate_quick_sim_executor(parameter_path, strength_path)
    baseline = {cell.seed: cell.summary for cell in batch.cells}
    definitions = {
        "home-advantage-low": ("home_advantage_points", 1.5),
        "home-advantage-high": ("home_advantage_points", 3.0),
        "pace-sd-low": ("pace_standard_deviation", 3.0),
        "pace-sd-high": ("pace_standard_deviation", 5.0),
    }
    variants: dict[str, dict[int, QuickSimSeasonSummary]] = {}
    for variant_id, (factor, value) in definitions.items():
        if factor == "home_advantage_points":
            parameters = replace(executor.parameters, home_advantage_points=value)
        elif factor == "pace_standard_deviation":
            parameters = replace(executor.parameters, pace_standard_deviation=value)
        else:  # pragma: no cover - definitions above are deliberately closed
            raise QuickSimConsistencyError(f"unsupported sensitivity factor: {factor}")
        varied = replace(executor, parameters=parameters)
        variants[variant_id] = {
            cell.seed: varied(cell.season_id, cell.seed) for cell in batch.cells
        }
    report = build_aggregate_sensitivity_report(
        baseline,
        variants,
        changed_factors=definitions,
    )
    report["baseline_batch_sha256"] = batch.batch_sha256
    return report


def _metric(summary: QuickSimSeasonSummary, name: str) -> float:
    values = {
        "win-rate-stddev": summary.win_rate_stddev,
        "pace-possessions-per-team": summary.pace_possessions_per_team,
        "offensive-rating": summary.offensive_rating,
        "point-differential-stddev": summary.point_differential_stddev,
        "playoff-upset-rate": summary.playoff_upset_rate,
        "champion-seed-mean": summary.champion_seed,
    }
    value = values[name]
    if value is None:
        raise QuickSimConsistencyError(f"metric is unavailable: {name}")
    return float(value)
