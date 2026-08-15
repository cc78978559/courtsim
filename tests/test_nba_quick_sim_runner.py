from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from pathlib import Path
from types import SimpleNamespace

import pytest
from pytest import MonkeyPatch

from courtsim.analysis import nba_quick_sim_runner as runner
from courtsim.analysis.nba_player_aggregates import NBAPlayerSeasonAggregate
from courtsim.analysis.nba_player_targets import (
    NBAPlayerSourceReceipt,
    NBAPlayerTarget,
    NBAPlayerTargetSet,
)
from courtsim.analysis.nba_quick_sim_executor import (
    NBA_QUICK_SIM_EXECUTOR_VERSION,
)
from courtsim.analysis.quick_sim_batch import quick_sim_batch_from_json
from courtsim.analysis.quick_sim_comparison import QuickSimSeasonSummary
from courtsim.domain.game import GameClockConfig

ROOT = Path(__file__).resolve().parents[1]
SHOT_PROFILE_FIXTURE = ROOT / "tests" / "fixtures" / "nba-team-shot-profiles-minimal.json"


class _FakeExecutor:
    player_targets = None

    def __call__(self, season_id: str, _seed: int) -> QuickSimSeasonSummary:
        return QuickSimSeasonSummary(season_id, 30, 1230, 0.14, 101.0, 113.0, 5.0, 0.4, 1)


def _player_targets() -> NBAPlayerTargetSet:
    return NBAPlayerTargetSet(
        "players-v1",
        "2024-25",
        "fixture",
        1,
        1.0,
        (NBAPlayerSourceReceipt("box", "box.json", "a" * 64),),
        (
            NBAPlayerTarget(
                100,
                "Player",
                "1",
                82,
                24.0,
                0.2,
                0.6,
                0.1,
                (0.4, 0.2, 0.4),
                (0.7, 0.4, 0.38),
            ),
        ),
    )


class _PlayerFakeExecutor:
    player_targets = _player_targets()

    def execute(self, season_id: str, _seed: int) -> SimpleNamespace:
        aggregate = NBAPlayerSeasonAggregate(
            "Atlanta Hawks",
            100,
            82,
            82,
            82 * 24 * 60,
            0.2,
            0.6,
            0.1,
            (0.4, 0.2, 0.4),
            (0.7, 0.4, 0.38),
            1,
            1,
            1,
            1,
            1,
            1.0,
            1.0,
        )
        return SimpleNamespace(
            summary=QuickSimSeasonSummary(season_id, 30, 1230, 0.14, 101.0, 113.0, 5.0, 0.4, 1),
            player_aggregates=(aggregate,),
        )


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
        profile_path=SHOT_PROFILE_FIXTURE,
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


def _run(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    **overrides: object,
) -> dict[str, object]:
    fake_executor = overrides.pop("_fake_executor", _FakeExecutor())
    monkeypatch.setattr(runner, "_build_executor", lambda _files, _config, _version: fake_executor)
    options: dict[str, object] = {
        "schema_path": ROOT / "data" / "model_schema_demo_v1_12.json",
        "parameters_path": ROOT / "data" / "model_parameters_demo_1.4.0.json",
        "lineup_path": ROOT / "examples" / "calibration_lineup_v1.json",
        "profile_path": SHOT_PROFILE_FIXTURE,
        "strength_path": ROOT / "experiments" / "sources" / "nba-2024-25-team-strength-v1.json",
        "checkpoint_path": tmp_path / "serial.json",
        "manifest_path": tmp_path / "serial.manifest.json",
        "batch_id": "serial-test",
        "master_seed": 71,
        "seasons": 1,
        "maximum_new_seasons": 1,
        "game_config": GameClockConfig(4, 720, 24, 300, 8, True),
        "workers": 1,
        "executor_version": NBA_QUICK_SIM_EXECUTOR_VERSION,
    }
    options.update(overrides)
    return runner.run_nba_quick_sim_batch(**options)  # type: ignore[arg-type]


