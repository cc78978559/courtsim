import json

import pytest
from test_phase12_manager_league_adapter import adapter, request

from courtsim.manager_ai import ManagerPolicyMode
from courtsim.manager_authority import (
    ManagerAuthorityPolicy,
    ManagerDecisionStage,
    default_manager_authority_policy,
    manager_execution_receipt,
)
from courtsim.manager_experiment import ManagerExperimentArm


def test_authority_modes_enforce_shadow_assist_and_active_execution() -> None:
    policy = ManagerAuthorityPolicy(
        tuple(
            (
                stage,
                (
                    ManagerPolicyMode.SHADOW
                    if stage is ManagerDecisionStage.DRAFT
                    else ManagerPolicyMode.ASSIST
                    if stage is ManagerDecisionStage.FREE_AGENCY
                    else ManagerPolicyMode.ACTIVE
                ),
            )
            for stage in ManagerDecisionStage
        )
    )
    shadow = manager_execution_receipt(
        policy,
        ManagerDecisionStage.DRAFT,
        evaluated=True,
        recommendation_count=2,
        executed_count=2,
        isolated_shadow=True,
    )
    assist = manager_execution_receipt(
        policy,
        ManagerDecisionStage.FREE_AGENCY,
        evaluated=True,
        recommendation_count=1,
        executed_count=0,
    )
    active = manager_execution_receipt(
        policy,
        ManagerDecisionStage.ROTATION,
        evaluated=True,
        recommendation_count=4,
        executed_count=4,
    )
    assert shadow.execution_authorized
    assert assist.reason == "awaiting-human-approval"
    assert active.reason == "active-policy"

    with pytest.raises(ValueError, match="unauthorized"):
        manager_execution_receipt(
            default_manager_authority_policy(),
            ManagerDecisionStage.DRAFT,
            evaluated=True,
            recommendation_count=1,
            executed_count=1,
        )


def test_adapter_audits_every_manager_authority_stage() -> None:
    incumbent = json.loads(adapter()(request(ManagerExperimentArm.INCUMBENT)).audit_payload)[
        "manager_authority"
    ]
    shadow = json.loads(adapter()(request(ManagerExperimentArm.SHADOW)).audit_payload)[
        "manager_authority"
    ]
    assert tuple(item["stage"] for item in incumbent["receipts"]) == (
        "draft",
        "free-agency",
        "trade",
        "rotation",
        "tactics",
    )
    incumbent_receipts = {item["stage"]: item for item in incumbent["receipts"]}
    shadow_receipts = {item["stage"]: item for item in shadow["receipts"]}
    assert not incumbent_receipts["draft"]["evaluated"]
    assert shadow_receipts["draft"]["isolated_shadow"]
    assert shadow_receipts["draft"]["execution_authorized"]
    assert incumbent_receipts["rotation"]["reason"] == "active-policy"
    assert incumbent_receipts["rotation"]["executed_count"] == 4
