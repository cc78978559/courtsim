import hashlib
import json
from pathlib import Path

from courtsim import __version__
from courtsim.analysis import (
    evaluate_audit_gates,
    load_audit_gates,
    load_distribution_audit,
)
from courtsim.analysis.realism_targets import (
    load_realism_target_set,
    score_audit_against_realism_targets,
)
from courtsim.cli import DEFAULT_MODEL_PARAMETERS, DEFAULT_MODEL_SCHEMA
from courtsim.management import (
    CONTRACT_VERSION,
    FREE_AGENCY_VERSION,
    MANAGEMENT_SCHEMA_VERSION,
    ContractRules,
)
from courtsim.parameters import load_model_parameters
from courtsim.rosters import ROSTER_VERSION, RosterRules
from courtsim.rotations import FATIGUE_VERSION, ROTATION_VERSION, FatigueConfig
from courtsim.rules import GameRules
from courtsim.season import (
    INJURY_VERSION,
    SEASON_SCHEMA_VERSION,
    SEASON_VERSION,
    SeasonConfig,
)

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
        "model",
        "audit",
        "promotion",
    }
    assert release["format_version"] == 6
    assert release["status"] == "frozen"
    assert release["engine_version"] == __version__
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
    }
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
