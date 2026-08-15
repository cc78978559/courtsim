import hashlib
import json
from pathlib import Path

from courtsim.analysis import (
    evaluate_audit_gates,
    load_audit_gates,
    load_distribution_audit,
)
from courtsim.analysis.nba_quick_sim_executor import NBA_QUICK_SIM_EXECUTOR_VERSION
from courtsim.analysis.quick_sim_artifacts import QUICK_SIM_ARTIFACT_VERSION
from courtsim.analysis.quick_sim_batch import QUICK_SIM_BATCH_VERSION
from courtsim.analysis.quick_sim_comparison import (
    QUICK_SIM_COMPARISON_VERSION,
    QUICK_SIM_METRICS,
)
from courtsim.analysis.realism_targets import (
    load_realism_target_set,
    score_audit_against_realism_targets,
)
from courtsim.cap_mechanics import CAP_MECHANICS_VERSION, CapMechanicsRules
from courtsim.career import (
    CAREER_VERSION,
    DRAFT_VERSION,
    OFFSEASON_SCHEMA_VERSION,
    RETIREMENT_VERSION,
    CareerRules,
    DraftRules,
)
from courtsim.cli import DEFAULT_MODEL_PARAMETERS, DEFAULT_MODEL_SCHEMA
from courtsim.draft_assets import DRAFT_ASSET_SCHEMA_VERSION, DRAFT_ASSET_VERSION
from courtsim.draft_lottery import DRAFT_LOTTERY_VERSION, DraftLotteryRules
from courtsim.management import (
    CONTRACT_VERSION,
    FREE_AGENCY_VERSION,
    MANAGEMENT_SCHEMA_VERSION,
    ContractRules,
)
from courtsim.manager_ai import MANAGER_AI_VERSION, ManagerPolicyMode
from courtsim.manager_authority import MANAGER_AUTHORITY_VERSION, ManagerDecisionStage
from courtsim.manager_evaluation import (
    MANAGER_EVIDENCE_VERSION,
    MANAGER_RELEASE_REGISTRY_VERSION,
    ManagerEvaluationWeights,
    ManagerEvidenceThresholds,
)
from courtsim.manager_experiment import MANAGER_EXPERIMENT_VERSION
from courtsim.manager_league_adapter import MANAGER_LEAGUE_ADAPTER_VERSION
from courtsim.manager_learning import MANAGER_LEARNING_VERSION
from courtsim.manager_objectives import MANAGER_OBJECTIVE_VERSION, ManagerObjective
from courtsim.manager_rotation import MANAGER_ROTATION_VERSION, ManagerRotationRules
from courtsim.manager_trade import MANAGER_TRADE_VERSION, ManagerTradeRules
from courtsim.nba_draft_lottery import (
    NBA_DRAFT_ASSET_SETTLEMENT_VERSION,
    NBA_DRAFT_LOTTERY_RULES,
    NBA_DRAFT_LOTTERY_VERSION,
)
from courtsim.nba_draft_offseason import NBA_DRAFT_OFFSEASON_VERSION
from courtsim.nba_franchise import NBA_FRANCHISE_VERSION
from courtsim.nba_franchise_artifacts import NBA_FRANCHISE_ARTIFACT_VERSION
from courtsim.nba_league import NBA_LEAGUE_VERSION, NBARegularSeasonRules
from courtsim.nba_offseason import NBA_OFFSEASON_VERSION
from courtsim.parameters import load_model_parameters
from courtsim.playoffs import PLAYOFF_SCHEMA_VERSION, PLAYOFF_VERSION, PlayoffConfig
from courtsim.prospects import PROSPECT_GENERATION_VERSION, ProspectGenerationRules
from courtsim.rosters import ROSTER_VERSION, RosterRules
from courtsim.rotations import FATIGUE_VERSION, ROTATION_VERSION, FatigueConfig
from courtsim.rules import GameRules
from courtsim.scouting import SCOUTING_VERSION, ScoutingRules
from courtsim.season import (
    INJURY_VERSION,
    SEASON_SCHEMA_VERSION,
    SEASON_VERSION,
    SeasonConfig,
)
from courtsim.three_team_market import THREE_TEAM_MARKET_VERSION, ThreeTeamMarketRules
from courtsim.three_team_trades import THREE_TEAM_TRADE_VERSION
from courtsim.trade_market import (
    MAXIMUM_SUPPORTED_NEGOTIATION_ROUNDS,
    TRADE_MARKET_VERSION,
    TradeMarketRules,
)
from courtsim.trades import TRADE_VERSION, TradeRules

