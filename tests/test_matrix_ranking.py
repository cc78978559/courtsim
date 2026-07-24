import json
from pathlib import Path

import pytest

from courtsim.analysis.experiment_matrix import run_experiment_matrix
from courtsim.analysis.matrix_ranking import (
    CandidateAssessment,
    MatrixRankingError,
    rank_candidate_assessments,
    rank_experiment_matrix,
)
from courtsim.cli import main

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "data" / "model_schema_demo_v1_3.json"
PARAMETERS = ROOT / "data" / "model_parameters_demo_0.4.0.json"
PROFILE = ROOT / "examples" / "player_profile_v1.json"
CORE_TARGETS = ROOT / "experiments" / "nba-2024-25-regular-season-core-v1.json"
CORE_SOURCE = ROOT / "experiments" / "sources" / "nba-2024-25-team-core.json"


def candidate(cell_id: str, *, eligible: bool, center: float) -> CandidateAssessment:
    return CandidateAssessment(
        cell_id=cell_id,
        eligible=eligible,
        active_targets=1,
        failed_active_targets=0 if eligible else 1,
        required_failures=0 if eligible else 1,
        center_weighted_rmse=center,
        result_path=f"cells/{cell_id}/cell-result.json",
        plan_sha256="a" * 64,
        audit_sha256="b" * 64,
    )


def test_pure_ranking_distinguishes_single_tie_and_no_candidate() -> None:
    ordered, status, recommended = rank_candidate_assessments(
        (
            candidate("worse", eligible=True, center=0.3),
            candidate("best", eligible=True, center=0.1),
            candidate("failed", eligible=False, center=0.0),
        )
    )
    assert tuple(item.cell_id for item in ordered) == ("best", "worse", "failed")
    assert status == "single-candidate"
    assert recommended == ("best",)

    _, status, recommended = rank_candidate_assessments(
        (
            candidate("alpha", eligible=True, center=0.1),
            candidate("beta", eligible=True, center=0.1),
        )
    )
    assert status == "tie"
    assert recommended == ("alpha", "beta")

    _, status, recommended = rank_candidate_assessments(
        (candidate("failed", eligible=False, center=0.0),)
    )
    assert status == "no-eligible-candidate"
    assert recommended == ()


def write_wide_target(path: Path) -> Path:
    source_directory = path.parent / "sources"
    source_directory.mkdir(parents=True)
    copied_source = source_directory / "nba-core.json"
    copied_source.write_bytes(CORE_SOURCE.read_bytes())
    payload = json.loads(CORE_TARGETS.read_text(encoding="utf-8"))
    metric = next(item for item in payload["metrics"] if item["metric"] == "mean_team_possessions")
    metric.update({"lower": 0.0, "target": 1.0, "upper": 2.0})
    payload["metrics"] = [metric]
    payload["target_set_id"] = "test-wide-active-v1"
    payload["sources"][0]["artifact_path"] = "sources/nba-core.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def write_matrix_spec(path: Path, target: Path) -> Path:
    payload = {
        "format_version": 1,
        "matrix_id": "ranking-test",
        "base_directory": ".",
        "master_seed": 818,
        "defaults": {
            "schema": str(SCHEMA),
            "profile": str(PROFILE),
            "games": 2,
            "workers": 1,
            "start_index": 0,
            "trace_mode": "aggregate-only",
            "clock": {
                "regulation_periods": 1,
                "period_seconds": 20,
                "possession_seconds": 10,
            },
        },
        "targets": [str(target)],
        "cells": [
            {"cell_id": "alpha", "parameters": str(PARAMETERS)},
            {"cell_id": "beta", "parameters": str(PARAMETERS)},
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_ranking_recomputes_scores_and_reports_tied_eligible_cells(tmp_path: Path) -> None:
    target = write_wide_target(tmp_path / "wide-target.json")
    spec = write_matrix_spec(tmp_path / "matrix.json", target)
    matrix_directory = tmp_path / "matrix-output"
    matrix_report = run_experiment_matrix(
        spec_path=spec,
        output_directory=matrix_directory,
    )
    ranking_path = tmp_path / "ranking.json"
    assert (
        main(
            [
                "matrix-rank",
                str(matrix_report),
                "--output",
                str(ranking_path),
            ]
        )
        == 0
    )
    ranking = json.loads(ranking_path.read_text(encoding="utf-8"))
    assert ranking["recommendation"] == {
        "status": "tie",
        "candidate_cell_ids": ["alpha", "beta"],
        "automatic_promotion": False,
    }
    assert ranking["summary"]["eligible_candidates"] == 2
    assert all(item["center_weighted_rmse"] == 0.0 for item in ranking["ranking"])

    alpha_result_path = matrix_directory / "cells" / "alpha" / "cell-result.json"
    alpha_result = json.loads(alpha_result_path.read_text(encoding="utf-8"))
    score_path = alpha_result_path.parent / alpha_result["targets"][0]["path"]
    score = json.loads(score_path.read_text(encoding="utf-8"))
    score["metric_results"][0]["value"] = 999.0
    score_path.write_text(json.dumps(score), encoding="utf-8")
    with pytest.raises(MatrixRankingError, match="missing or changed"):
        rank_experiment_matrix(
            matrix_report_path=matrix_report,
            output_path=tmp_path / "tampered-ranking.json",
        )


def test_matrix_rank_returns_nine_without_active_targets(tmp_path: Path) -> None:
    spec = write_matrix_spec(tmp_path / "matrix.json", tmp_path / "unused.json")
    payload = json.loads(spec.read_text(encoding="utf-8"))
    payload["targets"] = []
    payload["cells"] = payload["cells"][:1]
    spec.write_text(json.dumps(payload), encoding="utf-8")
    matrix_report = run_experiment_matrix(
        spec_path=spec,
        output_directory=tmp_path / "matrix-output",
    )
    ranking_path = tmp_path / "ranking.json"
    assert main(["matrix-rank", str(matrix_report), "--output", str(ranking_path)]) == 9
    ranking = json.loads(ranking_path.read_text(encoding="utf-8"))
    assert ranking["recommendation"]["status"] == "no-eligible-candidate"
    assert ranking["ranking"][0]["center_weighted_rmse"] is None
