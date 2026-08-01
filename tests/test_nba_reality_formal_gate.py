from __future__ import annotations

import json
from pathlib import Path
from typing import cast

from courtsim.analysis.quick_sim_batch import (
    QuickSimBatchSpec,
    quick_sim_batch_to_json,
    run_quick_sim_batch,
)
from courtsim.analysis.quick_sim_comparison import QuickSimSeasonSummary
from courtsim.analysis.quick_sim_formal_gate import evaluate_quick_sim_formal_gate

ROOT = Path(__file__).resolve().parents[1]
REALITY = ROOT / "experiments" / "sources" / "nba-2022-25-standings-playoffs.json"
GATE = ROOT / "experiments" / "gates" / "nba-2022-25-quick-sim-formal-gate-v1.json"


def _checkpoint(path: Path, master_seed: int = 9001) -> Path:
    spec = QuickSimBatchSpec("formal-nba-reality-test", master_seed, 30)

    def execute(season_id: str, _seed: int) -> QuickSimSeasonSummary:
        return QuickSimSeasonSummary(
            season_id,
            30,
            1230,
            0.15,
            101.0,
            113.0,
            5.0,
            0.42,
            1,
        )

    path.write_text(quick_sim_batch_to_json(run_quick_sim_batch(spec, execute)), encoding="utf-8")
    return path


def test_frozen_reality_contains_three_complete_nba_seasons() -> None:
    payload = json.loads(REALITY.read_text(encoding="utf-8"))
    assert payload["version"] == "nba-reality-multiseason-v1"
    assert [item["regular_season_games"] for item in payload["seasons"]] == [
        1230,
        1230,
        1230,
    ]
    assert [len(item["standings"]) for item in payload["seasons"]] == [30, 30, 30]
    assert [len(item["playoff_series"]) for item in payload["seasons"]] == [15, 15, 15]


def test_formal_gate_accepts_eligible_batch(tmp_path: Path) -> None:
    report = evaluate_quick_sim_formal_gate(_checkpoint(tmp_path / "batch.json"), GATE)
    assert report["integrity"] == {"reference": True, "reality": True}
    eligibility = cast(dict[str, bool], report["eligibility"])
    assert all(eligibility.values())
    assert report["passed"] is True


def test_formal_gate_rejects_development_seed(tmp_path: Path) -> None:
    report = evaluate_quick_sim_formal_gate(_checkpoint(tmp_path / "batch.json", 20260801), GATE)
    eligibility = cast(dict[str, bool], report["eligibility"])
    assert eligibility["unseen_master_seed"] is False
    assert report["comparison"] is None
    assert report["passed"] is False
