from __future__ import annotations

import argparse
import json
import platform
import sys
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from courtsim import __version__
from courtsim.analysis.artifact_archive import (
    ArtifactArchiveError,
    build_artifact_archive_plan,
    create_artifact_archive,
    restore_artifact_archive,
    verify_artifact_archive,
)
from courtsim.analysis.artifact_inventory import (
    ArtifactInventoryError,
    build_artifact_inventory,
)
from courtsim.analysis.artifact_retention import (
    ArtifactRetentionError,
    build_archive_plan_from_retention_report,
    build_artifact_retention_report,
    compare_artifact_retention_reports,
)
from courtsim.analysis.audit_gates import (
    AuditGateError,
    audit_comparison_to_json,
    audit_gate_report_to_json,
    compare_distribution_audits,
    evaluate_audit_gates,
    load_audit_gates,
    load_distribution_audit,
)
from courtsim.analysis.experiment_matrix import (
    ExperimentMatrixError,
    run_experiment_matrix,
)
from courtsim.analysis.matrix_contrast import (
    MatrixContrastError,
    run_matrix_contrasts,
)
from courtsim.analysis.matrix_contrast_robustness import (
    MatrixContrastRobustnessError,
    run_matrix_contrast_robustness,
)
from courtsim.analysis.matrix_ranking import MatrixRankingError, rank_experiment_matrix
from courtsim.analysis.matrix_robustness import (
    MatrixRobustnessError,
    run_matrix_robustness,
)
from courtsim.analysis.matrix_style_coverage import (
    MatrixStyleCoverageError,
    build_matrix_style_coverage,
)
from courtsim.analysis.model_audit_runner import run_model_audit_to_directory
from courtsim.analysis.nba_data_audit import (
    NbaDataAuditError,
    build_nba_data_audit,
    build_nba_possession_audit,
    build_nba_shot_audit,
)
from courtsim.analysis.nba_data_pipeline import (
    NbaDataPipelineError,
    build_nba_data_summary,
    inspect_nba_data,
    sync_nba_data,
)
from courtsim.analysis.nba_reference import (
    TEAM_METRIC_ORDER,
    NbaReferenceError,
    build_nba_core_target_payload,
    build_nba_team_target_payload,
)
from courtsim.analysis.nba_shot_profiles import (
    NbaShotProfileError,
    build_nba_shot_profile_payload,
)
from courtsim.analysis.performance import run_model_benchmark
from courtsim.analysis.quick_sim_batch import (
    QuickSimBatchError,
    quick_sim_batch_from_json,
)
from courtsim.analysis.quick_sim_comparison import (
    QuickSimComparisonError,
    compare_quick_sim_summaries,
    load_quick_sim_reference,
    quick_sim_report_to_json,
)
from courtsim.analysis.realism_targets import (
    RealismTargetError,
    load_realism_target_set,
    realism_score_report_to_json,
    score_audit_against_realism_targets,
)
from courtsim.analysis.shard_merge import ShardMergeError, merge_batch_audit_shards
from courtsim.analysis.tempo_policy import build_tempo_policy_audit
from courtsim.artifacts import write_json
from courtsim.config import ConfigError, load_scenario
from courtsim.demo import FoundationDemoSimulator
from courtsim.domain.game import GameClockConfig
from courtsim.model.trace_mode import TraceMode
from courtsim.nba_franchise_artifacts import (
    NBAFranchiseArtifactError,
    load_nba_franchise_checkpoint,
)
from courtsim.nba_franchise_runner import (
    NBAFranchiseRunnerError,
    inspect_nba_franchise_manifest,
)
from courtsim.parameter_overlay import (
    ParameterOverlayError,
    add_assist_occurrence_effects,
    add_assist_resolution_node,
    add_foul_free_throw_nodes,
    add_late_game_strategy_node,
    add_late_game_tempo_adjustments,
    add_non_shooting_foul_node,
    add_possession_duration_node,
    apply_parameter_overlay,
    enable_non_bonus_intentional_fouls,
    promote_intentional_foul_execution,
)
from courtsim.parameters import load_model_parameters
from courtsim.player_profile_overlay import (
    PlayerProfileOverlayError,
    materialize_player_lineup_overlay,
)
from courtsim.replay import ReplayError, replay_lines
from courtsim.runner import run_batch_to_directory, run_to_directory
from courtsim.tool_status import ProjectStatusError, build_project_status
from courtsim.verification import VerificationError, verify_manifest

