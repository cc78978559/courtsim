"""Resumable, input-pinned execution for formal thirty-team quick-sim batches."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

from courtsim.analysis.nba_quick_sim_executor import (
    NBA_QUICK_SIM_EXECUTOR_VERSION,
    NBAQuickSimExecutor,
)
from courtsim.analysis.nba_shot_profiles import load_nba_shot_profile_set
from courtsim.analysis.nba_team_strength import apply_nba_team_strengths
from courtsim.analysis.quick_sim_artifacts import run_quick_sim_checkpoint
from courtsim.analysis.quick_sim_batch import QuickSimBatchSpec
from courtsim.artifacts import sha256_file, write_json
from courtsim.domain.game import GameClockConfig
from courtsim.domain.plans import Lineup
from courtsim.domain.player import PlayerProfile
from courtsim.domain.player_serialization import player_lineup_from_json
from courtsim.model.game_runtime import GameTeam
from courtsim.model.interaction_compiler import ProfileLineup
from courtsim.model.trace_mode import TraceMode
from courtsim.nba_league import NBAConferenceAlignment
from courtsim.parameters import load_model_parameters

NBA_QUICK_SIM_RUNNER_VERSION = "nba-quick-sim-runner-v1"


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
) -> dict[str, object]:
    """Run or resume a batch, persisting one verified season at a time."""
    files = {
        "schema": Path(schema_path).resolve(),
        "parameters": Path(parameters_path).resolve(),
        "lineup": Path(lineup_path).resolve(),
        "shot_profiles": Path(profile_path).resolve(),
        "team_strength": Path(strength_path).resolve(),
    }
    for role, path in files.items():
        if not path.is_file():
            raise NbaQuickSimRunnerError(f"quick-sim {role} input is missing: {path}")
    inputs = {
        role: {"filename": path.name, "sha256": sha256_file(path), "bytes": path.stat().st_size}
        for role, path in files.items()
    }
    configuration = {
        "runner_version": NBA_QUICK_SIM_RUNNER_VERSION,
        "executor_version": NBA_QUICK_SIM_EXECUTOR_VERSION,
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

    profiles = load_nba_shot_profile_set(files["shot_profiles"])
    templates = player_lineup_from_json(files["lineup"].read_text(encoding="utf-8"))
    teams = _build_teams(tuple(item.team_id for item in profiles.teams), templates)
    teams = apply_nba_team_strengths(teams, files["team_strength"])
    team_ids = tuple(team.team_id for team in teams)
    executor = NBAQuickSimExecutor(
        load_model_parameters(files["schema"], files["parameters"]),
        game_config,
        teams,
        NBAConferenceAlignment(team_ids[:15], team_ids[15:]),
        trace_mode=TraceMode.AGGREGATE_ONLY,
        shot_zone_profiles=profiles,
    )
    _result, receipt = run_quick_sim_checkpoint(
        QuickSimBatchSpec(batch_id, master_seed, seasons),
        executor,
        checkpoint_file,
        maximum_new_seasons=maximum_new_seasons,
    )
    payload: dict[str, object] = {
        "version": NBA_QUICK_SIM_RUNNER_VERSION,
        "configuration_sha256": configuration_sha256,
        "configuration": configuration,
        "checkpoint": {
            "path": checkpoint_file.name,
            "sha256": receipt.file_sha256,
            "batch_sha256": receipt.batch_sha256,
            "completed_seasons": receipt.completed_after,
            "complete": receipt.complete,
        },
    }
    write_json(manifest_file, payload)
    return payload


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
