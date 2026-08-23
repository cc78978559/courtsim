from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from courtsim.analysis.nba_manager_source_sync import sync_nba_manager_state_source
from courtsim.analysis.nba_manager_state import (
    build_nba_manager_initial_state,
    load_nba_manager_state_source,
)
from courtsim.analysis.nba_player_targets import load_nba_player_target_set
from courtsim.analysis.nba_real_rosters import build_nba_real_roster_teams
from courtsim.analysis.nba_shot_profiles import load_nba_shot_profile_set
from courtsim.analysis.nba_team_strength import (
    apply_nba_team_strengths,
    load_nba_team_strength_alignment,
)
from courtsim.artifacts import write_json
from courtsim.config import ConfigError
from courtsim.domain.game import GameClockConfig
from courtsim.domain.player_serialization import player_lineup_from_json
from courtsim.management import ContractRules
from courtsim.nba_franchise_artifacts import write_nba_franchise_checkpoint
from courtsim.nba_manager_evaluation import NBAFrontOfficeEvidenceThresholds
from courtsim.nba_manager_experiment import (
    NBA_MANAGER_REQUIRED_CI,
    build_nba_manager_candidate_receipt,
    inspect_nba_manager_experiment,
    run_nba_manager_experiment,
    verify_nba_manager_experiment,
)
from courtsim.nba_manager_study import (
    build_nba_manager_study_bundle,
    portable_nba_manager_checkpoint_receipt,
)

MANAGER_COMMANDS = frozenset(
    {
        "nba-manager-source-sync",
        "nba-manager-state-build",
        "nba-manager-study-run",
        "nba-manager-study-status",
        "nba-manager-study-verify",
        "nba-manager-study-receipt",
    }
)


def register_manager_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
    *,
    default_schema: Path,
    default_parameters: Path,
) -> None:
    manager_state_build = subparsers.add_parser(
        "nba-manager-state-build",
        help="build a source-pinned real-player franchise checkpoint for manager studies",
    )
    manager_state_build.add_argument("player_targets", type=Path)
    manager_state_build.add_argument("management_source", type=Path)
    manager_state_build.add_argument("shot_profiles", type=Path)
    manager_state_build.add_argument("team_strength", type=Path)
    manager_state_build.add_argument("checkpoint", type=Path)
    manager_state_build.add_argument("receipt", type=Path)
    manager_state_build.add_argument(
        "--lineup", type=Path, default=Path("examples/calibration_lineup_v1.json")
    )
    manager_state_build.add_argument("--league-id", default="nba-manager-policy-v1")
    manager_state_build.add_argument("--season-year", type=int, default=2025)
    manager_state_build.add_argument("--salary-cap", type=int, default=140_000_000)
    manager_state_build.add_argument("--minimum-salary", type=int, default=1_000_000)
    manager_state_build.add_argument("--maximum-salary", type=int, default=60_000_000)
    manager_state_build.add_argument("--maximum-years", type=int, default=5)
    manager_state_build.add_argument("--maximum-roster-players", type=int, default=15)

    manager_source_sync = subparsers.add_parser(
        "nba-manager-source-sync",
        help="cache keyless ESPN age/contracts and build a compact manager-state source",
    )
    manager_source_sync.add_argument("player_targets", type=Path)
    manager_source_sync.add_argument("identity", type=Path)
    manager_source_sync.add_argument("output", type=Path)
    manager_source_sync.add_argument(
        "--cache", type=Path, default=Path(".cache/nba-manager-source")
    )
    manager_source_sync.add_argument("--season-year", type=int, default=2025)
    manager_source_sync.add_argument("--workers", type=int, default=8)
    manager_source_sync.add_argument("--offline", action="store_true")
    manager_source_sync.add_argument("--force", action="store_true")

    manager_study_run = subparsers.add_parser(
        "nba-manager-study-run",
        help="run or resume a focal-team paired thirty-team manager study",
    )
    manager_study_run.add_argument("initial_checkpoint", type=Path)
    manager_study_run.add_argument("state_build_receipt", type=Path)
    manager_study_run.add_argument("shot_profiles", type=Path)
    manager_study_run.add_argument("macro_reference", type=Path)
    manager_study_run.add_argument("manager_profiles", type=Path)
    manager_study_run.add_argument("output", type=Path)
    manager_study_run.add_argument("--schema", type=Path, default=default_schema)
    manager_study_run.add_argument("--parameters", type=Path, default=default_parameters)
    manager_study_run.add_argument(
        "--player-targets",
        type=Path,
        help="frozen player targets required by the formal manager study",
    )
    manager_study_run.add_argument(
        "--state-build-source",
        type=Path,
        default=Path("experiments/inputs/nba-manager-state-source-2025.json"),
        help="frozen source used to reconstruct the formal initial state",
    )
    manager_study_run.add_argument(
        "--protocol",
        type=Path,
        default=Path("experiments/promotion/nba-manager-policy-v1-protocol.json"),
        help="canonical frozen formal promotion protocol",
    )
    manager_study_run.add_argument("--experiment-id", default="nba-manager-policy-v1")
    manager_study_run.add_argument("--seed-start", type=int)
    manager_study_run.add_argument("--sources", type=int)
    manager_study_run.add_argument("--seasons", type=int)
    manager_study_run.add_argument("--maximum-new-sources", type=int)
    manager_study_run.add_argument("--workers", type=int, default=1)
    manager_study_run.add_argument(
        "--stop-file",
        type=Path,
        help="cooperatively stop after the current atomic season cell when this file exists",
    )
    manager_study_run.add_argument("--development", action="store_true")
    manager_study_run.add_argument("--periods", type=int, default=4)
    manager_study_run.add_argument("--period-seconds", type=int, default=720)
    manager_study_run.add_argument("--possession-seconds", type=int, default=24)
    manager_study_run.add_argument("--overtime-seconds", type=int, default=300)
    manager_study_run.add_argument("--max-overtimes", type=int, default=8)

    manager_study_status = subparsers.add_parser(
        "nba-manager-study-status",
        help="verify and summarize a complete or partial NBA manager study",
    )
    manager_study_status.add_argument("study", type=Path)
    manager_study_verify = subparsers.add_parser(
        "nba-manager-study-verify",
        help="recompute evidence from a complete tamper-checked NBA manager study",
    )
    manager_study_verify.add_argument("report", type=Path)
    manager_study_receipt = subparsers.add_parser(
        "nba-manager-study-receipt",
        help="emit a WIP-only candidate pass/fail receipt after required CI",
    )
    manager_study_receipt.add_argument("report", type=Path)
    manager_study_receipt.add_argument("output", type=Path)
    manager_study_receipt.add_argument("--git-commit", required=True)
    manager_study_receipt.add_argument(
        "--ci",
        action="append",
        default=[],
        metavar="NAME=passed@COMMIT@RUN_URL",
        help=(
            "commit-bound GitHub Actions attestation required exactly once for: "
            f"{', '.join(NBA_MANAGER_REQUIRED_CI)}"
        ),
    )


