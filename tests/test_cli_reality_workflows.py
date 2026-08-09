from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from pytest import CaptureFixture, MonkeyPatch

import courtsim.cli as cli


def test_player_and_pace_commands_write_compact_reports(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "build_nba_player_audit_from_bundle",
        lambda *_args: {"games": 2, "players": [{"id": 1}], "version": "audit-v1"},
    )
    audit_output = tmp_path / "audit.json"
    assert cli.main(["nba-player-audit", "manifest", "targets", "identity", str(audit_output)]) == 0
    assert json.loads(audit_output.read_text(encoding="utf-8"))["games"] == 2

    monkeypatch.setattr(
        cli,
        "evaluate_nba_player_audit_files",
        lambda *_args: {"metrics": [{"metric": "usage"}], "players": 1, "version": "eval-v1"},
    )
    evaluation_output = tmp_path / "evaluation.json"
    assert cli.main(["nba-player-evaluate", "audit", "targets", str(evaluation_output)]) == 0

    monkeypatch.setattr(
        cli,
        "aggregate_nba_player_evaluation_files",
        lambda _paths: {
            "metrics": [{"metric": "usage"}],
            "players": 1,
            "runs": 2,
            "version": "batch-v1",
        },
    )
    batch_output = tmp_path / "batch.json"
    assert cli.main(["nba-player-evaluate-batch", str(batch_output), "a.json", "b.json"]) == 0

    monkeypatch.setattr(
        cli,
        "build_pace_audit_from_bundle",
        lambda _path: {
            "contexts": [{"name": "all"}],
            "games": 2,
            "mean_team_possessions": 99.5,
            "version": "pace-v1",
        },
    )
    pace_output = tmp_path / "pace.json"
    assert cli.main(["pace-clock-audit", "manifest", str(pace_output)]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 4


def test_management_and_calibration_commands_preserve_exit_semantics(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "inspect_draft_obligation_files",
        lambda *_args: {
            "as_of_year": 2026,
            "counts": {"frozen": 1},
            "ready": False,
            "source_verified": True,
            "ledger_version": "v3",
        },
    )
    obligation_output = tmp_path / "obligations.json"
    assert (
        cli.main(
            [
                "draft-obligation-audit",
                "ledger.json",
                "assets.json",
                "--output",
                str(obligation_output),
            ]
        )
        == 6
    )
    assert obligation_output.is_file()

    identity = tmp_path / "identity.json"
    identity.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(cli, "load_nba_player_target_set", lambda _path: object())
    monkeypatch.setattr(
        cli,
        "build_player_calibration_plan",
        lambda *_args: {
            "players": 3,
            "promotion_ready": False,
            "version": "calibration-plan-v1",
        },
    )
    plan_output = tmp_path / "plan.json"
    assert (
        cli.main(["nba-player-calibration-plan", "targets.json", str(identity), str(plan_output)])
        == 17
    )
    assert json.loads(plan_output.read_text(encoding="utf-8"))["players"] == 3

    identity.write_text("[]", encoding="utf-8")
    assert (
        cli.main(["nba-player-calibration-plan", "targets.json", str(identity), str(plan_output)])
        == 2
    )


def test_quick_sim_runner_and_reality_commands_forward_configuration(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def run_full(**kwargs: object) -> dict[str, object]:
        captured.update(kwargs)
        return {"checkpoint": {"completed_seasons": 2, "complete": True}}

    monkeypatch.setattr(cli, "run_nba_quick_sim_batch", run_full)
    checkpoint = tmp_path / "full.json"
    assert (
        cli.main(
            [
                "nba-quick-sim-run",
                "profiles.json",
                "strength.json",
                str(checkpoint),
                "--batch-id",
                "holdout",
                "--master-seed",
                "77",
                "--seasons",
                "2",
                "--workers",
                "2",
            ]
        )
        == 0
    )
    assert captured["workers"] == 2
    assert captured["manifest_path"] == checkpoint.with_suffix(".manifest.json")

    monkeypatch.setattr(
        cli,
        "run_nba_aggregate_quick_sim_batch",
        lambda **_kwargs: {"checkpoint": {"completed_seasons": 2, "complete": True}},
    )
    aggregate = tmp_path / "aggregate.json"
    assert (
        cli.main(
            [
                "nba-aggregate-quick-sim-run",
                str(aggregate),
                "--batch-id",
                "holdout",
                "--master-seed",
                "77",
                "--seasons",
                "2",
            ]
        )
        == 0
    )

    monkeypatch.setattr(
        cli,
        "run_aggregate_sensitivity",
        lambda *_args: {
            "baseline_batch_sha256": "a" * 64,
            "variants": [{"name": "pace"}],
            "version": "sensitivity-v1",
        },
    )
    sensitivity = tmp_path / "sensitivity.json"
    assert cli.main(["nba-aggregate-sensitivity", "baseline.json", str(sensitivity)]) == 0

    monkeypatch.setattr(
        cli,
        "build_nba_reality_payload",
        lambda *_args: (
            {"dataset_id": "reality", "seasons": [{"season": "2024-25"}]},
            {"version": "reference-v1"},
        ),
    )
    reality = tmp_path / "reality.json"
    reference = tmp_path / "reference.json"
    assert (
        cli.main(
            [
                "nba-reality-build",
                "manifest.json",
                str(reality),
                str(reference),
                "--cache",
                str(tmp_path / "cache"),
            ]
        )
        == 0
    )
    assert reality.is_file() and reference.is_file()


def test_formal_gate_command_returns_failure_code_and_optional_output(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cli,
        "evaluate_quick_sim_formal_gate",
        lambda *_args: {"passed": False, "version": "gate-v1"},
    )
    output = tmp_path / "formal-gate.json"
    assert (
        cli.main(
            [
                "nba-quick-sim-formal-gate",
                "checkpoint.json",
                "gate.json",
                "manifest.json",
                "--output",
                str(output),
            ]
        )
        == 15
    )
    assert json.loads(output.read_text(encoding="utf-8"))["passed"] is False


def test_nba_data_player_builders_emit_compact_receipts(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        cli,
        "build_nba_data_summary",
        lambda *_args, **_kwargs: {
            "cached": True,
            "dataset_id": "nba",
            "groups": [1, 2],
            "rows_processed": 10,
            "season": "2024-25",
        },
    )
    assert cli.main(["nba-data", "build", "manifest", str(tmp_path / "summary.json")]) == 0

    monkeypatch.setattr(
        cli,
        "inspect_nba_data",
        lambda *_args: {"dataset_id": "nba", "status": "ready"},
    )
    assert cli.main(["nba-data", "status", "manifest"]) == 0

    monkeypatch.setattr(
        cli,
        "build_nba_player_identity_payload",
        lambda *_args, **_kwargs: {
            "coverage": {"players": 1.0},
            "promotion": {"ready": True},
            "season": "2024-25",
            "version": "identity-v1",
        },
    )
    assert (
        cli.main(
            [
                "nba-data",
                "build-player-identity",
                "box.json",
                "crosswalk.json",
                str(tmp_path / "identity.json"),
            ]
        )
        == 0
    )

    monkeypatch.setattr(
        cli,
        "augment_nba_player_crosswalk_payload",
        lambda *_args: {"augmentation": {"added": 2}, "season": "2024-25"},
    )
    assert (
        cli.main(
            [
                "nba-data",
                "augment-player-crosswalk",
                "box.json",
                "crosswalk.json",
                "shots.json",
                str(tmp_path / "augmented.json"),
            ]
        )
        == 0
    )

    monkeypatch.setattr(
        cli,
        "build_nba_player_target_payload",
        lambda *_args, **_kwargs: {
            "players": [{"nba_player_id": 1}],
            "season": "2024-25",
            "target_id": "players",
            "version": "targets-v1",
        },
    )
    assert (
        cli.main(
            [
                "nba-data",
                "build-player-targets",
                "box.json",
                "shots.json",
                "identity.json",
                str(tmp_path / "targets.json"),
                "--target-id",
                "players",
            ]
        )
        == 0
    )
    assert len(capsys.readouterr().out.splitlines()) == 5


def test_quick_sim_consistency_command_handles_diagnostic_and_frozen_gate(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    aggregate_path = tmp_path / "aggregate.json"
    full_path = tmp_path / "full.json"
    for path in (aggregate_path, full_path):
        path.write_text("{}", encoding="utf-8")
    spec = SimpleNamespace(master_seed=77)
    batch = SimpleNamespace(
        spec=spec,
        cells=(SimpleNamespace(seed=1, summary=SimpleNamespace()),),
    )
    monkeypatch.setattr(cli, "quick_sim_batch_from_json", lambda _raw: batch)
    monkeypatch.setattr(
        cli,
        "compare_quick_sim_engines",
        lambda *_args, **_kwargs: {"promotion_ready": False, "version": "consistency-v1"},
    )
    diagnostic_output = tmp_path / "diagnostic.json"
    assert (
        cli.main(
            [
                "nba-quick-sim-consistency",
                str(aggregate_path),
                str(full_path),
                str(diagnostic_output),
            ]
        )
        == 0
    )

    monkeypatch.setattr(cli, "load_quick_sim_consistency_gate", lambda _path: {"gate": True})
    monkeypatch.setattr(cli, "verify_quick_sim_consistency_manifests", lambda *_args: True)
    gated_output = tmp_path / "gated.json"
    assert (
        cli.main(
            [
                "nba-quick-sim-consistency",
                str(aggregate_path),
                str(full_path),
                str(gated_output),
                "--gate",
                "gate.json",
                "--aggregate-manifest",
                "aggregate.manifest.json",
                "--full-manifest",
                "full.manifest.json",
            ]
        )
        == 16
    )


def test_shot_profile_commands_forward_experiment_configuration(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "load_distribution_audit", lambda _path: object())
    monkeypatch.setattr(cli, "load_nba_shot_profile_set", lambda _path: object())
    monkeypatch.setattr(
        cli,
        "evaluate_nba_shot_profile_audits",
        lambda *_args: {
            "status": "improved",
            "baseline_rmse": 0.2,
            "candidate_rmse": 0.1,
        },
    )
    evaluation = tmp_path / "shot-evaluation.json"
    assert (
        cli.main(
            [
                "nba-shot-profile-evaluate",
                "baseline.json",
                "candidate.json",
                "profiles.json",
                str(evaluation),
            ]
        )
        == 0
    )

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first.write_text("{}", encoding="utf-8")
    second.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        cli,
        "aggregate_nba_shot_profile_evaluations",
        lambda _reports: {
            "status": "improved",
            "improved_runs": 2,
            "runs": 2,
            "baseline_rmse": 0.2,
            "candidate_rmse": 0.1,
        },
    )
    assert (
        cli.main(
            [
                "nba-shot-profile-evaluate-batch",
                str(tmp_path / "shot-batch.json"),
                str(first),
                str(second),
            ]
        )
        == 0
    )

    monkeypatch.setattr(
        cli,
        "run_nba_shot_profile_experiment",
        lambda **_kwargs: {
            "summary": {
                "status": "improved",
                "games": 1230,
                "baseline_rmse": 0.2,
                "candidate_rmse": 0.1,
            }
        },
    )
    assert cli.main(["nba-shot-profile-run", "profiles.json", "--output", str(tmp_path)]) == 0

    monkeypatch.setattr(
        cli,
        "run_nba_shot_profile_batch",
        lambda **_kwargs: {"completed_runs": 2},
    )
    assert (
        cli.main(
            [
                "nba-shot-profile-run-batch",
                "profiles.json",
                "--runs",
                "2",
                "--output",
                str(tmp_path),
            ]
        )
        == 0
    )
