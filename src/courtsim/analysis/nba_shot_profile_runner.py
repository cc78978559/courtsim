"""Reproducible regular-season A/B runner for calibrated NBA shot profiles."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import cast

from courtsim.analysis.distribution import audit_game_results, distribution_audit_to_json
from courtsim.analysis.nba_shot_profile_evaluation import evaluate_nba_shot_profile_audits
from courtsim.analysis.nba_shot_profiles import apply_nba_shot_profiles, load_nba_shot_profile_set
from courtsim.artifacts import sha256_file, write_json
from courtsim.domain.game import GameClockConfig
from courtsim.domain.plans import Lineup
from courtsim.domain.player import PlayerProfile
from courtsim.domain.player_serialization import player_lineup_from_json
from courtsim.model.game_runtime import GameTeam
from courtsim.model.interaction_compiler import ProfileLineup
from courtsim.model.trace_mode import TraceMode
from courtsim.nba_league import NBAConferenceAlignment, generate_nba_schedule
from courtsim.parameters import load_model_parameters
from courtsim.randomness import RandomFrame, RandomFrameAddress
from courtsim.season import SeasonConfig, SeasonResult, sample_season

NBA_SHOT_PROFILE_RUNNER_VERSION = "nba-shot-profile-runner-v1"


class NbaShotProfileRunnerError(ValueError):
    pass


def run_nba_shot_profile_experiment(
    *,
    profile_path: str | Path,
    schema_path: str | Path,
    parameters_path: str | Path,
    lineup_path: str | Path,
    output_directory: str | Path,
    seed: int,
    game_config: GameClockConfig,
) -> dict[str, object]:
    """Run paired 30-team regular seasons and write compact, auditable artifacts."""
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise NbaShotProfileRunnerError("shot profile experiment seed must be an integer")
    profile_file = Path(profile_path).resolve()
    schema_file = Path(schema_path).resolve()
    parameters_file = Path(parameters_path).resolve()
    lineup_file = Path(lineup_path).resolve()
    output = Path(output_directory).resolve()
    profiles = load_nba_shot_profile_set(profile_file)
    templates = player_lineup_from_json(lineup_file.read_text(encoding="utf-8"))
    teams = _build_teams(tuple(item.team_id for item in profiles.teams), templates)
    parameters = load_model_parameters(schema_file, parameters_file)
    if profiles.zone_tendency_loading != parameters.schema.zone_tendency_loading:
        raise NbaShotProfileRunnerError("shot profile loading differs from model parameters")
    team_ids = tuple(team.team_id for team in teams)
    schedule = generate_nba_schedule(
        team_ids,
        alignment=NBAConferenceAlignment(team_ids[:15], team_ids[15:]),
    )
    address = RandomFrameAddress("nba-shot-profile-experiment", 0, 0, 0, 0)

    def sample(active_teams: tuple[GameTeam, ...]) -> SeasonResult:
        return sample_season(
            parameters=parameters,
            game_config=game_config,
            schedule=schedule,
            teams=active_teams,
            frame=RandomFrame(seed, address),
            season_config=SeasonConfig(injury_probability_bps=0),
            trace_mode=TraceMode.AGGREGATE_ONLY,
        )

    baseline_season = sample(teams)
    baseline = audit_game_results(
        tuple(record.result for record in baseline_season.games if record.result is not None)
    )
    del baseline_season
    candidate_season = sample(apply_nba_shot_profiles(teams, profiles))
    candidate = audit_game_results(
        tuple(record.result for record in candidate_season.games if record.result is not None)
    )
    del candidate_season
    evaluation = evaluate_nba_shot_profile_audits(baseline, candidate, profiles)
    baseline_path = output / "baseline-audit.json"
    candidate_path = output / "candidate-audit.json"
    evaluation_path = output / "evaluation.json"
    write_json(baseline_path, json.loads(distribution_audit_to_json(baseline)))
    write_json(candidate_path, json.loads(distribution_audit_to_json(candidate)))
    write_json(evaluation_path, evaluation)
    manifest = {
        "schema_version": 1,
        "runner_version": NBA_SHOT_PROFILE_RUNNER_VERSION,
        "seed": seed,
        "game_config": {
            "regulation_periods": game_config.regulation_periods,
            "period_seconds": game_config.period_seconds,
            "possession_seconds": game_config.possession_seconds,
            "overtime_seconds": game_config.overtime_seconds,
            "max_overtimes": game_config.max_overtimes,
            "overtime_enabled": game_config.overtime_enabled,
        },
        "inputs": [
            _file_receipt("profile", profile_file),
            _file_receipt("schema", schema_file),
            _file_receipt("parameters", parameters_file),
            _file_receipt("lineup", lineup_file),
        ],
        "outputs": [
            _file_receipt("baseline_audit", baseline_path),
            _file_receipt("candidate_audit", candidate_path),
            _file_receipt("evaluation", evaluation_path),
        ],
        "summary": {
            "status": evaluation["status"],
            "games": baseline.games,
            "baseline_rmse": evaluation["baseline_rmse"],
            "candidate_rmse": evaluation["candidate_rmse"],
            "relative_rmse_improvement": evaluation["relative_rmse_improvement"],
            "improved_team_zones": evaluation["improved_team_zones"],
            "worsened_team_zones": evaluation["worsened_team_zones"],
        },
    }
    write_json(output / "manifest.json", manifest)
    return manifest


def _build_teams(
    team_ids: tuple[str, ...],
    templates: tuple[PlayerProfile, ...],
) -> tuple[GameTeam, ...]:
    if len(team_ids) != 30 or len(set(team_ids)) != 30 or len(templates) != 5:
        raise NbaShotProfileRunnerError("shot profile experiment requires 30 teams and 5 roles")
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


def _file_receipt(role: str, path: Path) -> dict[str, object]:
    return {
        "role": role,
        "path": path.name,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
    }
