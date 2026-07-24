import json
from pathlib import Path

import pytest

from courtsim.analysis.artifact_inventory import (
    ArtifactInventoryError,
    build_artifact_inventory,
)
from courtsim.cli import main


def test_artifact_inventory_is_read_only_and_deterministic(tmp_path: Path) -> None:
    root = tmp_path / "work"
    (root / "audits").mkdir(parents=True)
    (root / "benchmarks").mkdir()
    (root / "audits" / "games.jsonl").write_bytes(b"x" * 20)
    (root / "audits" / "audit.json").write_bytes(b"x" * 10)
    (root / "benchmarks" / "report.json").write_bytes(b"x" * 5)

    first = build_artifact_inventory(root, largest=2)
    assert first == build_artifact_inventory(root, largest=2)
    assert first["summary"] == {"files": 3, "bytes": 35, "mib": 35 / (1024 * 1024)}
    assert first["largest_files"] == [
        {"path": "audits/games.jsonl", "bytes": 20},
        {"path": "audits/audit.json", "bytes": 10},
    ]
    assert {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    } == {
        "audits/games.jsonl": b"x" * 20,
        "audits/audit.json": b"x" * 10,
        "benchmarks/report.json": b"x" * 5,
    }


def test_artifact_inventory_cli_writes_optional_report(tmp_path: Path) -> None:
    root = tmp_path / "work"
    root.mkdir()
    (root / "result.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "inventory.json"

    assert main(["artifacts-audit", str(root), "--output", str(output)]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["kind"] == "courtsim-artifact-inventory"
    assert report["summary"]["files"] == 1


def test_artifact_inventory_rejects_invalid_inputs(tmp_path: Path) -> None:
    with pytest.raises(ArtifactInventoryError, match="not a directory"):
        build_artifact_inventory(tmp_path / "missing")
    with pytest.raises(ArtifactInventoryError, match="positive integer"):
        build_artifact_inventory(tmp_path, largest=0)
