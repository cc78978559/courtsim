"""Resumable, input-pinned execution for formal thirty-team quick-sim batches."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.nba_quick_sim_executor import (
    NBA_QUICK_SIM_EXECUTOR_VERSION,
    NBA_QUICK_SIM_EXECUTOR_VERSIONS,
    NBAQuickSimExecutor,
)
from courtsim.analysis.nba_shot_profiles import load_nba_shot_profile_set
from courtsim.analysis.nba_team_strength import (
    apply_nba_team_strengths,
    load_nba_team_strength_alignment,
)
from courtsim.analysis.quick_sim_artifacts import run_quick_sim_checkpoint
from courtsim.analysis.quick_sim_batch import (
    QUICK_SIM_BATCH_VERSION,
    QuickSimBatchResult,
    QuickSimBatchSpec,
    append_precomputed_quick_sim_summaries,
    quick_sim_batch_from_json,
    quick_sim_batch_to_json,
)
from courtsim.analysis.quick_sim_comparison import QuickSimSeasonSummary
from courtsim.artifacts import sha256_file, write_json
from courtsim.domain.game import GameClockConfig
from courtsim.domain.plans import Lineup
from courtsim.domain.player import PlayerProfile
from courtsim.domain.player_serialization import player_lineup_from_json
from courtsim.model.game_runtime import GameTeam
from courtsim.model.interaction_compiler import ProfileLineup
from courtsim.model.trace_mode import TraceMode
from courtsim.parameters import load_model_parameters
from courtsim.randomness import derive_seed

NBA_QUICK_SIM_RUNNER_VERSION = "nba-quick-sim-runner-v1"
_WORKER_EXECUTOR: NBAQuickSimExecutor | None = None


class NbaQuickSimRunnerError(ValueError):
    pass


def run_nba_quick_sim_batch(
    *,
    schema_path: str | Path,
    parameters_path: str | Path,
    lineup_path: str | Path,
    profile_path: str | Path,
    strength_path: str | Path,
    checkpoint_path: str | Path,
    manifest_path: str | Path,
    batch_id: str,
    master_seed: int,
    seasons: int,
    maximum_new_seasons: int | None,
    game_config: GameClockConfig,
    workers: int = 1,
    executor_version: str = NBA_QUICK_SIM_EXECUTOR_VERSION,
) -> dict[str, object]:
    """Run or resume a batch, persisting one verified season at a time."""
    files: dict[str, Path] = {
        "schema": Path(schema_path).resolve(),
        "parameters": Path(parameters_path).resolve(),
        "lineup": Path(lineup_path).resolve(),
        "shot_profiles": Path(profile_path).resolve(),
        "team_strength": Path(strength_path).resolve(),
    }
    for role, path in files.items():
        if not path.is_file():
            raise NbaQuickSimRunnerError(f"quick-sim {role} input is missing: {path}")
    if not isinstance(workers, int) or isinstance(workers, bool) or not 1 <= workers <= 32:
        raise NbaQuickSimRunnerError("quick-sim workers must be from 1 through 32")
    if executor_version not in NBA_QUICK_SIM_EXECUTOR_VERSIONS:
        raise NbaQuickSimRunnerError("unsupported quick-sim executor version")
    if maximum_new_seasons is not None and (
        not isinstance(maximum_new_seasons, int)
        or isinstance(maximum_new_seasons, bool)
        or maximum_new_seasons < 1
    ):
        raise NbaQuickSimRunnerError("maximum new quick-sim seasons must be positive")
    inputs = {
        role: {"filename": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}
        for role, path in files.items()
    }
    configuration: dict[str, object] = {
        "runner_version": NBA_QUICK_SIM_RUNNER_VERSION,
        "executor_version": executor_version,
        "batch": {
            "batch_id": batch_id,
            "master_seed": master_seed,
            "seasons": seasons,
            "team_count": 30,
        },
        "game_config": {
            "regulation_periods": game_config.regulation_periods,
            "period_seconds": game_config.period_seconds,
            "possession_seconds": game_config.possession_seconds,
            "overtime_seconds": game_config.overtime_seconds,
            "max_overtimes": game_config.max_overtimes,
            "overtime_enabled": game_config.overtime_enabled,
        },
        "season_config": "injury-v1-default",
        "trace_mode": TraceMode.AGGREGATE_ONLY.value,
        "inputs": inputs,
    }
    configuration_sha256 = _digest(configuration)
    manifest_file = Path(manifest_path).resolve()
    checkpoint_file = Path(checkpoint_path).resolve()
    _verify_resume_manifest(manifest_file, checkpoint_file, configuration_sha256)

    executor = _build_executor(files, game_config, executor_version)
    spec = QuickSimBatchSpec(batch_id, master_seed, seasons)
    if workers == 1:
        result, receipt = run_quick_sim_checkpoint(
            spec,
            executor,
            checkpoint_file,
            maximum_new_seasons=maximum_new_seasons,
        )
        payload = _manifest_payload(
            configuration,
            configuration_sha256,
            checkpoint_file,
            result,
            receipt.file_sha256,
        )
        write_json(manifest_file, payload)
        return payload

    previous = (
        quick_sim_batch_from_json(checkpoint_file.read_text(encoding="utf-8"))
        if checkpoint_file.is_file()
        else None
    )
    if previous is not None and previous.spec != spec:
        raise NbaQuickSimRunnerError("parallel quick-sim checkpoint spec differs")
    completed = len(previous.cells) if previous is not None else 0
    remaining = seasons - completed
    budget = remaining if maximum_new_seasons is None else min(remaining, maximum_new_seasons)
    path_items = tuple((role, str(path)) for role, path in sorted(files.items()))
    parallel_result = previous
    with ProcessPoolExecutor(
        max_workers=workers,
        initializer=_initialize_worker,
        initargs=(path_items, game_config, executor_version),
    ) as pool:
        while budget > 0:
            wave_size = min(workers, budget)
            start = len(parallel_result.cells) if parallel_result is not None else 0
            tasks = tuple(
                (
                    f"{batch_id}:season-{index + 1:04d}",
                    derive_seed(master_seed, QUICK_SIM_BATCH_VERSION, batch_id, index),
                )
                for index in range(start, start + wave_size)
            )
            summaries = tuple(pool.map(_execute_worker_task, tasks))
            parallel_result = append_precomputed_quick_sim_summaries(
                spec, summaries, previous=parallel_result
            )
            write_json(
                checkpoint_file,
                json.loads(quick_sim_batch_to_json(parallel_result)),
            )
            payload = _manifest_payload(
                configuration,
                configuration_sha256,
                checkpoint_file,
                parallel_result,
                sha256_file(checkpoint_file),
            )
            write_json(manifest_file, payload)
            budget -= wave_size
    if parallel_result is None:
        raise NbaQuickSimRunnerError("quick-sim parallel runner produced no checkpoint")
    return _manifest_payload(
        configuration,
        configuration_sha256,
        checkpoint_file,
        parallel_result,
        sha256_file(checkpoint_file),
    )


def _manifest_payload(
    configuration: dict[str, object],
    configuration_sha256: str,
    checkpoint_file: Path,
    result: QuickSimBatchResult,
    file_sha256: str,
) -> dict[str, object]:
    return {
        "version": NBA_QUICK_SIM_RUNNER_VERSION,
        "configuration_sha256": configuration_sha256,
        "configuration": configuration,
        "checkpoint": {
            "path": checkpoint_file.name,
            "sha256": file_sha256,
            "batch_sha256": result.batch_sha256,
            "completed_seasons": len(result.cells),
            "complete": result.complete,
        },
    }


def _build_executor(
    files: dict[str, Path],
    game_config: GameClockConfig,
    executor_version: str = NBA_QUICK_SIM_EXECUTOR_VERSION,
) -> NBAQuickSimExecutor:
    profiles = load_nba_shot_profile_set(files["shot_profiles"])
    templates = player_lineup_from_json(files["lineup"].read_text(encoding="utf-8"))
    teams = _build_teams(tuple(item.team_id for item in profiles.teams), templates)
    teams = apply_nba_team_strengths(teams, files["team_strength"])
    alignment = load_nba_team_strength_alignment(files["team_strength"])
    return NBAQuickSimExecutor(
        load_model_parameters(files["schema"], files["parameters"]),
        game_config,
        teams,
        alignment,
        trace_mode=TraceMode.AGGREGATE_ONLY,
        version=executor_version,
        shot_zone_profiles=profiles,
    )


def _initialize_worker(
    path_items: tuple[tuple[str, str], ...],
    game_config: GameClockConfig,
    executor_version: str,
) -> None:
    global _WORKER_EXECUTOR
    _WORKER_EXECUTOR = _build_executor(
        {role: Path(path) for role, path in path_items}, game_config, executor_version
    )


def _execute_worker_task(task: tuple[str, int]) -> QuickSimSeasonSummary:
    if _WORKER_EXECUTOR is None:
        raise NbaQuickSimRunnerError("quick-sim worker was not initialized")
    return _WORKER_EXECUTOR(*task)


def _verify_resume_manifest(manifest: Path, checkpoint: Path, configuration_sha256: str) -> None:
    if not manifest.exists():
        if checkpoint.exists():
            raise NbaQuickSimRunnerError("checkpoint exists without its run manifest")
        return
    try:
        raw: object = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NbaQuickSimRunnerError("cannot read quick-sim run manifest") from error
    if not isinstance(raw, dict):
        raise NbaQuickSimRunnerError("quick-sim run manifest must be an object")
    value = cast(dict[str, Any], raw)
    if value.get("version") != NBA_QUICK_SIM_RUNNER_VERSION:
        raise NbaQuickSimRunnerError("quick-sim run manifest version differs")
    if value.get("configuration_sha256") != configuration_sha256:
        raise NbaQuickSimRunnerError("quick-sim resume configuration differs")
    checkpoint_record = value.get("checkpoint")
    if not isinstance(checkpoint_record, dict) or not checkpoint.is_file():
        raise NbaQuickSimRunnerError("quick-sim resume checkpoint is missing")
    if checkpoint_record.get("sha256") != sha256_file(checkpoint):
        raise NbaQuickSimRunnerError("quick-sim resume checkpoint hash differs")


def _build_teams(
    team_ids: tuple[str, ...], templates: tuple[PlayerProfile, ...]
) -> tuple[GameTeam, ...]:
    if len(team_ids) != 30 or len(set(team_ids)) != 30 or len(templates) != 5:
        raise NbaQuickSimRunnerError("formal quick-sim requires 30 teams and five role templates")
    teams = []
    for team_index, team_id in enumerate(team_ids):
        roster = tuple(
            replace(
                templates[slot % 5],
                player_id=team_index * 15 + slot + 1,
                name=f"{team_id} {templates[slot % 5].name} {slot // 5 + 1}",
            )
            for slot in range(15)
        )
        teams.append(
            GameTeam(
                team_id,
                cast(Lineup, tuple(item.player_id for item in roster[:5])),
                cast(ProfileLineup, roster[:5]),
                bench_profiles=roster[5:],
                substitution_order=tuple(item.player_id for item in roster),
            )
        )
    return tuple(teams)


def _digest(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
