import json
from pathlib import Path

import pytest

from courtsim.analysis.experiment_matrix import run_experiment_matrix
from courtsim.analysis.matrix_ranking import MatrixRankingError, rank_experiment_matrix
from courtsim.analysis.matrix_style_coverage import build_matrix_style_coverage

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "data" / "model_schema_demo_v1_3.json"
PARAMETERS = ROOT / "data" / "model_parameters_demo_0.4.0.json"
PROFILE = ROOT / "examples" / "player_profile_v1.json"
CORE_TARGETS = ROOT / "experiments" / "nba-2024-25-regular-season-core-v1.json"
CORE_SOURCE = ROOT / "experiments" / "sources" / "nba-2024-25-team-core.json"


def _target(path: Path, target_id: str, lower: float, upper: float) -> Path:
    source = path.parent / "sources" / "nba-core.json"
    source.parent.mkdir(exist_ok=True)
    source.write_bytes(CORE_SOURCE.read_bytes())
    payload = json.loads(CORE_TARGETS.read_text(encoding="utf-8"))
    metric = next(item for item in payload["metrics"] if item["metric"] == "mean_team_possessions")
    metric.update({"lower": lower, "target": (lower + upper) / 2.0, "upper": upper})
    payload["target_set_id"] = target_id
    payload["metrics"] = [metric]
    payload["sources"][0]["artifact_path"] = "sources/nba-core.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_heterogeneous_targets_use_coverage_and_cannot_be_ranked(
    tmp_path: Path,
) -> None:
    first_target = _target(tmp_path / "first-target.json", "first-style", 0.0, 20.0)
    second_target = _target(
        tmp_path / "second-target.json",
        "second-style",
        0.0,
        20.0,
    )
    spec = tmp_path / "matrix.json"
    spec.write_text(
        json.dumps(
            {
                "format_version": 1,
                "matrix_id": "style-coverage-test",
                "base_directory": ".",
                "master_seed": 819,
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
                "targets": [str(first_target)],
                "cells": [
                    {
                        "cell_id": "first",
                        "parameters": str(PARAMETERS),
                        "targets": [str(first_target)],
                        "seed_group": "shared",
                    },
                    {
                        "cell_id": "second",
                        "parameters": str(PARAMETERS),
                        "targets": [str(second_target)],
                        "seed_group": "shared",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    report = run_experiment_matrix(
        spec_path=spec,
        output_directory=tmp_path / "matrix-output",
    )
    coverage_path = build_matrix_style_coverage(
        matrix_report_path=report,
        output_path=tmp_path / "coverage.json",
    )
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    assert coverage["summary"]["integrity_checked"] == 2
    assert coverage["summary"]["metrics_evaluated"] == 2
    assert coverage["summary"]["constant_metrics"] == 1
    assert coverage["policy"]["cross_cell_ranking"] is False

    with pytest.raises(MatrixRankingError, match="heterogeneous"):
        rank_experiment_matrix(
            matrix_report_path=report,
            output_path=tmp_path / "ranking.json",
        )
