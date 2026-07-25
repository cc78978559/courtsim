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
from courtsim.parameters import load_model_parameters
from courtsim.rotations import FATIGUE_VERSION, ROTATION_VERSION, FatigueConfig
from courtsim.rules import GameRules

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
        "model",
        "audit",
        "promotion",
    }
    assert release["format_version"] == 3
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
