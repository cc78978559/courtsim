import json
from dataclasses import asdict, replace
from pathlib import Path

import pytest
from test_phase48_nba_franchise import _state

from courtsim.artifacts import write_json
from courtsim.domain.game import GameClockConfig
from courtsim.manager_ai import ManagerProfile
from courtsim.model.trace_mode import TraceMode
from courtsim.nba_franchise_artifacts import write_nba_franchise_checkpoint
from courtsim.nba_manager_adapter import (
    NBA_MANAGER_ADAPTER_VERSION,
    MacroMetricRange,
)
from courtsim.nba_manager_experiment import (
    NBAManagerExperimentArm,
    NBAManagerSeasonRequest,
)
from courtsim.nba_manager_study import (
    NBA_MANAGER_PROFILE_SET_VERSION,
    NBAManagerStudyError,
    build_nba_manager_study_bundle,
)


def _inputs(tmp_path: Path, *, eligible: bool = True) -> tuple[Path, Path, Path]:
    state, profiles, rules = _state()
    checkpoint = tmp_path / "initial.json"
    write_nba_franchise_checkpoint(state, rules, checkpoint)
    receipt = tmp_path / "state-receipt.json"
    write_json(receipt, {"build": {"formal_source_eligible": eligible}})
    manager_profiles = tmp_path / "manager-profiles.json"
    write_json(
        manager_profiles,
        {
            "version": NBA_MANAGER_PROFILE_SET_VERSION,
            "profile_set_id": "test",
            "profiles": [
                asdict(ManagerProfile(profile.manager_id, profile.team_id))
                for profile in profiles.values()
            ],
        },
    )
    return checkpoint, receipt, manager_profiles


def test_study_bundle_freezes_all_formal_sources_and_configuration(tmp_path: Path) -> None:
    checkpoint, receipt, manager_profiles = _inputs(tmp_path)
    bundle = build_nba_manager_study_bundle(
        experiment_id="formal",
        initial_checkpoint=checkpoint,
        state_build_receipt_path=receipt,
        schema_path=Path("data/model_schema_demo_v1_12.json"),
        parameters_path=Path("data/model_parameters_demo_1.4.0.json"),
        shot_profiles_path=Path(
            "experiments/inputs/nba-2024-25-team-shot-profiles-calibrated.json"
        ),
        macro_reference_path=Path("experiments/sources/nba-2022-25-quick-sim-reference.json"),
        manager_profiles_path=manager_profiles,
        master_seeds=tuple(range(20270401, 20270431)),
    )
    assert bundle.spec.formal_run
    assert bundle.spec.seasons == 5
    assert len(bundle.spec.focal_team_ids) == 30
    assert dict(bundle.source_hashes).keys() == {
        "initial_checkpoint",
        "macro_reference",
        "manager_profiles",
        "model_parameters",
        "model_schema",
        "shot_profiles",
        "state_build_receipt",
    }
    assert bundle.spec.execution_config_sha256
    assert bundle.adapter.trace_mode.name == "AGGREGATE_ONLY"


def test_adapter_rejects_invalid_formal_configuration(tmp_path: Path) -> None:
    checkpoint, receipt, manager_profiles = _inputs(tmp_path)
    bundle = build_nba_manager_study_bundle(
        experiment_id="validation",
        initial_checkpoint=checkpoint,
        state_build_receipt_path=receipt,
        schema_path=Path("data/model_schema_demo_v1_12.json"),
        parameters_path=Path("data/model_parameters_demo_1.4.0.json"),
        shot_profiles_path=Path(
            "experiments/inputs/nba-2024-25-team-shot-profiles-calibrated.json"
        ),
        macro_reference_path=Path("experiments/sources/nba-2022-25-quick-sim-reference.json"),
        manager_profiles_path=manager_profiles,
        master_seeds=(20270301,),
        focal_team_ids=("T01",),
        seasons=1,
        formal_run=False,
    )
    with pytest.raises(ValueError, match="thirty keyed"):
        replace(bundle.adapter, profiles={})
    with pytest.raises(ValueError, match="unsupported NBA manager adapter"):
        replace(bundle.adapter, version=NBA_MANAGER_ADAPTER_VERSION + "-changed")
    with pytest.raises(ValueError, match="minimum roster"):
        replace(bundle.adapter, minimum_roster_players=4)
    with pytest.raises(ValueError, match="aggregate-only"):
        replace(bundle.adapter, trace_mode=TraceMode.FULL)
    with pytest.raises(ValueError, match="macro metric range"):
        MacroMetricRange("", 0.0, 1.0)
    with pytest.raises(ValueError, match="macro metric range"):
        MacroMetricRange("pace", 2.0, 1.0)


def test_formal_study_rejects_ineligible_state_source_coverage(tmp_path: Path) -> None:
    checkpoint, receipt, manager_profiles = _inputs(tmp_path, eligible=False)
    with pytest.raises(NBAManagerStudyError, match="eligible source coverage"):
        build_nba_manager_study_bundle(
            experiment_id="formal",
            initial_checkpoint=checkpoint,
            state_build_receipt_path=receipt,
            schema_path=Path("data/model_schema_demo_v1_12.json"),
            parameters_path=Path("data/model_parameters_demo_1.4.0.json"),
            shot_profiles_path=Path(
                "experiments/inputs/nba-2024-25-team-shot-profiles-calibrated.json"
            ),
            macro_reference_path=Path("experiments/sources/nba-2022-25-quick-sim-reference.json"),
            manager_profiles_path=manager_profiles,
            master_seeds=tuple(range(20270401, 20270431)),
        )


@pytest.mark.slow
@pytest.mark.franchise
def test_study_adapter_executes_one_real_paired_arm_with_compact_audit(tmp_path: Path) -> None:
    checkpoint, receipt, manager_profiles = _inputs(tmp_path)
    bundle = build_nba_manager_study_bundle(
        experiment_id="development-adapter",
        initial_checkpoint=checkpoint,
        state_build_receipt_path=receipt,
        schema_path=Path("data/model_schema_demo_v1_12.json"),
        parameters_path=Path("data/model_parameters_demo_1.4.0.json"),
        shot_profiles_path=Path(
            "experiments/inputs/nba-2024-25-team-shot-profiles-calibrated.json"
        ),
        macro_reference_path=Path("experiments/sources/nba-2022-25-quick-sim-reference.json"),
        manager_profiles_path=manager_profiles,
        master_seeds=(20270301,),
        focal_team_ids=("T01",),
        seasons=1,
        formal_run=False,
        game_config=GameClockConfig(1, 24, 24, 24, 1, True),
    )
    request = NBAManagerSeasonRequest(
        bundle.spec.experiment_id,
        bundle.spec.baseline_policy_id,
        bundle.spec.candidate_policy_id,
        NBAManagerExperimentArm.TREATMENT,
        "source-0001",
        20270301,
        "T01",
        bundle.spec.start_season,
        bundle.initial_state_payload,
    )

    adapter = replace(
        bundle.adapter,
        shot_zone_profiles=None,
        macro_ranges=(),
        minimum_roster_players=5,
    )
    execution = adapter(request)
    audit = json.loads(execution.audit_payload)

    assert execution.outcome.address == ("source-0001", 20270301, 2029, "T01")
    assert audit["candidate_teams"] == ["T01"]
    assert audit["arm"] == "treatment"
    assert execution.next_state_payload != bundle.initial_state_payload
