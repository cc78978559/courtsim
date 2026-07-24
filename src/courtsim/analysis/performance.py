"""Reproducible local performance benchmarks for the basketball model."""

from __future__ import annotations

import os
import platform
import statistics
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from courtsim import __version__
from courtsim.analysis.model_audit_runner import (
    prepare_model_audit_context,
    run_model_audit_to_directory,
)
from courtsim.artifacts import sha256_file, write_json
from courtsim.domain.game import GameClockConfig
from courtsim.model.trace_mode import TraceMode


@dataclass(frozen=True, slots=True)
class PerformanceTrial:
    trial: int
    elapsed_seconds: float
    games_per_second: float
    manifest: str
    audit_sha256: str


def run_model_benchmark(
    *,
    schema_path: str | Path,
    parameters_path: str | Path,
    profile_path: str | Path,
    output_directory: str | Path,
    master_seed: int,
    games: int,
    workers: int,
    repeats: int,
    warmups: int,
    clock: GameClockConfig,
    trace_mode: TraceMode = TraceMode.AGGREGATE_ONLY,
    minimum_games_per_second: float | None = None,
) -> Path:
    if games < 1 or workers < 1 or repeats < 1 or warmups < 0:
        raise ValueError(
            "games, workers and repeats must be positive; warmups must be non-negative"
        )
    if minimum_games_per_second is not None and minimum_games_per_second <= 0:
        raise ValueError("minimum_games_per_second must be positive")
    destination = Path(output_directory)
    report_path = destination / "benchmark.json"
    if report_path.exists():
        raise ValueError(f"benchmark report already exists: {report_path}")
    context = prepare_model_audit_context(schema_path, parameters_path, profile_path)

    for index in range(warmups):
        run_model_audit_to_directory(
            schema_path=schema_path,
            parameters_path=parameters_path,
            profile_path=profile_path,
            output_directory=destination / f"warmup-{index + 1:03d}",
            master_seed=master_seed,
            games=games,
            start_index=0,
            clock=clock,
            workers=workers,
            trace_mode=trace_mode,
        )

    trials: list[PerformanceTrial] = []
    expected_audit_sha256: str | None = None
    for index in range(repeats):
        trial_directory = destination / f"trial-{index + 1:03d}"
        started = time.perf_counter()
        manifest_path = run_model_audit_to_directory(
            schema_path=schema_path,
            parameters_path=parameters_path,
            profile_path=profile_path,
            output_directory=trial_directory,
            master_seed=master_seed,
            games=games,
            start_index=0,
            clock=clock,
            workers=workers,
            trace_mode=trace_mode,
        )
        elapsed = time.perf_counter() - started
        audit_sha256 = sha256_file(trial_directory / "audit.json")
        if expected_audit_sha256 is None:
            expected_audit_sha256 = audit_sha256
        elif audit_sha256 != expected_audit_sha256:
            raise RuntimeError("benchmark trials produced different audit hashes")
        trials.append(
            PerformanceTrial(
                trial=index + 1,
                elapsed_seconds=elapsed,
                games_per_second=games / elapsed,
                manifest=manifest_path.relative_to(destination).as_posix(),
                audit_sha256=audit_sha256,
            )
        )

    throughput = tuple(trial.games_per_second for trial in trials)
    median_throughput = statistics.median(throughput)
    gate_passed = (
        None if minimum_games_per_second is None else median_throughput >= minimum_games_per_second
    )
    write_json(
        report_path,
        {
            "format_version": 1,
            "kind": "courtsim-model-performance-benchmark",
            "engine_version": __version__,
            "environment": {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "logical_cpu_count": os.cpu_count(),
            },
            "model": {
                "schema_version": context.parameters.schema.schema_version,
                "schema_hash": context.parameters.schema.schema_hash,
                "parameter_hash": context.parameters.parameter_hash,
                "schema_file_sha256": sha256_file(schema_path),
                "parameter_file_sha256": sha256_file(parameters_path),
                "profile_file_sha256": sha256_file(profile_path),
            },
            "configuration": {
                "master_seed": master_seed,
                "games": games,
                "workers": workers,
                "repeats": repeats,
                "warmups": warmups,
                "trace_mode": trace_mode.value,
                "clock": asdict(clock),
            },
            "trials": [asdict(trial) for trial in trials],
            "summary": {
                "median_games_per_second": median_throughput,
                "minimum_games_per_second_observed": min(throughput),
                "maximum_games_per_second_observed": max(throughput),
                "spread_percent_of_median": (
                    100.0 * (max(throughput) - min(throughput)) / median_throughput
                ),
                "audit_sha256": expected_audit_sha256,
                "required_minimum_games_per_second": minimum_games_per_second,
                "gate_passed": gate_passed,
            },
        },
    )
    return report_path
