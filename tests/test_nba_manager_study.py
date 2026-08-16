import json
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import pytest
from test_game_runtime import player
from test_phase12_manager_league_adapter import career_player
from test_phase48_nba_franchise import _state

from courtsim.analysis.nba_manager_state import NBAManagerStateBuildReceipt
from courtsim.analysis.nba_player_targets import (
    NBAPlayerSourceReceipt,
    NBAPlayerTarget,
    NBAPlayerTargetSet,
    nba_player_target_set_to_dict,
)
from courtsim.artifacts import write_json
from courtsim.domain.game import GameClockConfig
from courtsim.manager_ai import ManagerProfile
from courtsim.model.trace_mode import TraceMode
from courtsim.nba_franchise_artifacts import (
    NBAFranchiseCheckpointReceipt,
    write_nba_franchise_checkpoint,
)
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
    portable_nba_manager_checkpoint_receipt,
)


def _inputs(tmp_path: Path, *, eligible: bool = True) -> tuple[Path, Path, Path, Path]:
    state, profiles, rules = _state()
    extra_by_team = {
        roster.team_id: tuple(range(151 + index * 5, 156 + index * 5))
        for index, roster in enumerate(state.management.rosters)
    }
    expanded_rosters = tuple(
        replace(roster, player_ids=(*roster.player_ids, *extra_by_team[roster.team_id]))
        for roster in state.management.rosters
    )
    expanded_teams = tuple(
        replace(
            team,
            bench_profiles=tuple(player(player_id) for player_id in extra_by_team[team.team_id]),
            substitution_order=(*team.roster_order, *extra_by_team[team.team_id]),
        )
        for team in state.teams
    )
    state = replace(
        state,
        management=replace(
            state.management,
            rosters=expanded_rosters,
            contracts=tuple(
                sorted(
                    (
                        *state.management.contracts,
                        *(
                            type(state.management.contracts[0])(
                                player_id, team_id, rules.minimum_salary, 4
                            )
                            for team_id, player_ids in extra_by_team.items()
                            for player_id in player_ids
                        ),
                    ),
                    key=lambda item: item.player_id,
                )
            ),
        ),
        players=(
            *state.players,
            *(career_player(player_id) for player_id in range(151, 301)),
        ),
        teams=expanded_teams,
    )
    checkpoint = tmp_path / "initial.json"
    checkpoint_receipt = write_nba_franchise_checkpoint(state, rules, checkpoint)
    receipt = tmp_path / "state-receipt.json"
    coverage = 0.95 if eligible else 0.94
    build_receipt = NBAManagerStateBuildReceipt(
        state.league_id,
        state.management.season_year,
        "test-target",
        "test-player-source",
        "a" * 64,
        checkpoint_receipt.state_sha256,
        sum(len(roster.player_ids) for roster in state.management.rosters),
        coverage,
        0.90,
        eligible,
        (),
        (),
        (),
        (),
    )
    write_json(
        receipt,
        {
            "version": "nba-manager-state-build-receipt-v1",
            "build": asdict(build_receipt),
            "checkpoint": asdict(checkpoint_receipt),
        },
    )
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
    team_by_player = {
        player_id: roster.team_id
        for roster in state.management.rosters
        for player_id in roster.player_ids
    }
    player_targets = tmp_path / "player-targets.json"
    write_json(
        player_targets,
        nba_player_target_set_to_dict(
            NBAPlayerTargetSet(
                "test-target",
                "2028-29",
                "unit-test",
                1,
                1.0,
                (NBAPlayerSourceReceipt("box-score", "cache/players.json", "b" * 64),),
                tuple(
                    NBAPlayerTarget(
                        player_id,
                        f"Player {player_id}",
                        team_by_player[player_id],
                        82,
                        16.0,
                        0.20,
                        0.56,
                        1.0 / len(state.players),
                        (0.35, 0.20, 0.45),
                        (0.65, 0.42, 0.36),
                    )
                    for player_id in sorted(team_by_player)
                ),
            )
        ),
    )
    return checkpoint, receipt, manager_profiles, player_targets


