import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from courtsim.analysis.artifact_retention import (
    ArtifactRetentionError,
    build_archive_plan_from_retention_report,
    build_artifact_retention_report,
    compare_artifact_retention_reports,
)
from courtsim.artifacts import write_json
from courtsim.cli import main


def write_policy(path: Path, *, rules: list[dict[str, object]] | None = None) -> Path:
    write_json(
        path,
        {
            "format_version": 1,
            "kind": "courtsim-artifact-retention-policy",
            "policy_id": "test-review-v1",
            "status": "draft",
            "default_category": "unclassified",
            "rules": rules
            or [
                {
                    "id": "protect-formal",
                    "category": "protected",
                    "patterns": ["formal/**"],
                    "reason": "Formal evidence remains directly available.",
                },
                {
                    "id": "ignore-cache",
                    "category": "ignored",
                    "patterns": ["cache/**"],
                    "reason": "Cache is outside archive review.",
                },
                {
                    "id": "archive-jsonl",
                    "category": "archive_candidate",
                    "patterns": ["**/*.jsonl"],
                    "reason": "Large reproducible ledgers are review candidates.",
                },
            ],
        },
    )
    return path


def fixture_root(tmp_path: Path) -> Path:
    root = tmp_path / "work"
    (root / "formal").mkdir(parents=True)
    (root / "old").mkdir()
    (root / "cache").mkdir()
    (root / "formal" / "games.jsonl").write_bytes(b"protected\n")
    (root / "old" / "games.jsonl").write_bytes(b"candidate\n")
    (root / "cache" / "events.jsonl").write_bytes(b"ignored\n")
    (root / "notes.json").write_text("{}", encoding="utf-8")
    return root


def entry_map(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["path"]: entry for entry in report["entries"]}


def test_retention_precedence_and_unclassified_are_explicit(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    policy = write_policy(tmp_path / "policy.json")

    first = build_artifact_retention_report(root, policy)
    second = build_artifact_retention_report(root, policy)
    entries = entry_map(first)

    assert first == second
    assert entries["formal/games.jsonl"]["category"] == "protected"
    assert entries["formal/games.jsonl"]["matched_rule_ids"] == [
        "protect-formal",
        "archive-jsonl",
    ]
    assert entries["cache/events.jsonl"]["category"] == "ignored"
    assert entries["old/games.jsonl"]["category"] == "archive_candidate"
    assert entries["notes.json"]["category"] == "unclassified"
    assert first["summary"]["total"] == {"files": 4, "bytes": 30}


def test_retention_report_marks_symlinks_unsafe_when_supported(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    link = root / "old" / "linked.jsonl"
    try:
        os.symlink(root / "old" / "games.jsonl", link)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    report = build_artifact_retention_report(root, write_policy(tmp_path / "policy.json"))

    assert entry_map(report)["old/linked.jsonl"]["category"] == "unsafe"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"status": "approved"}, "metadata"),
        ({"default_category": "archive_candidate"}, "metadata"),
        (
            {
                "rules": [
                    {
                        "id": "bad",
                        "category": "archive_candidate",
                        "patterns": ["../outside"],
                        "reason": "bad",
                    }
                ]
            },
            "invalid retention rule pattern",
        ),
    ],
)
def test_retention_policy_rejects_unsafe_contracts(
    tmp_path: Path,
    change: dict[str, object],
    message: str,
) -> None:
    root = fixture_root(tmp_path)
    policy = write_policy(tmp_path / "policy.json")
    value = json.loads(policy.read_text(encoding="utf-8"))
    value.update(change)
    write_json(policy, value)

    with pytest.raises(ArtifactRetentionError, match=message):
        build_artifact_retention_report(root, policy)


