import pytest
from test_game_runtime import game

from courtsim.analysis.pace_diagnostics import (
    PaceDiagnosticError,
    audit_pace_clock,
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