def test_study_bundle_freezes_all_development_sources_and_configuration(tmp_path: Path) -> None:
    checkpoint, receipt, manager_profiles, player_targets = _inputs(tmp_path)
    bundle = build_nba_manager_study_bundle(
        experiment_id="development",
        initial_checkpoint=checkpoint,
        state_build_receipt_path=receipt,
        schema_path=Path("data/model_schema_demo_v1_12.json"),
        parameters_path=Path("data/model_parameters_demo_1.4.0.json"),
        shot_profiles_path=Path(
            "experiments/inputs/nba-2024-25-team-shot-profiles-calibrated.json"
        ),
        macro_reference_path=Path("experiments/sources/nba-2022-25-quick-sim-reference.json"),
        manager_profiles_path=manager_profiles,
        player_targets_path=player_targets,
        state_build_source_path=player_targets,
        master_seeds=(20270301,),
        focal_team_ids=("T01",),
        seasons=1,
        formal_run=False,
    )
    assert not bundle.spec.formal_run
    assert bundle.spec.seasons == 1
    assert len(bundle.spec.focal_team_ids) == 1
    assert dict(bundle.source_hashes).keys() == {
        "initial_checkpoint",
        "macro_reference",
        "manager_profiles",
        "model_parameters",
        "model_schema",
        "player_targets",
        "shot_profiles",
        "state_build_receipt",
        "state_build_source",
    }
    assert bundle.spec.execution_config_sha256
    assert bundle.adapter.trace_mode.name == "AGGREGATE_ONLY"


def test_adapter_rejects_invalid_formal_configuration(tmp_path: Path) -> None:
    checkpoint, receipt, manager_profiles, player_targets = _inputs(tmp_path)
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
        player_targets_path=player_targets,
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


def test_study_rejects_missing_mismatched_or_incomplete_player_targets(tmp_path: Path) -> None:
    checkpoint, receipt, manager_profiles, player_targets = _inputs(tmp_path)
    common: dict[str, Any] = {
        "experiment_id": "validation",
        "initial_checkpoint": checkpoint,
        "state_build_receipt_path": receipt,
        "schema_path": Path("data/model_schema_demo_v1_12.json"),
        "parameters_path": Path("data/model_parameters_demo_1.4.0.json"),
        "shot_profiles_path": Path(
            "experiments/inputs/nba-2024-25-team-shot-profiles-calibrated.json"
        ),
        "macro_reference_path": Path("experiments/sources/nba-2022-25-quick-sim-reference.json"),
        "manager_profiles_path": manager_profiles,
        "master_seeds": (20270301,),
        "focal_team_ids": ("T01",),
        "seasons": 1,
    }
    with pytest.raises(NBAManagerStudyError, match="requires frozen player targets"):
        build_nba_manager_study_bundle(**common)

    with pytest.raises(NBAManagerStudyError, match="requires the state-build source"):
        build_nba_manager_study_bundle(
            **common,
            player_targets_path=player_targets,
        )

    payload = json.loads(player_targets.read_text(encoding="utf-8"))
    payload["target_id"] = "different-target"
    write_json(player_targets, payload)
    with pytest.raises(NBAManagerStudyError, match="differ from state receipt"):
        build_nba_manager_study_bundle(
            **common,
            player_targets_path=player_targets,
            formal_run=False,
        )

    payload["target_id"] = "test-target"
    payload["players"] = payload["players"][:-1]
    write_json(player_targets, payload)
    with pytest.raises(NBAManagerStudyError, match="do not cover initial rosters"):
        build_nba_manager_study_bundle(
            **common,
            player_targets_path=player_targets,
            formal_run=False,
        )