ROOT = Path(__file__).resolve().parents[1]
RELEASE_PATH = ROOT / "governance" / "current-release.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_current_release_registry_is_complete_and_verified() -> None:
    release = json.loads(RELEASE_PATH.read_text(encoding="utf-8"))
    assert set(release) == {
        "format_version",
        "status",
        "engine_version",
        "rules",
        "rotation_fatigue",
        "season_injury",
        "roster_transactions",
        "contracts_free_agency",
        "playoffs",
        "career_draft",
        "manager_ai",
        "manager_authority",
        "manager_objectives",
        "manager_evidence",
        "manager_experiment",
        "manager_league_adapter",
        "prospect_generation",
        "manager_rotation",
        "trades",
        "manager_trade",
        "trade_market",
        "draft_assets",
        "draft_lottery",
        "nba_draft_lottery",
        "nba_draft_asset_settlement",
        "nba_draft_offseason",
        "nba_offseason",
        "nba_franchise",
        "nba_franchise_artifact",
        "nba_franchise_runner",
        "three_team_trades",
        "three_team_market",
        "scouting",
        "cap_mechanics",
        "nba_league",
        "manager_learning",
        "quick_sim_comparison",
        "quick_sim_batch",
        "quick_sim_artifact",
        "nba_quick_sim_executor",
        "model",
        "audit",
        "promotion",
    }
    assert release["format_version"] == 55
    assert release["status"] == "frozen"
    assert release["engine_version"] == "0.54.0"
    rules_registry = release["rules"]
    assert set(rules_registry) == {
        "version",
        "path",
        "file_sha256",
        "source_pull_request",
    }
    assert rules_registry["source_pull_request"] == 13
    rules_path = ROOT / rules_registry["path"]
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    assert _sha256(rules_path) == rules_registry["file_sha256"]
    assert rules == {
        "version": GameRules().version,
        "player_foul_limit": GameRules().player_foul_limit,
        "regulation_bonus_threshold": GameRules().regulation_bonus_threshold,
        "final_two_minute_threshold": GameRules().final_two_minute_threshold,
        "final_two_minute_seconds": GameRules().final_two_minute_seconds,
        "overtime_bonus_threshold": GameRules().overtime_bonus_threshold,
    }
    rotation_registry = release["rotation_fatigue"]
    assert set(rotation_registry) == {
        "rotation_version",
        "fatigue_version",
        "path",
        "file_sha256",
        "source_pull_request",
    }
    assert rotation_registry["source_pull_request"] == 19
    rotation_path = ROOT / rotation_registry["path"]
    rotation_config = json.loads(rotation_path.read_text(encoding="utf-8"))
    assert _sha256(rotation_path) == rotation_registry["file_sha256"]
    assert rotation_registry["rotation_version"] == ROTATION_VERSION
    assert rotation_registry["fatigue_version"] == FATIGUE_VERSION
    assert rotation_config == {
        "format_version": 1,
        "rotation_version": ROTATION_VERSION,
        "fatigue": {
            "version": FatigueConfig().version,
            "active_load_per_second": FatigueConfig().active_load_per_second,
            "bench_recovery_per_second": FatigueConfig().bench_recovery_per_second,
            "maximum_ability_penalty": FatigueConfig().maximum_ability_penalty,
            "maximum_fatigue": FatigueConfig().maximum_fatigue,
        },
    }
    season_registry = release["season_injury"]
    assert set(season_registry) == {
        "season_version",
        "injury_version",
        "path",
        "file_sha256",
        "source_pull_request",
    }
    assert season_registry["source_pull_request"] == 25
    season_path = ROOT / season_registry["path"]
    season_config = json.loads(season_path.read_text(encoding="utf-8"))
    assert _sha256(season_path) == season_registry["file_sha256"]
    assert season_registry["season_version"] == SEASON_VERSION
    assert season_registry["injury_version"] == INJURY_VERSION
    assert season_config == {
        "format_version": 1,
        "season_version": SEASON_VERSION,
        "injury": {
            "version": SeasonConfig().version,
            "injury_probability_bps": SeasonConfig().injury_probability_bps,
            "minimum_days_out": SeasonConfig().minimum_days_out,
            "maximum_days_out": SeasonConfig().maximum_days_out,
            "daily_fatigue_recovery": SeasonConfig().daily_fatigue_recovery,
            "forfeit_score": SeasonConfig().forfeit_score,
        },
        "game_specific_team_resolver": True,
        "postseason_injury_engine": True,
        "absolute_calendar_return_dates": True,
    }
    roster_registry = release["roster_transactions"]
    assert set(roster_registry) == {
        "roster_version",
        "path",
        "file_sha256",
        "source_pull_request",
    }
    assert roster_registry["source_pull_request"] == 31
    roster_path = ROOT / roster_registry["path"]
    roster_config = json.loads(roster_path.read_text(encoding="utf-8"))
    assert _sha256(roster_path) == roster_registry["file_sha256"]
    assert roster_registry["roster_version"] == ROSTER_VERSION
    assert roster_config == {
        "format_version": 1,
        "roster_version": ROSTER_VERSION,
        "minimum_players": RosterRules().minimum_players,
        "maximum_players": RosterRules().maximum_players,
        "season_schema_version": SEASON_SCHEMA_VERSION,
    }
    management_registry = release["contracts_free_agency"]
    assert set(management_registry) == {
        "contract_version",
        "free_agency_version",
        "path",
        "file_sha256",
        "source_pull_request",
    }
    assert management_registry["source_pull_request"] == 37
    management_path = ROOT / management_registry["path"]
    management_config = json.loads(management_path.read_text(encoding="utf-8"))
    assert _sha256(management_path) == management_registry["file_sha256"]
    assert management_registry["contract_version"] == CONTRACT_VERSION
    assert management_registry["free_agency_version"] == FREE_AGENCY_VERSION
    assert management_config == {
        "format_version": 1,
        "contract_version": CONTRACT_VERSION,
        "free_agency_version": FREE_AGENCY_VERSION,
        "salary_cap": ContractRules().salary_cap,
        "minimum_salary": ContractRules().minimum_salary,
        "maximum_salary": ContractRules().maximum_salary,
        "maximum_years": ContractRules().maximum_years,
        "maximum_roster_players": ContractRules().maximum_roster_players,
        "management_schema_version": MANAGEMENT_SCHEMA_VERSION,
        "cap_ledger_aware_entrypoint": True,
        "bird_rights_over_cap_signing": True,
        "second_apron_hard_ceiling": True,
    }
    playoff_registry = release["playoffs"]
    assert set(playoff_registry) == {
        "playoff_version",
        "path",
        "file_sha256",
        "source_pull_request",
    }
    assert playoff_registry["source_pull_request"] == 43
    playoff_path = ROOT / playoff_registry["path"]
    playoff_config = json.loads(playoff_path.read_text(encoding="utf-8"))
    assert _sha256(playoff_path) == playoff_registry["file_sha256"]
    assert playoff_registry["playoff_version"] == PLAYOFF_VERSION
    assert playoff_config == {
        "format_version": 1,
        "playoff_version": PLAYOFF_VERSION,
        "team_count": 4,
        "supported_best_of": [1, 3, 5, 7],
        "default_best_of": PlayoffConfig().best_of,
        "default_higher_seed_home": list(PlayoffConfig().higher_seed_home),
        "playoff_schema_version": PLAYOFF_SCHEMA_VERSION,
        "regular_season_state_continuity": True,
        "cross_game_fatigue_continuity": True,
        "cross_game_injury_continuity": True,
        "postseason_career_feedback": True,
        "default_postseason_rest_days": 2,
        "default_game_rest_days": 1,
        "default_round_rest_days": 2,
    }
    career_registry = release["career_draft"]
    assert set(career_registry) == {
        "career_version",
        "draft_version",
        "retirement_version",
        "path",
        "file_sha256",
    }
    career_path = ROOT / career_registry["path"]
    career_config = json.loads(career_path.read_text(encoding="utf-8"))
    assert _sha256(career_path) == career_registry["file_sha256"]
    assert career_registry["career_version"] == CAREER_VERSION
    assert career_registry["draft_version"] == DRAFT_VERSION
    assert career_registry["retirement_version"] == RETIREMENT_VERSION
    assert career_config == {
        "format_version": 1,
        "career_version": CAREER_VERSION,
        "draft_version": DRAFT_VERSION,
        "retirement_version": RETIREMENT_VERSION,
        "offseason_schema_version": OFFSEASON_SCHEMA_VERSION,
        "minimum_player_age": CareerRules().minimum_player_age,
        "minimum_retirement_age": CareerRules().minimum_retirement_age,
        "maximum_player_age": CareerRules().maximum_player_age,
        "heavy_injury_days": CareerRules().heavy_injury_days,
        "low_minutes_per_game": CareerRules().low_minutes_per_game,
        "draft_rounds": DraftRules().rounds,
        "rookie_salary": DraftRules().rookie_salary,
        "rookie_contract_years": DraftRules().rookie_contract_years,
    }
    manager_registry = release["manager_ai"]
    assert set(manager_registry) == {
        "manager_ai_version",
        "path",
        "file_sha256",
    }
    manager_path = ROOT / manager_registry["path"]
    manager_config = json.loads(manager_path.read_text(encoding="utf-8"))
    assert _sha256(manager_path) == manager_registry["file_sha256"]
    assert manager_registry["manager_ai_version"] == MANAGER_AI_VERSION
    assert manager_config == {
        "format_version": 1,
        "manager_ai_version": MANAGER_AI_VERSION,
        "default_mode": ManagerPolicyMode.SHADOW.name.lower(),
        "reasonable_band": 0.08,
        "style_contribution_limit": 0.04,
        "supported_stages": ["draft", "market"],
    }
    authority_registry = release["manager_authority"]
    assert set(authority_registry) == {
        "manager_authority_version",
        "path",
        "file_sha256",
    }
    authority_path = ROOT / authority_registry["path"]
    authority_config = json.loads(authority_path.read_text(encoding="utf-8"))
    assert _sha256(authority_path) == authority_registry["file_sha256"]
    assert authority_registry["manager_authority_version"] == MANAGER_AUTHORITY_VERSION
    assert authority_config == {
        "format_version": 1,
        "manager_authority_version": MANAGER_AUTHORITY_VERSION,
        "canonical_stages": [
            "draft",
            "free-agency",
            "trade",
            "rotation",
            "tactics",
        ],
        "default_stage_modes": {
            "draft": ManagerPolicyMode.SHADOW.name.lower(),
            "free-agency": ManagerPolicyMode.SHADOW.name.lower(),
            "trade": ManagerPolicyMode.SHADOW.name.lower(),
            "rotation": ManagerPolicyMode.ACTIVE.name.lower(),
            "tactics": ManagerPolicyMode.ACTIVE.name.lower(),
        },
        "shadow_execution_scope": "isolated-experiment-only",
        "assist_execution_requirement": "human-approval",
        "active_execution": "authorized",
        "unauthorized_execution_rejected": True,
        "canonical_execution_receipts": True,
        "automatic_activation": False,
    }
    assert tuple(ManagerDecisionStage) == (
        ManagerDecisionStage.DRAFT,
        ManagerDecisionStage.FREE_AGENCY,
        ManagerDecisionStage.TRADE,
        ManagerDecisionStage.ROTATION,
        ManagerDecisionStage.TACTICS,
    )
    objective_registry = release["manager_objectives"]
    assert set(objective_registry) == {
        "manager_objective_version",
        "path",
        "file_sha256",
    }
    objective_path = ROOT / objective_registry["path"]
    objective_config = json.loads(objective_path.read_text(encoding="utf-8"))
    assert _sha256(objective_path) == objective_registry["file_sha256"]
    assert objective_registry["manager_objective_version"] == MANAGER_OBJECTIVE_VERSION
    assert objective_config == {
        "format_version": 1,
        "manager_objective_version": MANAGER_OBJECTIVE_VERSION,
        "objectives": [
            "contend",
            "develop",
            "rebuild",
            "cap-relief",
            "balanced",
        ],
        "context_signals": [
            "current-ability",
            "potential",
            "average-age",
            "payroll-bps",
            "future-firsts",
        ],
        "annual_recomputation": True,
        "original_profile_preserved": True,
        "effective_profile_bounds": [0, 100],
        "effective_profile_consumers": [
            "draft",
            "free-agency",
            "trade",
            "rotation",
        ],
        "canonical_score_contributions": True,
        "automatic_activation": False,
    }
    assert tuple(ManagerObjective) == (
        ManagerObjective.CONTEND,
        ManagerObjective.DEVELOP,
        ManagerObjective.REBUILD,
        ManagerObjective.CAP_RELIEF,
        ManagerObjective.BALANCED,
    )
    evidence_registry = release["manager_evidence"]
    assert set(evidence_registry) == {
        "manager_evidence_version",
        "release_registry_version",
        "path",
        "file_sha256",
    }
    evidence_path = ROOT / evidence_registry["path"]
    evidence_config = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert _sha256(evidence_path) == evidence_registry["file_sha256"]
    assert evidence_registry["manager_evidence_version"] == MANAGER_EVIDENCE_VERSION
    assert evidence_registry["release_registry_version"] == MANAGER_RELEASE_REGISTRY_VERSION
    weights = ManagerEvaluationWeights()
    thresholds = ManagerEvidenceThresholds()
    assert evidence_config == {
        "format_version": 1,
        "manager_evidence_version": MANAGER_EVIDENCE_VERSION,
        "release_registry_version": MANAGER_RELEASE_REGISTRY_VERSION,
        "weights": {
            "win_rate": weights.win_rate,
            "playoff_progress": weights.playoff_progress,
            "roster_value": weights.roster_value,
            "cap_flexibility": weights.cap_flexibility,
        },
        "thresholds": {
            "minimum_independent_sources": thresholds.minimum_independent_sources,
            "minimum_seasons_per_source": thresholds.minimum_seasons_per_source,
            "minimum_mean_utility_delta": thresholds.minimum_mean_utility_delta,
            "minimum_win_rate_delta": thresholds.minimum_win_rate_delta,
            "maximum_loss_rate": thresholds.maximum_loss_rate,
            "minimum_worst_source_delta": thresholds.minimum_worst_source_delta,
            "neutral_band": thresholds.neutral_band,
        },
        "automatic_activation": False,
    }
    experiment_registry = release["manager_experiment"]
    assert set(experiment_registry) == {
        "manager_experiment_version",
        "path",
        "file_sha256",
    }
    experiment_path = ROOT / experiment_registry["path"]
    experiment_config = json.loads(experiment_path.read_text(encoding="utf-8"))
    assert _sha256(experiment_path) == experiment_registry["file_sha256"]
    assert experiment_registry["manager_experiment_version"] == MANAGER_EXPERIMENT_VERSION
    assert experiment_config == {
        "format_version": 1,
        "manager_experiment_version": MANAGER_EXPERIMENT_VERSION,
        "arms": ["incumbent", "shadow"],
        "paired_source_seed_required": True,
        "multiseason_state_continuity_required": True,
        "resumable_cells": True,
        "hash_verified_manifest": True,
        "automatic_activation": False,
    }
    adapter_registry = release["manager_league_adapter"]
    assert set(adapter_registry) == {
        "manager_league_adapter_version",
        "path",
        "file_sha256",
    }
    adapter_path = ROOT / adapter_registry["path"]
    adapter_config = json.loads(adapter_path.read_text(encoding="utf-8"))
    assert _sha256(adapter_path) == adapter_registry["file_sha256"]
    assert adapter_registry["manager_league_adapter_version"] == MANAGER_LEAGUE_ADAPTER_VERSION
    assert adapter_config == {
        "format_version": 1,
        "manager_league_adapter_version": MANAGER_LEAGUE_ADAPTER_VERSION,
        "manager_authority_engine": MANAGER_AUTHORITY_VERSION,
        "manager_authority_receipts": True,
        "manager_objective_engine": MANAGER_OBJECTIVE_VERSION,
        "manager_objective_audit": True,
        "effective_profile_stages": ["draft", "free-agency", "trade", "rotation"],
        "team_count": 4,
        "schedule": "round-robin",
        "paired_common_random_numbers": True,
        "season_engine": SEASON_VERSION,
        "playoff_engine": PLAYOFF_VERSION,
        "career_engine": CAREER_VERSION,
        "draft_engine": DRAFT_VERSION,
        "contract_engine": CONTRACT_VERSION,
        "free_agency_engine": FREE_AGENCY_VERSION,
        "prospect_engine": PROSPECT_GENERATION_VERSION,
        "scouting_engine": SCOUTING_VERSION,
        "scouting_stage": "predraft-shadow",
        "rotation_engine": MANAGER_ROTATION_VERSION,
        "regular_season_matchup_rotations": True,
        "postseason_matchup_rotations": True,
        "regular_season_matchup_tactics": True,
        "postseason_matchup_tactics": True,
        "matchup_tactical_dimensions": ["offense", "defense", "tempo"],
        "manager_learning_observation_source": "season-game-event-ledger",
        "manager_learning_outcome_feedback_audit": True,
        "postseason_state_continuity": True,
        "postseason_rest_days": 2,
        "playoff_game_rest_days": 1,
        "playoff_round_rest_days": 2,
        "postseason_career_feedback": True,
        "trade_engine": TRADE_VERSION,
        "trade_market_engine": TRADE_MARKET_VERSION,
        "three_team_market_engine": THREE_TEAM_MARKET_VERSION,
        "trade_market_stage": "preseason-shadow",
        "bilateral_negotiation_audit": True,
        "trade_clearing": "highest-combined-rational-gain",
        "bilateral_tie_preference": True,
        "cap_ledger_transaction_authority": True,
        "scaled_custom_league_aprons": True,
        "draft_asset_engine": DRAFT_ASSET_VERSION,
        "league_state_schema_version": 4,
        "legacy_state_schema_versions": [1, 2, 3],
        "advanced_state": ["cap-ledger", "manager-learning", "nba-alignment"],
        "future_pick_horizon": 3,
        "draft_lottery_engine": DRAFT_LOTTERY_VERSION,
        "draft_lottery_stage": "postseason-first-round",
        "playoff_safety_tiebreak": "derived-seed-v1",
        "automatic_activation": False,
    }
    prospect_registry = release["prospect_generation"]
    assert set(prospect_registry) == {
        "prospect_generation_version",
        "path",
        "file_sha256",
    }
    prospect_path = ROOT / prospect_registry["path"]
    prospect_config = json.loads(prospect_path.read_text(encoding="utf-8"))
    assert _sha256(prospect_path) == prospect_registry["file_sha256"]
    assert prospect_registry["prospect_generation_version"] == PROSPECT_GENERATION_VERSION
    prospect_rules = ProspectGenerationRules()
    assert prospect_config == {
        "format_version": 1,
        "prospect_generation_version": PROSPECT_GENERATION_VERSION,
        "class_size": prospect_rules.class_size,
        "minimum_age": prospect_rules.minimum_age,
        "maximum_age": prospect_rules.maximum_age,
        "minimum_ability": prospect_rules.minimum_ability,
        "maximum_ability": prospect_rules.maximum_ability,
        "minimum_potential_gain": prospect_rules.minimum_potential_gain,
        "maximum_potential_gain": prospect_rules.maximum_potential_gain,
        "player_id_base": prospect_rules.player_id_base,
        "field_level_potential": True,
        "addressed_randomness": True,
    }
    rotation_registry = release["manager_rotation"]
    assert set(rotation_registry) == {
        "manager_rotation_version",
        "path",
        "file_sha256",
    }
    rotation_path = ROOT / rotation_registry["path"]
    rotation_config = json.loads(rotation_path.read_text(encoding="utf-8"))
    assert _sha256(rotation_path) == rotation_registry["file_sha256"]
    assert rotation_registry["manager_rotation_version"] == MANAGER_ROTATION_VERSION
    rotation_rules = ManagerRotationRules()
    assert rotation_config == {
        "format_version": 1,
        "manager_rotation_version": MANAGER_ROTATION_VERSION,
        "maximum_rotation_players": rotation_rules.maximum_rotation_players,
        "segments_per_period": rotation_rules.segments_per_period,
        "reasonable_band": 0.08,
        "style_contribution_limit": 0.04,
        "clock_addressed": True,
        "emergency_substitutes_retained": True,
        "development_feedback": True,
        "opponent_model_engine": MANAGER_LEARNING_VERSION,
        "opponent_specific_adjustments": True,
        "per_game_matchup_resolution": True,
    }
    trade_registry = release["trades"]
    assert set(trade_registry) == {
        "trade_version",
        "path",
        "file_sha256",
    }
    trade_path = ROOT / trade_registry["path"]
    trade_config = json.loads(trade_path.read_text(encoding="utf-8"))
    assert _sha256(trade_path) == trade_registry["file_sha256"]
    assert trade_registry["trade_version"] == TRADE_VERSION
    trade_rules = TradeRules()
    assert trade_config == {
        "format_version": 1,
        "trade_version": TRADE_VERSION,
        "minimum_roster_players": trade_rules.minimum_roster_players,
        "salary_matching_threshold": trade_rules.salary_matching_threshold,
        "maximum_incoming_salary_bps": trade_rules.maximum_incoming_salary_bps,
        "salary_matching_buffer": trade_rules.salary_matching_buffer,
        "enforce_stepien_rule": trade_rules.enforce_stepien_rule,
        "stepien_round_number": trade_rules.stepien_round_number,
        "stepien_horizon_years": trade_rules.stepien_horizon_years,
        "conditional_firsts_are_not_guaranteed": True,
        "supported_assets": ["player", "draft-pick", "future-draft-pick"],
        "contract_conditions": True,
        "contract_follows_player": True,
        "atomic_state_transition": True,
        "cap_ledger_aware_entrypoint": True,
        "trade_exception_creation_and_consumption": True,
        "tiered_salary_matching": True,
        "replay_audit_required": True,
    }
    manager_trade_registry = release["manager_trade"]
    assert set(manager_trade_registry) == {
        "manager_trade_version",
        "path",
        "file_sha256",
    }
    manager_trade_path = ROOT / manager_trade_registry["path"]
    manager_trade_config = json.loads(manager_trade_path.read_text(encoding="utf-8"))
    assert _sha256(manager_trade_path) == manager_trade_registry["file_sha256"]
    assert manager_trade_registry["manager_trade_version"] == MANAGER_TRADE_VERSION
    manager_trade_rules = ManagerTradeRules()
    assert manager_trade_config == {
        "format_version": 1,
        "manager_trade_version": MANAGER_TRADE_VERSION,
        "trade_version": TRADE_VERSION,
        "default_mode": ManagerPolicyMode.SHADOW.name.lower(),
        "reasonable_band": manager_trade_rules.reasonable_band,
        "style_contribution_limit": manager_trade_rules.style_contribution_limit,
        "minimum_rational_gain": manager_trade_rules.minimum_rational_gain,
        "independent_bilateral_approval": True,
        "supported_participant_counts": [2, 3],
        "unanimous_multi_team_approval": True,
        "automatic_execution": False,
        "automatic_activation": False,
    }
    trade_market_registry = release["trade_market"]
    assert set(trade_market_registry) == {
        "trade_market_version",
        "path",
        "file_sha256",
    }
    trade_market_path = ROOT / trade_market_registry["path"]
    trade_market_config = json.loads(trade_market_path.read_text(encoding="utf-8"))
    assert _sha256(trade_market_path) == trade_market_registry["file_sha256"]
    assert trade_market_registry["trade_market_version"] == TRADE_MARKET_VERSION
    trade_market_rules = TradeMarketRules()
    assert trade_market_config == {
        "format_version": 1,
        "trade_market_version": TRADE_MARKET_VERSION,
        "trade_version": TRADE_VERSION,
        "manager_trade_version": MANAGER_TRADE_VERSION,
        "maximum_candidates_per_pair": trade_market_rules.maximum_candidates_per_pair,
        "maximum_trades_per_team": trade_market_rules.maximum_trades_per_team,
        "minimum_combined_rational_gain": trade_market_rules.minimum_combined_rational_gain,
        "generate_pick_counteroffers": trade_market_rules.generate_pick_counteroffers,
        "generate_player_for_pick_offers": trade_market_rules.generate_player_for_pick_offers,
        "generate_two_for_one_offers": trade_market_rules.generate_two_for_one_offers,
        "maximum_negotiation_rounds": trade_market_rules.maximum_negotiation_rounds,
        "maximum_round_three_candidates": trade_market_rules.maximum_round_three_candidates,
        "generate_round_three_counteroffers": (
            trade_market_rules.generate_round_three_counteroffers
        ),
        "maximum_supported_negotiation_rounds": MAXIMUM_SUPPORTED_NEGOTIATION_ROUNDS,
        "maximum_contract_condition_candidates": (
            trade_market_rules.maximum_contract_condition_candidates
        ),
        "generate_contract_condition_counteroffers": (
            trade_market_rules.generate_contract_condition_counteroffers
        ),
        "round_three_compensation": "additional-owned-pick",
        "late_round_compensation": "binding-contract-condition",
        "negotiation_terminal_reasons": ["accepted", "round-limit", "no-counter"],
        "canonical_negotiation_summaries": True,
        "candidate_kind_mixing": True,
        "stable_candidate_order": True,
        "team_and_asset_locking": True,
        "sequential_cap_ledger_clearing": True,
        "default_mode": ManagerPolicyMode.SHADOW.name.lower(),
        "automatic_activation": False,
    }
    draft_asset_registry = release["draft_assets"]
    assert set(draft_asset_registry) == {
        "draft_asset_version",
        "path",
        "file_sha256",
    }
    draft_asset_path = ROOT / draft_asset_registry["path"]
    draft_asset_config = json.loads(draft_asset_path.read_text(encoding="utf-8"))
    assert _sha256(draft_asset_path) == draft_asset_registry["file_sha256"]
    assert draft_asset_registry["draft_asset_version"] == DRAFT_ASSET_VERSION
    assert draft_asset_config == {
        "format_version": 1,
        "draft_asset_version": DRAFT_ASSET_VERSION,
        "schema_version": DRAFT_ASSET_SCHEMA_VERSION,
        "league_state_schema_version": 4,
        "legacy_schema_versions": [1],
        "future_year_horizon": 7,
        "supported_protection": "ordered-selection-ranges",
        "condition_outcomes": ["defer", "convert", "retain"],
        "protection_rollover": True,
        "round_conversion": True,
        "supported_swap": "one-way-better-slot",
        "stable_asset_identity": True,
        "original_team_identity_immutable": True,
        "owner_team_transferable": True,
    }
    lottery_registry = release["draft_lottery"]
    assert set(lottery_registry) == {
        "draft_lottery_version",
        "path",
        "file_sha256",
    }
    lottery_path = ROOT / lottery_registry["path"]
    lottery_config = json.loads(lottery_path.read_text(encoding="utf-8"))
    assert _sha256(lottery_path) == lottery_registry["file_sha256"]
    assert lottery_registry["draft_lottery_version"] == DRAFT_LOTTERY_VERSION
    lottery_rules = DraftLotteryRules()
    assert lottery_config == {
        "format_version": 1,
        "draft_lottery_version": DRAFT_LOTTERY_VERSION,
        "drawn_slots": lottery_rules.drawn_slots,
        "weight_bps": list(lottery_rules.weight_bps),
        "draw_without_replacement": True,
        "addressed_randomness": True,
        "first_round_only": True,
        "complete_draw_ledger": True,
    }
    nba_lottery_registry = release["nba_draft_lottery"]
    assert set(nba_lottery_registry) == {
        "nba_draft_lottery_version",
        "path",
        "file_sha256",
    }
    nba_lottery_path = ROOT / nba_lottery_registry["path"]
    nba_lottery_config = json.loads(nba_lottery_path.read_text(encoding="utf-8"))
    assert _sha256(nba_lottery_path) == nba_lottery_registry["file_sha256"]
    assert nba_lottery_registry["nba_draft_lottery_version"] == NBA_DRAFT_LOTTERY_VERSION
    assert nba_lottery_config == {
        "format_version": 1,
        "nba_draft_lottery_version": NBA_DRAFT_LOTTERY_VERSION,
        "base_lottery_version": DRAFT_LOTTERY_VERSION,
        "lottery_teams": 14,
        "playoff_teams": 16,
        "drawn_slots": NBA_DRAFT_LOTTERY_RULES.drawn_slots,
        "weight_bps": list(NBA_DRAFT_LOTTERY_RULES.weight_bps),
        "draw_without_replacement": True,
        "complete_thirty_team_order": True,
        "non_playoff_order_source": "reverse-regular-season-standing",
        "playoff_order_primary": "elimination-round",
        "playoff_order_tiebreak": "reverse-regular-season-standing",
        "champion_final_pick": True,
        "addressed_randomness": True,
    }
    nba_asset_registry = release["nba_draft_asset_settlement"]
    assert set(nba_asset_registry) == {
        "nba_draft_asset_settlement_version",
        "path",
        "file_sha256",
    }
    nba_asset_path = ROOT / nba_asset_registry["path"]
    nba_asset_config = json.loads(nba_asset_path.read_text(encoding="utf-8"))
    assert _sha256(nba_asset_path) == nba_asset_registry["file_sha256"]
    assert (
        nba_asset_registry["nba_draft_asset_settlement_version"]
        == NBA_DRAFT_ASSET_SETTLEMENT_VERSION
    )
    assert nba_asset_config == {
        "format_version": 1,
        "nba_draft_asset_settlement_version": NBA_DRAFT_ASSET_SETTLEMENT_VERSION,
        "nba_draft_lottery_version": NBA_DRAFT_LOTTERY_VERSION,
        "draft_asset_version": DRAFT_ASSET_VERSION,
        "first_round_order": "nba-lottery-final-order",
        "later_round_order": "pre-lottery-worst-to-best",
        "top_n_protection_uses_final_lottery_slot": True,
        "protected_pick_rollover": True,
        "swap_uses_final_round_slot": True,
        "ownership_preserved": True,
        "native_team_identity_preserved": True,
        "atomic_settlement": True,
        "complete_thirty_team_first_round": True,
    }
    nba_draft_registry = release["nba_draft_offseason"]
    assert set(nba_draft_registry) == {
        "nba_draft_offseason_version",
        "path",
        "file_sha256",
    }
    nba_draft_path = ROOT / nba_draft_registry["path"]
    nba_draft_config = json.loads(nba_draft_path.read_text(encoding="utf-8"))
    assert _sha256(nba_draft_path) == nba_draft_registry["file_sha256"]
    assert nba_draft_registry["nba_draft_offseason_version"] == NBA_DRAFT_OFFSEASON_VERSION
    assert nba_draft_config == {
        "format_version": 1,
        "nba_draft_offseason_version": NBA_DRAFT_OFFSEASON_VERSION,
        "nba_draft_asset_settlement_version": NBA_DRAFT_ASSET_SETTLEMENT_VERSION,
        "manager_ai_version": MANAGER_AI_VERSION,
        "scouting_version": SCOUTING_VERSION,
        "draft_version": DRAFT_VERSION,
        "team_count": 30,
        "required_first_round_picks": 30,
        "one_manager_profile_per_team": True,
        "one_scouting_report_per_team_prospect": True,
        "true_potential_hidden_from_manager": True,
        "white_box_candidate_contributions": True,
        "pick_owner_controls_selection": True,
        "unique_prospect_selection": True,
        "roster_limit_enforced": True,
        "payroll_limit_enforced": True,
        "rookie_contract_created": True,
        "career_draft_metadata_written": True,
        "execution_authority": "explicit-active-entrypoint",
        "atomic_draft_execution": True,
    }
    nba_offseason_registry = release["nba_offseason"]
    assert set(nba_offseason_registry) == {
        "nba_offseason_version",
        "path",
        "file_sha256",
    }
    nba_offseason_path = ROOT / nba_offseason_registry["path"]
    nba_offseason_config = json.loads(nba_offseason_path.read_text(encoding="utf-8"))
    assert _sha256(nba_offseason_path) == nba_offseason_registry["file_sha256"]
    assert nba_offseason_registry["nba_offseason_version"] == NBA_OFFSEASON_VERSION
    assert nba_offseason_config == {
        "format_version": 1,
        "nba_offseason_version": NBA_OFFSEASON_VERSION,
        "career_version": CAREER_VERSION,
        "retirement_version": RETIREMENT_VERSION,
        "contract_version": CONTRACT_VERSION,
        "nba_draft_offseason_version": NBA_DRAFT_OFFSEASON_VERSION,
        "free_agency_version": FREE_AGENCY_VERSION,
        "draft_asset_version": DRAFT_ASSET_VERSION,
        "team_count": 30,
        "stage_order": [
            "career-development-retirement",
            "contract-expiration",
            "scouting",
            "manager-draft",
            "manager-free-agency",
            "future-pick-reseed",
        ],
        "white_box_draft_plan": True,
        "white_box_market_plan": True,
        "draft_plan_execution_match": True,
        "market_plan_execution_match": True,
        "default_future_pick_horizon": 3,
        "expired_picks_rejected": True,
        "deterministic_replay": True,
        "atomic_offseason_result": True,
    }
    three_team_registry = release["three_team_trades"]
    assert set(three_team_registry) == {
        "three_team_trade_version",
        "path",
        "file_sha256",
    }
    three_team_path = ROOT / three_team_registry["path"]
    three_team_config = json.loads(three_team_path.read_text(encoding="utf-8"))
    assert _sha256(three_team_path) == three_team_registry["file_sha256"]
    assert three_team_registry["three_team_trade_version"] == THREE_TEAM_TRADE_VERSION
    assert three_team_config == {
        "format_version": 1,
        "three_team_trade_version": THREE_TEAM_TRADE_VERSION,
        "trade_version": TRADE_VERSION,
        "manager_trade_version": MANAGER_TRADE_VERSION,
        "participant_count": 3,
        "explicit_asset_routes": True,
        "supported_assets": ["player", "draft-pick", "future-draft-pick"],
        "every_team_sends_and_receives": True,
        "unanimous_manager_approval": True,
        "atomic_state_transition": True,
        "cap_ledger_aware_entrypoint": True,
        "tiered_salary_matching": True,
        "replay_audit_required": True,
        "automatic_market_generation": False,
    }
    three_team_market_registry = release["three_team_market"]
    assert set(three_team_market_registry) == {
        "three_team_market_version",
        "path",
        "file_sha256",
    }
    three_team_market_path = ROOT / three_team_market_registry["path"]
    three_team_market_config = json.loads(three_team_market_path.read_text(encoding="utf-8"))
    assert _sha256(three_team_market_path) == three_team_market_registry["file_sha256"]
    assert three_team_market_registry["three_team_market_version"] == THREE_TEAM_MARKET_VERSION
    three_team_market_rules = ThreeTeamMarketRules()
    assert three_team_market_config == {
        "format_version": 1,
        "three_team_market_version": THREE_TEAM_MARKET_VERSION,
        "three_team_trade_version": THREE_TEAM_TRADE_VERSION,
        "maximum_candidates_per_trio": (three_team_market_rules.maximum_candidates_per_trio),
        "maximum_cyclic_candidates_per_trio": (
            three_team_market_rules.maximum_cyclic_candidates_per_trio
        ),
        "maximum_hub_candidates_per_trio": (
            three_team_market_rules.maximum_hub_candidates_per_trio
        ),
        "minimum_combined_rational_gain": (three_team_market_rules.minimum_combined_rational_gain),
        "search_pick_compensation": three_team_market_rules.search_pick_compensation,
        "maximum_compensation_picks": three_team_market_rules.maximum_compensation_picks,
        "maximum_negotiation_rounds": 2,
        "cyclic_orientations": 2,
        "hub_team_round_robin": True,
        "salary_aware_hub_ordering": three_team_market_rules.salary_aware_hub_ordering,
        "salary_imbalance_metric": "sum-absolute-net-player-salary",
        "salary_imbalance_tiebreak": True,
        "candidate_kinds": [
            "cyclic",
            "hub",
            "pick-compensation",
            "multi-pick-compensation",
        ],
        "stable_candidate_order": True,
        "team_locking": True,
        "sequential_cap_ledger_clearing": True,
        "unified_bilateral_comparison": True,
        "default_mode": ManagerPolicyMode.SHADOW.name.lower(),
        "automatic_activation": False,
    }
    scouting_registry = release["scouting"]
    scouting_path = ROOT / scouting_registry["path"]
    scouting_config = json.loads(scouting_path.read_text(encoding="utf-8"))
    scouting_rules = ScoutingRules()
    assert _sha256(scouting_path) == scouting_registry["file_sha256"]
    assert scouting_registry["scouting_version"] == SCOUTING_VERSION
    assert scouting_config == {
        "format_version": 1,
        "scouting_version": SCOUTING_VERSION,
        "base_uncertainty": scouting_rules.base_uncertainty,
        "minimum_uncertainty": scouting_rules.minimum_uncertainty,
        "uncertainty_reduction_per_exposure": (scouting_rules.uncertainty_reduction_per_exposure),
        "maximum_exposures": scouting_rules.maximum_exposures,
        "team_specific_reports": True,
        "field_level_potential_estimates": True,
        "true_potential_hidden_from_manager": True,
        "addressed_randomness": True,
    }
    cap_registry = release["cap_mechanics"]
    cap_path = ROOT / cap_registry["path"]
    cap_config = json.loads(cap_path.read_text(encoding="utf-8"))
    cap_rules = CapMechanicsRules()
    assert _sha256(cap_path) == cap_registry["file_sha256"]
    assert cap_registry["cap_mechanics_version"] == CAP_MECHANICS_VERSION
    assert cap_config == {
        "format_version": 1,
        "cap_mechanics_version": CAP_MECHANICS_VERSION,
        "draft_asset_version": DRAFT_ASSET_VERSION,
        "salary_cap": cap_rules.salary_cap,
        "first_apron": cap_rules.first_apron,
        "second_apron": cap_rules.second_apron,
        "bird_rights_levels": ["non-bird", "early-bird", "full-bird"],
        "small_outgoing_threshold": cap_rules.small_outgoing_threshold,
        "medium_outgoing_threshold": cap_rules.medium_outgoing_threshold,
        "matching_buffer": cap_rules.matching_buffer,
        "medium_matching_allowance": cap_rules.medium_matching_allowance,
        "exception_buffer": cap_rules.exception_buffer,
        "exception_lifetime_years": cap_rules.exception_lifetime_years,
        "exception_aggregation": False,
        "atomic_exception_ledger": True,
        "canonical_transaction_activation": True,
        "scaled_aprons_for_custom_leagues": True,
        "league_state_persistence": True,
        "season_expiry_transition": True,
    }
    nba_registry = release["nba_league"]
    nba_path = ROOT / nba_registry["path"]
    nba_config = json.loads(nba_path.read_text(encoding="utf-8"))
    nba_rules = NBARegularSeasonRules()
    assert _sha256(nba_path) == nba_registry["file_sha256"]
    assert nba_registry["nba_league_version"] == NBA_LEAGUE_VERSION
    assert nba_config == {
        "format_version": 1,
        "nba_league_version": NBA_LEAGUE_VERSION,
        "team_count": nba_rules.team_count,
        "games_per_team": nba_rules.games_per_team,
        "regular_season_games": 1230,
        "conferences": 2,
        "divisions_per_conference": 3,
        "teams_per_division": 5,
        "division_opponent_games": 4,
        "conference_four_game_opponents": 6,
        "conference_three_game_opponents": 4,
        "interconference_opponent_games": 2,
        "home_games_per_team": 41,
        "same_day_team_conflicts": False,
        "play_in_seeds": [7, 8, 9, 10],
        "playoff_teams": 16,
        "playoff_series": 15,
        "series_best_of": 7,
        "deterministic_schedule": True,
        "explicit_division_persistence": True,
        "legacy_conference_alignment_migration": True,
        "conference_alignment_persistence": True,
        "derived_bracket_validation": True,
    }
    learning_registry = release["manager_learning"]
    learning_path = ROOT / learning_registry["path"]
    learning_config = json.loads(learning_path.read_text(encoding="utf-8"))
    assert _sha256(learning_path) == learning_registry["file_sha256"]
    assert learning_registry["manager_learning_version"] == MANAGER_LEARNING_VERSION
    assert learning_config == {
        "format_version": 1,
        "manager_learning_version": MANAGER_LEARNING_VERSION,
        "cross_season_memory": True,
        "observation_weight": "games-observed",
        "observation_source": "canonical-game-event-ledger",
        "strength_normalization": "points-per-100-possessions",
        "pace_normalization": "clock-config-neutral-possessions",
        "shot_profile_source": "shot-segment-zone",
        "empty_shot_profile_fallback": 50,
        "tracked_opponent_dimensions": [
            "offense-strength",
            "defense-strength",
            "pace",
            "three-point-rate",
            "rim-rate",
        ],
        "maximum_adjustment_bps": 2500,
        "rotation_integration": True,
        "tactical_integration": [
            "play-family-logit-bias",
            "coverage-logit-bias",
            "tempo",
        ],
        "tactical_confidence_full_games": 8,
        "maximum_tactical_logit_bias": 0.75,
        "maximum_tempo_delta": 15,
        "tactical_outcome_signal": "matchup-net-rating",
        "tactical_outcome_causal_claim": False,
        "minimum_response_multiplier_bps": 7500,
        "maximum_response_multiplier_bps": 12500,
        "style_direction_separate_from_outcome_intensity": True,
        "regular_season_tactics": True,
        "postseason_tactics": True,
        "white_box_contributions": True,
        "league_state_persistence": True,
        "automatic_season_observations": True,
        "automatic_activation": False,
    }
    quick_sim_registry = release["quick_sim_comparison"]
    assert set(quick_sim_registry) == {
        "quick_sim_comparison_version",
        "path",
        "file_sha256",
    }
    quick_sim_path = ROOT / quick_sim_registry["path"]
    quick_sim_config = json.loads(quick_sim_path.read_text(encoding="utf-8"))
    assert _sha256(quick_sim_path) == quick_sim_registry["file_sha256"]
    assert quick_sim_registry["quick_sim_comparison_version"] == QUICK_SIM_COMPARISON_VERSION
    assert quick_sim_config == {
        "format_version": 1,
        "quick_sim_comparison_version": QUICK_SIM_COMPARISON_VERSION,
        "default_team_count": 30,
        "canonical_metrics": list(QUICK_SIM_METRICS),
        "multi_season_aggregation": "arithmetic-mean",
        "season_source": "canonical-season-ledger",
        "postseason_source": "canonical-playoff-ledger",
        "observed_reference_required": True,
        "observed_reference_builder": True,
        "observed_reference_range_method": "observed-min-max",
        "incomplete_template_rejected_for_scoring": True,
        "fabricated_2k_targets": False,
        "strict_reference_json": True,
        "canonical_reference_json": True,
        "canonical_report_json": True,
    }
    quick_sim_batch_registry = release["quick_sim_batch"]
    assert set(quick_sim_batch_registry) == {
        "quick_sim_batch_version",
        "path",
        "file_sha256",
    }
    quick_sim_batch_path = ROOT / quick_sim_batch_registry["path"]
    quick_sim_batch_config = json.loads(quick_sim_batch_path.read_text(encoding="utf-8"))
    assert _sha256(quick_sim_batch_path) == quick_sim_batch_registry["file_sha256"]
    assert quick_sim_batch_registry["quick_sim_batch_version"] == QUICK_SIM_BATCH_VERSION
    assert quick_sim_batch_config == {
        "format_version": 1,
        "quick_sim_batch_version": QUICK_SIM_BATCH_VERSION,
        "quick_sim_comparison_version": QUICK_SIM_COMPARISON_VERSION,
        "default_team_count": 30,
        "maximum_seasons": 10_000,
        "deterministic_season_seeds": True,
        "resumable_contiguous_checkpoints": True,
        "strict_checkpoint_json": True,
        "summary_sha256": True,
        "batch_sha256": True,
        "observed_reference_builder": True,
        "reference_range_method": "observed-min-max",
    }
    quick_sim_artifact_registry = release["quick_sim_artifact"]
    assert set(quick_sim_artifact_registry) == {
        "quick_sim_artifact_version",
        "path",
        "file_sha256",
    }
    quick_sim_artifact_path = ROOT / quick_sim_artifact_registry["path"]
    quick_sim_artifact_config = json.loads(quick_sim_artifact_path.read_text(encoding="utf-8"))
    assert _sha256(quick_sim_artifact_path) == quick_sim_artifact_registry["file_sha256"]
    assert quick_sim_artifact_registry["quick_sim_artifact_version"] == QUICK_SIM_ARTIFACT_VERSION
    assert quick_sim_artifact_config == {
        "format_version": 1,
        "quick_sim_artifact_version": QUICK_SIM_ARTIFACT_VERSION,
        "quick_sim_batch_version": QUICK_SIM_BATCH_VERSION,
        "quick_sim_comparison_version": QUICK_SIM_COMPARISON_VERSION,
        "checkpoint_write": "atomic-after-every-season",
        "resume_mode": "verified-contiguous-prefix",
        "completed_cells_reexecuted": False,
        "single_writer_required": True,
        "canonical_checkpoint_json": True,
        "canonical_reference_json": True,
        "checkpoint_file_sha256_receipt": True,
        "reference_file_sha256_receipt": True,
        "complete_batch_required_for_reference": True,
    }
    nba_quick_sim_registry = release["nba_quick_sim_executor"]
    assert set(nba_quick_sim_registry) == {
        "nba_quick_sim_executor_version",
        "path",
        "file_sha256",
    }
    nba_quick_sim_path = ROOT / nba_quick_sim_registry["path"]
    nba_quick_sim_config = json.loads(nba_quick_sim_path.read_text(encoding="utf-8"))
    assert _sha256(nba_quick_sim_path) == nba_quick_sim_registry["file_sha256"]
    assert (
        nba_quick_sim_registry["nba_quick_sim_executor_version"] == NBA_QUICK_SIM_EXECUTOR_VERSION
    )
    assert nba_quick_sim_config == {
        "format_version": 1,
        "nba_quick_sim_executor_version": NBA_QUICK_SIM_EXECUTOR_VERSION,
        "quick_sim_comparison_version": QUICK_SIM_COMPARISON_VERSION,
        "nba_league_version": NBA_LEAGUE_VERSION,
        "career_version": CAREER_VERSION,
        "manager_learning_version": MANAGER_LEARNING_VERSION,
        "team_count": 30,
        "regular_season_games": 1_230,
        "games_per_team": 82,
        "play_in_games_per_conference": 3,
        "playoff_teams": 16,
        "playoff_series": 15,
        "series_best_of": 7,
        "regular_season_engine": "canonical-season-state-machine",
        "game_engine": "canonical-possession-runtime",
        "default_trace_mode": "aggregate-only",
        "conference_seed_order": [
            "wins-plus-half-ties",
            "point-differential",
            "team-id",
        ],
        "postseason_decisive_retry_limit": 100,
        "deterministic_addressed_randomness": True,
        "league_unique_player_ids": True,
        "postseason_fatigue_continuity": True,
        "postseason_injury_continuity": True,
        "postseason_new_injuries": True,
        "default_postseason_rest_days": 2,
        "default_game_rest_days": 1,
        "default_round_rest_days": 2,
        "play_in_conferences_start_concurrently": True,
        "play_in_openers_start_concurrently": True,
        "same_round_series_start_concurrently": True,
        "next_round_waits_for_latest_feeder_series": True,
        "postseason_games_chronologically_serialized": True,
        "postseason_game_availability_ledger": True,
        "postseason_initial_final_state_audit": True,
        "postseason_player_seconds": True,
        "postseason_player_games": True,
        "postseason_team_games": True,
        "career_summary_regular_and_postseason": True,
        "deterministic_forfeit_resolution": True,
        "opponent_specific_matchup_teams": True,
        "maximum_directed_matchup_teams": 870,
        "matchup_roster_identity_required": True,
        "regular_season_matchup_resolution": True,
        "postseason_matchup_resolution": True,
        "matchup_team_count_audit": True,
        "postseason_learning_totals": True,
        "directed_learning_totals_per_game": 2,
        "learning_score_totals": True,
        "learning_possession_totals": True,
        "learning_shot_zone_totals": True,
        "forfeit_learning_totals": True,
        "promotion_full_engine_seasons": 30,
        "promotion_reality_gate_id": "nba-full-engine-strength035-reality-long-v1",
        "promotion_consistency_gate_id": ("full-season-engine-consistency-strength035-long-v1"),
        "promotion_receipt_path": "experiments/promotion/nba-quick-sim-executor-v6.json",
        "promotion_receipt_sha256": (
            "cadafaadabe474d4d20747cc33d6fb920eacc55069127d5985e02317d552c962"
        ),
    }
    promotion_receipt_path = ROOT / nba_quick_sim_config["promotion_receipt_path"]
    assert _sha256(promotion_receipt_path) == nba_quick_sim_config["promotion_receipt_sha256"]
    promotion_receipt = json.loads(promotion_receipt_path.read_text(encoding="utf-8"))
    assert promotion_receipt["candidate_id"] == NBA_QUICK_SIM_EXECUTOR_VERSION
    assert promotion_receipt["promotion_ready"] is True
    assert promotion_receipt["reality_gate"]["passed"] is True
    assert promotion_receipt["consistency_gate"]["passed"] is True
    nba_franchise_registry = release["nba_franchise"]
    assert set(nba_franchise_registry) == {
        "nba_franchise_version",
        "path",
        "file_sha256",
    }
    nba_franchise_path = ROOT / nba_franchise_registry["path"]
    nba_franchise_config = json.loads(nba_franchise_path.read_text(encoding="utf-8"))
    assert _sha256(nba_franchise_path) == nba_franchise_registry["file_sha256"]
    assert nba_franchise_registry["nba_franchise_version"] == NBA_FRANCHISE_VERSION
    assert nba_franchise_config == {
        "format_version": 1,
        "nba_franchise_version": NBA_FRANCHISE_VERSION,
        "nba_quick_sim_executor_version": NBA_QUICK_SIM_EXECUTOR_VERSION,
        "nba_draft_lottery_version": NBA_DRAFT_LOTTERY_VERSION,
        "nba_draft_asset_settlement_version": NBA_DRAFT_ASSET_SETTLEMENT_VERSION,
        "nba_offseason_version": NBA_OFFSEASON_VERSION,
        "prospect_generation_version": PROSPECT_GENERATION_VERSION,
        "manager_rotation_version": MANAGER_ROTATION_VERSION,
        "manager_learning_version": MANAGER_LEARNING_VERSION,
        "trade_market_version": TRADE_MARKET_VERSION,
        "three_team_market_version": THREE_TEAM_MARKET_VERSION,
        "cap_mechanics_version": CAP_MECHANICS_VERSION,
        "draft_asset_version": DRAFT_ASSET_VERSION,
        "team_count": 30,
        "stage_order": [
            "cap-ledger-expiry",
            "seven-year-draft-asset-seeding",
            "bilateral-trade-market-evaluation",
            "three-team-trade-market-evaluation",
            "trade-market-clearing",
            "rotation-rebuild",
            "matchup-team-build",
            "regular-season",
            "play-in",
            "playoffs",
            "manager-learning-update",
            "career-summary",
            "lottery",
            "draft-asset-settlement",
            "offseason",
            "rotation-rebuild",
        ],
        "annual_prospect_class_size": 30,
        "management_year_increment": 1,
        "completed_seasons_increment": 1,
        "opponents_per_manager": 29,
        "maximum_directed_matchup_teams": 870,
        "first_season_base_matchups": True,
        "regular_season_event_learning": True,
        "postseason_event_learning": True,
        "directed_regular_season_game_samples": 2_460,
        "directed_postseason_samples_per_game": 2,
        "exact_learning_sample_accounting": True,
        "regular_and_postseason_tactic_application": True,
        "manager_change_resets_team_memory": True,
        "roster_identity_rebuilt_from_management": True,
        "deterministic_addressed_randomness": True,
        "composable_next_season_state": True,
        "persistent_manager_learning_integration": True,
        "opponent_specific_rotation_rebuild": True,
        "bilateral_market_evaluated_each_season": True,
        "three_team_market_evaluated_each_season": True,
        "exclusive_gain_based_trade_clearing": True,
        "cap_aware_trade_evaluation": True,
        "complete_seven_year_stepien_enforcement": True,
        "conditional_pick_settlement": True,
        "post_trade_roster_rebuild_before_games": True,
        "draft_assets_updated_by_trades": True,
        "cap_ledger_persisted_across_seasons": True,
        "trade_exceptions_expire_by_season": True,
        "postseason_schedule": "concurrent-round-v1",
        "disk_resume": True,
    }
    nba_franchise_artifact_registry = release["nba_franchise_artifact"]
    assert set(nba_franchise_artifact_registry) == {
        "nba_franchise_artifact_version",
        "path",
        "file_sha256",
    }
    nba_franchise_artifact_path = ROOT / nba_franchise_artifact_registry["path"]
    nba_franchise_artifact_config = json.loads(
        nba_franchise_artifact_path.read_text(encoding="utf-8")
    )
    assert _sha256(nba_franchise_artifact_path) == nba_franchise_artifact_registry["file_sha256"]
    assert (
        nba_franchise_artifact_registry["nba_franchise_artifact_version"]
        == NBA_FRANCHISE_ARTIFACT_VERSION
    )
    assert nba_franchise_artifact_config == {
        "format_version": 1,
        "nba_franchise_artifact_version": NBA_FRANCHISE_ARTIFACT_VERSION,
        "nba_franchise_version": NBA_FRANCHISE_VERSION,
        "manager_league_state_schema": 4,
        "franchise_state_schema": 2,
        "legacy_franchise_state_schemas": [1],
        "legacy_franchise_versions": [
            "nba-franchise-v3",
            "nba-franchise-v4",
            "nba-franchise-v5",
        ],
        "checkpoint_envelope_schema": 2,
        "legacy_checkpoint_envelope_schemas": [1],
        "legacy_artifact_versions": [
            "nba-franchise-artifact-v1",
            "nba-franchise-artifact-v2",
            "nba-franchise-artifact-v3",
        ],
        "compression": ["none", "gzip"],
        "deterministic_gzip_mtime": 0,
        "canonical_state_json": True,
        "strict_state_keys": True,
        "atomic_checkpoint_write": True,
        "embedded_state_sha256": True,
        "checkpoint_file_sha256_receipt": True,
        "expected_file_sha256_verification": True,
        "corrupted_state_rejected": True,
        "legacy_version_migration": True,
        "unsupported_version_rejected": True,
        "contract_rules_persisted": True,
        "management_persisted": True,
        "career_players_persisted": True,
        "draft_assets_persisted": True,
        "cap_ledger_persisted": True,
        "manager_learning_persisted": True,
        "conference_alignment_persisted": True,
        "game_team_profiles_persisted": True,
        "team_strategies_persisted": True,
        "rotation_plans_persisted": True,
        "exact_round_trip": True,
        "next_season_resume": True,
    }
    nba_franchise_runner_registry = release["nba_franchise_runner"]
    assert set(nba_franchise_runner_registry) == {
        "nba_franchise_runner_version",
        "path",
        "file_sha256",
    }
    nba_franchise_runner_path = ROOT / nba_franchise_runner_registry["path"]
    nba_franchise_runner_config = json.loads(nba_franchise_runner_path.read_text(encoding="utf-8"))
    assert _sha256(nba_franchise_runner_path) == nba_franchise_runner_registry["file_sha256"]
    assert nba_franchise_runner_registry["nba_franchise_runner_version"] == (
        "nba-franchise-runner-v4"
    )
    assert nba_franchise_runner_config == {
        "format_version": 1,
        "nba_franchise_runner_version": "nba-franchise-runner-v4",
        "nba_franchise_artifact_version": NBA_FRANCHISE_ARTIFACT_VERSION,
        "nba_franchise_version": NBA_FRANCHISE_VERSION,
        "manifest_schema": 2,
        "legacy_manifest_schemas": [1, 2],
        "legacy_runner_versions": [
            "nba-franchise-runner-v2",
            "nba-franchise-runner-v3",
        ],
        "deterministic_season_seeds": True,
        "per_checkpoint_seed_version": True,
        "seed_address_fields": [
            "master-seed",
            "runner-version",
            "run-id",
            "completed-season-number",
        ],
        "initial_state_checkpoint": True,
        "checkpoint_after_every_season": True,
        "atomic_state_before_manifest": True,
        "verified_contiguous_metadata_prefix": True,
        "retained_file_hashes_verified": True,
        "retained_state_hashes_verified": True,
        "retention_keep_last": True,
        "retention_keep_every": True,
        "retention_preserves_initial": True,
        "retention_preserves_latest": True,
        "older_checkpoint_gzip": True,
        "pruned_checkpoint_metadata_retained": True,
        "contract_rules_verified": True,
        "league_identity_verified": True,
        "cap_ledger_continuity_required": True,
        "execution_state_continuity_required": True,
        "completed_seasons_reexecuted": False,
        "bounded_new_seasons_per_call": True,
        "orphan_checkpoint_safe": True,
        "complete_run_noop": True,
        "manifest_sha256_receipt": True,
    }

    model = release["model"]
    schema_path = ROOT / model["schema_path"]
    parameter_path = ROOT / model["parameter_path"]
    assert Path(model["schema_path"]) == DEFAULT_MODEL_SCHEMA
    assert Path(model["parameter_path"]) == DEFAULT_MODEL_PARAMETERS
    assert _sha256(schema_path) == model["schema_file_sha256"]
    assert _sha256(parameter_path) == model["parameter_file_sha256"]

    parameters = load_model_parameters(schema_path, parameter_path)
    assert parameters.schema.schema_version == model["schema_version"]
    assert parameters.schema.schema_hash == model["schema_hash"]
    assert parameters.payload["metadata"]["parameter_version"] == model["parameter_version"]
    assert parameters.parameter_hash == model["parameter_hash"]

    audit_registry = release["audit"]
    baseline_path = ROOT / audit_registry["baseline_path"]
    experiment_path = ROOT / audit_registry["experiment_path"]
    gates_path = ROOT / audit_registry["regression_gates_path"]
    experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
    baseline = load_distribution_audit(baseline_path)
    assert _sha256(baseline_path) == audit_registry["baseline_sha256"]
    assert experiment["acceptance"]["audit_sha256"] == audit_registry["baseline_sha256"]
    assert baseline.completed_games == audit_registry["games"]
    assert experiment["master_seed"] == audit_registry["master_seed"]

    kind, gates = load_audit_gates(gates_path)
    gate_report = evaluate_audit_gates(baseline, kind, gates)
    assert gate_report.passed
    assert len(gate_report.findings) == 0
    assert len(gates) == audit_registry["regression_gates_passed"]

    metrics_evaluated = 0
    for target_name in audit_registry["realism_targets"]:
        targets = load_realism_target_set(ROOT / target_name)
        score = score_audit_against_realism_targets(baseline, targets)
        assert score.gate_passed
        metrics_evaluated += score.metrics_evaluated
    assert metrics_evaluated == audit_registry["realism_metrics_passed"]
