import json
from pathlib import Path

from courtsim.cli import main

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "examples" / "minimal_scenario.json"
MODEL_SCHEMA = ROOT / "data" / "model_schema_demo_v1_3.json"
MODEL_PARAMETERS = ROOT / "data" / "model_parameters_demo_0.4.0.json"
PLAYER_PROFILE = ROOT / "examples" / "player_profile_v1.json"
AUDIT_BASELINE = ROOT / "data" / "baselines" / "model-audit-demo-0.4.0.json"
AUDIT_GATES = ROOT / "experiments" / "model-audit-demo-0.4.0-regression-gates.json"
REALISM_TEMPLATE = ROOT / "experiments" / "realism-targets-template-v1.json"
LATE_TEMPO_SCHEMA = ROOT / "data" / "model_schema_demo_v1_9.json"
LATE_TEMPO_PARAMETERS = ROOT / "data" / "model_parameters_demo_1.1.0.json"


def test_doctor_and_validate_commands() -> None:
    assert main(["doctor"]) == 0
    assert main(["validate", str(SCENARIO)]) == 0


def test_tempo_policy_audit_command(tmp_path: Path) -> None:
    output = tmp_path / "tempo-policy.json"
    assert (
        main(
            [
                "tempo-policy-audit",
                str(LATE_TEMPO_SCHEMA),
                str(LATE_TEMPO_PARAMETERS),
                "--output",
                str(output),
            ]
        )
        == 0
    )
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["summary"] == {"checked": 4, "failed": 0, "passed": True}


