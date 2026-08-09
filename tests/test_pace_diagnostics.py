import json
import math
from types import SimpleNamespace

import pytest
from test_game_runtime import game

import courtsim.analysis.pace_diagnostics as pace_module
from courtsim.analysis.pace_diagnostics import (
    PaceDiagnosticError,
    audit_pace_clock,
    build_pace_audit_from_bundle,
    build_single_factor_pace_experiment,
    evaluate_pace_holdout,
)


def test_pace_clock_audit_accounts_for_every_possession() -> None:
    results = tuple(game(seed).result for seed in range(10, 20))
    report = audit_pace_clock(results)
    assert report["games"] == 10
    assert report["possessions"] == sum(len(result.possessions) for result in results)
    clock_semantics = report["clock_semantics"]
    contexts = report["contexts"]
    assert isinstance(clock_semantics, dict)
    assert isinstance(contexts, list)
    assert clock_semantics["free_throw_dead_ball_clock_seconds"] == 0
    assert sum(row["possessions"] for row in contexts) == report["possessions"]


def test_pace_experiment_freezes_before_disjoint_holdout() -> None:
    frozen = build_single_factor_pace_experiment(
        experiment_id="pace-short-weight-v1",
        factor_path=("nodes", "possession_duration", "base_probabilities", "SHORT"),
        baseline_value=0.2,
        candidate_values=(0.2, 0.3, 0.4),
        development_observations={
            0.2: (96.7, 96.8),
            0.3: (98.1, 98.2),
            0.4: (99.1, 99.2),
        },
        target_minimum=97.8,
        target_maximum=104.7,
        development_seeds=(11, 12),
        holdout_seeds=(101, 102),
    )
    assert frozen["selected_value"] == 0.3
    holdout = evaluate_pace_holdout(
        frozen,
        holdout_seeds=(101, 102),
        observations=(98.0, 98.4),
    )
    assert holdout["passed"] is True
    with pytest.raises(PaceDiagnosticError, match="seed receipt"):
        evaluate_pace_holdout(frozen, holdout_seeds=(101, 103), observations=(98.0, 98.4))


def test_pace_experiment_rejects_seed_leakage() -> None:
    with pytest.raises(PaceDiagnosticError, match="disjoint"):
        build_single_factor_pace_experiment(
            experiment_id="bad",
            factor_path=("x",),
            baseline_value=0.2,
            candidate_values=(0.2,),
            development_observations={0.2: (96.0,)},
            target_minimum=97.0,
            target_maximum=100.0,
            development_seeds=(1,),
            holdout_seeds=(1,),
        )


