import gzip
import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest

from courtsim.nba_manager_evaluation import NBAFrontOfficeOutcome
from courtsim.nba_manager_experiment import (
    NBAManagerExperimentArm,
    NBAManagerExperimentError,
    NBAManagerExperimentSpec,
    NBAManagerSeasonExecution,
    NBAManagerSeasonRequest,
    run_nba_manager_experiment,
    verify_nba_manager_experiment,
)

TEAM_IDS = tuple(f"T{index:02d}" for index in range(1, 31))


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def spec(initial: str) -> NBAManagerExperimentSpec:
    return NBAManagerExperimentSpec(
        "nba-manager-study",
        "baseline",
        "candidate",
        tuple(range(20270401, 20270431)),
        TEAM_IDS,
        2029,
        5,
        TEAM_IDS,
        digest(initial),
        (("players", "a" * 64),),
        "b" * 64,
    )


def executor(
    calls: list[NBAManagerSeasonRequest],
) -> Callable[[NBAManagerSeasonRequest], NBAManagerSeasonExecution]:
    def execute(request: NBAManagerSeasonRequest) -> NBAManagerSeasonExecution:
        calls.append(request)
        previous = json.loads(request.state_payload)
        step = int(previous.get("step", 0)) + 1
        value = 0.53 if request.arm is NBAManagerExperimentArm.TREATMENT else 0.50
        outcome = NBAFrontOfficeOutcome(
            request.source_id,
            request.master_seed,
            request.season_year,
            request.focal_team_id,
            value,
            value,
            value,
            value,
            value,
            value,
            negotiations_opened=2,
            negotiations_accepted=1,
            negotiation_rounds=3,
        )
        return NBAManagerSeasonExecution(
            json.dumps({"arm": request.arm.name.lower(), "step": step}, sort_keys=True),
            outcome,
            json.dumps({"step": step}),
        )

    return execute


def test_nba_manager_experiment_resumes_and_verifies(tmp_path: Path) -> None:
    initial = '{"league":"initial"}'
    output = tmp_path / "study"
    first_calls: list[NBAManagerSeasonRequest] = []
    first = run_nba_manager_experiment(
        spec=spec(initial),
        initial_state_payload=initial,
        executor=executor(first_calls),
        output_directory=output,
        maximum_new_sources=1,
    )
    assert not first.complete
    assert first.executed_cells == 10
    assert first.completed_sources == 1

    resumed_calls: list[NBAManagerSeasonRequest] = []
    resumed = run_nba_manager_experiment(
        spec=spec(initial),
        initial_state_payload=initial,
        executor=executor(resumed_calls),
        output_directory=output,
    )
    assert resumed.complete
    assert resumed.executed_cells == 290
    assert resumed.reused_cells == 10
    assert resumed.evidence is not None and resumed.evidence.recommended
    assert resumed.report_path is not None
    assert verify_nba_manager_experiment(resumed.report_path) == resumed.evidence

    no_calls: list[NBAManagerSeasonRequest] = []
    reused = run_nba_manager_experiment(
        spec=spec(initial),
        initial_state_payload=initial,
        executor=executor(no_calls),
        output_directory=output,
    )
    assert reused.complete
    assert reused.executed_cells == 0
    assert reused.reused_cells == 300
    assert no_calls == []


def test_nba_manager_experiment_detects_tampered_cell(tmp_path: Path) -> None:
    initial = '{"league":"initial"}'
    result = run_nba_manager_experiment(
        spec=spec(initial),
        initial_state_payload=initial,
        executor=executor([]),
        output_directory=tmp_path / "study",
    )
    assert result.report_path is not None
    cell = tmp_path / "study" / "sources" / "source-0001" / "control" / "season-2029.json.gz"
    raw = json.loads(gzip.decompress(cell.read_bytes()))
    raw["execution"]["outcome"]["win_rate"] = 0.99
    cell.write_bytes(gzip.compress(json.dumps(raw).encode(), mtime=0))
    with pytest.raises(NBAManagerExperimentError, match="cell changed"):
        verify_nba_manager_experiment(result.report_path)


def test_nba_manager_spec_rejects_incomplete_focal_coverage() -> None:
    initial = "{}"
    with pytest.raises(ValueError, match="mapping"):
        NBAManagerExperimentSpec(
            "study",
            "baseline",
            "candidate",
            tuple(range(30)),
            ("T01",) * 30,
            2029,
            5,
            TEAM_IDS,
            digest(initial),
            (),
            "b" * 64,
        )


def test_development_spec_allows_eight_unique_focal_sources() -> None:
    initial = "{}"
    development = NBAManagerExperimentSpec(
        "study-development",
        "baseline",
        "candidate",
        tuple(range(20270301, 20270309)),
        TEAM_IDS[:8],
        2029,
        3,
        TEAM_IDS,
        digest(initial),
        (),
        "b" * 64,
        formal_run=False,
    )
    assert not development.formal_run
    assert len(development.master_seeds) == 8


def test_worker_count_changes_only_dispatch_not_evidence(tmp_path: Path) -> None:
    initial = '{"league":"initial"}'
    serial = run_nba_manager_experiment(
        spec=spec(initial),
        initial_state_payload=initial,
        executor=executor([]),
        output_directory=tmp_path / "serial",
        workers=1,
    )
    parallel = run_nba_manager_experiment(
        spec=spec(initial),
        initial_state_payload=initial,
        executor=executor([]),
        output_directory=tmp_path / "parallel",
        workers=4,
    )
    assert serial.evidence == parallel.evidence
    assert (tmp_path / "serial" / "report.json").read_bytes() == (
        tmp_path / "parallel" / "report.json"
    ).read_bytes()
