"""Matched, multi-season evidence gates and releases for manager policies."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import asdict, dataclass, replace
from enum import IntEnum
from math import isclose, isfinite
from typing import Any, cast

from courtsim.domain.serialization import SerializationError
from courtsim.manager_ai import MANAGER_AI_VERSION

MANAGER_EVIDENCE_VERSION = "manager-evidence-v1"
MANAGER_RELEASE_REGISTRY_VERSION = "manager-release-registry-v1"


@dataclass(frozen=True, slots=True)
class ManagerOutcome:
    source_id: str
    master_seed: int
    season_year: int
    team_id: str
    win_rate: float
    playoff_progress: float
    roster_value: float
    cap_flexibility: float

    def __post_init__(self) -> None:
        if not self.source_id.strip() or not self.team_id.strip():
            raise ValueError("manager outcome source_id and team_id must not be blank")
        if (
            not isinstance(self.master_seed, int)
            or isinstance(self.master_seed, bool)
            or self.master_seed < 0
            or not isinstance(self.season_year, int)
            or isinstance(self.season_year, bool)
            or self.season_year < 1
        ):
            raise ValueError("manager outcome seed and season must be non-negative integers")
        metrics = (
            self.win_rate,
            self.playoff_progress,
            self.roster_value,
            self.cap_flexibility,
        )
        if any(not isfinite(value) or not 0 <= value <= 1 for value in metrics):
            raise ValueError("manager outcome metrics must be finite values from zero through one")

    @property
    def address(self) -> tuple[str, int, int, str]:
        return (self.source_id, self.master_seed, self.season_year, self.team_id)


@dataclass(frozen=True, slots=True)
class PairedManagerOutcome:
    incumbent: ManagerOutcome
    shadow: ManagerOutcome

    def __post_init__(self) -> None:
        if self.incumbent.address != self.shadow.address:
            raise ValueError("manager outcomes must share an exact source, seed, season, and team")


@dataclass(frozen=True, slots=True)
class ManagerEvaluationWeights:
    win_rate: float = 0.45
    playoff_progress: float = 0.20
    roster_value: float = 0.25
    cap_flexibility: float = 0.10

    def __post_init__(self) -> None:
        values = (
            self.win_rate,
            self.playoff_progress,
            self.roster_value,
            self.cap_flexibility,
        )
        if any(not isfinite(value) or value < 0 for value in values):
            raise ValueError("manager evaluation weights must be finite and non-negative")
        if not isclose(sum(values), 1.0, abs_tol=1e-9):
            raise ValueError("manager evaluation weights must sum to one")


@dataclass(frozen=True, slots=True)
class ManagerEvidenceThresholds:
    minimum_independent_sources: int = 30
    minimum_seasons_per_source: int = 2
    minimum_mean_utility_delta: float = 0.005
    minimum_win_rate_delta: float = -0.002
    maximum_loss_rate: float = 0.45
    minimum_worst_source_delta: float = -0.04
    neutral_band: float = 0.001

    def __post_init__(self) -> None:
        if (
            not isinstance(self.minimum_independent_sources, int)
            or isinstance(self.minimum_independent_sources, bool)
            or self.minimum_independent_sources < 1
            or not isinstance(self.minimum_seasons_per_source, int)
            or isinstance(self.minimum_seasons_per_source, bool)
            or self.minimum_seasons_per_source < 1
        ):
            raise ValueError("manager evidence sample thresholds must be positive integers")
        values = (
            self.minimum_mean_utility_delta,
            self.minimum_win_rate_delta,
            self.maximum_loss_rate,
            self.minimum_worst_source_delta,
            self.neutral_band,
        )
        if any(not isfinite(value) for value in values):
            raise ValueError("manager evidence thresholds must be finite")
        if not 0 <= self.maximum_loss_rate <= 1 or self.neutral_band < 0:
            raise ValueError("manager evidence rate thresholds are invalid")


@dataclass(frozen=True, slots=True)
class ManagerEvidenceMetrics:
    mean_utility_delta: float
    mean_win_rate_delta: float
    mean_playoff_delta: float
    mean_roster_value_delta: float
    mean_cap_flexibility_delta: float
    loss_rate: float
    worst_source_delta: float


@dataclass(frozen=True, slots=True)
class ManagerEvidenceResult:
    policy_version: str
    observation_count: int
    independent_sources: int
    seasons_per_source: tuple[tuple[str, int], ...]
    better: int
    neutral: int
    worse: int
    metrics: ManagerEvidenceMetrics
    hard_rejections: tuple[str, ...]
    recommended: bool
    evidence_digest: str
    evidence_version: str = MANAGER_EVIDENCE_VERSION
    manager_ai_version: str = MANAGER_AI_VERSION


def evaluate_manager_policy(
    *,
    policy_version: str,
    observations: Sequence[PairedManagerOutcome],
    weights: ManagerEvaluationWeights | None = None,
    thresholds: ManagerEvidenceThresholds | None = None,
) -> ManagerEvidenceResult:
    """Evaluate matched outcomes; sufficient sample count alone can never pass."""
    if not policy_version.strip():
        raise ValueError("policy_version must not be blank")
    active_weights = weights or ManagerEvaluationWeights()
    active_thresholds = thresholds or ManagerEvidenceThresholds()
    ordered = tuple(sorted(observations, key=lambda item: item.incumbent.address))
    addresses = tuple(item.incumbent.address for item in ordered)
    if len(addresses) != len(set(addresses)):
        raise ValueError("manager evidence contains duplicate outcome addresses")

    utility_deltas = tuple(_utility_delta(item, active_weights) for item in ordered)
    win_deltas = tuple(item.shadow.win_rate - item.incumbent.win_rate for item in ordered)
    playoff_deltas = tuple(
        item.shadow.playoff_progress - item.incumbent.playoff_progress for item in ordered
    )
    roster_deltas = tuple(
        item.shadow.roster_value - item.incumbent.roster_value for item in ordered
    )
    cap_deltas = tuple(
        item.shadow.cap_flexibility - item.incumbent.cap_flexibility for item in ordered
    )
    source_seasons: dict[str, set[int]] = defaultdict(set)
    source_seeds: dict[str, set[int]] = defaultdict(set)
    source_deltas: dict[str, list[float]] = defaultdict(list)
    for item, delta in zip(ordered, utility_deltas, strict=True):
        source_id = item.incumbent.source_id
        source_seasons[source_id].add(item.incumbent.season_year)
        source_seeds[source_id].add(item.incumbent.master_seed)
        source_deltas[source_id].append(delta)
    if any(len(seeds) != 1 for seeds in source_seeds.values()):
        raise ValueError("each manager evidence source must use one stable master seed")
    seed_values = tuple(next(iter(source_seeds[source])) for source in sorted(source_seeds))
    if len(seed_values) != len(set(seed_values)):
        raise ValueError("independent manager evidence sources must use distinct master seeds")

    mean_utility = _mean(utility_deltas)
    mean_win = _mean(win_deltas)
    mean_playoff = _mean(playoff_deltas)
    mean_roster = _mean(roster_deltas)
    mean_cap = _mean(cap_deltas)
    better = sum(delta > active_thresholds.neutral_band for delta in utility_deltas)
    worse = sum(delta < -active_thresholds.neutral_band for delta in utility_deltas)
    neutral = len(utility_deltas) - better - worse
    loss_rate = worse / len(utility_deltas) if utility_deltas else 1.0
    worst_source = min(
        (_mean(tuple(values)) for values in source_deltas.values()),
        default=float("-inf"),
    )
    metrics = ManagerEvidenceMetrics(
        _rounded(mean_utility),
        _rounded(mean_win),
        _rounded(mean_playoff),
        _rounded(mean_roster),
        _rounded(mean_cap),
        _rounded(loss_rate),
        _rounded(worst_source),
    )
    rejected: list[str] = []
    if len(source_seasons) < active_thresholds.minimum_independent_sources:
        rejected.append("insufficient-independent-sources")
    if (
        any(
            len(seasons) < active_thresholds.minimum_seasons_per_source
            for seasons in source_seasons.values()
        )
        or not source_seasons
    ):
        rejected.append("insufficient-seasons-per-source")
    if mean_utility < active_thresholds.minimum_mean_utility_delta:
        rejected.append("insufficient-utility-improvement")
    if mean_win < active_thresholds.minimum_win_rate_delta:
        rejected.append("win-rate-regression")
    if loss_rate > active_thresholds.maximum_loss_rate:
        rejected.append("excessive-loss-rate")
    if worst_source < active_thresholds.minimum_worst_source_delta:
        rejected.append("unsafe-source-regression")

    digest_payload = {
        "policy_version": policy_version,
        "weights": asdict(active_weights),
        "thresholds": asdict(active_thresholds),
        "observations": [
            {"incumbent": asdict(item.incumbent), "shadow": asdict(item.shadow)} for item in ordered
        ],
    }
    digest = hashlib.sha256(
        json.dumps(
            digest_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ManagerEvidenceResult(
        policy_version,
        len(ordered),
        len(source_seasons),
        tuple(sorted((source, len(seasons)) for source, seasons in source_seasons.items())),
        better,
        neutral,
        worse,
        metrics,
        tuple(rejected),
        not rejected,
        digest,
    )


class ManagerPolicyReleaseStatus(IntEnum):
    CANDIDATE = 0
    ACTIVE = 1
    REJECTED = 2
    RETIRED = 3


@dataclass(frozen=True, slots=True)
class ManagerPolicyRelease:
    policy_version: str
    status: ManagerPolicyReleaseStatus
    parent_version: str | None = None
    evidence_digest: str | None = None
    reason: str | None = None

    def __post_init__(self) -> None:
        if not self.policy_version.strip():
            raise ValueError("release policy_version must not be blank")
        if self.parent_version is not None and not self.parent_version.strip():
            raise ValueError("release parent_version must not be blank")
        if not isinstance(self.status, ManagerPolicyReleaseStatus):
            raise ValueError("release status is invalid")
        if self.evidence_digest is not None and (
            len(self.evidence_digest) != 64
            or any(character not in "0123456789abcdef" for character in self.evidence_digest)
        ):
            raise ValueError("release evidence_digest must be lowercase SHA-256")
        if self.reason is not None and not self.reason.strip():
            raise ValueError("release reason must not be blank")


@dataclass(frozen=True, slots=True)
class ManagerReleaseRegistry:
    releases: tuple[ManagerPolicyRelease, ...] = ()
    active_version: str | None = None
    version: str = MANAGER_RELEASE_REGISTRY_VERSION

    def __post_init__(self) -> None:
        if self.version != MANAGER_RELEASE_REGISTRY_VERSION:
            raise ValueError("unsupported manager release registry version")
        versions = tuple(item.policy_version for item in self.releases)
        if len(versions) != len(set(versions)):
            raise ValueError("manager policy release versions must be unique")
        active = tuple(
            item.policy_version
            for item in self.releases
            if item.status is ManagerPolicyReleaseStatus.ACTIVE
        )
        if active != (() if self.active_version is None else (self.active_version,)):
            raise ValueError("registry active pointer must match exactly one active release")

    def register(
        self,
        policy_version: str,
        *,
        parent_version: str | None = None,
    ) -> ManagerReleaseRegistry:
        if any(item.policy_version == policy_version for item in self.releases):
            raise ValueError("manager policy version is already registered")
        if parent_version is not None and not any(
            item.policy_version == parent_version for item in self.releases
        ):
            raise ValueError("manager policy parent version is not registered")
        release = ManagerPolicyRelease(
            policy_version,
            ManagerPolicyReleaseStatus.CANDIDATE,
            parent_version,
        )
        return ManagerReleaseRegistry((*self.releases, release), self.active_version)

    def activate(self, evidence: ManagerEvidenceResult) -> ManagerReleaseRegistry:
        if not evidence.recommended:
            raise ValueError("manager policy evidence does not pass activation gates")
        target = self._release(evidence.policy_version)
        if target.status is not ManagerPolicyReleaseStatus.CANDIDATE:
            raise ValueError("only a candidate manager policy can be activated")
        updated = tuple(
            replace(
                item,
                status=(
                    ManagerPolicyReleaseStatus.ACTIVE
                    if item.policy_version == target.policy_version
                    else ManagerPolicyReleaseStatus.RETIRED
                    if item.status is ManagerPolicyReleaseStatus.ACTIVE
                    else item.status
                ),
                evidence_digest=(
                    evidence.evidence_digest
                    if item.policy_version == target.policy_version
                    else item.evidence_digest
                ),
            )
            for item in self.releases
        )
        return ManagerReleaseRegistry(updated, target.policy_version)

    def reject(self, policy_version: str, reason: str) -> ManagerReleaseRegistry:
        target = self._release(policy_version)
        if target.status is not ManagerPolicyReleaseStatus.CANDIDATE:
            raise ValueError("only a candidate manager policy can be rejected")
        updated = tuple(
            replace(item, status=ManagerPolicyReleaseStatus.REJECTED, reason=reason)
            if item.policy_version == policy_version
            else item
            for item in self.releases
        )
        return ManagerReleaseRegistry(updated, self.active_version)

    def rollback(self, policy_version: str, reason: str) -> ManagerReleaseRegistry:
        target = self._release(policy_version)
        if target.status is not ManagerPolicyReleaseStatus.RETIRED:
            raise ValueError("rollback target must be a retired manager policy")
        if self.active_version is None:
            raise ValueError("rollback requires a currently active manager policy")
        updated = tuple(
            replace(
                item,
                status=(
                    ManagerPolicyReleaseStatus.ACTIVE
                    if item.policy_version == policy_version
                    else ManagerPolicyReleaseStatus.RETIRED
                    if item.policy_version == self.active_version
                    else item.status
                ),
                reason=(reason if item.policy_version == self.active_version else item.reason),
            )
            for item in self.releases
        )
        return ManagerReleaseRegistry(updated, policy_version)

    def _release(self, policy_version: str) -> ManagerPolicyRelease:
        for item in self.releases:
            if item.policy_version == policy_version:
                return item
        raise ValueError("manager policy version is not registered")


def manager_release_registry_to_json(registry: ManagerReleaseRegistry) -> str:
    payload = {
        "version": registry.version,
        "active_version": registry.active_version,
        "releases": [
            {
                "policy_version": item.policy_version,
                "status": item.status.name.lower(),
                "parent_version": item.parent_version,
                "evidence_digest": item.evidence_digest,
                "reason": item.reason,
            }
            for item in registry.releases
        ],
    }
    return f"{json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'))}\n"


def manager_release_registry_from_json(payload: str) -> ManagerReleaseRegistry:
    try:
        raw: object = json.loads(payload)
        value = _object(raw, "manager release registry")
        _exact(value, {"version", "active_version", "releases"}, "manager release registry")
        if value["version"] != MANAGER_RELEASE_REGISTRY_VERSION:
            raise SerializationError("unsupported manager release registry version")
        active = value["active_version"]
        if active is not None and not isinstance(active, str):
            raise SerializationError("manager release active_version must be text or null")
        raw_releases = value["releases"]
        if not isinstance(raw_releases, list):
            raise SerializationError("manager releases must be a list")
        releases = tuple(_parse_release(item) for item in raw_releases)
        return ManagerReleaseRegistry(releases, active)
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, SerializationError):
            raise
        raise SerializationError(f"invalid manager release registry: {error}") from error


def _utility_delta(
    observation: PairedManagerOutcome,
    weights: ManagerEvaluationWeights,
) -> float:
    incumbent = observation.incumbent
    shadow = observation.shadow
    return (
        (shadow.win_rate - incumbent.win_rate) * weights.win_rate
        + (shadow.playoff_progress - incumbent.playoff_progress) * weights.playoff_progress
        + (shadow.roster_value - incumbent.roster_value) * weights.roster_value
        + (shadow.cap_flexibility - incumbent.cap_flexibility) * weights.cap_flexibility
    )


def _mean(values: tuple[float, ...]) -> float:
    return sum(values) / len(values) if values else float("-inf")


def _rounded(value: float) -> float:
    return round(value, 6) if isfinite(value) else value


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SerializationError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _exact(value: dict[str, Any], keys: set[str], field: str) -> None:
    if set(value) != keys:
        raise SerializationError(f"{field} keys must be exactly {sorted(keys)}")


def _parse_release(value: object) -> ManagerPolicyRelease:
    raw = _object(value, "manager policy release")
    _exact(
        raw,
        {
            "policy_version",
            "status",
            "parent_version",
            "evidence_digest",
            "reason",
        },
        "manager policy release",
    )
    policy_version = raw["policy_version"]
    status = raw["status"]
    parent = raw["parent_version"]
    digest = raw["evidence_digest"]
    reason = raw["reason"]
    if not isinstance(policy_version, str) or not isinstance(status, str):
        raise SerializationError("manager policy version and status must be text")
    if parent is not None and not isinstance(parent, str):
        raise SerializationError("manager policy parent must be text or null")
    if digest is not None and not isinstance(digest, str):
        raise SerializationError("manager policy evidence digest must be text or null")
    if reason is not None and not isinstance(reason, str):
        raise SerializationError("manager policy reason must be text or null")
    try:
        parsed_status = ManagerPolicyReleaseStatus[status.upper()]
    except KeyError as error:
        raise SerializationError("unknown manager policy release status") from error
    return ManagerPolicyRelease(
        policy_version,
        parsed_status,
        parent,
        digest,
        reason,
    )
