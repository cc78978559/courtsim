import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

import courtsim.analysis.quick_sim_consistency as consistency_module
from courtsim.analysis.quick_sim_comparison import QUICK_SIM_METRICS, QuickSimSeasonSummary
from courtsim.analysis.quick_sim_consistency import (
    QuickSimConsistencyError,
    build_aggregate_sensitivity_report,
    compare_quick_sim_engines,
    load_quick_sim_consistency_gate,
    run_aggregate_sensitivity,
    verify_quick_sim_consistency_manifests,
)


def _summary(
    season: str,
    pace: float,
    champion: int = 2,
    rank_order: tuple[str, ...] | None = None,
) -> QuickSimSeasonSummary:
    return QuickSimSeasonSummary(
        season, 30, 1230, 0.14, pace, 115.0, 4.5, 0.35, champion, rank_order
    )


def _gate() -> dict[str, object]:
    return {
        "version": "quick-sim-consistency-gate-v2",
        "gate_id": "strict-test-gate",
        "frozen_at": "2026-08-02",
        "minimum_paired_seasons": 3,
        "forbidden_master_seeds": [],
        "required_input_sha256": {
            "aggregate": {"parameters": "0" * 64},
            "full_engine": {"parameters": "1" * 64},
        },
        "maximum_mae": {metric: 1.0 for metric in QUICK_SIM_METRICS[:4]},
        "maximum_absolute_mean_error": {metric: 1.0 for metric in QUICK_SIM_METRICS[4:]},
        "minimum_mean_team_rank_spearman": 0.75,
        "methodology": "test",
    }


def test_consistency_report_requires_a_frozen_accuracy_gate_for_promotion() -> None:
    aggregate = {seed: _summary(str(seed), 99.0) for seed in (1, 2)}
    full = {seed: _summary(str(seed), 98.0) for seed in (1, 2)}
    partial = compare_quick_sim_engines(aggregate, full)
    assert partial["paired_seasons"] == 2
    assert partial["sample_ready"] is False
    assert partial["promotion_ready"] is False
    aggregate[3] = _summary("3", 99.0)
    full[3] = _summary("3", 98.0)
    complete = compare_quick_sim_engines(aggregate, full)
    assert complete["sample_ready"] is True
    assert complete["accuracy_gate"] == {"configured": False, "passed": None}
    assert complete["promotion_ready"] is False


def test_consistency_report_compares_team_rank_order_when_available() -> None:
    ordered = tuple(f"team-{index:02d}" for index in range(30))
    aggregate = {1: _summary("1", 99.0, rank_order=ordered)}
    full = {1: _summary("1", 99.0, rank_order=tuple(reversed(ordered)))}
    report = compare_quick_sim_engines(aggregate, full)
    assert report["team_rank_correlation"] == {
        "available_seasons": 1,
        "mean_spearman": -1.0,
        "values": [-1.0],
    }


def test_consistency_report_compares_home_win_rate_when_available() -> None:
    aggregate = {
        1: QuickSimSeasonSummary("1", 30, 1230, 0.14, 99.0, 115.0, 4.5, 0.35, 2, None, 0.60)
    }
    full = {1: QuickSimSeasonSummary("1", 30, 1230, 0.14, 99.0, 115.0, 4.5, 0.35, 2, None, 0.55)}
    report = compare_quick_sim_engines(aggregate, full)
    assert report["home_advantage"] == {
        "available_seasons": 1,
        "aggregate_mean_home_win_rate": 0.60,
        "full_engine_mean_home_win_rate": 0.55,
        "mae": pytest.approx(0.05),
    }


def test_frozen_consistency_gate_requires_unseen_seed_metrics_and_ranks() -> None:
    ordered = tuple(f"team-{index:02d}" for index in range(30))
    aggregate = {seed: _summary(str(seed), 99.0, rank_order=ordered) for seed in (1, 2, 3)}
    full = {seed: _summary(str(seed), 98.8, rank_order=ordered) for seed in (1, 2, 3)}
    gate = {
        "version": "quick-sim-consistency-gate-v1",
        "gate_id": "test-gate",
        "frozen_at": "2026-08-02",
        "minimum_paired_seasons": 3,
        "forbidden_master_seeds": [10],
        "required_input_sha256": {
            "aggregate": {"parameters": "0" * 64},
            "full_engine": {"parameters": "1" * 64},
        },
        "maximum_mae": {
            "win-rate-stddev": 0.01,
            "pace-possessions-per-team": 0.5,
            "offensive-rating": 0.1,
            "point-differential-stddev": 0.1,
            "playoff-upset-rate": 0.1,
            "champion-seed-mean": 0.1,
        },
        "minimum_mean_team_rank_spearman": 0.9,
        "methodology": "test",
    }
    report = compare_quick_sim_engines(
        aggregate, full, gate=gate, master_seed=11, inputs_verified=True
    )
    assert report["promotion_ready"] is True
    rejected = compare_quick_sim_engines(
        aggregate, full, gate=gate, master_seed=10, inputs_verified=True
    )
    assert rejected["promotion_ready"] is False


