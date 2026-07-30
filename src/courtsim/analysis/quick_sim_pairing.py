"""Paired-seed comparison for baseline and candidate quick-simulation batches."""

from __future__ import annotations

import math
from statistics import fmean

from courtsim.analysis.quick_sim_batch import QuickSimBatchResult
from courtsim.analysis.quick_sim_comparison import QUICK_SIM_METRICS, QuickSimSeasonSummary

QUICK_SIM_PAIRED_COMPARISON_VERSION = 1


class QuickSimPairingError(ValueError):
    """Raised when two quick-sim batches are not a valid paired experiment."""


def compare_paired_quick_sim_batches(
    baseline: QuickSimBatchResult,
    candidate: QuickSimBatchResult,
) -> dict[str, object]:
    """Compare complete batches whose season ids and derived seeds are identical."""
    if not baseline.complete or not candidate.complete:
        raise QuickSimPairingError("paired quick-sim comparison requires complete batches")
    if baseline.spec != candidate.spec:
        raise QuickSimPairingError("paired quick-sim batches must use the same spec")
    baseline_keys = tuple((cell.season_index, cell.season_id, cell.seed) for cell in baseline.cells)
    candidate_keys = tuple(
        (cell.season_index, cell.season_id, cell.seed) for cell in candidate.cells
    )
    if baseline_keys != candidate_keys:
        raise QuickSimPairingError("paired quick-sim cells must use identical ids and seeds")
    metrics: list[dict[str, object]] = []
    changed = False
    for metric in QUICK_SIM_METRICS:
        baseline_values = tuple(_metric_value(cell.summary, metric) for cell in baseline.cells)
        candidate_values = tuple(_metric_value(cell.summary, metric) for cell in candidate.cells)
        deltas = tuple(
            candidate_value - baseline_value
            for baseline_value, candidate_value in zip(
                baseline_values,
                candidate_values,
                strict=True,
            )
        )
        mean_delta = fmean(deltas)
        changed = changed or any(delta != 0.0 for delta in deltas)
        metrics.append(
            {
                "metric": metric,
                "baseline_mean": round(fmean(baseline_values), 12),
                "candidate_mean": round(fmean(candidate_values), 12),
                "mean_delta": round(mean_delta, 12),
                "minimum_delta": round(min(deltas), 12),
                "maximum_delta": round(max(deltas), 12),
            }
        )
    return {
        "schema_version": QUICK_SIM_PAIRED_COMPARISON_VERSION,
        "comparison_id": f"{baseline.spec.batch_id}-paired-v1",
        "status": "changed" if changed else "identical",
        "batch_id": baseline.spec.batch_id,
        "master_seed": baseline.spec.master_seed,
        "seasons": baseline.spec.seasons,
        "team_count": baseline.spec.team_count,
        "baseline_batch_sha256": baseline.batch_sha256,
        "candidate_batch_sha256": candidate.batch_sha256,
        "metrics": metrics,
    }


def _metric_value(summary: QuickSimSeasonSummary, metric: str) -> float:
    values = {
        "win-rate-stddev": summary.win_rate_stddev,
        "pace-possessions-per-team": summary.pace_possessions_per_team,
        "offensive-rating": summary.offensive_rating,
        "point-differential-stddev": summary.point_differential_stddev,
        "playoff-upset-rate": summary.playoff_upset_rate,
        "champion-seed-mean": summary.champion_seed,
    }
    value = values[metric]
    if value is None or not math.isfinite(float(value)):
        raise QuickSimPairingError(f"paired quick-sim metric is unavailable: {metric}")
    return float(value)
