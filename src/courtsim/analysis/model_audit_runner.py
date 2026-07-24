"""Local command-oriented construction of a reproducible model audit batch."""

from __future__ import annotations

import json
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

from courtsim.analysis.batch_artifacts import write_batch_audit_bundle
from courtsim.domain.game import GameClockConfig, GameResult
from courtsim.domain.plans import Lineup
from courtsim.domain.player_serialization import (
    player_lineup_from_dict,
    player_profile_from_dict,
)
from courtsim.model.game_batch import GameBatchSample, sample_game_batch_indices
from courtsim.model.game_runtime import (
    GameMatchups,
    GameSample,
    GameTeam,
    TeamTempoStrategy,
    sample_game,
)
from courtsim.model.interaction_compiler import (
    DefensiveMatchups,
    Matchup,
    ProfileLineup,
)
from courtsim.model.trace_mode import TraceMode
from courtsim.parameters import ModelParameters, load_model_parameters
from courtsim.randomness import RandomFrame, RandomFrameAddress, derive_seed

HOME_LINEUP: Lineup = (1, 2, 3, 4, 5)
AWAY_LINEUP: Lineup = (11, 12, 13, 14, 15)


@dataclass(frozen=True, slots=True)
class PreparedModelAuditContext:
    parameters: ModelParameters
    home: GameTeam
    away: GameTeam
    matchups: GameMatchups


def _profile_templates(path: str | Path) -> ProfileLineup:
    try:
        payload: object = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid player input JSON: {path}") from error
    if isinstance(payload, dict) and "players" in payload:
        return cast(ProfileLineup, player_lineup_from_dict(payload))
    template = player_profile_from_dict(payload)
    return (template,) * 5


def _profiles(templates: ProfileLineup, lineup: Lineup, prefix: str) -> ProfileLineup:
    return cast(
        ProfileLineup,
        tuple(
            replace(template, player_id=player_id, name=f"{prefix} {template.name}")
            for template, player_id in zip(templates, lineup, strict=True)
        ),
    )


def _matchups() -> GameMatchups:
    return GameMatchups(
        DefensiveMatchups(
            (
                Matchup(1, 11),
                Matchup(2, 12),
                Matchup(3, 13),
                Matchup(4, 14),
                Matchup(5, 15),
            )
        ),
        DefensiveMatchups(
            (
                Matchup(11, 1),
                Matchup(12, 2),
                Matchup(13, 3),
                Matchup(14, 4),
                Matchup(15, 5),
            )
        ),
    )


def prepare_model_audit_context(
    schema_path: str | Path,
    parameters_path: str | Path,
    profile_path: str | Path,
    opponent_profile_path: str | Path | None = None,
    home_tempo: int = 50,
    away_tempo: int = 50,
) -> PreparedModelAuditContext:
    home_templates = _profile_templates(profile_path)
    away_templates = _profile_templates(
        opponent_profile_path if opponent_profile_path is not None else profile_path
    )
    return PreparedModelAuditContext(
        load_model_parameters(schema_path, parameters_path),
        GameTeam(
            "home",
            HOME_LINEUP,
            _profiles(home_templates, HOME_LINEUP, "Home"),
            tempo_strategy=TeamTempoStrategy(home_tempo),
        ),
        GameTeam(
            "away",
            AWAY_LINEUP,
            _profiles(away_templates, AWAY_LINEUP, "Away"),
            tempo_strategy=TeamTempoStrategy(away_tempo),
        ),
        _matchups(),
    )


_PARALLEL_CONTEXT: PreparedModelAuditContext | None = None


def _initialize_parallel_worker(
    schema_path: str,
    parameters_path: str,
    profile_path: str,
    opponent_profile_path: str | None = None,
    home_tempo: int = 50,
    away_tempo: int = 50,
) -> None:
    global _PARALLEL_CONTEXT
    _PARALLEL_CONTEXT = prepare_model_audit_context(
        schema_path,
        parameters_path,
        profile_path,
        opponent_profile_path,
        home_tempo,
        away_tempo,
    )


def _parallel_game_job(
    job: tuple[GameClockConfig, int, int, TraceMode],
) -> tuple[int, int, GameResult]:
    if _PARALLEL_CONTEXT is None:
        raise RuntimeError("parallel model-audit worker was not initialized")
    clock, master_seed, index, trace_mode = job
    seed = derive_seed(master_seed, "model-game", index)
    sampled = sample_game(
        parameters=_PARALLEL_CONTEXT.parameters,
        config=clock,
        home=_PARALLEL_CONTEXT.home,
        away=_PARALLEL_CONTEXT.away,
        matchups=_PARALLEL_CONTEXT.matchups,
        frame=RandomFrame(
            seed,
            RandomFrameAddress("model-audit", 0, index, 0, 0),
        ),
        trace_mode=trace_mode,
    )
    return index, seed, sampled.result


def run_model_audit_to_directory(
    *,
    schema_path: str | Path,
    parameters_path: str | Path,
    profile_path: str | Path,
    opponent_profile_path: str | Path | None = None,
    home_tempo: int = 50,
    away_tempo: int = 50,
    output_directory: str | Path,
    master_seed: int,
    games: int,
    start_index: int,
    clock: GameClockConfig,
    workers: int = 1,
    trace_mode: TraceMode = TraceMode.FULL,
) -> Path:
    if start_index < 0:
        raise ValueError("start_index must be non-negative")
    if games < 1:
        raise ValueError("games must be positive")
    if workers < 1:
        raise ValueError("workers must be positive")
    context = prepare_model_audit_context(
        schema_path,
        parameters_path,
        profile_path,
        opponent_profile_path,
        home_tempo,
        away_tempo,
    )
    indices = tuple(range(start_index, start_index + games))
    if workers == 1:
        batch = sample_game_batch_indices(
            parameters=context.parameters,
            config=clock,
            home=context.home,
            away=context.away,
            matchups=context.matchups,
            frame=RandomFrame(
                master_seed,
                RandomFrameAddress("model-audit", 0, 0, 0, 0),
            ),
            game_indices=indices,
            trace_mode=trace_mode,
        )
    else:
        jobs = tuple((clock, master_seed, index, trace_mode) for index in indices)
        chunksize = max(1, len(jobs) // (workers * 4))
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_initialize_parallel_worker,
            initargs=(
                str(schema_path),
                str(parameters_path),
                str(profile_path),
                str(opponent_profile_path) if opponent_profile_path is not None else None,
                home_tempo,
                away_tempo,
            ),
        ) as executor:
            rows = tuple(executor.map(_parallel_game_job, jobs, chunksize=chunksize))
        batch = GameBatchSample(
            master_seed,
            tuple(row[0] for row in rows),
            tuple(row[1] for row in rows),
            tuple(GameSample(row[2], ()) for row in rows),
        )
    return write_batch_audit_bundle(
        batch=batch,
        parameters=context.parameters,
        config=clock,
        home=context.home,
        away=context.away,
        output_directory=output_directory,
        schema_path=schema_path,
        parameters_path=parameters_path,
        profile_path=profile_path,
        opponent_profile_path=opponent_profile_path,
        trace_mode=trace_mode,
    )
