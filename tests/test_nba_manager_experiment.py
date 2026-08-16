import gzip
import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import courtsim.nba_manager_experiment as manager_experiment_module
from courtsim.cli import main
from courtsim.manager_ai import REALITY_BASELINE_POLICY_ID, WHITE_BOX_CANDIDATE_POLICY_ID
from courtsim.nba_manager_evaluation import NBAFrontOfficeOutcome
from courtsim.nba_manager_experiment import (
    NBA_MANAGER_REQUIRED_CI,
    NBAManagerExperimentArm,
    NBAManagerExperimentError,
    NBAManagerExperimentSpec,
    NBAManagerSeasonExecution,
    NBAManagerSeasonRequest,
    build_nba_manager_candidate_receipt,
    inspect_nba_manager_experiment,
    nba_manager_code_identity,
    run_nba_manager_experiment,
    verify_nba_manager_experiment,
)
from courtsim.nba_manager_protocol import (
    NBA_MANAGER_CANONICAL_TEAM_IDS,
    NBA_MANAGER_PROTOCOL_INPUT_ROLES,
    NBA_MANAGER_PROTOCOL_SOURCE_ROLE,
)

TEAM_IDS = NBA_MANAGER_CANONICAL_TEAM_IDS
CODE_COMMIT, CODE_TREE_SHA256 = nba_manager_code_identity()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def simple_outcome() -> NBAFrontOfficeOutcome:
    return NBAFrontOfficeOutcome("source-0001", 1, 2029, "T01", *(0.5,) * 6)


def spec(initial: str) -> NBAManagerExperimentSpec:
    return NBAManagerExperimentSpec(
        "nba-manager-policy-v1",
        REALITY_BASELINE_POLICY_ID,
        WHITE_BOX_CANDIDATE_POLICY_ID,
        tuple(range(20270401, 20270431)),
        TEAM_IDS,
        2029,
        5,
        TEAM_IDS,
        digest(initial),
        tuple(
            (role, "a" * 64)
            for role in sorted(
                {*NBA_MANAGER_PROTOCOL_INPUT_ROLES, NBA_MANAGER_PROTOCOL_SOURCE_ROLE}
            )
        ),
        "b" * 64,
        (("pace", 90.0, 110.0),),
        CODE_COMMIT,
        CODE_TREE_SHA256,
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
            macro_metrics=(("pace", 100.0),),
        )
        return NBAManagerSeasonExecution(
            json.dumps({"arm": request.arm.name.lower(), "step": step}, sort_keys=True),
            outcome,
            json.dumps(
                {
                    "version": "nba-manager-adapter-v1",
                    "arm": request.arm.name.lower(),
                    "focal_team_id": request.focal_team_id,
                    "candidate_teams": (
                        []
                        if request.arm is NBAManagerExperimentArm.CONTROL
                        else [request.focal_team_id]
                    ),
                    "outcome": asdict(outcome),
                },
                sort_keys=True,
            ),
        )

    return execute