ParameterMigration = Callable[[str | Path, str | Path], dict[str, Any]]
DEFAULT_MODEL_SCHEMA = Path("data/model_schema_demo_v1_12.json")
DEFAULT_MODEL_PARAMETERS = Path("data/model_parameters_demo_1.4.0.json")
PARAMETER_MIGRATIONS: dict[str, tuple[str, ParameterMigration]] = {
    "parameters-overlay": (
        "materialize and validate a numerical calibration overlay",
        apply_parameter_overlay,
    ),
    "parameters-add-assist": (
        "migrate demo-v1.3 parameters to demo-v1.4 with an assist node",
        add_assist_resolution_node,
    ),
    "parameters-add-fouls": (
        "migrate demo-v1.4 parameters to demo-v1.5 with foul/free-throw nodes",
        add_foul_free_throw_nodes,
    ),
    "parameters-add-common-fouls": (
        "migrate demo-v1.5 parameters to demo-v1.6 with common fouls and bonus",
        add_non_shooting_foul_node,
    ),
    "parameters-add-assist-occurrence": (
        "migrate demo-v1.6 parameters to demo-v1.7 with passer occurrence effects",
        add_assist_occurrence_effects,
    ),
    "parameters-add-tempo": (
        "migrate demo-v1.7 parameters to demo-v1.8 with possession duration",
        add_possession_duration_node,
    ),
    "parameters-add-late-game-tempo": (
        "migrate demo-v1.8 parameters to demo-v1.9 with score-aware tempo",
        add_late_game_tempo_adjustments,
    ),
    "parameters-add-late-game-strategy": (
        "migrate demo-v1.9 parameters to demo-v1.10 with late-game states",
        add_late_game_strategy_node,
    ),
    "parameters-promote-intentional-foul": (
        "migrate demo-v1.10 parameters to demo-v1.11 with formal bonus fouls",
        promote_intentional_foul_execution,
    ),
    "parameters-enable-non-bonus-intentional-foul": (
        "migrate demo-v1.11 parameters to demo-v1.12 with inbound continuation",
        enable_non_bonus_intentional_fouls,
    ),
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="courtsim")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("doctor", help="check the local runtime")

    project_status = subparsers.add_parser(
        "project-status",
        help="emit compact release, Git, and tooling readiness JSON",
    )
    project_status.add_argument("--root", type=Path, default=Path("."))
    project_status.add_argument("--pretty", action="store_true")

    nba_data = subparsers.add_parser(
        "nba-data",
        help="sync and stream-reduce free personal NBA datasets locally",
    )
    nba_data_actions = nba_data.add_subparsers(dest="nba_data_action", required=True)
    nba_data_sync = nba_data_actions.add_parser(
        "sync",
        help="populate the verified local raw-data cache",
    )
    nba_data_sync.add_argument("manifest", type=Path)
    nba_data_sync.add_argument("--cache", type=Path, default=Path(".cache/nba-data"))
    nba_data_sync.add_argument("--offline", action="store_true")
    nba_data_sync.add_argument("--force", action="store_true")
    nba_data_build = nba_data_actions.add_parser(
        "build",
        help="stream cached CSV data into a compact JSON summary",
    )
    nba_data_build.add_argument("manifest", type=Path)
    nba_data_build.add_argument("output", type=Path)
    nba_data_build.add_argument("--cache", type=Path, default=Path(".cache/nba-data"))
    nba_data_build.add_argument("--force", action="store_true")
    nba_data_status = nba_data_actions.add_parser(
        "status",
        help="inspect cache and summary freshness without reading raw rows",
    )
    nba_data_status.add_argument("manifest", type=Path)
    nba_data_status.add_argument("--cache", type=Path, default=Path(".cache/nba-data"))
    nba_data_status.add_argument("--output", type=Path)
    nba_data_audit = nba_data_actions.add_parser(
        "audit",
        help="reconcile a local event summary with pinned NBA totals",
    )
    nba_data_audit.add_argument("summary", type=Path)
    nba_data_audit.add_argument("core_snapshot", type=Path)
    nba_data_audit.add_argument("free_throw_snapshot", type=Path)
    nba_data_audit.add_argument("output", type=Path)
    nba_data_audit.add_argument("--tolerance", type=float, default=0.001)
    nba_data_audit.add_argument("--warning-multiplier", type=float, default=5.0)
    nba_possession_audit = nba_data_actions.add_parser(
        "audit-possessions",
        help="reconcile deduplicated possessions with pinned NBA totals",
    )
    nba_possession_audit.add_argument("summary", type=Path)
    nba_possession_audit.add_argument("core_snapshot", type=Path)
    nba_possession_audit.add_argument("output", type=Path)
    nba_possession_audit.add_argument("--tolerance", type=float, default=0.001)
    nba_possession_audit.add_argument("--warning-multiplier", type=float, default=5.0)
    nba_shot_audit = nba_data_actions.add_parser(
        "audit-shots",
        help="reconcile shot-detail totals and preserve zone calibration targets",
    )
    nba_shot_audit.add_argument("summary", type=Path)
    nba_shot_audit.add_argument("core_snapshot", type=Path)
    nba_shot_audit.add_argument("output", type=Path)
    nba_shot_audit.add_argument("--tolerance", type=float, default=0.001)
    nba_shot_audit.add_argument("--warning-multiplier", type=float, default=5.0)
    nba_shot_profiles = nba_data_actions.add_parser(
        "build-shot-profiles",
        help="derive quick-sim team shot-zone profiles from a passed local audit",
    )
    nba_shot_profiles.add_argument("summary", type=Path)
    nba_shot_profiles.add_argument("audit", type=Path)
    nba_shot_profiles.add_argument("output", type=Path)
    nba_shot_profiles.add_argument("--zone-tendency-loading", type=float, default=0.75)

    quick_sim_status = subparsers.add_parser(
        "nba-quick-sim-status",
        help="verify and summarize a quick-simulation checkpoint",
    )
    quick_sim_status.add_argument("checkpoint", type=Path)

    quick_sim_compare = subparsers.add_parser(
        "nba-quick-sim-compare",
        help="compare a verified quick-simulation checkpoint with a reference",
    )
    quick_sim_compare.add_argument("checkpoint", type=Path)
    quick_sim_compare.add_argument("reference", type=Path)
    quick_sim_compare.add_argument("--output", type=Path)

    franchise_checkpoint = subparsers.add_parser(
        "nba-franchise-checkpoint-verify",
        help="verify and summarize a franchise checkpoint",
    )
    franchise_checkpoint.add_argument("checkpoint", type=Path)
    franchise_checkpoint.add_argument("--expected-file-sha256")

    franchise_status = subparsers.add_parser(
        "nba-franchise-status",
        help="verify and summarize a resumable franchise manifest",
    )
    franchise_status.add_argument("manifest", type=Path)

    validate = subparsers.add_parser("validate", help="validate a scenario JSON file")
    validate.add_argument("scenario", type=Path)

    demo = subparsers.add_parser("demo", help="run the foundation smoke simulator")
    demo.add_argument("--scenario", type=Path, default=Path("examples/minimal_scenario.json"))
    demo.add_argument("--seed", type=int, default=1)
    demo.add_argument("--output", type=Path, default=Path("work/runs/demo"))
    demo.add_argument("--possessions", type=int, default=12)

    batch = subparsers.add_parser("batch", help="run deterministic local simulations")
    batch.add_argument("--scenario", type=Path, default=Path("examples/minimal_scenario.json"))
    batch.add_argument("--master-seed", type=int, default=1)
    batch.add_argument("--runs", type=int, default=10)
    batch.add_argument("--workers", type=int, default=1)
    batch.add_argument("--output", type=Path, default=Path("work/runs/batch"))
    batch.add_argument("--possessions", type=int, default=12)

    model_audit = subparsers.add_parser(
        "model-audit",
        help="run a deterministic basketball-model distribution audit",
    )
    model_audit.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_MODEL_SCHEMA,
    )
    model_audit.add_argument(
        "--parameters",
        type=Path,
        default=DEFAULT_MODEL_PARAMETERS,
    )
    model_audit.add_argument(
        "--profile",
        type=Path,
        default=Path("examples/calibration_lineup_v1.json"),
    )
    model_audit.add_argument(
        "--opponent-profile",
        type=Path,
        help="optional away-team lineup; defaults to the tested profile",
    )
    model_audit.add_argument("--master-seed", type=int, default=20260723)
    model_audit.add_argument("--games", type=int, default=10)
    model_audit.add_argument("--workers", type=int, default=1)
    model_audit.add_argument("--start-index", type=int, default=0)
    model_audit.add_argument("--periods", type=int, default=4)
    model_audit.add_argument("--period-seconds", type=int, default=720)
    model_audit.add_argument("--possession-seconds", type=int, default=15)
    model_audit.add_argument("--tempo", type=int, default=50)
    model_audit.add_argument("--opponent-tempo", type=int, default=50)
    model_audit.add_argument(
        "--trace-mode",
        type=TraceMode,
        choices=tuple(TraceMode),
        default=TraceMode.FULL,
    )
    model_audit.add_argument("--output", type=Path, default=Path("work/runs/model-audit"))

    model_benchmark = subparsers.add_parser(
        "model-benchmark",
        help="run a repeatable local basketball-model performance benchmark",
    )
    model_benchmark.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_MODEL_SCHEMA,
    )
    model_benchmark.add_argument(
        "--parameters",
        type=Path,
        default=DEFAULT_MODEL_PARAMETERS,
    )
    model_benchmark.add_argument(
        "--profile",
        type=Path,
        default=Path("examples/calibration_lineup_v1.json"),
    )
    model_benchmark.add_argument("--master-seed", type=int, default=20260728)
    model_benchmark.add_argument("--games", type=int, default=100)
    model_benchmark.add_argument("--workers", type=int, default=1)
    model_benchmark.add_argument("--repeats", type=int, default=3)
    model_benchmark.add_argument("--warmups", type=int, default=1)
    model_benchmark.add_argument("--periods", type=int, default=4)
    model_benchmark.add_argument("--period-seconds", type=int, default=720)
    model_benchmark.add_argument("--possession-seconds", type=int, default=15)
    model_benchmark.add_argument(
        "--trace-mode",
        type=TraceMode,
        choices=tuple(TraceMode),
        default=TraceMode.AGGREGATE_ONLY,
    )
    model_benchmark.add_argument("--minimum-games-per-second", type=float)
    model_benchmark.add_argument(
        "--output",
        type=Path,
        default=Path("work/benchmarks/model"),
    )

    tempo_policy_audit = subparsers.add_parser(
        "tempo-policy-audit",
        help="write a deterministic early/late score-context tempo table",
    )
    tempo_policy_audit.add_argument("schema", type=Path)
    tempo_policy_audit.add_argument("parameters", type=Path)
    tempo_policy_audit.add_argument("--tempo", type=int, default=50)
    tempo_policy_audit.add_argument("--output", type=Path, required=True)

    experiment_matrix = subparsers.add_parser(
        "experiment-matrix",
        help="run or resume a local multi-profile and multi-parameter experiment matrix",
    )
    experiment_matrix.add_argument("spec", type=Path)
    experiment_matrix.add_argument("--output", type=Path, required=True)
    experiment_matrix.add_argument("--resume", action="store_true")

    matrix_rank = subparsers.add_parser(
        "matrix-rank",
        help="integrity-check and rank completed matrix candidates without promotion",
    )
    matrix_rank.add_argument("report", type=Path)
    matrix_rank.add_argument("--output", type=Path, required=True)

    matrix_style_coverage = subparsers.add_parser(
        "matrix-style-coverage",
        help="summarize heterogeneous team-style target coverage without ranking",
    )
    matrix_style_coverage.add_argument("report", type=Path)
    matrix_style_coverage.add_argument("--output", type=Path, required=True)

    matrix_robustness = subparsers.add_parser(
        "matrix-robustness",
        help="run independent-seed robustness audits for completed matrix candidates",
    )
    matrix_robustness.add_argument("report", type=Path)
    matrix_robustness.add_argument("--output", type=Path, required=True)
    matrix_robustness.add_argument("--replicates", type=int, default=5)
    matrix_robustness.add_argument("--minimum-pass-rate", type=float, default=1.0)
    matrix_robustness.add_argument(
        "--maximum-worst-required-failures",
        type=int,
        default=0,
    )
    matrix_robustness.add_argument("--maximum-center-rmse", type=float)
    matrix_robustness.add_argument("--maximum-center-rmse-stddev", type=float)
    matrix_robustness.add_argument("--resume", action="store_true")

    matrix_contrast = subparsers.add_parser(
        "matrix-contrast",
        help="evaluate paired-seed counterfactual gates across matrix cells",
    )
    matrix_contrast.add_argument("report", type=Path)
    matrix_contrast.add_argument("spec", type=Path)
    matrix_contrast.add_argument("--output", type=Path, required=True)

    matrix_contrast_robustness = subparsers.add_parser(
        "matrix-contrast-robustness",
        help="aggregate paired counterfactual gates across robustness replicates",
    )
    matrix_contrast_robustness.add_argument("report", type=Path)
    matrix_contrast_robustness.add_argument("spec", type=Path)
    matrix_contrast_robustness.add_argument("--output", type=Path, required=True)
    matrix_contrast_robustness.add_argument(
        "--minimum-pass-rate",
        type=float,
        default=1.0,
    )

    audit_merge = subparsers.add_parser(
        "model-audit-merge",
        help="verify and merge model-audit shard manifests",
    )
    audit_merge.add_argument("--output", type=Path, required=True)
    audit_merge.add_argument("manifests", type=Path, nargs="+")

    audit_diff = subparsers.add_parser("audit-diff", help="compare two audit snapshots")
    audit_diff.add_argument("baseline", type=Path)
    audit_diff.add_argument("current", type=Path)
    audit_diff.add_argument("--output", type=Path)

    audit_check = subparsers.add_parser("audit-check", help="evaluate explicit audit gates")
    audit_check.add_argument("audit", type=Path)
    audit_check.add_argument("gates", type=Path)
    audit_check.add_argument("--output", type=Path)

    audit_score = subparsers.add_parser(
        "audit-score",
        help="score an audit against provenance-aware realism targets",
    )
    audit_score.add_argument("audit", type=Path)
    audit_score.add_argument("targets", type=Path)
    audit_score.add_argument("--output", type=Path)

    targets_build_nba = subparsers.add_parser(
        "targets-build-nba",
        help="build active core targets from a pinned NBA.com team snapshot",
    )
    targets_build_nba.add_argument("source", type=Path)
    targets_build_nba.add_argument("output", type=Path)
    targets_build_nba.add_argument("--tolerance", type=float, default=0.05)

    targets_build_nba_team = subparsers.add_parser(
        "targets-build-nba-team",
        help="build selected team-style targets from a pinned NBA.com team snapshot",
    )
    targets_build_nba_team.add_argument("source", type=Path)
    targets_build_nba_team.add_argument("output", type=Path)
    targets_build_nba_team.add_argument("--team", required=True)
    targets_build_nba_team.add_argument("--metric", action="append", dest="metrics")
    targets_build_nba_team.add_argument("--audit-team")
    targets_build_nba_team.add_argument("--tolerance", type=float, default=0.075)

    for command, (help_text, _) in PARAMETER_MIGRATIONS.items():
        migration = subparsers.add_parser(command, help=help_text)
        migration.add_argument("schema", type=Path)
        migration.add_argument("base", type=Path)
        migration.add_argument("migration", type=Path)
        migration.add_argument("output", type=Path)

    profile_overlay = subparsers.add_parser(
        "profile-overlay",
        help="materialize and validate a strict player-lineup rating overlay",
    )
    profile_overlay.add_argument("base", type=Path)
    profile_overlay.add_argument("overlay", type=Path)
    profile_overlay.add_argument("output", type=Path)

    replay = subparsers.add_parser("replay", help="render a saved JSONL event stream")
    replay.add_argument("events", type=Path)
    replay.add_argument("--possession", type=int)
    replay.add_argument("--limit", type=int)

    verify = subparsers.add_parser("verify", help="verify hashes in a run manifest")
    verify.add_argument("manifest", type=Path)
    verify.add_argument("--outputs-only", action="store_true")

    artifact_inventory = subparsers.add_parser(
        "artifacts-audit",
        help="inspect generated artifact count and disk usage without deleting files",
    )
    artifact_inventory.add_argument("root", type=Path, nargs="?", default=Path("work"))
    artifact_inventory.add_argument("--largest", type=int, default=10)
    artifact_inventory.add_argument("--output", type=Path)

    artifact_plan = subparsers.add_parser(
        "artifacts-plan",
        help="create a hash-addressed, non-destructive archive plan",
    )
    artifact_plan.add_argument("root", type=Path)
    artifact_plan.add_argument("output", type=Path)
    artifact_plan.add_argument("--include", action="append", required=True)
    artifact_plan.add_argument("--exclude", action="append", default=[])

    artifact_archive = subparsers.add_parser(
        "artifacts-archive",
        help="create and verify a ZIP from an unchanged archive plan",
    )
    artifact_archive.add_argument("plan", type=Path)
    artifact_archive.add_argument("output", type=Path)

    artifact_verify = subparsers.add_parser(
        "artifacts-verify-archive",
        help="verify an archive manifest, CRC, entry set, and content hashes",
    )
    artifact_verify.add_argument("archive", type=Path)

    artifact_restore = subparsers.add_parser(
        "artifacts-restore",
        help="verify and restore an archive into a new directory",
    )
    artifact_restore.add_argument("archive", type=Path)
    artifact_restore.add_argument("destination", type=Path)

    artifact_retention_audit = subparsers.add_parser(
        "artifacts-retention-audit",
        help="classify artifacts with a draft, read-only retention policy",
    )
    artifact_retention_audit.add_argument("root", type=Path)
    artifact_retention_audit.add_argument("policy", type=Path)
    artifact_retention_audit.add_argument("output", type=Path)

    artifact_retention_plan = subparsers.add_parser(
        "artifacts-retention-plan",
        help="turn a fresh retention report into a hash-addressed archive plan",
    )
    artifact_retention_plan.add_argument("report", type=Path)
    artifact_retention_plan.add_argument("output", type=Path)

    artifact_retention_compare = subparsers.add_parser(
        "artifacts-retention-compare",
        help="compare retention reports and detect protection regressions",
    )
    artifact_retention_compare.add_argument("baseline", type=Path)
    artifact_retention_compare.add_argument("candidate", type=Path)
    artifact_retention_compare.add_argument("output", type=Path)
    artifact_retention_compare.add_argument(
        "--fail-on-protection-loss",
        action="store_true",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "doctor":
            print(
                json.dumps(
                    {
                        "courtsim": __version__,
                        "python": platform.python_version(),
                        "executable": sys.executable,
                        "offline_runtime_dependencies": [],
                        "status": "ok",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        if arguments.command == "project-status":
            status_report = build_project_status(arguments.root)
            print(
                json.dumps(
                    status_report,
                    ensure_ascii=False,
                    indent=2 if arguments.pretty else None,
                    sort_keys=True,
                    separators=None if arguments.pretty else (",", ":"),
                )
            )
            release_status = cast(dict[str, object], status_report["release"])
            return 0 if release_status["hashes_ok"] is True else 4

        if arguments.command == "nba-data":
            if arguments.nba_data_action == "sync":
                nba_data_report = sync_nba_data(
                    arguments.manifest,
                    arguments.cache,
                    offline=arguments.offline,
                    force=arguments.force,
                )
            elif arguments.nba_data_action == "build":
                nba_data_report = build_nba_data_summary(
                    arguments.manifest,
                    arguments.cache,
                    arguments.output,
                    force=arguments.force,
                )
            elif arguments.nba_data_action == "status":
                nba_data_report = inspect_nba_data(
                    arguments.manifest,
                    arguments.cache,
                    arguments.output,
                )
            elif arguments.nba_data_action == "audit":
                nba_data_report = build_nba_data_audit(
                    arguments.summary,
                    arguments.core_snapshot,
                    arguments.free_throw_snapshot,
                    tolerance=arguments.tolerance,
                    warning_multiplier=arguments.warning_multiplier,
                )
                write_json(arguments.output, nba_data_report)
            elif arguments.nba_data_action == "audit-possessions":
                nba_data_report = build_nba_possession_audit(
                    arguments.summary,
                    arguments.core_snapshot,
                    tolerance=arguments.tolerance,
                    warning_multiplier=arguments.warning_multiplier,
                )
                write_json(arguments.output, nba_data_report)
            elif arguments.nba_data_action == "audit-shots":
                nba_data_report = build_nba_shot_audit(
                    arguments.summary,
                    arguments.core_snapshot,
                    tolerance=arguments.tolerance,
                    warning_multiplier=arguments.warning_multiplier,
                )
                write_json(arguments.output, nba_data_report)
            else:
                nba_data_report = build_nba_shot_profile_payload(
                    arguments.summary,
                    arguments.audit,
                    zone_tendency_loading=arguments.zone_tendency_loading,
                )
                write_json(arguments.output, nba_data_report)
            print(
                json.dumps(
                    nba_data_report,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0

        if arguments.command == "nba-quick-sim-status":
            result = quick_sim_batch_from_json(arguments.checkpoint.read_text(encoding="utf-8"))
            print(
                json.dumps(
                    {
                        "batch_id": result.spec.batch_id,
                        "completed_seasons": len(result.cells),
                        "target_seasons": result.spec.seasons,
                        "team_count": result.spec.team_count,
                        "complete": result.complete,
                        "batch_sha256": result.batch_sha256,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0

        if arguments.command == "nba-quick-sim-compare":
            result = quick_sim_batch_from_json(arguments.checkpoint.read_text(encoding="utf-8"))
            if not result.complete:
                raise QuickSimBatchError("quick-simulation comparison requires a complete batch")
            reference = load_quick_sim_reference(arguments.reference.read_text(encoding="utf-8"))
            comparison_report = compare_quick_sim_summaries(
                tuple(cell.summary for cell in result.cells),
                reference,
            )
            payload = quick_sim_report_to_json(comparison_report)
            if arguments.output is None:
                print(payload)
            else:
                write_json(arguments.output, json.loads(payload))
                print(f"completed: {arguments.output}")
            return 0 if comparison_report.passed else 14

        if arguments.command == "nba-franchise-checkpoint-verify":
            state, _, receipt = load_nba_franchise_checkpoint(
                arguments.checkpoint,
                expected_file_sha256=arguments.expected_file_sha256,
            )
            print(
                json.dumps(
                    {
                        **asdict(receipt),
                        "management_year": state.management.season_year,
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0

        if arguments.command == "nba-franchise-status":
            print(
                json.dumps(
                    asdict(inspect_nba_franchise_manifest(arguments.manifest)),
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0

        if arguments.command == "validate":
            config = load_scenario(arguments.scenario)
            print(f"valid: {config.name} ({len(config.zones)} zones)")
            return 0

        if arguments.command == "demo":
            if arguments.possessions < 1:
                raise ConfigError("possessions must be at least 1")
            config = load_scenario(arguments.scenario)
            simulator = FoundationDemoSimulator(config, possessions=arguments.possessions)
            manifest = run_to_directory(
                simulator,
                seed=arguments.seed,
                scenario_path=arguments.scenario,
                output_directory=arguments.output,
            )
            print(f"completed: {manifest}")
            return 0

        if arguments.command == "batch":
            if arguments.possessions < 1:
                raise ConfigError("possessions must be at least 1")
            if arguments.runs < 1 or arguments.workers < 1:
                raise ConfigError("runs and workers must be at least 1")
            config = load_scenario(arguments.scenario)
            simulator = FoundationDemoSimulator(config, possessions=arguments.possessions)
            manifest = run_batch_to_directory(
                simulator,
                master_seed=arguments.master_seed,
                runs=arguments.runs,
                workers=arguments.workers,
                scenario_path=arguments.scenario,
                output_directory=arguments.output,
            )
            print(f"completed: {manifest}")
            return 0

        if arguments.command == "model-audit":
            try:
                manifest = run_model_audit_to_directory(
                    schema_path=arguments.schema,
                    parameters_path=arguments.parameters,
                    profile_path=arguments.profile,
                    opponent_profile_path=arguments.opponent_profile,
                    home_tempo=arguments.tempo,
                    away_tempo=arguments.opponent_tempo,
                    output_directory=arguments.output,
                    master_seed=arguments.master_seed,
                    games=arguments.games,
                    start_index=arguments.start_index,
                    workers=arguments.workers,
                    trace_mode=arguments.trace_mode,
                    clock=GameClockConfig(
                        arguments.periods,
                        arguments.period_seconds,
                        arguments.possession_seconds,
                    ),
                )
            except ValueError as exc:
                raise ConfigError(str(exc)) from exc
            print(f"completed: {manifest}")
            return 0

        if arguments.command == "model-benchmark":
            try:
                report_path = run_model_benchmark(
                    schema_path=arguments.schema,
                    parameters_path=arguments.parameters,
                    profile_path=arguments.profile,
                    output_directory=arguments.output,
                    master_seed=arguments.master_seed,
                    games=arguments.games,
                    workers=arguments.workers,
                    repeats=arguments.repeats,
                    warmups=arguments.warmups,
                    trace_mode=arguments.trace_mode,
                    minimum_games_per_second=arguments.minimum_games_per_second,
                    clock=GameClockConfig(
                        arguments.periods,
                        arguments.period_seconds,
                        arguments.possession_seconds,
                    ),
                )
            except ValueError as exc:
                raise ConfigError(str(exc)) from exc
            report = json.loads(report_path.read_text(encoding="utf-8"))
            print(f"completed: {report_path}")
            return 7 if report["summary"]["gate_passed"] is False else 0

        if arguments.command == "tempo-policy-audit":
            parameters = load_model_parameters(arguments.schema, arguments.parameters)
            write_json(
                arguments.output,
                build_tempo_policy_audit(parameters, tempo=arguments.tempo),
            )
            print(f"completed: {arguments.output}")
            return 0

        if arguments.command == "experiment-matrix":
            report_path = run_experiment_matrix(
                spec_path=arguments.spec,
                output_directory=arguments.output,
                resume=arguments.resume,
            )
            report = json.loads(report_path.read_text(encoding="utf-8"))
            print(f"completed: {report_path}")
            return 8 if report["status"] == "partial" else 0

        if arguments.command == "matrix-rank":
            ranking_path = rank_experiment_matrix(
                matrix_report_path=arguments.report,
                output_path=arguments.output,
            )
            ranking = json.loads(ranking_path.read_text(encoding="utf-8"))
            print(f"completed: {ranking_path}")
            return 9 if ranking["recommendation"]["status"] == "no-eligible-candidate" else 0

        if arguments.command == "matrix-style-coverage":
            coverage_path = build_matrix_style_coverage(
                matrix_report_path=arguments.report,
                output_path=arguments.output,
            )
            print(f"completed: {coverage_path}")
            return 0

        if arguments.command == "matrix-robustness":
            robustness_path = run_matrix_robustness(
                matrix_report_path=arguments.report,
                output_directory=arguments.output,
                replicates=arguments.replicates,
                minimum_pass_rate=arguments.minimum_pass_rate,
                maximum_worst_required_failures=(arguments.maximum_worst_required_failures),
                maximum_center_rmse=arguments.maximum_center_rmse,
                maximum_center_rmse_stddev=arguments.maximum_center_rmse_stddev,
                resume=arguments.resume,
            )
            robustness = json.loads(robustness_path.read_text(encoding="utf-8"))
            print(f"completed: {robustness_path}")
            if robustness["summary"]["failed"] > 0:
                return 10
            if robustness["recommendation"]["status"] == "no-eligible-candidate":
                return 11
            return 0

        if arguments.command == "matrix-contrast":
            contrast_path = run_matrix_contrasts(
                matrix_report_path=arguments.report,
                spec_path=arguments.spec,
                output_directory=arguments.output,
            )
            contrast = json.loads(contrast_path.read_text(encoding="utf-8"))
            print(f"completed: {contrast_path}")
            return 12 if contrast["status"] == "failed" else 0

        if arguments.command == "matrix-contrast-robustness":
            contrast_path = run_matrix_contrast_robustness(
                robustness_report_path=arguments.report,
                spec_path=arguments.spec,
                output_path=arguments.output,
                minimum_pass_rate=arguments.minimum_pass_rate,
            )
            contrast = json.loads(contrast_path.read_text(encoding="utf-8"))
            print(f"completed: {contrast_path}")
            return 13 if contrast["status"] == "failed" else 0

        if arguments.command == "model-audit-merge":
            manifest = merge_batch_audit_shards(
                shard_manifests=tuple(arguments.manifests),
                output_directory=arguments.output,
            )
            print(f"completed: {manifest}")
            return 0

        if arguments.command == "audit-diff":
            comparison = compare_distribution_audits(
                load_distribution_audit(arguments.baseline),
                load_distribution_audit(arguments.current),
            )
            payload = audit_comparison_to_json(comparison)
            if arguments.output is None:
                print(payload)
            else:
                write_json(arguments.output, json.loads(payload))
                print(f"completed: {arguments.output}")
            return 0

        if arguments.command == "audit-check":
            gate_kind, gates = load_audit_gates(arguments.gates)
            report = evaluate_audit_gates(
                load_distribution_audit(arguments.audit),
                gate_kind,
                gates,
            )
            payload = audit_gate_report_to_json(report)
            if arguments.output is None:
                print(payload)
            else:
                write_json(arguments.output, json.loads(payload))
                print(f"completed: {arguments.output}")
            return 0 if report.passed else 5

        if arguments.command == "audit-score":
            score_report = score_audit_against_realism_targets(
                load_distribution_audit(arguments.audit),
                load_realism_target_set(arguments.targets),
            )
            payload = realism_score_report_to_json(score_report)
            if arguments.output is None:
                print(payload)
            else:
                write_json(arguments.output, json.loads(payload))
                print(f"completed: {arguments.output}")
            return 6 if score_report.gate_passed is False else 0

        if arguments.command == "targets-build-nba":
            try:
                artifact_path = arguments.source.resolve().relative_to(
                    arguments.output.parent.resolve()
                )
            except ValueError as error:
                raise NbaReferenceError(
                    "source must be inside the target file's directory"
                ) from error
            target_payload = build_nba_core_target_payload(
                arguments.source,
                artifact_path=artifact_path.as_posix(),
                tolerance=arguments.tolerance,
            )
            write_json(arguments.output, target_payload)
            load_realism_target_set(arguments.output)
            print(f"completed: {arguments.output}")
            return 0

        if arguments.command == "targets-build-nba-team":
            try:
                artifact_path = arguments.source.resolve().relative_to(
                    arguments.output.parent.resolve()
                )
            except ValueError as error:
                raise NbaReferenceError(
                    "source must be inside the target file's directory"
                ) from error
            metrics = (
                tuple(arguments.metrics) if arguments.metrics is not None else TEAM_METRIC_ORDER
            )
            target_payload = build_nba_team_target_payload(
                arguments.source,
                team=arguments.team,
                artifact_path=artifact_path.as_posix(),
                metrics=metrics,
                tolerance=arguments.tolerance,
                audit_team_id=arguments.audit_team,
            )
            write_json(arguments.output, target_payload)
            load_realism_target_set(arguments.output)
            print(f"completed: {arguments.output}")
            return 0

        if arguments.command in PARAMETER_MIGRATIONS:
            migration = PARAMETER_MIGRATIONS[arguments.command][1]
            candidate = migration(arguments.base, arguments.migration)
            write_json(arguments.output, candidate)
            loaded = load_model_parameters(arguments.schema, arguments.output)
            print(f"completed: {arguments.output} ({loaded.parameter_hash})")
            return 0

        if arguments.command == "profile-overlay":
            output, manifest = materialize_player_lineup_overlay(
                base_path=arguments.base,
                overlay_path=arguments.overlay,
                output_path=arguments.output,
            )
            print(f"completed: {output} (manifest: {manifest})")
            return 0

        if arguments.command == "replay":
            for line in replay_lines(
                arguments.events,
                possession=arguments.possession,
                limit=arguments.limit,
            ):
                print(line)
            return 0

        if arguments.command == "verify":
            verification_report = verify_manifest(
                arguments.manifest,
                check_inputs=not arguments.outputs_only,
            )
            if verification_report.ok:
                print(f"verified: {verification_report.checked} files")
                return 0
            for issue in verification_report.issues:
                print(f"verification error: {issue}", file=sys.stderr)
            return 4

        if arguments.command == "artifacts-audit":
            report = build_artifact_inventory(
                arguments.root,
                largest=arguments.largest,
            )
            if arguments.output is not None:
                write_json(arguments.output, report)
                print(f"completed: {arguments.output}")
            else:
                summary = report["summary"]
                print(f"artifacts: {summary['files']} files, {summary['mib']:.2f} MiB")
            return 0

        if arguments.command == "artifacts-plan":
            plan = build_artifact_archive_plan(
                arguments.root,
                include=tuple(arguments.include),
                exclude=tuple(arguments.exclude),
            )
            write_json(arguments.output, plan)
            print(
                f"planned: {arguments.output} "
                f"({plan['summary']['files']} files, {plan['summary']['bytes']} bytes)"
            )
            return 0

        if arguments.command == "artifacts-archive":
            archive_result = create_artifact_archive(arguments.plan, arguments.output)
            print(
                f"archived: {archive_result.path} "
                f"({archive_result.files} files, {archive_result.archive_bytes} bytes, "
                f"{archive_result.sha256})"
            )
            return 0

        if arguments.command == "artifacts-verify-archive":
            verification_result = verify_artifact_archive(arguments.archive)
            print(
                f"verified archive: {verification_result.path} "
                f"({verification_result.files} files, "
                f"{verification_result.archive_bytes} bytes, "
                f"{verification_result.sha256})"
            )
            return 0

        if arguments.command == "artifacts-restore":
            restore_result = restore_artifact_archive(
                arguments.archive,
                arguments.destination,
            )
            print(
                f"restored: {restore_result.path} "
                f"({restore_result.files} files, {restore_result.restored_bytes} bytes, "
                f"{restore_result.archive_sha256})"
            )
            return 0

        if arguments.command == "artifacts-retention-audit":
            report = build_artifact_retention_report(arguments.root, arguments.policy)
            root = Path(report["root"]).resolve()
            output = arguments.output.resolve()
            try:
                output.relative_to(root)
            except ValueError:
                pass
            else:
                raise ArtifactRetentionError(
                    "retention report must be stored outside its scanned root"
                )
            write_json(output, report)
            summary = report["summary"]
            print(
                f"classified: {output} "
                f"({summary['total']['files']} files, "
                f"{summary['archive_candidate']['files']} archive candidates)"
            )
            return 0

        if arguments.command == "artifacts-retention-plan":
            plan = build_archive_plan_from_retention_report(arguments.report)
            write_json(arguments.output, plan)
            print(
                f"planned: {arguments.output} "
                f"({plan['summary']['files']} files, {plan['summary']['bytes']} bytes)"
            )
            return 0

        if arguments.command == "artifacts-retention-compare":
            retention_comparison = compare_artifact_retention_reports(
                arguments.baseline,
                arguments.candidate,
            )
            write_json(arguments.output, retention_comparison)
            summary = retention_comparison["summary"]
            print(
                f"compared: {arguments.output} "
                f"({summary['changed_paths']} changed paths, "
                f"{summary['protection_losses']} protection losses)"
            )
            if arguments.fail_on_protection_loss and summary["protection_losses"]:
                return 10
            return 0
    except (
        ArtifactArchiveError,
        ArtifactInventoryError,
        ArtifactRetentionError,
        AuditGateError,
        ConfigError,
        ExperimentMatrixError,
        MatrixContrastError,
        MatrixContrastRobustnessError,
        MatrixRankingError,
        MatrixStyleCoverageError,
        MatrixRobustnessError,
        NbaReferenceError,
        NbaDataAuditError,
        NbaShotProfileError,
        NbaDataPipelineError,
        NBAFranchiseArtifactError,
        NBAFranchiseRunnerError,
        ParameterOverlayError,
        PlayerProfileOverlayError,
        ProjectStatusError,
        QuickSimBatchError,
        QuickSimComparisonError,
        ReplayError,
        RealismTargetError,
        ShardMergeError,
        VerificationError,
    ) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"I/O error: {exc}", file=sys.stderr)
        return 3
    return 1
