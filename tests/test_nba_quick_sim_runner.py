from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from pathlib import Path

from pytest import MonkeyPatch

from courtsim.analysis import nba_quick_sim_runner as runner
from courtsim.analysis.nba_quick_sim_executor import (
    NBA_QUICK_SIM_EXECUTOR_VERSION,
)
from courtsim.analysis.quick_sim_batch import quick_sim_batch_from_json
from courtsim.analysis.quick_sim_comparison import QuickSimSeasonSummary
from courtsim.domain.game import GameClockConfig

ROOT = Path(__file__).resolve().parents[1]


class _FakeExecutor:
    def __call__(self, season_id: str, _seed: int) -> QuickSimSeasonSummary:
        return QuickSimSeasonSummary(season_id, 30, 1230, 0.14, 101.0, 113.0, 5.0, 0.4, 1)


class _InlinePool:
    def __init__(
        self,
        *,
        max_workers: int,
        initializer: Callable[..., None],
        initargs: tuple[object, ...],
    ) -> None:
        assert max_workers == 2
        initializer(*initargs)

    def __enter__(self) -> _InlinePool:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def map(
        self,
        function: Callable[[tuple[str, int]], QuickSimSeasonSummary],
        tasks: Iterable[tuple[str, int]],
    ) -> Iterable[QuickSimSeasonSummary]:
        return map(function, tasks)


def test_parallel_runner_writes_canonical_checkpoint_waves(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    monkeypatch.setattr(
        runner, "_build_executor", lambda _files, _config, _version: _FakeExecutor()
    )
    monkeypatch.setattr(runner, "ProcessPoolExecutor", _InlinePool)
    checkpoint = tmp_path / "batch.json"
    manifest = tmp_path / "batch.manifest.json"
    payload = runner.run_nba_quick_sim_batch(
        schema_path=ROOT / "data" / "model_schema_demo_v1_12.json",
        parameters_path=ROOT / "data" / "model_parameters_demo_1.4.0.json",
        lineup_path=ROOT / "examples" / "calibration_lineup_v1.json",
        profile_path=ROOT / "work" / "nba-2024-25-team-shot-profiles-calibrated.json",
        strength_path=ROOT / "experiments" / "sources" / "nba-2024-25-team-strength-v1.json",
        checkpoint_path=checkpoint,
        manifest_path=manifest,
        batch_id="formal-nba-reality-parallel-test",
        master_seed=9002,
        seasons=3,
        maximum_new_seasons=3,
        game_config=GameClockConfig(4, 720, 24, 300, 8, True),
        workers=2,
        executor_version=NBA_QUICK_SIM_EXECUTOR_VERSION,
    )
    result = quick_sim_batch_from_json(checkpoint.read_text(encoding="utf-8"))
    assert result.complete
    assert len(result.cells) == 3
    assert payload["checkpoint"] == json.loads(manifest.read_text(encoding="utf-8"))["checkpoint"]
    configuration = payload["configuration"]
    assert isinstance(configuration, dict)
    assert configuration["executor_version"] == NBA_QUICK_SIM_EXECUTOR_VERSION
