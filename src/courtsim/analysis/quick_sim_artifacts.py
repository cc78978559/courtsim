"""Crash-resilient local artifacts for multi-season quick simulations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from courtsim.analysis.quick_sim_batch import (
    QuickSimBatchError,
    QuickSimBatchResult,
    QuickSimBatchSpec,
    QuickSimSeasonExecutor,
    quick_sim_batch_from_json,
    quick_sim_batch_to_json,
    run_quick_sim_batch,
)
from courtsim.analysis.quick_sim_comparison import (
    QuickSimReference,
    build_quick_sim_reference,
    quick_sim_reference_to_json,
)
from courtsim.artifacts import sha256_file, write_json

QUICK_SIM_ARTIFACT_VERSION = "quick-sim-artifact-v1"


@dataclass(frozen=True, slots=True)
class QuickSimCheckpointReceipt:
    checkpoint_path: str
    completed_before: int
    completed_after: int
    complete: bool
    batch_sha256: str
    file_sha256: str
    version: str = QUICK_SIM_ARTIFACT_VERSION


@dataclass(frozen=True, slots=True)
class QuickSimReferenceReceipt:
    reference_path: str
    reference_id: str
    observed_seasons: int
    file_sha256: str
    version: str = QUICK_SIM_ARTIFACT_VERSION


def run_quick_sim_checkpoint(
    spec: QuickSimBatchSpec,
    executor: QuickSimSeasonExecutor,
    checkpoint_path: str | Path,
    *,
    maximum_new_seasons: int | None = None,
) -> tuple[QuickSimBatchResult, QuickSimCheckpointReceipt]:
    path = Path(checkpoint_path)
    previous = _load_checkpoint(path)
    if previous is not None and previous.spec != spec:
        raise QuickSimBatchError("checkpoint quick-sim batch spec differs")
    if maximum_new_seasons is not None and (
        not isinstance(maximum_new_seasons, int)
        or isinstance(maximum_new_seasons, bool)
        or maximum_new_seasons < 1
    ):
        raise QuickSimBatchError("maximum_new_seasons must be a positive integer")
    completed_before = len(previous.cells) if previous is not None else 0
    result = previous
    remaining = spec.seasons - completed_before
    budget = remaining if maximum_new_seasons is None else min(remaining, maximum_new_seasons)
    for _ in range(budget):
        result = run_quick_sim_batch(spec, executor, previous=result, maximum_new_seasons=1)
        _write_canonical_json(path, quick_sim_batch_to_json(result))
    if result is None:
        result = run_quick_sim_batch(spec, executor, maximum_new_seasons=1)
        _write_canonical_json(path, quick_sim_batch_to_json(result))
    return result, QuickSimCheckpointReceipt(
        str(path.resolve()),
        completed_before,
        len(result.cells),
        result.complete,
        result.batch_sha256,
        sha256_file(path),
    )


def write_observed_quick_sim_reference(
    result: QuickSimBatchResult,
    reference_path: str | Path,
    *,
    reference_id: str,
    source_label: str,
    game_version: str,
    roster_date: str,
) -> tuple[QuickSimReference, QuickSimReferenceReceipt]:
    if not result.complete:
        raise QuickSimBatchError("observed reference requires a complete quick-sim batch")
    reference = build_quick_sim_reference(
        tuple(cell.summary for cell in result.cells),
        reference_id=reference_id,
        source_label=source_label,
        game_version=game_version,
        roster_date=roster_date,
    )
    path = Path(reference_path)
    _write_canonical_json(path, quick_sim_reference_to_json(reference))
    return reference, QuickSimReferenceReceipt(
        str(path.resolve()),
        reference.reference_id,
        reference.observed_seasons,
        sha256_file(path),
    )


def _load_checkpoint(path: Path) -> QuickSimBatchResult | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise QuickSimBatchError("quick-sim checkpoint path must be a file")
    return quick_sim_batch_from_json(path.read_text(encoding="utf-8"))


def _write_canonical_json(path: Path, payload: str) -> None:
    write_json(path, json.loads(payload))