def run_manager_command(arguments: argparse.Namespace) -> int:
    if arguments.command == "nba-manager-source-sync":
        report = sync_nba_manager_state_source(
            player_targets_path=arguments.player_targets,
            identity_path=arguments.identity,
            output_path=arguments.output,
            cache_directory=arguments.cache,
            season_year=arguments.season_year,
            workers=arguments.workers,
            offline=arguments.offline,
            force=arguments.force,
        )
        print(json.dumps(report, separators=(",", ":"), sort_keys=True))
        return 0

    if arguments.command == "nba-manager-state-build":
        player_targets = load_nba_player_target_set(arguments.player_targets)
        shot_profiles = load_nba_shot_profile_set(arguments.shot_profiles)
        team_ids = tuple(sorted(item.team_id for item in shot_profiles.teams))
        templates = player_lineup_from_json(arguments.lineup.read_text(encoding="utf-8"))
        teams = apply_nba_team_strengths(
            build_nba_real_roster_teams(player_targets, templates, team_ids),
            arguments.team_strength,
        )
        contract_rules = ContractRules(
            arguments.salary_cap,
            arguments.minimum_salary,
            arguments.maximum_salary,
            arguments.maximum_years,
            arguments.maximum_roster_players,
        )
        state_build = build_nba_manager_initial_state(
            league_id=arguments.league_id,
            season_year=arguments.season_year,
            teams=teams,
            alignment=load_nba_team_strength_alignment(arguments.team_strength),
            player_targets=player_targets,
            player_source=load_nba_manager_state_source(arguments.management_source),
            contract_rules=contract_rules,
        )
        checkpoint_receipt = write_nba_franchise_checkpoint(
            state_build.state,
            contract_rules,
            arguments.checkpoint,
        )
        state_receipt = {
            "version": "nba-manager-state-build-receipt-v1",
            "build": asdict(state_build.receipt),
            "checkpoint": asdict(portable_nba_manager_checkpoint_receipt(checkpoint_receipt)),
        }
        write_json(arguments.receipt, state_receipt)
        print(json.dumps(state_receipt, separators=(",", ":"), sort_keys=True))
        return 0

    if arguments.command == "nba-manager-study-run":
        return _run_manager_study(arguments)

    if arguments.command == "nba-manager-study-status":
        print(
            json.dumps(
                inspect_nba_manager_experiment(arguments.study),
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 0

    if arguments.command == "nba-manager-study-verify":
        evidence = verify_nba_manager_experiment(arguments.report)
        print(json.dumps(asdict(evidence), separators=(",", ":"), sort_keys=True))
        return 0 if evidence.recommended else 18

    if arguments.command == "nba-manager-study-receipt":
        ci_checks: dict[str, str] = {}
        for raw_ci in arguments.ci:
            name, separator, value = raw_ci.partition("=")
            if not separator or name in ci_checks:
                raise ConfigError(
                    "NBA manager CI values must be unique NAME=passed@COMMIT@RUN_URL entries"
                )
            ci_checks[name] = value
        candidate_receipt = build_nba_manager_candidate_receipt(
            arguments.report,
            git_commit=arguments.git_commit,
            ci_checks=ci_checks,
        )
        write_json(arguments.output, candidate_receipt)
        print(json.dumps(candidate_receipt, separators=(",", ":"), sort_keys=True))
        return 0 if candidate_receipt["status"] == "candidate-pass" else 18

    raise ValueError(f"unsupported manager command: {arguments.command}")


def _run_manager_study(arguments: argparse.Namespace) -> int:
    formal_run = not arguments.development
    default_sources = 30 if formal_run else 8
    default_seed_start = 20270401 if formal_run else 20270301
    default_seasons = 5 if formal_run else 3
    sources = default_sources if arguments.sources is None else arguments.sources
    seed_start = default_seed_start if arguments.seed_start is None else arguments.seed_start
    seasons = default_seasons if arguments.seasons is None else arguments.seasons
    if formal_run and (sources, seed_start, seasons) != (30, 20270401, 5):
        raise ConfigError(
            "formal NBA manager study is frozen to seeds 20270401-20270430 and five seasons"
        )
    if not 1 <= sources <= 30:
        raise ConfigError("NBA manager study sources must be from one through thirty")
    bundle = build_nba_manager_study_bundle(
        experiment_id=arguments.experiment_id,
        initial_checkpoint=arguments.initial_checkpoint,
        state_build_receipt_path=arguments.state_build_receipt,
        schema_path=arguments.schema,
        parameters_path=arguments.parameters,
        shot_profiles_path=arguments.shot_profiles,
        macro_reference_path=arguments.macro_reference,
        manager_profiles_path=arguments.manager_profiles,
        player_targets_path=arguments.player_targets,
        state_build_source_path=arguments.state_build_source,
        promotion_protocol_path=arguments.protocol,
        master_seeds=tuple(range(seed_start, seed_start + sources)),
        seasons=seasons,
        formal_run=formal_run,
        game_config=GameClockConfig(
            arguments.periods,
            arguments.period_seconds,
            arguments.possession_seconds,
            arguments.overtime_seconds,
            arguments.max_overtimes,
            True,
        ),
    )
    thresholds = None
    season_weights: tuple[float, ...] = (0.10, 0.15, 0.20, 0.25, 0.30)
    if not formal_run:
        thresholds = NBAFrontOfficeEvidenceThresholds(
            minimum_independent_sources=sources,
            minimum_seasons_per_source=seasons,
        )
        season_weights = tuple(1 / seasons for _ in range(seasons))
    result = run_nba_manager_experiment(
        spec=bundle.spec,
        initial_state_payload=bundle.initial_state_payload,
        executor=bundle.adapter,
        output_directory=arguments.output,
        thresholds=thresholds,
        season_weights=season_weights,
        maximum_new_sources=arguments.maximum_new_sources,
        workers=arguments.workers,
        stop_file=arguments.stop_file,
    )
    summary = {
        "version": result.version,
        "complete": result.complete,
        "executed_cells": result.executed_cells,
        "reused_cells": result.reused_cells,
        "completed_sources": result.completed_sources,
        "status": (
            "stopped"
            if result.stopped
            else "running"
            if not result.complete
            else "candidate-pass"
            if result.evidence is not None and result.evidence.recommended
            else "candidate-fail"
        ),
    }
    print(json.dumps(summary, separators=(",", ":"), sort_keys=True))
    return (
        0 if not result.complete or result.evidence is None or result.evidence.recommended else 19
    )