def test_consistency_manifest_verification_pins_both_engine_inputs(tmp_path: Path) -> None:
    aggregate_checkpoint = tmp_path / "aggregate.json"
    full_checkpoint = tmp_path / "full.json"
    aggregate_checkpoint.write_text("aggregate", encoding="utf-8")
    full_checkpoint.write_text("full", encoding="utf-8")
    gate = {
        "version": "quick-sim-consistency-gate-v3",
        "gate_id": "test-gate",
        "frozen_at": "2026-08-02",
        "minimum_paired_seasons": 3,
        "forbidden_master_seeds": [],
        "required_input_sha256": {
            "aggregate": {"parameters": "0" * 64},
            "full_engine": {"parameters": "1" * 64},
        },
        "required_executor_version": {"aggregate": "aggregate-v1", "full_engine": "full-v6"},
        "required_runner_version": {
            "aggregate": "aggregate-runner-v1",
            "full_engine": "full-runner-v1",
        },
        "maximum_mae": {
            metric: 1.0
            for metric in (
                "win-rate-stddev",
                "pace-possessions-per-team",
                "offensive-rating",
                "point-differential-stddev",
            )
        },
        "maximum_absolute_mean_error": {
            "playoff-upset-rate": 1.0,
            "champion-seed-mean": 1.0,
        },
        "minimum_mean_team_rank_spearman": 0.75,
        "methodology": "test",
    }

    def manifest(checkpoint: Path, digest: str, executor: str, runner: str) -> dict[str, object]:
        return {
            "version": runner,
            "checkpoint": {
                "sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            },
            "configuration": {
                "executor_version": executor,
                "inputs": {"parameters": {"sha256": digest}},
            },
        }

    aggregate_manifest = tmp_path / "aggregate.manifest.json"
    full_manifest = tmp_path / "full.manifest.json"
    aggregate_manifest.write_text(
        json.dumps(manifest(aggregate_checkpoint, "0" * 64, "aggregate-v1", "aggregate-runner-v1")),
        encoding="utf-8",
    )
    full_manifest.write_text(
        json.dumps(manifest(full_checkpoint, "1" * 64, "full-v6", "full-runner-v1")),
        encoding="utf-8",
    )
    assert verify_quick_sim_consistency_manifests(
        gate,
        aggregate_manifest,
        full_manifest,
        aggregate_checkpoint,
        full_checkpoint,
    )


def test_v2_gate_uses_distribution_mean_for_stochastic_postseason_metrics() -> None:
    ordered = tuple(f"team-{index:02d}" for index in range(30))
    aggregate = {
        seed: _summary(str(seed), 99.0, champion=champion, rank_order=ordered)
        for seed, champion in zip(range(1, 6), (1, 5, 1, 5, 1), strict=True)
    }
    full = {
        seed: _summary(str(seed), 99.0, champion=champion, rank_order=ordered)
        for seed, champion in zip(range(1, 6), (5, 1, 5, 1, 1), strict=True)
    }
    gate = {
        "version": "quick-sim-consistency-gate-v2",
        "gate_id": "distribution-gate",
        "frozen_at": "2026-08-02",
        "minimum_paired_seasons": 5,
        "forbidden_master_seeds": [],
        "required_input_sha256": {
            "aggregate": {"parameters": "0" * 64},
            "full_engine": {"parameters": "1" * 64},
        },
        "maximum_mae": {
            "win-rate-stddev": 0.1,
            "pace-possessions-per-team": 0.1,
            "offensive-rating": 0.1,
            "point-differential-stddev": 0.1,
        },
        "maximum_absolute_mean_error": {
            "playoff-upset-rate": 0.1,
            "champion-seed-mean": 1.0,
        },
        "minimum_mean_team_rank_spearman": 0.9,
        "methodology": "test",
    }
    report = compare_quick_sim_engines(
        aggregate,
        full,
        gate=gate,
        master_seed=20,
        inputs_verified=True,
    )
    assert report["requested_minimum_seasons"] == 5
    assert report["promotion_ready"] is True


def test_sensitivity_report_is_paired_and_single_factor() -> None:
    baseline = {seed: _summary(str(seed), 99.0) for seed in (1, 2, 3)}
    report = build_aggregate_sensitivity_report(
        baseline,
        {
            "home-low": {seed: _summary(str(seed), 99.0, 3) for seed in baseline},
            "pace-sd-high": {seed: _summary(str(seed), 100.0) for seed in baseline},
        },
        changed_factors={
            "home-low": ("home_advantage_points", 1.5),
            "pace-sd-high": ("pace_standard_deviation", 5.0),
        },
    )
    assert report["single_factor_required"] is True
    variants = report["variants"]
    assert isinstance(variants, list)
    assert len(variants) == 2


def test_consistency_public_guards_reject_unpaired_or_incomplete_inputs() -> None:
    with pytest.raises(QuickSimConsistencyError, match="no paired seeds"):
        compare_quick_sim_engines({1: _summary("1", 99.0)}, {2: _summary("2", 99.0)})
    with pytest.raises(QuickSimConsistencyError, match="master seed"):
        compare_quick_sim_engines({1: _summary("1", 99.0)}, {1: _summary("1", 99.0)}, gate=_gate())
    left_order = tuple(f"team-{index}" for index in range(30))
    right_order = (*left_order[:-1], "different-team")
    with pytest.raises(QuickSimConsistencyError, match="rank orders differ"):
        consistency_module._rank_correlation(
            _summary("1", 99.0, rank_order=left_order),
            _summary("1", 99.0, rank_order=right_order),
        )
    with pytest.raises(QuickSimConsistencyError, match="variants and factors differ"):
        build_aggregate_sensitivity_report({}, {}, changed_factors={})
    with pytest.raises(QuickSimConsistencyError, match="paired complete seeds"):
        build_aggregate_sensitivity_report(
            {1: _summary("1", 99.0)},
            {"pace": {2: _summary("2", 99.0)}},
            changed_factors={"pace": ("pace_standard_deviation", 5.0)},
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda gate: gate.__setitem__("version", "future-v9"), "schema differs"),
        (lambda gate: gate.__setitem__("maximum_mae", []), "metric set differs"),
        (
            lambda gate: gate["maximum_mae"].__setitem__("unexpected", 1.0),
            "metric set differs",
        ),
        (
            lambda gate: gate["maximum_mae"].__setitem__("win-rate-stddev", -1.0),
            "MAE limits are invalid",
        ),
        (lambda gate: gate.__setitem__("required_input_sha256", {}), "requirements differ"),
        (
            lambda gate: gate["required_input_sha256"]["aggregate"].__setitem__(
                "parameters", "bad"
            ),
            "input hashes are invalid",
        ),
        (lambda gate: gate.__setitem__("minimum_paired_seasons", 2), "minimum seasons"),
        (lambda gate: gate.__setitem__("forbidden_master_seeds", [2, 1]), "forbidden seeds"),
        (
            lambda gate: gate.__setitem__("minimum_mean_team_rank_spearman", 2.0),
            "rank threshold",
        ),
    ],
)
def test_consistency_gate_strict_validation(mutation: object, message: str) -> None:
    gate = deepcopy(_gate())
    assert callable(mutation)
    mutation(gate)
    with pytest.raises(QuickSimConsistencyError, match=message):
        consistency_module._validated_consistency_gate(gate)


