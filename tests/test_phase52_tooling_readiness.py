import json
from pathlib import Path

import pytest

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
    assert release["verified_files"] > 30

    assert main(["project-status", "--root", str(ROOT)]) == 0
    captured = capsys.readouterr()
    assert "\n" not in captured.out.strip()
    cli_report = json.loads(captured.out)
    assert cli_report["courtsim_version"] == report["courtsim_version"]
    assert "nba-quick-sim-comparison" in cli_report["capabilities"]


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