def test_demo_replay_and_verify_commands(tmp_path: Path) -> None:
    output = tmp_path / "demo"
    assert (
        main(
            [
                "demo",
                "--scenario",
                str(SCENARIO),
                "--seed",
                "123",
                "--possessions",
                "2",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert main(["replay", str(output / "events.jsonl"), "--limit", "1"]) == 0
    assert main(["verify", str(output / "manifest.json")]) == 0
    assert main(["verify", str(output / "manifest.json"), "--outputs-only"]) == 0


def test_batch_command(tmp_path: Path) -> None:
    output = tmp_path / "batch"
    assert (
        main(
            [
                "batch",
                "--scenario",
                str(SCENARIO),
                "--runs",
                "2",
                "--workers",
                "1",
                "--possessions",
                "2",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    manifest = json.loads((output / "batch_manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["runs"]) == 2


def test_model_audit_command_writes_a_verifiable_shard(tmp_path: Path) -> None:
    output = tmp_path / "model-audit"
    assert (
        main(
            [
                "model-audit",
                "--schema",
                str(MODEL_SCHEMA),
                "--parameters",
                str(MODEL_PARAMETERS),
                "--profile",
                str(PLAYER_PROFILE),
                "--games",
                "2",
                "--workers",
                "2",
                "--start-index",
                "4",
                "--periods",
                "1",
                "--period-seconds",
                "20",
                "--possession-seconds",
                "10",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["game_indices"] == [4, 5]
    assert main(["verify", str(output / "manifest.json")]) == 0


def test_model_audit_aggregate_only_writes_no_event_stream(tmp_path: Path) -> None:
    output = tmp_path / "model-audit-aggregate"
    assert (
        main(
            [
                "model-audit",
                "--schema",
                str(MODEL_SCHEMA),
                "--parameters",
                str(MODEL_PARAMETERS),
                "--profile",
                str(PLAYER_PROFILE),
                "--games",
                "2",
                "--trace-mode",
                "aggregate-only",
                "--periods",
                "1",
                "--period-seconds",
                "20",
                "--possession-seconds",
                "10",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert (output / "audit.json").is_file()
    assert not (output / "games.jsonl").exists()
    assert main(["verify", str(output / "manifest.json")]) == 0


def test_model_benchmark_command_writes_repeatable_report(tmp_path: Path) -> None:
    output = tmp_path / "model-benchmark"
    assert (
        main(
            [
                "model-benchmark",
                "--schema",
                str(MODEL_SCHEMA),
                "--parameters",
                str(MODEL_PARAMETERS),
                "--profile",
                str(PLAYER_PROFILE),
                "--games",
                "1",
                "--repeats",
                "2",
                "--warmups",
                "0",
                "--periods",
                "1",
                "--period-seconds",
                "10",
                "--possession-seconds",
                "10",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    report = json.loads((output / "benchmark.json").read_text(encoding="utf-8"))
    assert len(report["trials"]) == 2
    assert report["summary"]["audit_sha256"]

    failing_output = tmp_path / "model-benchmark-failing-gate"
    assert (
        main(
            [
                "model-benchmark",
                "--schema",
                str(MODEL_SCHEMA),
                "--parameters",
                str(MODEL_PARAMETERS),
                "--profile",
                str(PLAYER_PROFILE),
                "--games",
                "1",
                "--repeats",
                "1",
                "--warmups",
                "0",
                "--periods",
                "1",
                "--period-seconds",
                "10",
                "--possession-seconds",
                "10",
                "--minimum-games-per-second",
                "1000000000",
                "--output",
                str(failing_output),
            ]
        )
        == 7
    )
    failing_report = json.loads((failing_output / "benchmark.json").read_text(encoding="utf-8"))
    assert failing_report["summary"]["gate_passed"] is False


def test_audit_diff_check_and_disk_merge_commands(tmp_path: Path) -> None:
    diff = tmp_path / "diff.json"
    report = tmp_path / "gate-report.json"
    assert (
        main(
            [
                "audit-diff",
                str(AUDIT_BASELINE),
                str(AUDIT_BASELINE),
                "--output",
                str(diff),
            ]
        )
        == 0
    )
    assert main(["audit-check", str(AUDIT_BASELINE), str(AUDIT_GATES)]) == 0
    assert diff.is_file()
    realism_report = tmp_path / "realism-report.json"
    assert (
        main(
            [
                "audit-score",
                str(AUDIT_BASELINE),
                str(REALISM_TEMPLATE),
                "--output",
                str(realism_report),
            ]
        )
        == 0
    )
    assert json.loads(realism_report.read_text(encoding="utf-8"))["gate_passed"] is None
    failing_gates = tmp_path / "failing-gates.json"
    failing_gates.write_text(
        json.dumps(
            {
                "format_version": 1,
                "kind": "test",
                "gates": [
                    {
                        "metric": "points_per_100_possessions",
                        "minimum": 0,
                        "maximum": 100,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert (
        main(
            [
                "audit-check",
                str(AUDIT_BASELINE),
                str(failing_gates),
                "--output",
                str(report),
            ]
        )
        == 5
    )
    assert json.loads(report.read_text(encoding="utf-8"))["findings"]

    manifests = []
    for index in (0, 1):
        output = tmp_path / f"shard-{index}"
        assert (
            main(
                [
                    "model-audit",
                    "--schema",
                    str(MODEL_SCHEMA),
                    "--parameters",
                    str(MODEL_PARAMETERS),
                    "--profile",
                    str(PLAYER_PROFILE),
                    "--games",
                    "1",
                    "--start-index",
                    str(index),
                    "--periods",
                    "1",
                    "--period-seconds",
                    "10",
                    "--possession-seconds",
                    "10",
                    "--output",
                    str(output),
                ]
            )
            == 0
        )
        manifests.append(output / "manifest.json")
    merged = tmp_path / "merged"
    assert (
        main(
            [
                "model-audit-merge",
                "--output",
                str(merged),
                *(str(path) for path in manifests),
            ]
        )
        == 0
    )
    assert main(["verify", str(merged / "manifest.json")]) == 0


def test_cli_reports_user_errors(tmp_path: Path) -> None:
    assert main(["demo", "--possessions", "0"]) == 2
    assert main(["batch", "--runs", "0"]) == 2
    assert main(["model-audit", "--games", "0"]) == 2
    assert main(["model-benchmark", "--games", "0"]) == 2
    assert main(["model-audit-merge", "--output", str(tmp_path), "missing.json"]) == 2
    assert main(["replay", str(tmp_path / "missing.jsonl")]) == 2
    assert main(["verify", str(tmp_path / "missing.json")]) == 2
