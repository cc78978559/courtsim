"""Single-run and deterministic local batch persistence boundaries."""

from __future__ import annotations

from collections.abc import Iterable
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from courtsim.artifacts import build_manifest, sha256_file, write_events, write_json
from courtsim.contracts import Simulator
from courtsim.randomness import derive_seed


def run_to_directory(
    simulator: Simulator,
    *,
    seed: int,
    scenario_path: str | Path,
    output_directory: str | Path,
) -> Path:
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    result = simulator.run(seed)
    events_path = destination / "events.jsonl"
    summary_path = destination / "summary.json"
    manifest_path = destination / "manifest.json"
    write_events(events_path, result.events)
    write_json(summary_path, result.summary)
    manifest = build_manifest(
        seed=seed,
        scenario_path=scenario_path,
        outputs=(events_path, summary_path),
    )
    write_json(manifest_path, manifest)
    return manifest_path


def planned_run_seeds(master_seed: int, runs: int) -> tuple[int, ...]:
    if runs < 1:
        raise ValueError("runs must be at least 1")
    return tuple(derive_seed(master_seed, "run", index) for index in range(runs))


def _execute_run(job: tuple[Simulator, int, str, str]) -> str:
    simulator, seed, scenario_path, output_directory = job
    return str(
        run_to_directory(
            simulator,
            seed=seed,
            scenario_path=scenario_path,
            output_directory=output_directory,
        )
    )


def run_batch_to_directory(
    simulator: Simulator,
    *,
    master_seed: int,
    runs: int,
    workers: int,
    scenario_path: str | Path,
    output_directory: str | Path,
) -> Path:
    if workers < 1:
        raise ValueError("workers must be at least 1")
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    seeds = planned_run_seeds(master_seed, runs)
    jobs = [
        (
            simulator,
            seed,
            str(scenario_path),
            str(destination / "runs" / f"{index:06d}"),
        )
        for index, seed in enumerate(seeds)
    ]
    if workers == 1:
        manifests: Iterable[str] = map(_execute_run, jobs)
    else:
        with ProcessPoolExecutor(max_workers=workers) as executor:
            manifests = tuple(executor.map(_execute_run, jobs))

    run_records = []
    for index, (seed, manifest_name) in enumerate(zip(seeds, manifests, strict=True)):
        manifest_path = Path(manifest_name)
        run_records.append(
            {
                "index": index,
                "seed": seed,
                "manifest": str(manifest_path.relative_to(destination)),
                "manifest_sha256": sha256_file(manifest_path),
            }
        )
    batch_manifest = destination / "batch_manifest.json"
    write_json(
        batch_manifest,
        {
            "format_version": 1,
            "master_seed": master_seed,
            "runs": run_records,
        },
    )
    return batch_manifest