def test_formal_study_rejects_short_game_clock(tmp_path: Path) -> None:
    checkpoint, receipt, manager_profiles, player_targets = _inputs(tmp_path)
    with pytest.raises(NBAManagerStudyError, match="frozen full-game clock"):
        build_nba_manager_study_bundle(
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
            player_targets_path=player_targets,
            state_build_source_path=player_targets,
            master_seeds=(20270301,),
            focal_team_ids=("T01",),
            seasons=1,
            game_config=GameClockConfig(1, 24, 24, 24, 1, True),
        )


def test_state_build_checkpoint_receipt_path_is_portable() -> None:
    receipt = NBAFranchiseCheckpointReceipt(
        "C:/machine/work/initial-franchise.json.gz",
        "nba",
        0,
        "a" * 64,
        "b" * 64,
        "gzip",
    )
    portable = portable_nba_manager_checkpoint_receipt(receipt)
    assert portable.checkpoint_path == "initial-franchise.json.gz"
    assert portable.state_sha256 == receipt.state_sha256


def test_formal_study_rejects_ineligible_state_source_coverage(tmp_path: Path) -> None:
    checkpoint, receipt, manager_profiles, player_targets = _inputs(tmp_path, eligible=False)
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
            player_targets_path=player_targets,
            master_seeds=tuple(range(20270401, 20270431)),
        )


def test_formal_study_rejects_unbound_minimal_state_receipt(tmp_path: Path) -> None:
    checkpoint, receipt, manager_profiles, player_targets = _inputs(tmp_path)
    write_json(receipt, {"build": {"formal_source_eligible": True}})
    with pytest.raises(NBAManagerStudyError, match="receipt root"):
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
            player_targets_path=player_targets,
            master_seeds=tuple(range(20270401, 20270431)),
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    (
        ("missing-build-field", "result schema"),
        ("invalid-fallback-list", "fallback identities"),
        ("state-hash-mismatch", "not bound"),
        ("checkpoint-hash-mismatch", "not bound"),
    ),
)
def test_formal_study_rejects_tampered_state_receipt_fields(
    tmp_path: Path, mutation: str, message: str
) -> None:
    checkpoint, receipt, manager_profiles, player_targets = _inputs(tmp_path)
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    if mutation == "missing-build-field":
        del payload["build"]["player_target_id"]
    elif mutation == "invalid-fallback-list":
        payload["build"]["proxy_age_player_ids"] = "invalid"
    elif mutation == "state-hash-mismatch":
        payload["build"]["initial_state_sha256"] = "0" * 64
    else:
        payload["checkpoint"]["file_sha256"] = "0" * 64
    write_json(receipt, payload)
    with pytest.raises(NBAManagerStudyError, match=message):
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
            player_targets_path=player_targets,
            master_seeds=tuple(range(20270401, 20270431)),
        )


@pytest.mark.slow
@pytest.mark.franchise
def test_study_adapter_executes_one_real_paired_arm_with_compact_audit(tmp_path: Path) -> None:
    checkpoint, receipt, manager_profiles, player_targets = _inputs(tmp_path)
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
        player_targets_path=player_targets,
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
        player_targets=None,
        minimum_roster_players=5,
    )
    with pytest.raises(ValueError, match="policy identity"):
        adapter(replace(request, baseline_policy_id="mislabelled-baseline"))
    execution = adapter(request)
    audit = json.loads(execution.audit_payload)

    assert execution.outcome.address == ("source-0001", 20270301, 2029, "T01")
    assert audit["candidate_teams"] == ["T01"]
    assert audit["arm"] == "treatment"
    assert audit["calendar"]["passed"] is True
    assert execution.outcome.illegal_transactions == 0
    assert execution.outcome.unplayable_rosters == 0
    assert set(dict(execution.outcome.macro_metrics)) == {
        "champion-seed-mean",
        "home-win-rate",
        "injury-rate",
        "offensive-rating",
        "pace-possessions-per-team",
        "playoff-upset-rate",
        "point-differential-stddev",
        "win-rate-stddev",
    }
    assert execution.next_state_payload != bundle.initial_state_payload
