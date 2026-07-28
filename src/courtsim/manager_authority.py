"""Unified authority and execution receipts for white-box manager policies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from courtsim.manager_ai import ManagerPolicyMode

MANAGER_AUTHORITY_VERSION = "manager-authority-v1"


class ManagerDecisionStage(IntEnum):
    DRAFT = 0
    FREE_AGENCY = 1
    TRADE = 2
    ROTATION = 3
    TACTICS = 4


@dataclass(frozen=True, slots=True)
class ManagerAuthorityPolicy:
    stage_modes: tuple[tuple[ManagerDecisionStage, ManagerPolicyMode], ...]
    version: str = MANAGER_AUTHORITY_VERSION

    def __post_init__(self) -> None:
        if tuple(stage for stage, _ in self.stage_modes) != tuple(ManagerDecisionStage):
            raise ValueError("manager authority stages must use canonical order")
        if any(not isinstance(mode, ManagerPolicyMode) for _, mode in self.stage_modes):
            raise ValueError("manager authority modes must be ManagerPolicyMode")
        if self.version != MANAGER_AUTHORITY_VERSION:
            raise ValueError("unsupported manager authority version")

    def mode_for(self, stage: ManagerDecisionStage) -> ManagerPolicyMode:
        return dict(self.stage_modes)[stage]


@dataclass(frozen=True, slots=True)
class ManagerExecutionReceipt:
    stage: ManagerDecisionStage
    mode: ManagerPolicyMode
    evaluated: bool
    recommendation_count: int
    execution_authorized: bool
    executed_count: int
    human_approved: bool
    isolated_shadow: bool
    reason: str
    version: str = MANAGER_AUTHORITY_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.stage, ManagerDecisionStage) or not isinstance(
            self.mode, ManagerPolicyMode
        ):
            raise ValueError("manager execution receipt stage and mode are invalid")
        if self.recommendation_count < 0 or self.executed_count < 0:
            raise ValueError("manager execution counts must be non-negative")
        if self.executed_count > self.recommendation_count:
            raise ValueError("executed recommendations cannot exceed recommendations")
        if self.executed_count and not self.execution_authorized:
            raise ValueError("unauthorized manager recommendations cannot execute")
        if not self.reason.strip():
            raise ValueError("manager execution receipt reason must not be blank")
        if self.version != MANAGER_AUTHORITY_VERSION:
            raise ValueError("unsupported manager authority version")


def default_manager_authority_policy() -> ManagerAuthorityPolicy:
    return ManagerAuthorityPolicy(
        (
            (ManagerDecisionStage.DRAFT, ManagerPolicyMode.SHADOW),
            (ManagerDecisionStage.FREE_AGENCY, ManagerPolicyMode.SHADOW),
            (ManagerDecisionStage.TRADE, ManagerPolicyMode.SHADOW),
            (ManagerDecisionStage.ROTATION, ManagerPolicyMode.ACTIVE),
            (ManagerDecisionStage.TACTICS, ManagerPolicyMode.ACTIVE),
        )
    )


def manager_execution_receipt(
    policy: ManagerAuthorityPolicy,
    stage: ManagerDecisionStage,
    *,
    evaluated: bool,
    recommendation_count: int,
    executed_count: int,
    human_approved: bool = False,
    isolated_shadow: bool = False,
) -> ManagerExecutionReceipt:
    mode = policy.mode_for(stage)
    authorized = (
        mode is ManagerPolicyMode.ACTIVE
        or (mode is ManagerPolicyMode.ASSIST and human_approved)
        or (mode is ManagerPolicyMode.SHADOW and isolated_shadow)
    )
    if not evaluated:
        reason = "policy-not-evaluated"
    elif mode is ManagerPolicyMode.ACTIVE:
        reason = "active-policy"
    elif mode is ManagerPolicyMode.ASSIST:
        reason = "human-approved" if human_approved else "awaiting-human-approval"
    else:
        reason = "isolated-shadow-experiment" if isolated_shadow else "shadow-only"
    return ManagerExecutionReceipt(
        stage,
        mode,
        evaluated,
        recommendation_count,
        authorized,
        executed_count,
        human_approved,
        isolated_shadow,
        reason,
    )


def manager_authority_to_dict(
    policy: ManagerAuthorityPolicy,
    receipts: tuple[ManagerExecutionReceipt, ...],
) -> dict[str, object]:
    if tuple(receipt.stage for receipt in receipts) != tuple(ManagerDecisionStage):
        raise ValueError("manager authority receipts must use canonical stage order")
    return {
        "version": policy.version,
        "stage_modes": {
            _stage_name(stage): mode.name.lower() for stage, mode in policy.stage_modes
        },
        "receipts": [
            {
                "stage": _stage_name(receipt.stage),
                "mode": receipt.mode.name.lower(),
                "evaluated": receipt.evaluated,
                "recommendation_count": receipt.recommendation_count,
                "execution_authorized": receipt.execution_authorized,
                "executed_count": receipt.executed_count,
                "human_approved": receipt.human_approved,
                "isolated_shadow": receipt.isolated_shadow,
                "reason": receipt.reason,
                "version": receipt.version,
            }
            for receipt in receipts
        ],
    }


def _stage_name(stage: ManagerDecisionStage) -> str:
    return stage.name.lower().replace("_", "-")