def test_consistency_gate_loader_wraps_file_and_root_errors(tmp_path: Path) -> None:
    valid = tmp_path / "valid.json"
    valid.write_text(json.dumps(_gate()), encoding="utf-8")
    assert load_quick_sim_consistency_gate(valid)["gate_id"] == "strict-test-gate"
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(QuickSimConsistencyError, match="must be an object"):
        load_quick_sim_consistency_gate(invalid)
    invalid.write_text("not-json", encoding="utf-8")
    with pytest.raises(QuickSimConsistencyError, match="cannot read"):
        load_quick_sim_consistency_gate(invalid)


@dataclass(frozen=True)
class _Parameters:
    home_advantage_points: float = 2.0
    pace_standard_deviation: float = 4.0


@dataclass(frozen=True)
class _Executor:
    parameters: _Parameters

    def __call__(self, season_id: str, _seed: int) -> QuickSimSeasonSummary:
        return _summary(season_id, 99.0 + self.parameters.pace_standard_deviation / 10)


def test_run_aggregate_sensitivity_executes_each_single_factor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    checkpoint.write_text("{}", encoding="utf-8")
    batch = SimpleNamespace(
        complete=True,
        cells=(SimpleNamespace(seed=7, season_id="season-1", summary=_summary("season-1", 99.0)),),
        batch_sha256="b" * 64,
    )
    monkeypatch.setattr(consistency_module, "quick_sim_batch_from_json", lambda _raw: batch)
    monkeypatch.setattr(
        consistency_module,
        "build_nba_aggregate_quick_sim_executor",
        lambda *_args: _Executor(_Parameters()),
    )
    report = run_aggregate_sensitivity("parameters.json", "strength.json", checkpoint)
    assert report["baseline_batch_sha256"] == "b" * 64
    variants = report["variants"]
    assert isinstance(variants, list)
    assert len(variants) == 4

    monkeypatch.setattr(
        consistency_module,
        "quick_sim_batch_from_json",
        lambda _raw: SimpleNamespace(complete=False),
    )
    with pytest.raises(QuickSimConsistencyError, match="complete checkpoint"):
        run_aggregate_sensitivity("parameters.json", "strength.json", checkpoint)
