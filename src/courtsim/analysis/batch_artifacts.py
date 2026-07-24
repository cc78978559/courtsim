"""Atomic, hash-addressed output bundle for model batch audits."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from courtsim import __version__
from courtsim.analysis.distribution import audit_game_results
from courtsim.artifacts import sha256_file, write_json, write_jsonl
from courtsim.domain.game import GameClockConfig, validate_game_result
from courtsim.domain.game_serialization import game_result_to_dict
from courtsim.model.game_batch import GameBatchSample
from courtsim.model.game_runtime import GameTeam, possession_duration_options
from courtsim.model.late_game_strategy import late_game_strategy_config
from courtsim.model.trace_mode import TraceMode
from courtsim.parameters import ModelParameters, load_model_parameters


def write_batch_audit_bundle(
    *,
    batch: GameBatchSample,
    parameters: ModelParameters,
    config: GameClockConfig,
    home: GameTeam,
    away: GameTeam,
    output_directory: str | Path,
    schema_path: str | Path,
    parameters_path: str | Path,
    profile_path: str | Path,
    opponent_profile_path: str | Path | None = None,
    trace_mode: TraceMode = TraceMode.FULL,
) -> Path:
    disk_parameters = load_model_parameters(schema_path, parameters_path)
    if (
        disk_parameters.schema.schema_hash != parameters.schema.schema_hash
        or disk_parameters.parameter_hash != parameters.parameter_hash
    ):
        raise ValueError("model paths do not match the sampled parameters")
    for sample in batch.games:
        validate_game_result(sample.result, config, possession_duration_options(parameters))
        if sample.result.home_team_id != home.team_id or sample.result.away_team_id != away.team_id:
            raise ValueError("batch teams do not match the artifact metadata")
    destination = Path(output_directory)
    destination.mkdir(parents=True, exist_ok=True)
    games_path = destination / "games.jsonl"
    audit_path = destination / "audit.json"
    manifest_path = destination / "manifest.json"
    audit = audit_game_results(
        tuple(sample.result for sample in batch.games),
        late_game_strategy_config(parameters, shadow_legacy=True),
    )

    if trace_mode is TraceMode.FULL:
        write_jsonl(
            games_path,
            (
                {
                    "game_index": index,
                    "seed": seed,
                    "result": game_result_to_dict(sample.result),
                }
                for index, seed, sample in zip(
                    batch.game_indices,
                    batch.game_seeds,
                    batch.games,
                    strict=True,
                )
            ),
        )
    write_json(audit_path, asdict(audit))
    schema = Path(schema_path).resolve()
    parameter_file = Path(parameters_path).resolve()
    profile_file = Path(profile_path).resolve()
    opponent_profile_file = (
        Path(opponent_profile_path).resolve() if opponent_profile_path is not None else profile_file
    )
    outputs = [
        {
            "path": audit_path.name,
            "sha256": sha256_file(audit_path),
            "bytes": audit_path.stat().st_size,
        }
    ]
    if trace_mode is TraceMode.FULL:
        outputs = [
            {
                "path": games_path.name,
                "sha256": sha256_file(games_path),
                "bytes": games_path.stat().st_size,
            },
            *outputs,
        ]
    inputs = [
        {"path": str(schema), "sha256": sha256_file(schema)},
        {
            "path": str(parameter_file),
            "sha256": sha256_file(parameter_file),
        },
        {
            "path": str(profile_file),
            "sha256": sha256_file(profile_file),
        },
    ]
    if opponent_profile_file != profile_file:
        inputs.append(
            {
                "path": str(opponent_profile_file),
                "sha256": sha256_file(opponent_profile_file),
            }
        )
    manifest = {
        "format_version": 1,
        "kind": "courtsim-model-distribution-audit",
        "engine_version": __version__,
        "master_seed": batch.master_seed,
        "game_indices": list(batch.game_indices),
        "clock": asdict(config),
        "teams": {
            "home": {"team_id": home.team_id, "lineup": list(home.lineup)},
            "away": {"team_id": away.team_id, "lineup": list(away.lineup)},
        },
        "model": {
            "schema_version": parameters.schema.schema_version,
            "schema_hash": parameters.schema.schema_hash,
            "parameter_hash": parameters.parameter_hash,
        },
        "inputs": inputs,
        "outputs": outputs,
    }
    if trace_mode is TraceMode.AGGREGATE_ONLY:
        manifest["artifact_mode"] = trace_mode.value
    if home.tempo_strategy.tempo != 50 or away.tempo_strategy.tempo != 50:
        teams = cast(dict[str, dict[str, Any]], manifest["teams"])
        teams["home"]["tempo"] = home.tempo_strategy.tempo
        teams["away"]["tempo"] = away.tempo_strategy.tempo
    write_json(
        manifest_path,
        manifest,
    )
    return manifest_path
