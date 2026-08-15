import json
from pathlib import Path

import pytest

from courtsim import tool_status
from courtsim.analysis.quick_sim_batch import (
    QuickSimBatchSpec,
    quick_sim_batch_to_json,
    run_quick_sim_batch,
)
from courtsim.analysis.quick_sim_comparison import (
    QuickSimSeasonSummary,
    build_quick_sim_reference,
    quick_sim_reference_to_json,
)
from courtsim.cli import main
from courtsim.tool_status import build_project_status

ROOT = Path(__file__).resolve().parents[1]


def _summary(season_id: str, seed: int) -> QuickSimSeasonSummary:
    offset = seed % 3
    return QuickSimSeasonSummary(
        season_id,
        30,
        1_230,
        0.12 + offset * 0.001,
        98.0 + offset,
        114.0 + offset,
        6.0 + offset,
        0.25,
        2,
    )


def test_project_status_is_compact_and_verifies_governance(
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = build_project_status(ROOT)
    release = report["release"]
    assert isinstance(release, dict)
    assert release["hashes_ok"] is True
    assert release["verified_files"] == 40
    assert release["engine_version"] == "0.54.0"
    assert release["matches_workspace"] is False
    candidate = report["candidate"]
    assert isinstance(candidate, dict)
    assert candidate["hashes_ok"] is True
    assert candidate["verified_files"] == 8
    assert candidate["status"] == "wip"
    assert candidate["engine_version"] == report["courtsim_version"]
    assert candidate["capability_scope"] == "workspace-wip"

    assert main(["project-status", "--root", str(ROOT)]) == 0
    captured = capsys.readouterr()
    assert "\n" not in captured.out.strip()
    cli_report = json.loads(captured.out)
    assert cli_report["courtsim_version"] == report["courtsim_version"]
    assert "nba-quick-sim-comparison" in cli_report["capabilities"]


@pytest.mark.parametrize(
    ("relative_path", "mismatch"),
    [
        ("data/model_schema_demo_v1_12.json", "model.schema"),
        ("data/model_parameters_demo_1.4.0.json", "model.parameters"),
        ("data/baselines/model-audit-demo-1.4.0.json", "audit.baseline"),
    ],
)
def test_project_status_cannot_report_false_green_for_special_release_artifacts(
    monkeypatch: pytest.MonkeyPatch,
    relative_path: str,
    mismatch: str,
) -> None:
    target = (ROOT / relative_path).resolve()
    original_sha256 = tool_status._sha256

    def mismatched_sha256(path: Path) -> str:
        if path.resolve() == target:
            return "0" * 64
        return original_sha256(path)

    monkeypatch.setattr(tool_status, "_sha256", mismatched_sha256)
    report = tool_status.build_project_status(ROOT)
    release = report["release"]
    assert isinstance(release, dict)
    assert release["hashes_ok"] is False
    assert release["verified_files"] == 39
    assert release["mismatches"] == [mismatch]


def test_quick_sim_status_and_comparison_cli(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = run_quick_sim_batch(QuickSimBatchSpec("nba-observed", 7, 2), _summary)
    checkpoint = tmp_path / "batch.json"
    checkpoint.write_text(quick_sim_batch_to_json(result), encoding="utf-8")
    reference = build_quick_sim_reference(
        tuple(cell.summary for cell in result.cells),
        reference_id="reality",
        source_label="pinned NBA sample",
        game_version="NBA-2024-25",
        roster_date="2025-04-13",
    )
    reference_path = tmp_path / "reference.json"
    reference_path.write_text(quick_sim_reference_to_json(reference), encoding="utf-8")

    assert main(["nba-quick-sim-status", str(checkpoint)]) == 0
    status = json.loads(capsys.readouterr().out)
    assert status["completed_seasons"] == 2
    assert status["complete"] is True

    assert main(["nba-quick-sim-compare", str(checkpoint), str(reference_path)]) == 0
    comparison = json.loads(capsys.readouterr().out)
    assert comparison["passed"] is True
    assert len(comparison["comparisons"]) == 6
