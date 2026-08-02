"""Paired aggregate/full-engine consistency and sensitivity reports."""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from statistics import fmean
from typing import cast

from courtsim.analysis.nba_aggregate_quick_sim import build_nba_aggregate_quick_sim_executor
from courtsim.analysis.quick_sim_batch import quick_sim_batch_from_json
from courtsim.analysis.quick_sim_comparison import QUICK_SIM_METRICS, QuickSimSeasonSummary
from courtsim.artifacts import sha256_file

QUICK_SIM_CONSISTENCY_VERSION = "quick-sim-consistency-v1"


class QuickSimConsistencyError(ValueError):
    pass


def compare_quick_sim_engines(
    aggregate: Mapping[int, QuickSimSeasonSummary],
    full_engine: Mapping[int, QuickSimSeasonSummary],
    *,
    gate: Mapping[str, object] | None = None,
    master_seed: int | None = None,
    inputs_verified: bool | None = None,
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
    rank_correlations = [
        _rank_correlation(aggregate[seed], full_engine[seed])
        for seed in seeds
        if aggregate[seed].team_rank_order is not None
        and full_engine[seed].team_rank_order is not None
    ]
    sample_ready = len(seeds) >= 3
    accuracy_gate: dict[str, object] = {"configured": False, "passed": None}
    promotion_ready = False
    if gate is not None:
        frozen = _validated_consistency_gate(gate)
        if master_seed is None:
            raise QuickSimConsistencyError("consistency gate requires the batch master seed")
        maximum_mae = cast(dict[str, float], frozen["maximum_mae"])
        metric_results = [
            {
                "metric": row["metric"],
                "observed_mae": row["mae"],
                "maximum_mae": maximum_mae[cast(str, row["metric"])],
                "passed": cast(float, row["mae"]) <= maximum_mae[cast(str, row["metric"])],
            }
            for row in metrics
        ]
        rank_mean = fmean(rank_correlations) if rank_correlations else None
        rank_passed = (
            len(rank_correlations) == len(seeds)
            and rank_mean is not None
            and rank_mean >= cast(float, frozen["minimum_mean_team_rank_spearman"])
        )
        eligibility = {
            "minimum_paired_seasons": len(seeds) >= cast(int, frozen["minimum_paired_seasons"]),
            "unseen_master_seed": master_seed
            not in cast(list[int], frozen["forbidden_master_seeds"]),
            "rank_vectors_complete": len(rank_correlations) == len(seeds),
            "inputs_verified": inputs_verified is True,
        }
        gate_passed = (
            all(eligibility.values())
            and all(cast(bool, row["passed"]) for row in metric_results)
            and rank_passed
        )
        accuracy_gate = {
            "configured": True,
            "gate_id": frozen["gate_id"],
            "eligibility": eligibility,
            "metric_results": metric_results,
            "rank_result": {
                "observed_mean_spearman": rank_mean,
                "minimum_mean_spearman": frozen["minimum_mean_team_rank_spearman"],
                "passed": rank_passed,
            },
            "passed": gate_passed,
        }
        promotion_ready = gate_passed
    return {
        "schema_version": 1,
        "version": QUICK_SIM_CONSISTENCY_VERSION,
        "paired_seeds": list(seeds),
        "paired_seasons": len(seeds),
        "requested_minimum_seasons": 3,
        "sample_ready": sample_ready,
        # Accuracy tolerances must be frozen before a new holdout batch. The first
        # diagnostic batch deliberately cannot promote itself after its errors are seen.
        "accuracy_gate": accuracy_gate,
        "promotion_ready": promotion_ready,
        "team_rank_correlation": {
            "available_seasons": len(rank_correlations),
            "mean_spearman": fmean(rank_correlations) if rank_correlations else None,
            "values": rank_correlations,
        },
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


def _rank_correlation(
    aggregate: QuickSimSeasonSummary,
    full_engine: QuickSimSeasonSummary,
) -> float:
    left = aggregate.team_rank_order
    right = full_engine.team_rank_order
    if left is None or right is None or set(left) != set(right):
        raise QuickSimConsistencyError("paired team rank orders differ")
    right_rank = {team_id: index for index, team_id in enumerate(right, 1)}
    squared_difference = sum(
        (index - right_rank[team_id]) ** 2 for index, team_id in enumerate(left, 1)
    )
    count = len(left)
    return 1 - (6 * squared_difference) / (count * (count * count - 1))


def load_quick_sim_consistency_gate(path: str | Path) -> dict[str, object]:
    try:
        raw: object = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise QuickSimConsistencyError(f"cannot read consistency gate: {path}") from error
    if not isinstance(raw, dict) or any(not isinstance(key, str) for key in raw):
        raise QuickSimConsistencyError("consistency gate must be an object")
    return _validated_consistency_gate(cast(dict[str, object], raw))


def verify_quick_sim_consistency_manifests(
    gate: Mapping[str, object],
    aggregate_manifest_path: str | Path,
    full_manifest_path: str | Path,
    aggregate_checkpoint_path: str | Path,
    full_checkpoint_path: str | Path,
) -> bool:
    frozen = _validated_consistency_gate(gate)
    required = cast(dict[str, dict[str, str]], frozen["required_input_sha256"])
    pairs = (
        ("aggregate", aggregate_manifest_path, aggregate_checkpoint_path),
        ("full_engine", full_manifest_path, full_checkpoint_path),
    )
    for engine, manifest_path, checkpoint_path in pairs:
        try:
            raw: object = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise QuickSimConsistencyError(f"cannot read {engine} manifest") from error
        if not isinstance(raw, dict):
            raise QuickSimConsistencyError(f"{engine} manifest must be an object")
        checkpoint = raw.get("checkpoint")
        configuration = raw.get("configuration")
        if not isinstance(checkpoint, dict) or not isinstance(configuration, dict):
            raise QuickSimConsistencyError(f"{engine} manifest schema differs")
        if checkpoint.get("sha256") != sha256_file(Path(checkpoint_path)):
            raise QuickSimConsistencyError(f"{engine} manifest checkpoint hash differs")
        inputs = configuration.get("inputs")
        if not isinstance(inputs, dict) or set(inputs) != set(required[engine]):
            return False
        for role, digest in required[engine].items():
            receipt = inputs.get(role)
            if not isinstance(receipt, dict) or receipt.get("sha256") != digest:
                return False
    return True


def _validated_consistency_gate(raw: Mapping[str, object]) -> dict[str, object]:
    expected = {
        "version",
        "gate_id",
        "frozen_at",
        "minimum_paired_seasons",
        "forbidden_master_seeds",
        "required_input_sha256",
        "maximum_mae",
        "minimum_mean_team_rank_spearman",
        "methodology",
    }
    if set(raw) != expected or raw.get("version") != "quick-sim-consistency-gate-v1":
        raise QuickSimConsistencyError("consistency gate schema differs")
    maximum_mae = raw["maximum_mae"]
    if not isinstance(maximum_mae, dict) or set(maximum_mae) != set(QUICK_SIM_METRICS):
        raise QuickSimConsistencyError("consistency gate metric set differs")
    if any(
        not isinstance(value, (int, float)) or isinstance(value, bool) or value < 0
        for value in maximum_mae.values()
    ):
        raise QuickSimConsistencyError("consistency gate MAE limits are invalid")
    required_inputs = raw["required_input_sha256"]
    if (
        not isinstance(required_inputs, dict)
        or set(required_inputs) != {"aggregate", "full_engine"}
        or any(not isinstance(value, dict) or not value for value in required_inputs.values())
    ):
        raise QuickSimConsistencyError("consistency gate input requirements differ")
    if any(
        not isinstance(role, str)
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
        for requirements in required_inputs.values()
        for role, digest in cast(dict[object, object], requirements).items()
    ):
        raise QuickSimConsistencyError("consistency gate input hashes are invalid")
    minimum = raw["minimum_paired_seasons"]
    seeds = raw["forbidden_master_seeds"]
    rank_minimum = raw["minimum_mean_team_rank_spearman"]
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 3:
        raise QuickSimConsistencyError("consistency gate minimum seasons are invalid")
    if (
        not isinstance(seeds, list)
        or seeds != sorted(set(seeds))
        or any(not isinstance(seed, int) or isinstance(seed, bool) for seed in seeds)
    ):
        raise QuickSimConsistencyError("consistency gate forbidden seeds are invalid")
    if (
        not isinstance(rank_minimum, (int, float))
        or isinstance(rank_minimum, bool)
        or not -1 <= rank_minimum <= 1
    ):
        raise QuickSimConsistencyError("consistency gate rank threshold is invalid")
    return dict(raw)
