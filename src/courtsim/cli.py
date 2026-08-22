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
from courtsim.analysis.nba_aggregate_quick_sim import (
    NbaAggregateQuickSimError,
    run_nba_aggregate_quick_sim_batch,
)
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
from courtsim.analysis.nba_manager_source_sync import (
    NBAManagerSourceSyncError,
    sync_nba_manager_state_source,
)
from courtsim.analysis.nba_manager_state import (
    NBAManagerStateError,
    build_nba_manager_initial_state,
    load_nba_manager_state_source,
)
from courtsim.analysis.nba_player_calibration import build_player_calibration_plan
from courtsim.analysis.nba_player_evaluation import (
    NbaPlayerEvaluationError,
    aggregate_nba_player_evaluation_files,
    build_nba_player_audit_from_bundle,
    evaluate_nba_player_audit_files,
    evaluate_nba_player_reality_gate_files,
)
from courtsim.analysis.nba_player_holdout import (
    NbaPlayerHoldoutError,
    evaluate_nba_player_holdout,
    load_nba_player_holdout_gate,
    nba_player_holdout_from_dict,
)
from courtsim.analysis.nba_player_identity import (
    NbaPlayerIdentityError,
    augment_nba_player_crosswalk_payload,
    build_nba_player_identity_payload,
)
from courtsim.analysis.nba_player_targets import (
    NbaPlayerTargetError,
    build_nba_player_target_payload,
    load_nba_player_target_set,
)
from courtsim.analysis.nba_quick_sim_runner import (
    NbaQuickSimRunnerError,
    run_nba_quick_sim_batch,
)
from courtsim.analysis.nba_real_rosters import build_nba_real_roster_teams
from courtsim.analysis.nba_reality import NbaRealityError, build_nba_reality_payload
from courtsim.analysis.nba_reference import (
    TEAM_METRIC_ORDER,
    NbaReferenceError,
    build_nba_core_target_payload,
    build_nba_team_target_payload,
)
from courtsim.analysis.nba_shot_profile_batch import (
    NbaShotProfileBatchError,
    inspect_nba_shot_profile_batch,
    run_nba_shot_profile_batch,
)
from courtsim.analysis.nba_shot_profile_evaluation import (
    NbaShotProfileEvaluationError,
    aggregate_nba_shot_profile_evaluations,
    evaluate_nba_shot_profile_audits,
)
from courtsim.analysis.nba_shot_profile_runner import (
    NbaShotProfileRunnerError,
    run_nba_shot_profile_experiment,
)
from courtsim.analysis.nba_shot_profiles import (
    NbaShotProfileError,
    build_calibrated_nba_shot_profile_payload,
    build_nba_shot_profile_payload,
    load_nba_shot_profile_set,
)
from courtsim.analysis.nba_team_strength import (
    NbaTeamStrengthError,
    apply_nba_team_strengths,
    load_nba_team_strength_alignment,
)
from courtsim.analysis.pace_diagnostics import PaceDiagnosticError, build_pace_audit_from_bundle
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
from courtsim.analysis.quick_sim_consistency import (
    QuickSimConsistencyError,
    compare_quick_sim_engines,
    load_quick_sim_consistency_gate,
    run_aggregate_sensitivity,
    verify_quick_sim_consistency_manifests,
)
from courtsim.analysis.quick_sim_formal_gate import (
    QuickSimFormalGateError,
    evaluate_quick_sim_formal_gate,
)
from courtsim.analysis.quick_sim_pairing import (
    QuickSimPairingError,
    compare_paired_quick_sim_batches,
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
from courtsim.domain.player_serialization import player_lineup_from_json
from courtsim.draft_obligations import DraftObligationError, inspect_draft_obligation_files
from courtsim.management import ContractRules
from courtsim.model.trace_mode import TraceMode
from courtsim.nba_franchise_artifacts import (
    NBAFranchiseArtifactError,
    load_nba_franchise_checkpoint,
    write_nba_franchise_checkpoint,
)
from courtsim.nba_franchise_runner import (
    NBAFranchiseRunnerError,
    inspect_nba_franchise_manifest,
)
from courtsim.nba_manager_evaluation import NBAFrontOfficeEvidenceThresholds
from courtsim.nba_manager_experiment import (
    NBA_MANAGER_REQUIRED_CI,
    NBAManagerExperimentError,
    build_nba_manager_candidate_receipt,
    inspect_nba_manager_experiment,
    run_nba_manager_experiment,
    verify_nba_manager_experiment,
)
from courtsim.nba_manager_study import (
    NBAManagerStudyError,
    build_nba_manager_study_bundle,
    portable_nba_manager_checkpoint_receipt,
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
    nba_data_build.add_argument("--quiet", action="store_true")
    nba_data_status = nba_data_actions.add_parser(
        "status",
        help="inspect cache and summary freshness without reading raw rows",
    )
    nba_data_status.add_argument("manifest", type=Path)
    nba_data_status.add_argument("--cache", type=Path, default=Path(".cache/nba-data"))
    nba_data_status.add_argument("--output", type=Path)
    nba_player_identity = nba_data_actions.add_parser(
        "build-player-identity",
        help="join player-box ESPN ids to pinned NBA player ids",
    )
    nba_player_identity.add_argument("player_box_summary", type=Path)
    nba_player_identity.add_argument("crosswalk_summary", type=Path)
    nba_player_identity.add_argument("output", type=Path)
    nba_player_identity.add_argument("--minimum-player-coverage", type=float, default=0.9)
    nba_player_identity.add_argument("--minimum-minutes-coverage", type=float, default=0.95)
    nba_player_identity.add_argument("--minimum-match-confidence", type=float, default=0.9)
    nba_player_crosswalk = nba_data_actions.add_parser(
        "augment-player-crosswalk",
        help="augment a pinned crosswalk with unique exact names from same-season NBA shots",
    )
    nba_player_crosswalk.add_argument("player_box_summary", type=Path)
    nba_player_crosswalk.add_argument("crosswalk_summary", type=Path)
    nba_player_crosswalk.add_argument("player_shot_summary", type=Path)
    nba_player_crosswalk.add_argument("output", type=Path)
    nba_player_targets = nba_data_actions.add_parser(
        "build-player-targets",
        help="build source-pinned player usage, efficiency, shot and minutes targets",
    )
    nba_player_targets.add_argument("player_box_summary", type=Path)
    nba_player_targets.add_argument("player_shot_summary", type=Path)
    nba_player_targets.add_argument("identity", type=Path)
    nba_player_targets.add_argument("output", type=Path)
    nba_player_targets.add_argument("--target-id", required=True)
    nba_player_targets.add_argument("--minimum-games", type=int, default=10)
    nba_player_targets.add_argument("--minimum-minutes-per-game", type=float, default=8.0)
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

    nba_player_audit = subparsers.add_parser(
        "nba-player-audit",
        help="audit player metrics from a verified full-trace model bundle",
    )
    nba_player_audit.add_argument("manifest", type=Path)
    nba_player_audit.add_argument("targets", type=Path)
    nba_player_audit.add_argument("identity", type=Path)
    nba_player_audit.add_argument("output", type=Path)
    nba_player_evaluate = subparsers.add_parser(
        "nba-player-evaluate",
        help="evaluate a player simulation audit against observed targets",
    )
    nba_player_evaluate.add_argument("audit", type=Path)
    nba_player_evaluate.add_argument("targets", type=Path)
    nba_player_evaluate.add_argument("output", type=Path)
    nba_player_evaluate_batch = subparsers.add_parser(
        "nba-player-evaluate-batch",
        help="pool compatible player evaluation reports across seeds",
    )
    nba_player_evaluate_batch.add_argument("output", type=Path)
    nba_player_evaluate_batch.add_argument("reports", type=Path, nargs="+")
    nba_player_gate = subparsers.add_parser(
        "nba-player-formal-gate",
        help="enforce frozen player realism thresholds with a failing exit status",
    )
    nba_player_gate.add_argument("evaluation", type=Path)
    nba_player_gate.add_argument("audit", type=Path)
    nba_player_gate.add_argument("output", type=Path)
    nba_player_holdout_gate = subparsers.add_parser(
        "nba-player-holdout-gate",
        help="evaluate a complete thirty-season compact player holdout",
    )
    nba_player_holdout_gate.add_argument("checkpoint", type=Path)
    nba_player_holdout_gate.add_argument("gate", type=Path)
    nba_player_holdout_gate.add_argument("output", type=Path)
    pace_clock_audit = subparsers.add_parser(
        "pace-clock-audit",
        help="decompose possession clock use from a verified full-trace model bundle",
    )
    pace_clock_audit.add_argument("manifest", type=Path)
    pace_clock_audit.add_argument("output", type=Path)
    player_calibration_plan = subparsers.add_parser(
        "nba-player-calibration-plan",
        help="gate identity coverage and emit an ordered player calibration plan",
    )
    player_calibration_plan.add_argument("targets", type=Path)
    player_calibration_plan.add_argument("identity", type=Path)
    player_calibration_plan.add_argument("output", type=Path)

    draft_obligation_audit = subparsers.add_parser(
        "draft-obligation-audit",
        help="read-only verification of a draft obligation/freeze ledger v3",
    )
    draft_obligation_audit.add_argument("ledger", type=Path)
    draft_obligation_audit.add_argument("assets", type=Path)
    draft_obligation_audit.add_argument("--output", type=Path)

    quick_sim_status = subparsers.add_parser(
        "nba-quick-sim-status",
        help="verify and summarize a quick-simulation checkpoint",
    )
    quick_sim_status.add_argument("checkpoint", type=Path)

    quick_sim_run = subparsers.add_parser(
        "nba-quick-sim-run",
        help="run or resume an input-pinned formal thirty-team quick-sim batch",
    )
    quick_sim_run.add_argument("profile", type=Path)
    quick_sim_run.add_argument("strength", type=Path)
    quick_sim_run.add_argument("checkpoint", type=Path)
    quick_sim_run.add_argument("--manifest", type=Path)
    quick_sim_run.add_argument("--schema", type=Path, default=DEFAULT_MODEL_SCHEMA)
    quick_sim_run.add_argument("--parameters", type=Path, default=DEFAULT_MODEL_PARAMETERS)
    quick_sim_run.add_argument(
        "--lineup", type=Path, default=Path("examples/calibration_lineup_v1.json")
    )
    quick_sim_run.add_argument(
        "--player-rosters",
        type=Path,
        help="source-pinned NBA player target set used to build real rosters",
    )
    quick_sim_run.add_argument("--batch-id", required=True)
    quick_sim_run.add_argument("--master-seed", type=int, required=True)
    quick_sim_run.add_argument("--seasons", type=int, default=30)
    quick_sim_run.add_argument("--maximum-new-seasons", type=int)
    quick_sim_run.add_argument("--workers", type=int, default=1)
    quick_sim_run.add_argument(
        "--executor-version",
        default="nba-quick-sim-executor-v6",
        choices=(
            "nba-quick-sim-executor-v5",
            "nba-quick-sim-executor-v6",
            "nba-quick-sim-executor-v7",
        ),
    )
    quick_sim_run.add_argument("--periods", type=int, default=4)
    quick_sim_run.add_argument("--period-seconds", type=int, default=720)
    quick_sim_run.add_argument("--possession-seconds", type=int, default=24)
    quick_sim_run.add_argument("--overtime-seconds", type=int, default=300)
    quick_sim_run.add_argument("--max-overtimes", type=int, default=8)

    aggregate_quick_sim_run = subparsers.add_parser(
        "nba-aggregate-quick-sim-run",
        help="run or resume a source-pinned aggregate NBA quick-sim batch",
    )
    aggregate_quick_sim_run.add_argument("checkpoint", type=Path)
    aggregate_quick_sim_run.add_argument("--manifest", type=Path)
    aggregate_quick_sim_run.add_argument(
        "--aggregate-parameters",
        type=Path,
        default=Path("experiments/sources/nba-aggregate-quick-sim-parameters-v1.json"),
    )
    aggregate_quick_sim_run.add_argument(
        "--strength",
        type=Path,
        default=Path("experiments/sources/nba-2024-25-team-strength-v1.json"),
    )
    aggregate_quick_sim_run.add_argument("--batch-id", required=True)
    aggregate_quick_sim_run.add_argument("--master-seed", type=int, required=True)
    aggregate_quick_sim_run.add_argument("--seasons", type=int, default=30)
    aggregate_quick_sim_run.add_argument("--maximum-new-seasons", type=int)
    aggregate_sensitivity = subparsers.add_parser(
        "nba-aggregate-sensitivity",
        help="run paired home-advantage and pace-variance sensitivity",
    )
    aggregate_sensitivity.add_argument("baseline", type=Path)
    aggregate_sensitivity.add_argument("output", type=Path)
    aggregate_sensitivity.add_argument(
        "--aggregate-parameters",
        type=Path,
        default=Path("experiments/sources/nba-aggregate-quick-sim-parameters-v1.json"),
    )
    aggregate_sensitivity.add_argument(
        "--strength",
        type=Path,
        default=Path("experiments/sources/nba-2024-25-team-strength-v1.json"),
    )

    nba_reality_build = subparsers.add_parser(
        "nba-reality-build",
        help="build source-pinned multi-season NBA standings/playoff reality",
    )
    nba_reality_build.add_argument("manifest", type=Path)
    nba_reality_build.add_argument("reality_output", type=Path)
    nba_reality_build.add_argument("reference_output", type=Path)
    nba_reality_build.add_argument("--cache", type=Path, required=True)

    quick_sim_compare = subparsers.add_parser(
        "nba-quick-sim-compare",
        help="compare a verified quick-simulation checkpoint with a reference",
    )
    quick_sim_compare.add_argument("checkpoint", type=Path)
    quick_sim_compare.add_argument("reference", type=Path)
    quick_sim_compare.add_argument("--output", type=Path)
    quick_sim_paired = subparsers.add_parser(
        "nba-quick-sim-paired-diff",
        help="compare complete baseline and candidate batches with identical seeds",
    )
    quick_sim_paired.add_argument("baseline", type=Path)
    quick_sim_paired.add_argument("candidate", type=Path)
    quick_sim_paired.add_argument("output", type=Path)
    quick_sim_consistency = subparsers.add_parser(
        "nba-quick-sim-consistency",
        help="compare paired aggregate and full-engine checkpoint seasons",
    )
    quick_sim_consistency.add_argument("aggregate", type=Path)
    quick_sim_consistency.add_argument("full_engine", type=Path)
    quick_sim_consistency.add_argument("output", type=Path)
    quick_sim_consistency.add_argument("--gate", type=Path)
    quick_sim_consistency.add_argument("--aggregate-manifest", type=Path)
    quick_sim_consistency.add_argument("--full-manifest", type=Path)
    quick_sim_formal_gate = subparsers.add_parser(
        "nba-quick-sim-formal-gate",
        help="evaluate a complete unseen-seed batch against a frozen NBA reality gate",
    )
    quick_sim_formal_gate.add_argument("checkpoint", type=Path)
    quick_sim_formal_gate.add_argument("gate", type=Path)
    quick_sim_formal_gate.add_argument("run_manifest", type=Path)
    quick_sim_formal_gate.add_argument("--output", type=Path)
    shot_profile_evaluate = subparsers.add_parser(
        "nba-shot-profile-evaluate",
        help="compare baseline and candidate team shot-zone audits with NBA profiles",
    )
    shot_profile_evaluate.add_argument("baseline_audit", type=Path)
    shot_profile_evaluate.add_argument("candidate_audit", type=Path)
    shot_profile_evaluate.add_argument("profiles", type=Path)
    shot_profile_evaluate.add_argument("output", type=Path)
    shot_profile_evaluate.add_argument("--quiet", action="store_true")
    shot_profile_batch = subparsers.add_parser(
        "nba-shot-profile-evaluate-batch",
        help="pool multiple compatible shot-profile evaluation reports",
    )
    shot_profile_batch.add_argument("output", type=Path)
    shot_profile_batch.add_argument("reports", type=Path, nargs="+")
    shot_profile_batch.add_argument("--quiet", action="store_true")
    shot_profile_calibrate = subparsers.add_parser(
        "nba-shot-profile-calibrate",
        help="materialize a source-pinned profile from a complete simulation baseline",
    )
    shot_profile_calibrate.add_argument("profile", type=Path)
    shot_profile_calibrate.add_argument("baseline_audit", type=Path)
    shot_profile_calibrate.add_argument("output", type=Path)
    shot_profile_calibrate.add_argument("--calibration-strength", type=float, default=0.75)
    shot_profile_calibrate.add_argument("--rim-contrast-strength", type=float, default=1.0)
    shot_profile_calibrate.add_argument("--midrange-contrast-strength", type=float, default=0.75)
    shot_profile_calibrate.add_argument("--maximum-absolute-offset", type=int, default=30)
    shot_profile_calibrate.add_argument("--quiet", action="store_true")
    shot_profile_run = subparsers.add_parser(
        "nba-shot-profile-run",
        help="run a paired 30-team regular-season shot-profile experiment",
    )
    shot_profile_run.add_argument("profile", type=Path)
    shot_profile_run.add_argument("--schema", type=Path, default=DEFAULT_MODEL_SCHEMA)
    shot_profile_run.add_argument("--parameters", type=Path, default=DEFAULT_MODEL_PARAMETERS)
    shot_profile_run.add_argument(
        "--lineup", type=Path, default=Path("examples/calibration_lineup_v1.json")
    )
    shot_profile_run.add_argument("--seed", type=int, default=20260801)
    shot_profile_run.add_argument("--periods", type=int, default=4)
    shot_profile_run.add_argument("--period-seconds", type=int, default=720)
    shot_profile_run.add_argument("--possession-seconds", type=int, default=24)
    shot_profile_run.add_argument("--overtime-seconds", type=int, default=300)
    shot_profile_run.add_argument("--max-overtimes", type=int, default=8)
    shot_profile_run.add_argument("--output", type=Path, default=Path("work/runs/shot-profile"))
    shot_profile_run.add_argument("--quiet", action="store_true")
    shot_profile_run_batch = subparsers.add_parser(
        "nba-shot-profile-run-batch",
        help="resume a deterministic multi-seed shot-profile experiment batch",
    )
    shot_profile_run_batch.add_argument("profile", type=Path)
    shot_profile_run_batch.add_argument("--schema", type=Path, default=DEFAULT_MODEL_SCHEMA)
    shot_profile_run_batch.add_argument("--parameters", type=Path, default=DEFAULT_MODEL_PARAMETERS)
    shot_profile_run_batch.add_argument(
        "--lineup", type=Path, default=Path("examples/calibration_lineup_v1.json")
    )
    shot_profile_run_batch.add_argument("--master-seed", type=int, default=20260801)
    shot_profile_run_batch.add_argument("--runs", type=int, default=3)
    shot_profile_run_batch.add_argument("--maximum-new-runs", type=int)
    shot_profile_run_batch.add_argument("--workers", type=int, default=1)
    shot_profile_run_batch.add_argument("--periods", type=int, default=4)
    shot_profile_run_batch.add_argument("--period-seconds", type=int, default=720)
    shot_profile_run_batch.add_argument("--possession-seconds", type=int, default=24)
    shot_profile_run_batch.add_argument("--overtime-seconds", type=int, default=300)
    shot_profile_run_batch.add_argument("--max-overtimes", type=int, default=8)
    shot_profile_run_batch.add_argument(
        "--output", type=Path, default=Path("work/runs/shot-profile-batch")
    )
    shot_profile_run_batch.add_argument("--quiet", action="store_true")
    shot_profile_batch_status = subparsers.add_parser(
        "nba-shot-profile-batch-status",
        help="verify and summarize a shot-profile batch manifest",
    )
    shot_profile_batch_status.add_argument("manifest", type=Path)

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
    manager_study_run.add_argument("--schema", type=Path, default=DEFAULT_MODEL_SCHEMA)
    manager_study_run.add_argument("--parameters", type=Path, default=DEFAULT_MODEL_PARAMETERS)
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
            elif arguments.nba_data_action == "build-player-identity":
                nba_data_report = build_nba_player_identity_payload(
                    arguments.player_box_summary,
                    arguments.crosswalk_summary,
                    minimum_player_coverage=arguments.minimum_player_coverage,
                    minimum_minutes_coverage=arguments.minimum_minutes_coverage,
                    minimum_match_confidence=arguments.minimum_match_confidence,
                )
                write_json(arguments.output, nba_data_report)
            elif arguments.nba_data_action == "augment-player-crosswalk":
                nba_data_report = augment_nba_player_crosswalk_payload(
                    arguments.player_box_summary,
                    arguments.crosswalk_summary,
                    arguments.player_shot_summary,
                )
                write_json(arguments.output, nba_data_report)
            elif arguments.nba_data_action == "build-player-targets":
                nba_data_report = build_nba_player_target_payload(
                    arguments.player_box_summary,
                    arguments.player_shot_summary,
                    arguments.identity,
                    target_id=arguments.target_id,
                    minimum_games=arguments.minimum_games,
                    minimum_minutes_per_game=arguments.minimum_minutes_per_game,
                )
                write_json(arguments.output, nba_data_report)
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
            if not getattr(arguments, "quiet", False):
                console_report = nba_data_report
                groups = nba_data_report.get("groups")
                if arguments.nba_data_action == "build" and isinstance(groups, (dict, list)):
                    console_report = {
                        "cached": nba_data_report.get("cached"),
                        "dataset_id": nba_data_report.get("dataset_id"),
                        "group_count": len(groups),
                        "output": str(arguments.output),
                        "rows_processed": nba_data_report.get("rows_processed"),
                        "season": nba_data_report.get("season"),
                    }
                elif arguments.nba_data_action == "build-player-identity":
                    console_report = {
                        "coverage": nba_data_report.get("coverage"),
                        "output": str(arguments.output),
                        "promotion": nba_data_report.get("promotion"),
                        "season": nba_data_report.get("season"),
                        "version": nba_data_report.get("version"),
                    }
                elif arguments.nba_data_action == "augment-player-crosswalk":
                    console_report = {
                        "augmentation": nba_data_report.get("augmentation"),
                        "output": str(arguments.output),
                        "season": nba_data_report.get("season"),
                    }
                elif arguments.nba_data_action == "build-player-targets":
                    console_report = {
                        "output": str(arguments.output),
                        "players": len(cast(list[object], nba_data_report["players"])),
                        "season": nba_data_report.get("season"),
                        "target_id": nba_data_report.get("target_id"),
                        "version": nba_data_report.get("version"),
                    }
                print(
                    json.dumps(
                        console_report,
                        ensure_ascii=True,
                        separators=(",", ":"),
                        sort_keys=True,
                    )
                )
            return 0

        if arguments.command == "nba-player-audit":
            player_audit_report = build_nba_player_audit_from_bundle(
                arguments.manifest,
                arguments.targets,
                arguments.identity,
            )
            write_json(arguments.output, player_audit_report)
            print(
                json.dumps(
                    {
                        "games": player_audit_report.get("games"),
                        "output": str(arguments.output),
                        "players": len(cast(list[object], player_audit_report["players"])),
                        "version": player_audit_report.get("version"),
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0

        if arguments.command == "nba-player-evaluate":
            player_evaluation_report = evaluate_nba_player_audit_files(
                arguments.audit, arguments.targets
            )
            write_json(arguments.output, player_evaluation_report)
            print(
                json.dumps(
                    {
                        "metrics": len(cast(list[object], player_evaluation_report["metrics"])),
                        "output": str(arguments.output),
                        "players": player_evaluation_report.get("players"),
                        "version": player_evaluation_report.get("version"),
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0

        if arguments.command == "nba-player-evaluate-batch":
            player_batch_report = aggregate_nba_player_evaluation_files(tuple(arguments.reports))
            write_json(arguments.output, player_batch_report)
            print(
                json.dumps(
                    {
                        "metrics": len(cast(list[object], player_batch_report["metrics"])),
                        "output": str(arguments.output),
                        "players": player_batch_report.get("players"),
                        "runs": player_batch_report.get("runs"),
                        "version": player_batch_report.get("version"),
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0

        if arguments.command == "nba-player-formal-gate":
            player_gate_report = evaluate_nba_player_reality_gate_files(
                arguments.evaluation, arguments.audit
            )
            write_json(arguments.output, player_gate_report)
            print(
                json.dumps(
                    {
                        "output": str(arguments.output),
                        "passed": player_gate_report.get("passed"),
                        "version": player_gate_report.get("version"),
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0 if player_gate_report["passed"] is True else 16

        if arguments.command == "nba-player-holdout-gate":
            player_holdout = nba_player_holdout_from_dict(
                json.loads(arguments.checkpoint.read_text(encoding="utf-8"))
            )
            player_holdout_thresholds = load_nba_player_holdout_gate(
                json.loads(arguments.gate.read_text(encoding="utf-8"))
            )
            player_holdout_report = evaluate_nba_player_holdout(
                player_holdout, player_holdout_thresholds
            )
            write_json(arguments.output, player_holdout_report)
            print(
                json.dumps(
                    {
                        "output": str(arguments.output),
                        "passed": player_holdout_report["passed"],
                        "seasons": player_holdout_report["seasons"],
                        "version": player_holdout_report["version"],
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0 if player_holdout_report["passed"] is True else 17

        if arguments.command == "pace-clock-audit":
            pace_report = build_pace_audit_from_bundle(arguments.manifest)
            write_json(arguments.output, pace_report)
            print(
                json.dumps(
                    {
                        "contexts": len(cast(list[object], pace_report["contexts"])),
                        "games": pace_report["games"],
                        "mean_team_possessions": pace_report["mean_team_possessions"],
                        "output": str(arguments.output),
                        "version": pace_report["version"],
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0

        if arguments.command == "nba-player-calibration-plan":
            try:
                identity_payload = json.loads(arguments.identity.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise NbaPlayerIdentityError("invalid player identity JSON") from error
            if not isinstance(identity_payload, dict):
                raise NbaPlayerIdentityError("player identity must be an object")
            calibration_plan = build_player_calibration_plan(
                load_nba_player_target_set(arguments.targets),
                identity_payload,
            )
            write_json(arguments.output, calibration_plan)
            print(
                json.dumps(
                    {
                        "output": str(arguments.output),
                        "players": calibration_plan["players"],
                        "promotion_ready": calibration_plan["promotion_ready"],
                        "version": calibration_plan["version"],
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0 if calibration_plan["promotion_ready"] is True else 17

        if arguments.command == "draft-obligation-audit":
            draft_obligation_report = inspect_draft_obligation_files(
                arguments.ledger, arguments.assets
            )
            if arguments.output is not None:
                write_json(arguments.output, draft_obligation_report)
            print(
                json.dumps(
                    {
                        "as_of_year": draft_obligation_report.get("as_of_year"),
                        "counts": draft_obligation_report.get("counts"),
                        "ready": draft_obligation_report.get("ready"),
                        "source_verified": draft_obligation_report.get("source_verified"),
                        "version": draft_obligation_report.get("ledger_version"),
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0 if draft_obligation_report["ready"] is True else 6

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

        if arguments.command == "nba-quick-sim-run":
            run_manifest_path = arguments.manifest or arguments.checkpoint.with_suffix(
                ".manifest.json"
            )
            quick_sim_run_manifest = run_nba_quick_sim_batch(
                schema_path=arguments.schema,
                parameters_path=arguments.parameters,
                lineup_path=arguments.lineup,
                profile_path=arguments.profile,
                strength_path=arguments.strength,
                checkpoint_path=arguments.checkpoint,
                manifest_path=run_manifest_path,
                batch_id=arguments.batch_id,
                master_seed=arguments.master_seed,
                seasons=arguments.seasons,
                maximum_new_seasons=arguments.maximum_new_seasons,
                game_config=GameClockConfig(
                    arguments.periods,
                    arguments.period_seconds,
                    arguments.possession_seconds,
                    arguments.overtime_seconds,
                    arguments.max_overtimes,
                    True,
                ),
                workers=arguments.workers,
                executor_version=arguments.executor_version,
                player_roster_path=arguments.player_rosters,
            )
            print(
                json.dumps(
                    quick_sim_run_manifest["checkpoint"],
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0

        if arguments.command == "nba-aggregate-quick-sim-run":
            aggregate_manifest_path = arguments.manifest or arguments.checkpoint.with_suffix(
                ".manifest.json"
            )
            aggregate_manifest = run_nba_aggregate_quick_sim_batch(
                parameter_path=arguments.aggregate_parameters,
                strength_path=arguments.strength,
                checkpoint_path=arguments.checkpoint,
                manifest_path=aggregate_manifest_path,
                batch_id=arguments.batch_id,
                master_seed=arguments.master_seed,
                seasons=arguments.seasons,
                maximum_new_seasons=arguments.maximum_new_seasons,
            )
            print(
                json.dumps(
                    aggregate_manifest["checkpoint"],
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0

        if arguments.command == "nba-aggregate-sensitivity":
            sensitivity_report = run_aggregate_sensitivity(
                arguments.aggregate_parameters,
                arguments.strength,
                arguments.baseline,
            )
            write_json(arguments.output, sensitivity_report)
            print(
                json.dumps(
                    {
                        "baseline_batch_sha256": sensitivity_report["baseline_batch_sha256"],
                        "output": str(arguments.output),
                        "variants": len(cast(list[object], sensitivity_report["variants"])),
                        "version": sensitivity_report["version"],
                    },
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0

        if arguments.command == "nba-reality-build":
            reality, reality_reference = build_nba_reality_payload(
                arguments.manifest, arguments.cache
            )
            write_json(arguments.reality_output, reality)
            write_json(arguments.reference_output, reality_reference)
            print(
                json.dumps(
                    {
                        "dataset_id": reality["dataset_id"],
                        "seasons": len(cast(list[object], reality["seasons"])),
                        "reality_output": str(arguments.reality_output),
                        "reference_output": str(arguments.reference_output),
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

        if arguments.command == "nba-quick-sim-paired-diff":
            baseline = quick_sim_batch_from_json(arguments.baseline.read_text(encoding="utf-8"))
            paired_candidate = quick_sim_batch_from_json(
                arguments.candidate.read_text(encoding="utf-8")
            )
            paired_report = compare_paired_quick_sim_batches(baseline, paired_candidate)
            write_json(arguments.output, paired_report)
            print(
                json.dumps(paired_report, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
            )
            return 0

        if arguments.command == "nba-quick-sim-consistency":
            aggregate = quick_sim_batch_from_json(arguments.aggregate.read_text(encoding="utf-8"))
            full_engine = quick_sim_batch_from_json(
                arguments.full_engine.read_text(encoding="utf-8")
            )
            aggregate_by_seed = {cell.seed: cell.summary for cell in aggregate.cells}
            full_by_seed = {cell.seed: cell.summary for cell in full_engine.cells}
            if aggregate.spec != full_engine.spec:
                raise QuickSimConsistencyError("consistency batches must use the same spec")
            consistency_gate = (
                None if arguments.gate is None else load_quick_sim_consistency_gate(arguments.gate)
            )
            inputs_verified = None
            if consistency_gate is not None:
                if arguments.aggregate_manifest is None or arguments.full_manifest is None:
                    raise QuickSimConsistencyError(
                        "consistency gate requires both aggregate and full manifests"
                    )
                inputs_verified = verify_quick_sim_consistency_manifests(
                    consistency_gate,
                    arguments.aggregate_manifest,
                    arguments.full_manifest,
                    arguments.aggregate,
                    arguments.full_engine,
                )
            consistency_report = compare_quick_sim_engines(
                aggregate_by_seed,
                full_by_seed,
                gate=consistency_gate,
                master_seed=aggregate.spec.master_seed,
                inputs_verified=inputs_verified,
            )
            write_json(arguments.output, consistency_report)
            print(
                json.dumps(
                    consistency_report,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            if consistency_gate is None:
                return 0
            return 0 if consistency_report["promotion_ready"] is True else 16

        if arguments.command == "nba-quick-sim-formal-gate":
            formal_report = evaluate_quick_sim_formal_gate(
                arguments.checkpoint, arguments.gate, arguments.run_manifest
            )
            if arguments.output is not None:
                write_json(arguments.output, formal_report)
            print(
                json.dumps(
                    formal_report,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0 if formal_report["passed"] is True else 15

        if arguments.command == "nba-shot-profile-evaluate":
            evaluation = evaluate_nba_shot_profile_audits(
                load_distribution_audit(arguments.baseline_audit),
                load_distribution_audit(arguments.candidate_audit),
                load_nba_shot_profile_set(arguments.profiles),
            )
            write_json(arguments.output, evaluation)
            if not arguments.quiet:
                print(
                    f"{evaluation['status']}: RMSE {evaluation['baseline_rmse']} -> "
                    f"{evaluation['candidate_rmse']}"
                )
            return 0

        if arguments.command == "nba-shot-profile-evaluate-batch":
            reports: list[dict[str, object]] = []
            for path in arguments.reports:
                try:
                    raw = json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as error:
                    raise NbaShotProfileEvaluationError(
                        "invalid shot profile evaluation JSON"
                    ) from error
                if not isinstance(raw, dict):
                    raise NbaShotProfileEvaluationError(
                        "shot profile evaluation report must be an object"
                    )
                reports.append(raw)
            evaluation = aggregate_nba_shot_profile_evaluations(tuple(reports))
            write_json(arguments.output, evaluation)
            if not arguments.quiet:
                print(
                    f"{evaluation['status']}: {evaluation['improved_runs']}/"
                    f"{evaluation['runs']} runs improved; RMSE "
                    f"{evaluation['baseline_rmse']} -> {evaluation['candidate_rmse']}"
                )
            return 0

        if arguments.command == "nba-shot-profile-calibrate":
            calibrated_payload = build_calibrated_nba_shot_profile_payload(
                arguments.profile,
                arguments.baseline_audit,
                calibration_strength=arguments.calibration_strength,
                contrast_calibration_strengths=(
                    arguments.rim_contrast_strength,
                    arguments.midrange_contrast_strength,
                ),
                maximum_absolute_offset=arguments.maximum_absolute_offset,
            )
            write_json(arguments.output, calibrated_payload)
            if not arguments.quiet:
                calibrated_teams = calibrated_payload["teams"]
                if not isinstance(calibrated_teams, list):
                    raise NbaShotProfileError("calibrated shot profile teams are invalid")
                print(f"calibrated: {arguments.output} ({len(calibrated_teams)} teams)")
            return 0

        if arguments.command == "nba-shot-profile-run":
            run_manifest = run_nba_shot_profile_experiment(
                profile_path=arguments.profile,
                schema_path=arguments.schema,
                parameters_path=arguments.parameters,
                lineup_path=arguments.lineup,
                output_directory=arguments.output,
                seed=arguments.seed,
                game_config=GameClockConfig(
                    arguments.periods,
                    arguments.period_seconds,
                    arguments.possession_seconds,
                    arguments.overtime_seconds,
                    arguments.max_overtimes,
                    True,
                ),
            )
            if not arguments.quiet:
                summary = cast(dict[str, object], run_manifest["summary"])
                print(
                    f"{summary['status']}: {summary['games']} games; RMSE "
                    f"{summary['baseline_rmse']} -> {summary['candidate_rmse']}"
                )
            return 0

        if arguments.command == "nba-shot-profile-run-batch":
            batch_manifest = run_nba_shot_profile_batch(
                profile_path=arguments.profile,
                schema_path=arguments.schema,
                parameters_path=arguments.parameters,
                lineup_path=arguments.lineup,
                output_directory=arguments.output,
                master_seed=arguments.master_seed,
                runs=arguments.runs,
                maximum_new_runs=arguments.maximum_new_runs,
                workers=arguments.workers,
                game_config=GameClockConfig(
                    arguments.periods,
                    arguments.period_seconds,
                    arguments.possession_seconds,
                    arguments.overtime_seconds,
                    arguments.max_overtimes,
                    True,
                ),
            )
            if not arguments.quiet:
                print(
                    f"shot-profile batch: {batch_manifest['completed_runs']}/"
                    f"{arguments.runs} runs complete"
                )
            return 0

        if arguments.command == "nba-shot-profile-batch-status":
            print(
                json.dumps(
                    inspect_nba_shot_profile_batch(arguments.manifest),
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0

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

        if arguments.command == "nba-manager-source-sync":
            manager_source_report = sync_nba_manager_state_source(
                player_targets_path=arguments.player_targets,
                identity_path=arguments.identity,
                output_path=arguments.output,
                cache_directory=arguments.cache,
                season_year=arguments.season_year,
                workers=arguments.workers,
                offline=arguments.offline,
                force=arguments.force,
            )
            print(json.dumps(manager_source_report, separators=(",", ":"), sort_keys=True))
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
            manager_state_receipt_payload = {
                "version": "nba-manager-state-build-receipt-v1",
                "build": asdict(state_build.receipt),
                "checkpoint": asdict(portable_nba_manager_checkpoint_receipt(checkpoint_receipt)),
            }
            write_json(arguments.receipt, manager_state_receipt_payload)
            print(
                json.dumps(
                    manager_state_receipt_payload,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0

        if arguments.command == "nba-manager-study-run":
            formal_run = not arguments.development
            default_sources = 30 if formal_run else 8
            default_seed_start = 20270401 if formal_run else 20270301
            default_seasons = 5 if formal_run else 3
            sources = default_sources if arguments.sources is None else arguments.sources
            seed_start = (
                default_seed_start if arguments.seed_start is None else arguments.seed_start
            )
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
            manager_study_result = run_nba_manager_experiment(
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
            manager_study_summary = {
                "version": manager_study_result.version,
                "complete": manager_study_result.complete,
                "executed_cells": manager_study_result.executed_cells,
                "reused_cells": manager_study_result.reused_cells,
                "completed_sources": manager_study_result.completed_sources,
                "status": (
                    "stopped"
                    if manager_study_result.stopped
                    else "running"
                    if not manager_study_result.complete
                    else "candidate-pass"
                    if manager_study_result.evidence is not None
                    and manager_study_result.evidence.recommended
                    else "candidate-fail"
                ),
            }
            print(json.dumps(manager_study_summary, separators=(",", ":"), sort_keys=True))
            return (
                0
                if not manager_study_result.complete
                or manager_study_result.evidence is None
                or manager_study_result.evidence.recommended
                else 19
            )

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
            manager_candidate_receipt = build_nba_manager_candidate_receipt(
                arguments.report,
                git_commit=arguments.git_commit,
                ci_checks=ci_checks,
            )
            write_json(arguments.output, manager_candidate_receipt)
            print(
                json.dumps(
                    manager_candidate_receipt,
                    separators=(",", ":"),
                    sort_keys=True,
                )
            )
            return 0 if manager_candidate_receipt["status"] == "candidate-pass" else 18

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
        DraftObligationError,
        ExperimentMatrixError,
        MatrixContrastError,
        MatrixContrastRobustnessError,
        MatrixRankingError,
        MatrixStyleCoverageError,
        MatrixRobustnessError,
        NbaReferenceError,
        NbaDataAuditError,
        NbaAggregateQuickSimError,
        NbaShotProfileError,
        NbaShotProfileEvaluationError,
        NbaShotProfileBatchError,
        NbaShotProfileRunnerError,
        NbaTeamStrengthError,
        NbaDataPipelineError,
        NbaPlayerIdentityError,
        NbaPlayerEvaluationError,
        NbaPlayerHoldoutError,
        NbaPlayerTargetError,
        NbaQuickSimRunnerError,
        NbaRealityError,
        NBAFranchiseArtifactError,
        NBAFranchiseRunnerError,
        NBAManagerExperimentError,
        NBAManagerSourceSyncError,
        NBAManagerStateError,
        NBAManagerStudyError,
        ParameterOverlayError,
        PaceDiagnosticError,
        PlayerProfileOverlayError,
        ProjectStatusError,
        QuickSimBatchError,
        QuickSimPairingError,
        QuickSimComparisonError,
        QuickSimConsistencyError,
        QuickSimFormalGateError,
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
