import json
from collections.abc import Callable
from pathlib import Path

import pytest

from courtsim.manager_evaluation import ManagerEvidenceThresholds
from courtsim.manager_experiment import (
    ManagerExperimentArm,
    ManagerExperimentError,
    ManagerExperimentSpec,
    ManagerSeasonExecution,
    ManagerSeasonMetrics,
    ManagerSeasonRequest,
    run_manager_experiment,
    verify_manager_experiment,
)


def spec(*, seeds: tuple[int, ...] = (101, 202), seasons: int = 2) -> ManagerExperimentSpec:
    return ManagerExperimentSpec(
        "manager-study",
        "manager-policy-v1",
        seeds,
        2028,
        seasons,
        ("away", "home"),
        '{"league":"initial"}',
    )


def thresholds(sources: int = 2, seasons: int = 2) -> ManagerEvidenceThresholds:
    return ManagerEvidenceThresholds(
        minimum_independent_sources=sources,
        minimum_seasons_per_source=seasons,
        minimum_mean_utility_delta=0.005,
        minimum_win_rate_delta=-0.002,
        maximum_loss_rate=0.45,
        minimum_worst_source_delta=-0.04,
    )


def executor(
    calls: list[ManagerSeasonRequest],
    *,
    fail_after: int | None = None,
) -> Callable[[ManagerSeasonRequest], ManagerSeasonExecution]:
    def execute(request: ManagerSeasonRequest) -> ManagerSeasonExecution:
        if fail_after is not None and len(calls) >= fail_after:
            raise RuntimeError("planned interruption")
        calls.append(request)
        bonus = 0.02 if request.arm is ManagerExperimentArm.SHADOW else 0
        prior = json.loads(request.state_payload)
        step = int(prior.get("step", 0)) + 1
        metrics = tuple(
            ManagerSeasonMetrics(
                team_id,
                0.50 + bonus,
                0.25 + bonus,
                0.55 + bonus,
                0.40 + bonus,
            )
            for team_id in ("away", "home")
        )
        return ManagerSeasonExecution(
            json.dumps(
                {
                    "arm": request.arm.name.lower(),
                    "source": request.source_id,
                    "step": step,
                },
                sort_keys=True,
            ),
            metrics,
            json.dumps({"season": request.season_year}),
        )

    return execute


def test_experiment_runs_exact_paired_multiseason_cells(tmp_path: Path) -> None:
    calls: list[ManagerSeasonRequest] = []
    result = run_manager_experiment(
        spec=spec(),
        executor=executor(calls),
        output_directory=tmp_path / "study",
        thresholds=thresholds(),
    )
    assert result.executed_cells == 8
    assert result.reused_cells == 0
    assert result.evidence.recommended
    assert result.evidence.observation_count == 8
    assert result.evidence.independent_sources == 2
    assert verify_manager_experiment(result.report_path) == result.evidence
    assert calls[1].state_payload == json.dumps(
        {"arm": "incumbent", "source": "source-0001", "step": 1},
        sort_keys=True,
    )
    assert calls[4].state_payload == '{"league":"initial"}'


def test_interrupted_experiment_resumes_only_missing_cells(tmp_path: Path) -> None:
    output = tmp_path / "study"
    first_calls: list[ManagerSeasonRequest] = []
    with pytest.raises(RuntimeError, match="planned interruption"):
        run_manager_experiment(
            spec=spec(),
            executor=executor(first_calls, fail_after=3),
            output_directory=output,
            thresholds=thresholds(),
        )
    assert len(first_calls) == 3
    resumed_calls: list[ManagerSeasonRequest] = []
    result = run_manager_experiment(
        spec=spec(),
        executor=executor(resumed_calls),
        output_directory=output,
        thresholds=thresholds(),
    )
    assert result.reused_cells == 3
    assert result.executed_cells == 5
    assert len(resumed_calls) == 5


def test_completed_experiment_is_fully_reusable(tmp_path: Path) -> None:
    output = tmp_path / "study"
    run_manager_experiment(
        spec=spec(),
        executor=executor([]),
        output_directory=output,
        thresholds=thresholds(),
    )
    calls: list[ManagerSeasonRequest] = []
    result = run_manager_experiment(
        spec=spec(),
        executor=executor(calls),
        output_directory=output,
        thresholds=thresholds(),
    )
    assert result.executed_cells == 0
    assert result.reused_cells == 8
    assert calls == []


def test_tampered_cell_fails_integrity_verification_and_resume(tmp_path: Path) -> None:
    output = tmp_path / "study"
    result = run_manager_experiment(
        spec=spec(seeds=(101,), seasons=2),
        executor=executor([]),
        output_directory=output,
        thresholds=thresholds(1, 2),
    )
    cell = output / "sources" / "source-0001" / "shadow" / "season-2028.json"
    raw = json.loads(cell.read_text(encoding="utf-8"))
    raw["metrics"][0]["win_rate"] = 0.99
    cell.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ManagerExperimentError, match="cell changed"):
        verify_manager_experiment(result.report_path)
    with pytest.raises(ManagerExperimentError, match="cell changed"):
        run_manager_experiment(
            spec=spec(seeds=(101,), seasons=2),
            executor=executor([]),
            output_directory=output,
            thresholds=thresholds(1, 2),
        )


def test_existing_output_rejects_a_different_plan(tmp_path: Path) -> None:
    output = tmp_path / "study"
    run_manager_experiment(
        spec=spec(),
        executor=executor([]),
        output_directory=output,
        thresholds=thresholds(),
    )
    with pytest.raises(ManagerExperimentError, match="conflicts"):
        run_manager_experiment(
            spec=spec(seasons=3),
            executor=executor([]),
            output_directory=output,
            thresholds=thresholds(2, 3),
        )


def test_executor_must_cover_all_teams(tmp_path: Path) -> None:
    def incomplete(_: ManagerSeasonRequest) -> ManagerSeasonExecution:
        return ManagerSeasonExecution(
            "{}",
            (ManagerSeasonMetrics("home", 0.5, 0.5, 0.5, 0.5),),
        )

    with pytest.raises(ManagerExperimentError, match="cover every"):
        run_manager_experiment(
            spec=spec(seeds=(1,), seasons=1),
            executor=incomplete,
            output_directory=tmp_path / "study",
            thresholds=thresholds(1, 1),
        )


def test_experiment_contracts_reject_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="master_seeds"):
        spec(seeds=(1, 1))
    with pytest.raises(ValueError, match="team_ids"):
        ManagerExperimentSpec(
            "experiment",
            "policy",
            (1,),
            2028,
            1,
            ("home", "away"),
            "{}",
        )
    with pytest.raises(ValueError, match="metrics"):
        ManagerSeasonMetrics("home", 1.1, 0, 0, 0)