def test_retention_plan_rechecks_policy_report_and_source(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    policy = write_policy(tmp_path / "policy.json")
    report_path = tmp_path / "report.json"
    report = build_artifact_retention_report(root, policy)
    write_json(report_path, report)

    plan = build_archive_plan_from_retention_report(report_path)

    assert [entry["path"] for entry in plan["entries"]] == ["old/games.jsonl"]
    assert plan["summary"] == {"files": 1, "bytes": 10}
    assert len(plan["entries"][0]["sha256"]) == 64

    stale_report = tmp_path / "stale.json"
    write_json(stale_report, report)
    (root / "old" / "games.jsonl").write_bytes(b"changed-size")
    with pytest.raises(ArtifactRetentionError, match="stale"):
        build_archive_plan_from_retention_report(stale_report)

    (root / "old" / "games.jsonl").write_bytes(b"candidate\n")
    tampered = deepcopy(report)
    tampered["entries"][0]["category"] = "archive_candidate"
    write_json(tmp_path / "tampered.json", tampered)
    with pytest.raises(ArtifactRetentionError, match=r"stale|summary"):
        build_archive_plan_from_retention_report(tmp_path / "tampered.json")

    policy_value = json.loads(policy.read_text(encoding="utf-8"))
    policy_value["policy_id"] = "changed"
    write_json(policy, policy_value)
    with pytest.raises(ArtifactRetentionError, match="policy changed"):
        build_archive_plan_from_retention_report(report_path)


def test_retention_rejects_embedded_report_and_empty_candidates(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    policy = write_policy(
        tmp_path / "policy.json",
        rules=[
            {
                "id": "protect-all",
                "category": "protected",
                "patterns": ["**"],
                "reason": "Everything is protected.",
            }
        ],
    )
    report = build_artifact_retention_report(root, policy)
    external = tmp_path / "external-report.json"
    write_json(external, report)
    with pytest.raises(ArtifactRetentionError, match="no archive candidates"):
        build_archive_plan_from_retention_report(external)

    embedded = root / "report.json"
    write_json(embedded, report)
    with pytest.raises(ArtifactRetentionError, match="outside"):
        build_archive_plan_from_retention_report(embedded)


def test_retention_cli_writes_only_report_and_plan(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    policy = write_policy(tmp_path / "policy.json")
    report = tmp_path / "report.json"
    plan = tmp_path / "plan.json"

    assert main(["artifacts-retention-audit", str(root), str(policy), str(report)]) == 0
    assert main(["artifacts-retention-plan", str(report), str(plan)]) == 0
    assert plan.is_file()
    assert not list(tmp_path.glob("*.zip"))
    assert (root / "old" / "games.jsonl").read_bytes() == b"candidate\n"
    assert main(["artifacts-retention-audit", str(root), str(policy), str(root / "x")]) == 2


def test_retention_comparison_detects_protection_loss_and_expansion(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    baseline_policy = write_policy(tmp_path / "baseline-policy.json")
    candidate_policy = write_policy(
        tmp_path / "candidate-policy.json",
        rules=[
            {
                "id": "archive-jsonl",
                "category": "archive_candidate",
                "patterns": ["**/*.jsonl"],
                "reason": "Candidate policy broadens the archive review set.",
            }
        ],
    )
    baseline_path = tmp_path / "baseline-report.json"
    candidate_path = tmp_path / "candidate-report.json"
    write_json(
        baseline_path,
        build_artifact_retention_report(root, baseline_policy),
    )
    write_json(
        candidate_path,
        build_artifact_retention_report(root, candidate_policy),
    )

    comparison = compare_artifact_retention_reports(baseline_path, candidate_path)

    assert comparison["summary"] == {
        "changed_paths": 2,
        "added_paths": 0,
        "removed_paths": 0,
        "protection_losses": 1,
        "archive_candidate_expansions": 2,
        "newly_protected": 0,
        "protection_gate": "failed",
    }
    assert [entry["path"] for entry in comparison["protection_losses"]] == ["formal/games.jsonl"]
    assert {entry["path"] for entry in comparison["archive_candidate_expansions"]} == {
        "cache/events.jsonl",
        "formal/games.jsonl",
    }


def test_retention_comparison_cli_gate_and_report_validation(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    baseline_policy = write_policy(tmp_path / "baseline-policy.json")
    candidate_policy = write_policy(
        tmp_path / "candidate-policy.json",
        rules=[
            {
                "id": "archive-jsonl",
                "category": "archive_candidate",
                "patterns": ["**/*.jsonl"],
                "reason": "Candidate policy broadens the archive review set.",
            }
        ],
    )
    baseline_path = tmp_path / "baseline-report.json"
    candidate_path = tmp_path / "candidate-report.json"
    output = tmp_path / "comparison.json"
    write_json(
        baseline_path,
        build_artifact_retention_report(root, baseline_policy),
    )
    write_json(
        candidate_path,
        build_artifact_retention_report(root, candidate_policy),
    )

    assert (
        main(
            [
                "artifacts-retention-compare",
                str(baseline_path),
                str(candidate_path),
                str(output),
                "--fail-on-protection-loss",
            ]
        )
        == 10
    )
    assert json.loads(output.read_text(encoding="utf-8"))["summary"]["protection_gate"] == (
        "failed"
    )

    tampered = json.loads(baseline_path.read_text(encoding="utf-8"))
    tampered["summary"]["total"]["files"] += 1
    write_json(tmp_path / "tampered-report.json", tampered)
    with pytest.raises(ArtifactRetentionError, match="summary"):
        compare_artifact_retention_reports(
            tmp_path / "tampered-report.json",
            candidate_path,
        )


def test_retention_comparison_self_check_has_no_changes(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    report_path = tmp_path / "report.json"
    write_json(
        report_path,
        build_artifact_retention_report(root, write_policy(tmp_path / "policy.json")),
    )

    comparison = compare_artifact_retention_reports(report_path, report_path)

    assert comparison["summary"]["changed_paths"] == 0
    assert comparison["summary"]["protection_gate"] == "passed"
    assert comparison["changes"] == []