def test_nba_manager_experiment_resumes_and_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
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
    assert inspect_nba_manager_experiment(output) == {
        "version": "nba-manager-experiment-v1",
        "complete": False,
        "status": "running",
        "completed_cells": 10,
        "expected_cells": 300,
        "completed_sources": 1,
        "expected_sources": 30,
        "formal_run": True,
    }

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
    monkeypatch.setattr(
        manager_experiment_module,
        "nba_manager_code_identity",
        lambda **_: (CODE_COMMIT, CODE_TREE_SHA256),
    )
    frozen = spec(initial)
    monkeypatch.setattr(
        manager_experiment_module,
        "verify_nba_manager_protocol_file",
        lambda *_: None,
    )
    monkeypatch.setattr(
        manager_experiment_module,
        "load_nba_manager_promotion_protocol",
        lambda *_: SimpleNamespace(
            experiment_id=frozen.experiment_id,
            start_season=frozen.start_season,
            initial_state_sha256=frozen.initial_state_sha256,
            source_hashes=tuple(
                item for item in frozen.source_hashes if item[0] != NBA_MANAGER_PROTOCOL_SOURCE_ROLE
            ),
            execution_config_sha256=frozen.execution_config_sha256,
            macro_ranges=frozen.macro_ranges,
            team_ids=frozen.team_ids,
            master_seeds=frozen.master_seeds,
            focal_team_ids=frozen.focal_team_ids,
            seasons=frozen.seasons,
        ),
    )
    monkeypatch.setattr(
        manager_experiment_module,
        "_verify_github_ci_attestation",
        lambda *_: None,
    )
    ci_checks = {
        name: (f"passed@{CODE_COMMIT}@https://github.com/cc78978559/courtsim/actions/runs/1")
        for name in NBA_MANAGER_REQUIRED_CI
    }
    receipt = build_nba_manager_candidate_receipt(
        resumed.report_path,
        git_commit=CODE_COMMIT,
        ci_checks=ci_checks,
    )
    assert receipt["status"] == "candidate-pass"
    assert main(["nba-manager-study-status", str(output)]) == 0
    assert main(["nba-manager-study-verify", str(resumed.report_path)]) == 0
    receipt_path = tmp_path / "candidate.json"
    cli_arguments = [
        "nba-manager-study-receipt",
        str(resumed.report_path),
        str(receipt_path),
        "--git-commit",
        CODE_COMMIT,
    ]
    for name, value in ci_checks.items():
        cli_arguments.extend(("--ci", f"{name}={value}"))
    assert main(cli_arguments) == 0
    assert json.loads(receipt_path.read_text(encoding="utf-8"))["status"] == "candidate-pass"
    with pytest.raises(NBAManagerExperimentError, match="exact CI"):
        build_nba_manager_candidate_receipt(
            resumed.report_path,
            git_commit=CODE_COMMIT,
            ci_checks={},
        )
    invalid_ci = dict(ci_checks)
    invalid_ci[NBA_MANAGER_REQUIRED_CI[0]] = (
        f"passed@{'0' * 40}@https://github.com/x/actions/runs/1"
    )
    with pytest.raises(NBAManagerExperimentError, match="commit-bound"):
        build_nba_manager_candidate_receipt(
            resumed.report_path,
            git_commit=CODE_COMMIT,
            ci_checks=invalid_ci,
        )
    with pytest.raises(NBAManagerExperimentError, match="Git commit differs"):
        build_nba_manager_candidate_receipt(
            resumed.report_path,
            git_commit="0" * 40,
            ci_checks=ci_checks,
        )

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
            REALITY_BASELINE_POLICY_ID,
            WHITE_BOX_CANDIDATE_POLICY_ID,
            tuple(range(30)),
            ("T01",) * 30,
            2029,
            5,
            TEAM_IDS,
            digest(initial),
            (),
            "b" * 64,
            (("pace", 90.0, 110.0),),
            "c" * 40,
            "d" * 64,
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
        (),
        "c" * 40,
        "d" * 64,
        formal_run=False,
    )
    assert not development.formal_run
    assert len(development.master_seeds) == 8


