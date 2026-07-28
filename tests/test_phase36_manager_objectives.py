import json

from test_phase12_manager_league_adapter import adapter, request

from courtsim.manager_ai import ManagerProfile
from courtsim.manager_experiment import ManagerExperimentArm
from courtsim.manager_objectives import (
    ManagerObjective,
    ManagerObjectiveContext,
    select_manager_objective,
)


def test_strong_win_now_roster_selects_contend_and_changes_effective_profile() -> None:
    profile = ManagerProfile("manager-A", "A", win_now=85, star_preference=80)
    decision = select_manager_objective(
        profile,
        ManagerObjectiveContext("A", 82, 84, 28, 10_000, 3),
    )
    assert decision.selected is ManagerObjective.CONTEND
    assert decision.effective_profile.win_now > profile.win_now
    assert decision.effective_profile.development_bias < profile.development_bias
    assert tuple(item.objective for item in decision.scores) == tuple(ManagerObjective)


def test_low_talent_patient_roster_selects_rebuild() -> None:
    profile = ManagerProfile(
        "manager-A",
        "A",
        win_now=15,
        patience=95,
        development_bias=80,
    )
    decision = select_manager_objective(
        profile,
        ManagerObjectiveContext("A", 35, 78, 22, 7_000, 5),
    )
    assert decision.selected is ManagerObjective.REBUILD
    assert decision.effective_profile.patience == 100
    assert decision.effective_profile.win_now == 0


def test_expensive_cap_disciplined_roster_selects_cap_relief() -> None:
    profile = ManagerProfile(
        "manager-A",
        "A",
        cap_discipline=100,
        risk_tolerance=10,
    )
    decision = select_manager_objective(
        profile,
        ManagerObjectiveContext("A", 55, 58, 31, 14_000, 1),
    )
    assert decision.selected is ManagerObjective.CAP_RELIEF
    assert decision.effective_profile.cap_discipline == 100
    assert decision.effective_profile.continuity < profile.continuity


def test_adapter_applies_objective_profile_to_white_box_rotation() -> None:
    audit = json.loads(adapter()(request(ManagerExperimentArm.INCUMBENT)).audit_payload)
    objective = audit["manager_objectives"][0]
    assert objective["effective_profile"] != objective["original_profile"]
    team_id = objective["team_id"]
    assert any(
        contribution["source"] == "personality" and contribution["value"] != 0
        for decision in audit["rotations"][team_id]["base"]["decisions"]
        for candidate in decision["candidates"]
        for contribution in candidate["contributions"]
    )
