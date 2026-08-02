from __future__ import annotations

from pathlib import Path
from typing import cast

from courtsim.analysis.nba_aggregate_quick_sim import (
    build_nba_aggregate_quick_sim_executor,
    run_nba_aggregate_quick_sim_batch,
)
from courtsim.analysis.quick_sim_formal_gate import evaluate_quick_sim_formal_gate

ROOT = Path(__file__).resolve().parents[1]
PARAMETERS = ROOT / "experiments" / "sources" / "nba-aggregate-quick-sim-parameters-v1.json"
STRENGTH = ROOT / "experiments" / "sources" / "nba-2024-25-team-strength-v1.json"
GATE = ROOT / "experiments" / "gates" / "nba-2022-25-aggregate-quick-sim-formal-gate-v1.json"


def test_aggregate_executor_is_fast_deterministic_and_complete() -> None:
    executor = build_nba_aggregate_quick_sim_executor(PARAMETERS, STRENGTH)
    first = executor.execute("aggregate-season", 20260906)
    second = executor.execute("aggregate-season", 20260906)
    assert first == second
    assert len(first.standings) == 30
    assert {item.wins + item.losses for item in first.standings} == {82}
    assert len(first.postseason.series) == 15
    assert first.summary.games == 1230
    assert first.summary.champion_seed is not None


def test_aggregate_batch_reaches_formal_gate_without_target_fitting(tmp_path: Path) -> None:
    checkpoint = tmp_path / "aggregate.json"
    manifest = tmp_path / "aggregate.manifest.json"
    payload = run_nba_aggregate_quick_sim_batch(
        parameter_path=PARAMETERS,
        strength_path=STRENGTH,
        checkpoint_path=checkpoint,
        manifest_path=manifest,
        batch_id="formal-nba-aggregate-test-v1",
        master_seed=20260906,
        seasons=30,
        maximum_new_seasons=None,
    )
    assert cast(dict[str, object], payload["checkpoint"])["complete"] is True
    report = evaluate_quick_sim_formal_gate(checkpoint, GATE, manifest)
    assert all(cast(dict[str, bool], report["eligibility"]).values())
    comparison = cast(dict[str, object], report["comparison"])
    metrics = cast(list[dict[str, object]], comparison["comparisons"])
    pace = next(item for item in metrics if item["metric"] == "pace-possessions-per-team")
    assert pace["passed"] is False
    assert report["passed"] is False