def test_formal_spec_rejects_nonfrozen_seed_mapping() -> None:
    with pytest.raises(ValueError, match="identity is not frozen"):
        NBAManagerExperimentSpec(
            "wrong-formal",
            REALITY_BASELINE_POLICY_ID,
            WHITE_BOX_CANDIDATE_POLICY_ID,
            tuple(range(20270501, 20270531)),
            TEAM_IDS,
            2029,
            5,
            TEAM_IDS,
            digest("{}"),
            (),
            "b" * 64,
            (("pace", 90.0, 110.0),),
            CODE_COMMIT,
            CODE_TREE_SHA256,
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"experiment_id": ""}, "identity"),
        ({"seasons": 0, "formal_run": False}, "seasons"),
        ({"initial_state_sha256": "bad", "formal_run": False}, "initial state"),
        ({"execution_config_sha256": "bad", "formal_run": False}, "execution configuration"),
        ({"macro_ranges": (("pace", 2.0, 1.0),), "formal_run": False}, "macro ranges"),
        ({"code_commit": "bad", "formal_run": False}, "code commit"),
        ({"code_tree_sha256": "bad", "formal_run": False}, "code tree"),
        (
            {"source_hashes": (("z", "a" * 64), ("a", "b" * 64)), "formal_run": False},
            "source hashes",
        ),
    ),
)
def test_spec_rejects_invalid_frozen_identity(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(spec("{}"), **changes)


def test_code_identity_rejects_missing_git_and_invalid_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unavailable(*args: object, **kwargs: object) -> object:
        raise OSError("git unavailable")

    monkeypatch.setattr("courtsim.nba_manager_experiment.subprocess.run", unavailable)
    with pytest.raises(NBAManagerExperimentError, match="establish"):
        nba_manager_code_identity()
    monkeypatch.setattr(
        "courtsim.nba_manager_experiment.subprocess.run",
        lambda *args, **kwargs: SimpleNamespace(stdout="not-a-commit\n"),
    )
    with pytest.raises(NBAManagerExperimentError, match="Git commit"):
        nba_manager_code_identity()


def test_code_identity_clean_gate_rejects_dirty_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    results = iter(
        (
            SimpleNamespace(stdout=f"{CODE_COMMIT}\n"),
            SimpleNamespace(stdout=" M src/courtsim/example.py\n"),
        )
    )
    monkeypatch.setattr(
        "courtsim.nba_manager_experiment.subprocess.run",
        lambda *args, **kwargs: next(results),
    )
    with pytest.raises(NBAManagerExperimentError, match="clean code tree"):
        nba_manager_code_identity(require_clean=True)


def test_github_ci_attestation_verifies_repository_commit_and_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = json.dumps(payload).encode()

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return self.payload

    responses = iter(
        (
            Response(
                {
                    "head_sha": CODE_COMMIT,
                    "conclusion": "success",
                    "repository": {"full_name": "cc78978559/courtsim"},
                }
            ),
            Response(
                {
                    "jobs": [
                        {"name": "windows-ci", "conclusion": "success"},
                    ]
                }
            ),
        )
    )
    monkeypatch.setattr(
        "courtsim.nba_manager_experiment.urllib.request.urlopen",
        lambda *args, **kwargs: next(responses),
    )

    manager_experiment_module._verify_github_ci_attestation(
        "windows-ci",
        "https://github.com/cc78978559/courtsim/actions/runs/12345",
        CODE_COMMIT,
    )

    with pytest.raises(NBAManagerExperimentError, match="courtsim repository"):
        manager_experiment_module._verify_github_ci_attestation(
            "windows-ci",
            "https://github.com/example/courtsim/actions/runs/12345",
            CODE_COMMIT,
        )


def test_github_ci_attestation_rejects_failed_or_unavailable_runs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Response:
        def __init__(self, payload: dict[str, object]) -> None:
            self.payload = json.dumps(payload).encode()

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return self.payload

    responses = iter(
        (
            Response(
                {
                    "head_sha": "0" * 40,
                    "conclusion": "success",
                    "repository": {"full_name": "cc78978559/courtsim"},
                }
            ),
            Response({"jobs": []}),
        )
    )
    monkeypatch.setattr(
        "courtsim.nba_manager_experiment.urllib.request.urlopen",
        lambda *args, **kwargs: next(responses),
    )
    with pytest.raises(NBAManagerExperimentError, match="not successful"):
        manager_experiment_module._verify_github_ci_attestation(
            "windows-ci",
            "https://github.com/cc78978559/courtsim/actions/runs/12345",
            CODE_COMMIT,
        )

    def unavailable(*args: object, **kwargs: object) -> object:
        raise OSError("offline")

    monkeypatch.setattr(
        "courtsim.nba_manager_experiment.urllib.request.urlopen",
        unavailable,
    )
    with pytest.raises(NBAManagerExperimentError, match="cannot verify"):
        manager_experiment_module._verify_github_ci_attestation(
            "windows-ci",
            "https://github.com/cc78978559/courtsim/actions/runs/12345",
            CODE_COMMIT,
        )


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


@pytest.mark.parametrize("audit_payload", ("", "not-json", "[]"))
def test_season_execution_rejects_invalid_audit_payload(audit_payload: str) -> None:
    with pytest.raises(ValueError, match=r"payloads|JSON|object"):
        NBAManagerSeasonExecution("next", simple_outcome(), audit_payload)


@pytest.mark.parametrize("value", (None, "", "../cell.json", "C:\\absolute\\cell.json"))
def test_artifact_paths_are_confined(value: object) -> None:
    with pytest.raises(NBAManagerExperimentError, match="path"):
        manager_experiment_module._safe_relative(value)


def test_internal_artifact_schema_guards() -> None:
    with pytest.raises(NBAManagerExperimentError, match="object"):
        manager_experiment_module._object([], "artifact")
    with pytest.raises(NBAManagerExperimentError, match="fields differ"):
        manager_experiment_module._exact({"unexpected": 1}, {"expected"}, "artifact")
    with pytest.raises(NBAManagerExperimentError, match="paired arm"):
        manager_experiment_module._paired_outcomes(
            {
                (
                    "source-0001",
                    1,
                    2029,
                    "T01",
                    NBAManagerExperimentArm.CONTROL,
                ): simple_outcome()
            }
        )


@pytest.mark.parametrize(
    "change",
    (
        {"source_id": "invalid"},
        {"source_id": "source-9999"},
        {"experiment_id": "other"},
        {"baseline_policy_id": "other"},
        {"candidate_policy_id": "other"},
        {"master_seed": -1},
        {"focal_team_id": "other"},
        {"season_year": 9999},
    ),
)
def test_request_must_match_frozen_plan(change: dict[str, Any]) -> None:
    frozen = spec("{}")
    request = NBAManagerSeasonRequest(
        frozen.experiment_id,
        frozen.baseline_policy_id,
        frozen.candidate_policy_id,
        NBAManagerExperimentArm.CONTROL,
        "source-0001",
        frozen.master_seeds[0],
        frozen.focal_team_ids[0],
        frozen.start_season,
        "{}",
    )
    with pytest.raises(NBAManagerExperimentError, match=r"identity|frozen plan"):
        manager_experiment_module._validate_request_against_spec(replace(request, **change), frozen)
