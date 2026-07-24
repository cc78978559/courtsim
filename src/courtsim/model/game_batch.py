"""Deterministic local batches of canonical game samples."""

from __future__ import annotations

from dataclasses import dataclass, replace

from courtsim.domain.game import GameClockConfig
from courtsim.model.game_runtime import (
    GameMatchups,
    GameSample,
    GameTeam,
    sample_game,
)
from courtsim.model.trace_mode import TraceMode
from courtsim.parameters import ModelParameters
from courtsim.randomness import RandomFrame, derive_seed


@dataclass(frozen=True, slots=True)
class GameBatchSample:
    master_seed: int
    game_indices: tuple[int, ...]
    game_seeds: tuple[int, ...]
    games: tuple[GameSample, ...]


def planned_game_seeds(master_seed: int, games: int) -> tuple[int, ...]:
    if not isinstance(games, int) or isinstance(games, bool) or games < 1:
        raise ValueError("games must be a positive integer")
    return tuple(derive_seed(master_seed, "model-game", index) for index in range(games))


def _validate_indices(indices: tuple[int, ...]) -> None:
    if not indices:
        raise ValueError("game indices must not be empty")
    if any(not isinstance(index, int) or isinstance(index, bool) or index < 0 for index in indices):
        raise ValueError("game indices must be non-negative integers")
    if tuple(sorted(set(indices))) != indices:
        raise ValueError("game indices must be unique and ascending")


def sample_game_batch(
    *,
    parameters: ModelParameters,
    config: GameClockConfig,
    home: GameTeam,
    away: GameTeam,
    matchups: GameMatchups,
    frame: RandomFrame,
    games: int,
    trace_mode: TraceMode = TraceMode.FULL,
) -> GameBatchSample:
    planned_game_seeds(frame.master_seed, games)
    return sample_game_batch_indices(
        parameters=parameters,
        config=config,
        home=home,
        away=away,
        matchups=matchups,
        frame=frame,
        game_indices=tuple(range(games)),
        trace_mode=trace_mode,
    )


def sample_game_batch_indices(
    *,
    parameters: ModelParameters,
    config: GameClockConfig,
    home: GameTeam,
    away: GameTeam,
    matchups: GameMatchups,
    frame: RandomFrame,
    game_indices: tuple[int, ...],
    trace_mode: TraceMode = TraceMode.FULL,
) -> GameBatchSample:
    _validate_indices(game_indices)
    seeds = tuple(derive_seed(frame.master_seed, "model-game", index) for index in game_indices)
    samples = tuple(
        sample_game(
            parameters=parameters,
            config=config,
            home=home,
            away=away,
            matchups=matchups,
            frame=RandomFrame(
                seed,
                replace(
                    frame.address,
                    game_id=frame.address.game_id + index,
                    possession_index=0,
                    segment_index=0,
                ),
            ),
            trace_mode=trace_mode,
        )
        for index, seed in zip(game_indices, seeds, strict=True)
    )
    return GameBatchSample(frame.master_seed, game_indices, seeds, samples)


def merge_game_batches(*batches: GameBatchSample) -> GameBatchSample:
    if not batches:
        raise ValueError("at least one batch is required")
    master_seed = batches[0].master_seed
    if any(batch.master_seed != master_seed for batch in batches):
        raise ValueError("all shards must use the same master seed")
    rows = [
        (index, seed, game)
        for batch in batches
        for index, seed, game in zip(
            batch.game_indices,
            batch.game_seeds,
            batch.games,
            strict=True,
        )
    ]
    rows.sort(key=lambda item: item[0])
    indices = tuple(row[0] for row in rows)
    _validate_indices(indices)
    return GameBatchSample(
        master_seed,
        indices,
        tuple(row[1] for row in rows),
        tuple(row[2] for row in rows),
    )