def test_pace_bundle_adapter_verifies_and_receipts_full_trace(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path_factory.mktemp("pace-bundle")
    manifest = directory / "manifest.json"
    games = directory / "games.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "outputs": [{"path": "games.jsonl"}],
                "clock": {
                    "regulation_periods": 4,
                    "period_seconds": 720,
                    "possession_seconds": 24,
                    "overtime_enabled": False,
                },
            }
        ),
        encoding="utf-8",
    )
    games.write_text(
        json.dumps(
            {"result": {"possessions": [{"clock_start_seconds": 24, "clock_end_seconds": 0}]}}
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(pace_module, "verify_manifest", lambda _path: SimpleNamespace(ok=True))
    monkeypatch.setattr(pace_module, "game_result_from_dict", lambda *_args: game(10).result)
    report = build_pace_audit_from_bundle(manifest)
    assert report["games"] == 1
    sources = report["sources"]
    assert isinstance(sources, dict)
    assert set(sources) == {"manifest", "games"}

    monkeypatch.setattr(pace_module, "verify_manifest", lambda _path: SimpleNamespace(ok=False))
    with pytest.raises(PaceDiagnosticError, match="verification failed"):
        build_pace_audit_from_bundle(manifest)


def test_pace_bundle_rejects_manifest_and_trace_corruption(
    tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path_factory.mktemp("pace-errors")
    manifest = directory / "manifest.json"
    monkeypatch.setattr(pace_module, "verify_manifest", lambda _path: SimpleNamespace(ok=True))
    manifest.write_text("not-json", encoding="utf-8")
    with pytest.raises(PaceDiagnosticError, match="cannot read model-audit manifest"):
        build_pace_audit_from_bundle(manifest)
    manifest.write_text(json.dumps({"outputs": {}}), encoding="utf-8")
    with pytest.raises(PaceDiagnosticError, match="outputs are invalid"):
        build_pace_audit_from_bundle(manifest)
    manifest.write_text(json.dumps({"outputs": []}), encoding="utf-8")
    with pytest.raises(PaceDiagnosticError, match="full-trace"):
        build_pace_audit_from_bundle(manifest)


def _experiment() -> dict[str, object]:
    return build_single_factor_pace_experiment(
        experiment_id="pace-test",
        factor_path=("nodes", "possession_duration"),
        baseline_value=0.2,
        candidate_values=(0.2,),
        development_observations={0.2: (98.0,)},
        target_minimum=97.0,
        target_maximum=100.0,
        development_seeds=(1,),
        holdout_seeds=(101,),
    )


def test_pace_experiment_and_holdout_strict_validation() -> None:
    with pytest.raises(PaceDiagnosticError, match="identity is invalid"):
        build_single_factor_pace_experiment(
            experiment_id="",
            factor_path=("factor",),
            baseline_value=0.2,
            candidate_values=(0.2,),
            development_observations={0.2: (98.0,)},
            target_minimum=97.0,
            target_maximum=100.0,
            development_seeds=(1,),
            holdout_seeds=(101,),
        )
    with pytest.raises(PaceDiagnosticError, match="canonical and unique"):
        build_single_factor_pace_experiment(
            experiment_id="pace-test",
            factor_path=("factor",),
            baseline_value=0.2,
            candidate_values=(0.2,),
            development_observations={0.2: (98.0, 98.1)},
            target_minimum=97.0,
            target_maximum=100.0,
            development_seeds=(2, 1),
            holdout_seeds=(101,),
        )
    with pytest.raises(PaceDiagnosticError, match="cover every candidate"):
        build_single_factor_pace_experiment(
            experiment_id="pace-test",
            factor_path=("factor",),
            baseline_value=0.2,
            candidate_values=(0.2,),
            development_observations={},
            target_minimum=97.0,
            target_maximum=100.0,
            development_seeds=(1,),
            holdout_seeds=(101,),
        )
    with pytest.raises(PaceDiagnosticError, match="shape is invalid"):
        build_single_factor_pace_experiment(
            experiment_id="pace-test",
            factor_path=("factor",),
            baseline_value=0.2,
            candidate_values=(0.2,),
            development_observations={0.2: (math.nan,)},
            target_minimum=97.0,
            target_maximum=100.0,
            development_seeds=(1,),
            holdout_seeds=(101,),
        )

    frozen = _experiment()
    with pytest.raises(PaceDiagnosticError, match="version differs"):
        evaluate_pace_holdout(
            {**frozen, "version": "old"},
            holdout_seeds=(101,),
            observations=(98.0,),
        )
    with pytest.raises(PaceDiagnosticError, match="freeze hash differs"):
        evaluate_pace_holdout(
            {**frozen, "experiment_id": "changed"},
            holdout_seeds=(101,),
            observations=(98.0,),
        )
    with pytest.raises(PaceDiagnosticError, match="observation shape differs"):
        evaluate_pace_holdout(frozen, holdout_seeds=(101,), observations=())
    with pytest.raises(PaceDiagnosticError, match="must be an object"):
        pace_module._mapping([], "target")
    with pytest.raises(PaceDiagnosticError, match="finite numeric"):
        pace_module._number(math.inf, "target")
    assert pace_module._percentile([10], 0.5) == 10.0
