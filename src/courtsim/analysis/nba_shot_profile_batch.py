"""Resumable multi-seed orchestration for NBA shot-profile experiments."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import cast

from courtsim.analysis.nba_shot_profile_evaluation import (
    aggregate_nba_shot_profile_evaluations,
)
from courtsim.analysis.nba_shot_profile_runner import run_nba_shot_profile_experiment
from courtsim.artifacts import sha256_file, write_json
from courtsim.domain.game import GameClockConfig
from courtsim.randomness import derive_seed

NBA_SHOT_PROFILE_BATCH_VERSION = "nba-shot-profile-batch-v1"
ExperimentRunner = Callable[..., dict[str, object]]
ExperimentJob = tuple[str, str, str, str, str, int, GameClockConfig]


class NbaShotProfileBatchError(ValueError):
    pass


def inspect_nba_shot_profile_batch(manifest_path: str | Path) -> dict[str, object]:
    """Verify a batch checkpoint and return a compact, read-only status."""
    manifest_file = Path(manifest_path).resolve()
    manifest = _load_object(manifest_file, "shot profile batch manifest")
    if manifest.get("schema_version") != 1:
        raise NbaShotProfileBatchError("shot profile batch manifest version differs")
    spec = manifest.get("spec")
    if not isinstance(spec, dict) or spec.get("version") != NBA_SHOT_PROFILE_BATCH_VERSION:
        raise NbaShotProfileBatchError("shot profile batch spec version differs")
    master_seed = spec.get("master_seed")
    runs = spec.get("runs")
    if (
        not isinstance(master_seed, int)
        or isinstance(master_seed, bool)
        or not isinstance(runs, int)
        or isinstance(runs, bool)
        or not 1 <= runs <= 10_000
    ):
        raise NbaShotProfileBatchError("shot profile batch dimensions are invalid")
    raw_cells = manifest.get("cells")
    if not isinstance(raw_cells, list) or any(not isinstance(item, dict) for item in raw_cells):
        raise NbaShotProfileBatchError("shot profile batch cells are invalid")
    cells = [cast(dict[str, object], item) for item in raw_cells]
    output = manifest_file.parent
    _verify_cells(output, cells, master_seed, runs)
    _verify_checkpoint(manifest, output, cells, runs)
    aggregate = _load_object(output / "evaluation-batch.json", "evaluation batch")
    if aggregate.get("runs") != len(cells):
        raise NbaShotProfileBatchError("shot profile batch aggregate run count differs")
    return {
        "schema_version": 1,
        "batch_version": NBA_SHOT_PROFILE_BATCH_VERSION,
        "manifest_sha256": sha256_file(manifest_file),
        "master_seed": master_seed,
        "completed_runs": len(cells),
        "target_runs": runs,
        "remaining_runs": runs - len(cells),
        "complete": len(cells) == runs,
        "artifact_hashes_ok": True,
        "status": aggregate.get("status"),
        "baseline_rmse": aggregate.get("baseline_rmse"),
        "candidate_rmse": aggregate.get("candidate_rmse"),
        "relative_rmse_improvement": aggregate.get("relative_rmse_improvement"),
    }


def run_nba_shot_profile_batch(
    *,
    profile_path: str | Path,
    schema_path: str | Path,
    parameters_path: str | Path,
    lineup_path: str | Path,
    output_directory: str | Path,
    master_seed: int,
    runs: int,
    game_config: GameClockConfig,
    maximum_new_runs: int | None = None,
    workers: int = 1,
    experiment_runner: ExperimentRunner = run_nba_shot_profile_experiment,
) -> dict[str, object]:
    """Resume a deterministic batch, checkpointing after every completed seed."""
    if (
        not isinstance(master_seed, int)
        or isinstance(master_seed, bool)
        or not isinstance(runs, int)
        or isinstance(runs, bool)
        or not 1 <= runs <= 10_000
    ):
        raise NbaShotProfileBatchError("shot profile batch dimensions are invalid")
    if maximum_new_runs is not None and (
        not isinstance(maximum_new_runs, int)
        or isinstance(maximum_new_runs, bool)
        or maximum_new_runs < 1
    ):
        raise NbaShotProfileBatchError("maximum new runs must be a positive integer")
    if not isinstance(workers, int) or isinstance(workers, bool) or workers < 1:
        raise NbaShotProfileBatchError("shot profile batch workers must be positive")
    if workers > 1 and experiment_runner is not run_nba_shot_profile_experiment:
        raise NbaShotProfileBatchError("parallel shot profile batches require the default runner")
    output = Path(output_directory).resolve()
    profile = Path(profile_path).resolve()
    schema = Path(schema_path).resolve()
    parameters = Path(parameters_path).resolve()
    lineup = Path(lineup_path).resolve()
    spec = {
        "version": NBA_SHOT_PROFILE_BATCH_VERSION,
        "master_seed": master_seed,
        "runs": runs,
        "game_config": _game_config_dict(game_config),
        "inputs": [
            _input_receipt("profile", profile),
            _input_receipt("schema", schema),
            _input_receipt("parameters", parameters),
            _input_receipt("lineup", lineup),
        ],
    }
    manifest_path = output / "batch-manifest.json"
    cells: list[dict[str, object]] = []
    previous: dict[str, object] | None = None
    if manifest_path.exists():
        previous = _load_object(manifest_path, "shot profile batch manifest")
        if previous.get("spec") != spec:
            raise NbaShotProfileBatchError("shot profile batch spec differs from checkpoint")
        raw_cells = previous.get("cells")
        if not isinstance(raw_cells, list) or any(not isinstance(item, dict) for item in raw_cells):
            raise NbaShotProfileBatchError("shot profile batch cells are invalid")
        cells = [cast(dict[str, object], item) for item in raw_cells]
        _verify_cells(output, cells, master_seed, runs)
        _verify_checkpoint(previous, output, cells, runs)
    remaining = runs - len(cells)
    if remaining == 0 and previous is not None:
        return previous
    new_runs = remaining if maximum_new_runs is None else min(remaining, maximum_new_runs)
    start_index = len(cells)
    jobs = tuple(
        (
            str(profile),
            str(schema),
            str(parameters),
            str(lineup),
            str(output / f"run-{run_index + 1:04d}"),
            derive_seed(master_seed, NBA_SHOT_PROFILE_BATCH_VERSION, run_index),
            game_config,
        )
        for run_index in range(start_index, start_index + new_runs)
    )
    if workers == 1:
        manifests: Iterable[dict[str, object]] = (
            experiment_runner(**_job_arguments(job)) for job in jobs
        )
    else:
        executor = ProcessPoolExecutor(max_workers=min(workers, new_runs))
        manifests = executor.map(_run_experiment_job, jobs)
    latest: dict[str, object] | None = None
    try:
        for run_index, (job, run_manifest) in enumerate(
            zip(jobs, manifests, strict=True), start=start_index
        ):
            run_directory = Path(job[4])
            seed = job[5]
            evaluation_path = run_directory / "evaluation.json"
            run_manifest_path = run_directory / "manifest.json"
            cells.append(
                {
                    "run_index": run_index,
                    "seed": seed,
                    "directory": run_directory.name,
                    "manifest_sha256": sha256_file(run_manifest_path),
                    "evaluation_sha256": sha256_file(evaluation_path),
                    "summary": run_manifest["summary"],
                }
            )
            latest = _write_checkpoint(output, manifest_path, spec, cells, runs)
    finally:
        if workers > 1:
            executor.shutdown()
    if latest is None:
        raise NbaShotProfileBatchError("shot profile batch did not execute any runs")
    return latest


def _job_arguments(job: ExperimentJob) -> dict[str, object]:
    return {
        "profile_path": job[0],
        "schema_path": job[1],
        "parameters_path": job[2],
        "lineup_path": job[3],
        "output_directory": job[4],
        "seed": job[5],
        "game_config": job[6],
    }


def _run_experiment_job(job: ExperimentJob) -> dict[str, object]:
    return run_nba_shot_profile_experiment(
        profile_path=job[0],
        schema_path=job[1],
        parameters_path=job[2],
        lineup_path=job[3],
        output_directory=job[4],
        seed=job[5],
        game_config=job[6],
    )


def _write_checkpoint(
    output: Path,
    manifest_path: Path,
    spec: dict[str, object],
    cells: list[dict[str, object]],
    runs: int,
) -> dict[str, object]:
    evaluations = []
    for cell in cells:
        directory = cell.get("directory")
        if not isinstance(directory, str):
            raise NbaShotProfileBatchError("shot profile batch cell directory is invalid")
        evaluations.append(_load_object(output / directory / "evaluation.json", "evaluation"))
    aggregate_path = output / "evaluation-batch.json"
    aggregate_sha256: str | None = None
    if evaluations:
        write_json(
            aggregate_path,
            aggregate_nba_shot_profile_evaluations(tuple(evaluations)),
        )
        aggregate_sha256 = sha256_file(aggregate_path)
    manifest = {
        "schema_version": 1,
        "spec": spec,
        "cells": cells,
        "completed_runs": len(cells),
        "complete": len(cells) == runs,
        "aggregate": (
            None
            if aggregate_sha256 is None
            else {
                "path": aggregate_path.name,
                "sha256": aggregate_sha256,
                "bytes": aggregate_path.stat().st_size,
            }
        ),
    }
    write_json(manifest_path, manifest)
    return manifest


def _verify_cells(
    output: Path,
    cells: list[dict[str, object]],
    master_seed: int,
    runs: int,
) -> None:
    if len(cells) > runs:
        raise NbaShotProfileBatchError("shot profile batch has too many cells")
    for expected_index, cell in enumerate(cells):
        expected_seed = derive_seed(
            master_seed,
            NBA_SHOT_PROFILE_BATCH_VERSION,
            expected_index,
        )
        if cell.get("run_index") != expected_index or cell.get("seed") != expected_seed:
            raise NbaShotProfileBatchError("shot profile batch cells are not contiguous")
        directory = cell.get("directory")
        if not isinstance(directory, str) or directory != f"run-{expected_index + 1:04d}":
            raise NbaShotProfileBatchError("shot profile batch cell directory differs")
        run_directory = output / directory
        for filename, field in (
            ("manifest.json", "manifest_sha256"),
            ("evaluation.json", "evaluation_sha256"),
        ):
            path = run_directory / filename
            if not path.is_file() or sha256_file(path) != cell.get(field):
                raise NbaShotProfileBatchError("shot profile batch cell artifact hash differs")


def _verify_checkpoint(
    manifest: dict[str, object],
    output: Path,
    cells: list[dict[str, object]],
    runs: int,
) -> None:
    if manifest.get("completed_runs") != len(cells):
        raise NbaShotProfileBatchError("shot profile batch completed count differs")
    if manifest.get("complete") is not (len(cells) == runs):
        raise NbaShotProfileBatchError("shot profile batch completion state differs")
    aggregate = manifest.get("aggregate")
    if not cells:
        if aggregate is not None:
            raise NbaShotProfileBatchError("empty shot profile batch has an aggregate")
        return
    if not isinstance(aggregate, dict):
        raise NbaShotProfileBatchError("shot profile batch aggregate receipt is invalid")
    aggregate_path = output / "evaluation-batch.json"
    if (
        aggregate.get("path") != aggregate_path.name
        or not aggregate_path.is_file()
        or aggregate.get("sha256") != sha256_file(aggregate_path)
        or aggregate.get("bytes") != aggregate_path.stat().st_size
    ):
        raise NbaShotProfileBatchError("shot profile batch aggregate artifact differs")


def _input_receipt(role: str, path: Path) -> dict[str, object]:
    return {"role": role, "path": path.name, "sha256": sha256_file(path)}


def _game_config_dict(config: GameClockConfig) -> dict[str, object]:
    return {
        "regulation_periods": config.regulation_periods,
        "period_seconds": config.period_seconds,
        "possession_seconds": config.possession_seconds,
        "overtime_seconds": config.overtime_seconds,
        "max_overtimes": config.max_overtimes,
        "overtime_enabled": config.overtime_enabled,
    }


def _load_object(path: Path, field: str) -> dict[str, object]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise NbaShotProfileBatchError(f"cannot read {field}: {path}") from error
    if not isinstance(value, dict):
        raise NbaShotProfileBatchError(f"{field} must be an object")
    return value
