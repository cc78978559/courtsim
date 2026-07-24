import json
import shutil
import zipfile
from copy import deepcopy
from pathlib import Path

import pytest

from courtsim.analysis.artifact_archive import (
    ARCHIVE_MANIFEST_NAME,
    RESTORE_RECEIPT_NAME,
    ArtifactArchiveError,
    build_artifact_archive_plan,
    create_artifact_archive,
    restore_artifact_archive,
    verify_artifact_archive,
)
from courtsim.artifacts import write_json
from courtsim.cli import main


def fixture_root(tmp_path: Path) -> Path:
    root = tmp_path / "work"
    (root / "audits").mkdir(parents=True)
    (root / "runs").mkdir()
    (root / "audits" / "games.jsonl").write_bytes(b"canonical-events\n" * 10)
    (root / "audits" / "audit.json").write_text("{}", encoding="utf-8")
    (root / "runs" / "events.jsonl").write_bytes(b"excluded-events\n")
    return root


def test_archive_plan_is_explicit_hash_addressed_and_excludable(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    plan = build_artifact_archive_plan(
        root,
        include=("**/*.jsonl",),
        exclude=("runs/**",),
    )

    assert plan["summary"] == {"files": 1, "bytes": 170}
    assert [entry["path"] for entry in plan["entries"]] == ["audits/games.jsonl"]
    assert len(plan["entries"][0]["sha256"]) == 64
    assert (root / "audits" / "games.jsonl").read_bytes() == b"canonical-events\n" * 10


def test_archive_is_verified_deterministic_and_keeps_sources(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    plan_path = tmp_path / "plan.json"
    write_json(
        plan_path,
        build_artifact_archive_plan(root, include=("audits/**",)),
    )
    first = create_artifact_archive(plan_path, tmp_path / "first.zip")
    second = create_artifact_archive(plan_path, tmp_path / "second.zip")

    assert first.files == 2
    assert first.sha256 == second.sha256
    assert first.source_bytes == 172
    assert verify_artifact_archive(first.path).sha256 == first.sha256
    with zipfile.ZipFile(first.path, "r") as archive:
        assert sorted(archive.namelist()) == [
            ARCHIVE_MANIFEST_NAME,
            "audits/audit.json",
            "audits/games.jsonl",
        ]
        manifest = json.loads(archive.read(ARCHIVE_MANIFEST_NAME))
        assert manifest["summary"] == {"files": 2, "bytes": 172}
        assert archive.read("audits/games.jsonl") == b"canonical-events\n" * 10
    assert (root / "audits" / "games.jsonl").is_file()
    assert (root / "audits" / "audit.json").is_file()

    shutil.rmtree(root)
    restored = restore_artifact_archive(first.path, tmp_path / "restored")
    assert restored.files == 2
    assert restored.archive_sha256 == first.sha256
    assert (restored.path / "audits" / "games.jsonl").read_bytes() == (b"canonical-events\n" * 10)
    receipt = json.loads((restored.path / RESTORE_RECEIPT_NAME).read_text(encoding="utf-8"))
    assert receipt["archive_sha256"] == first.sha256
    with pytest.raises(ArtifactArchiveError, match="already exists"):
        restore_artifact_archive(first.path, restored.path)


def test_archive_refuses_changed_source_and_tampered_plan(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    plan = build_artifact_archive_plan(root, include=("**/*.jsonl",))
    plan_path = tmp_path / "plan.json"
    write_json(plan_path, plan)
    (root / "audits" / "games.jsonl").write_bytes(b"x" * 170)
    output = tmp_path / "changed.zip"

    with pytest.raises(ArtifactArchiveError, match="changed after planning"):
        create_artifact_archive(plan_path, output)
    assert not output.exists()

    tampered = deepcopy(plan)
    tampered["entries"][0]["path"] = "../outside.jsonl"
    write_json(plan_path, tampered)
    with pytest.raises(ArtifactArchiveError, match="entry 0 is invalid"):
        create_artifact_archive(plan_path, output)


def test_archive_cli_round_trip_and_input_guards(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    plan = tmp_path / "plan.json"
    archive = tmp_path / "archive.zip"
    assert (
        main(
            [
                "artifacts-plan",
                str(root),
                str(plan),
                "--include",
                "**/*.jsonl",
                "--exclude",
                "runs/**",
            ]
        )
        == 0
    )
    assert main(["artifacts-archive", str(plan), str(archive)]) == 0
    assert archive.is_file()
    assert main(["artifacts-verify-archive", str(archive)]) == 0
    restored = tmp_path / "restored"
    assert main(["artifacts-restore", str(archive), str(restored)]) == 0
    assert (restored / "audits" / "games.jsonl").is_file()
    assert main(["artifacts-archive", str(plan), str(archive)]) == 2

    with pytest.raises(ArtifactArchiveError, match="at least one pattern"):
        build_artifact_archive_plan(root, include=())
    empty_plan = tmp_path / "empty.json"
    write_json(empty_plan, build_artifact_archive_plan(root, include=("missing/**",)))
    with pytest.raises(ArtifactArchiveError, match="contains no files"):
        create_artifact_archive(empty_plan, tmp_path / "empty.zip")


def test_archive_verification_rejects_tampered_content_and_paths(tmp_path: Path) -> None:
    root = fixture_root(tmp_path)
    plan_path = tmp_path / "plan.json"
    write_json(plan_path, build_artifact_archive_plan(root, include=("audits/**",)))
    valid = create_artifact_archive(plan_path, tmp_path / "valid.zip")
    with zipfile.ZipFile(valid.path, "r") as source:
        manifest = source.read(ARCHIVE_MANIFEST_NAME)
        audit = source.read("audits/audit.json")
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(tampered, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(ARCHIVE_MANIFEST_NAME, manifest)
        archive.writestr("audits/audit.json", audit)
        archive.writestr("audits/games.jsonl", b"x" * 170)
    with pytest.raises(ArtifactArchiveError, match="hash mismatch"):
        verify_artifact_archive(tampered)
    assert not (tmp_path / "tampered-restore").exists()

    malicious_manifest = json.loads(manifest)
    malicious_manifest["entries"][0]["path"] = "../escape.json"
    malicious = tmp_path / "malicious.zip"
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr(ARCHIVE_MANIFEST_NAME, json.dumps(malicious_manifest))
        archive.writestr("../escape.json", b"{}")
        archive.writestr("audits/games.jsonl", b"canonical-events\n" * 10)
    with pytest.raises(ArtifactArchiveError, match="entry 0 is invalid"):
        verify_artifact_archive(malicious)