def test_serial_runner_resumes_verified_complete_checkpoint(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    first = _run(tmp_path, monkeypatch)
    second = _run(tmp_path, monkeypatch)
    assert first["checkpoint"] == second["checkpoint"]
    checkpoint = first["checkpoint"]
    assert isinstance(checkpoint, dict)
    assert checkpoint["complete"] is True


def test_runner_pins_optional_real_player_roster_input(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    roster = tmp_path / "player-rosters.json"
    roster.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runner, "ProcessPoolExecutor", _InlinePool)
    payload = _run(
        tmp_path,
        monkeypatch,
        player_roster_path=roster,
        workers=2,
        _fake_executor=_PlayerFakeExecutor(),
    )
    configuration = payload["configuration"]
    assert isinstance(configuration, dict)
    inputs = configuration["inputs"]
    assert isinstance(inputs, dict)
    assert inputs["player_rosters"]["filename"] == roster.name
    assert configuration["trace_mode"] == "player-aggregates"
    player_checkpoint = payload["player_checkpoint"]
    assert isinstance(player_checkpoint, dict)
    assert player_checkpoint["completed_seasons"] == 1


def test_player_runner_rolls_back_pair_after_manifest_crash(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    roster = tmp_path / "player-rosters.json"
    roster.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(runner, "ProcessPoolExecutor", _InlinePool)
    options = {
        "player_roster_path": roster,
        "workers": 2,
        "seasons": 2,
        "maximum_new_seasons": 1,
        "_fake_executor": _PlayerFakeExecutor(),
    }
    _run(tmp_path, monkeypatch, **options)
    manifest = tmp_path / "serial.manifest.json"
    committed_manifest = manifest.read_text(encoding="utf-8")
    _run(tmp_path, monkeypatch, **options)
    manifest.write_text(committed_manifest, encoding="utf-8")

    payload = _run(tmp_path, monkeypatch, **options)

    checkpoint = payload["checkpoint"]
    player_checkpoint = payload["player_checkpoint"]
    assert isinstance(checkpoint, dict) and checkpoint["completed_seasons"] == 2
    assert isinstance(player_checkpoint, dict) and player_checkpoint["completed_seasons"] == 2


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"workers": 0}, "workers"),
        ({"workers": True}, "workers"),
        ({"executor_version": "future-v99"}, "unsupported"),
        ({"maximum_new_seasons": 0}, "positive"),
        ({"maximum_new_seasons": True}, "positive"),
        ({"schema_path": "missing-schema.json"}, "input is missing"),
    ],
)
def test_runner_rejects_invalid_execution_configuration(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(runner.NbaQuickSimRunnerError, match=message):
        _run(tmp_path, monkeypatch, **overrides)


def test_runner_rejects_resume_configuration_change(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    _run(tmp_path, monkeypatch)
    with pytest.raises(runner.NbaQuickSimRunnerError, match="configuration differs"):
        _run(tmp_path, monkeypatch, master_seed=72)


@pytest.mark.parametrize(
    ("manifest_text", "checkpoint_text", "message"),
    [
        (None, "{}", "without its run manifest"),
        ("not-json", None, "cannot read"),
        ("[]", None, "must be an object"),
        ('{"version":"old"}', None, "version differs"),
    ],
)
def test_resume_manifest_rejects_broken_state(
    tmp_path: Path,
    manifest_text: str | None,
    checkpoint_text: str | None,
    message: str,
) -> None:
    manifest = tmp_path / "manifest.json"
    checkpoint = tmp_path / "checkpoint.json"
    if manifest_text is not None:
        manifest.write_text(manifest_text, encoding="utf-8")
    if checkpoint_text is not None:
        checkpoint.write_text(checkpoint_text, encoding="utf-8")
    with pytest.raises(runner.NbaQuickSimRunnerError, match=message):
        runner._verify_resume_manifest(manifest, checkpoint, "digest")


def test_worker_and_team_builders_enforce_initialization_and_shape() -> None:
    runner._WORKER_EXECUTOR = None
    with pytest.raises(runner.NbaQuickSimRunnerError, match="not initialized"):
        runner._execute_worker_task(("season", 1))
    with pytest.raises(runner.NbaQuickSimRunnerError, match="30 teams"):
        runner._build_teams(("A",), ())
    assert runner._digest({"b": 2, "a": 1}) == runner._digest({"a": 1, "b": 2})
