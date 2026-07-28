import json
from dataclasses import replace

import pytest

from courtsim.domain.serialization import SerializationError
from courtsim.manager_evaluation import (
    ManagerEvaluationWeights,
    ManagerEvidenceResult,
    ManagerEvidenceThresholds,
    ManagerOutcome,
    ManagerPolicyReleaseStatus,
    ManagerReleaseRegistry,
    PairedManagerOutcome,
    evaluate_manager_policy,
    manager_release_registry_from_json,
    manager_release_registry_to_json,
)


def outcome(
    source: str,
    season: int,
    *,
    shadow: bool,
    improvement: float = 0.02,
) -> ManagerOutcome:
    delta = improvement if shadow else 0.0
    source_seed = sum((index + 1) * ord(character) for index, character in enumerate(source))
    return ManagerOutcome(
        source,
        source_seed,
        2028 + season,
        "home",
        0.50 + delta,
        0.25 + delta,
        0.55 + delta,
        0.40 + delta,
    )


def evidence(
    *,
    improvement: float = 0.02,
    sources: int = 3,
    seasons: int = 2,
) -> ManagerEvidenceResult:
    observations = tuple(
        PairedManagerOutcome(
            outcome(f"source-{source}", season, shadow=False),
            outcome(
                f"source-{source}",
                season,
                shadow=True,
                improvement=improvement,
            ),
        )
        for source in range(sources)
        for season in range(seasons)
    )
    return evaluate_manager_policy(
        policy_version="manager-policy-v1",
        observations=observations,
        thresholds=ManagerEvidenceThresholds(
            minimum_independent_sources=3,
            minimum_seasons_per_source=2,
            minimum_mean_utility_delta=0.005,
            minimum_win_rate_delta=-0.002,
            maximum_loss_rate=0.45,
            minimum_worst_source_delta=-0.04,
        ),
    )


def test_matched_multiseason_evidence_passes_all_non_sample_gates() -> None:
    result = evidence()
    assert result.recommended
    assert result.observation_count == 6
    assert result.independent_sources == 3
    assert result.seasons_per_source == (
        ("source-0", 2),
        ("source-1", 2),
        ("source-2", 2),
    )
    assert (result.better, result.neutral, result.worse) == (6, 0, 0)
    assert result.metrics.mean_utility_delta == 0.02
    assert len(result.evidence_digest) == 64


def test_sample_count_alone_cannot_activate_a_policy() -> None:
    result = evidence(improvement=0.0)
    assert not result.recommended
    assert "insufficient-utility-improvement" in result.hard_rejections
    assert result.independent_sources == 3
    assert result.observation_count == 6


def test_evidence_reports_source_and_safety_failures() -> None:
    result = evidence(improvement=-0.08, sources=2, seasons=1)
    assert not result.recommended
    assert set(result.hard_rejections) == {
        "insufficient-independent-sources",
        "insufficient-seasons-per-source",
        "insufficient-utility-improvement",
        "win-rate-regression",
        "excessive-loss-rate",
        "unsafe-source-regression",
    }
    assert result.metrics.loss_rate == 1


def test_evidence_is_order_independent_and_rejects_duplicate_addresses() -> None:
    pairs = tuple(
        PairedManagerOutcome(
            outcome("source-a", season, shadow=False),
            outcome("source-a", season, shadow=True),
        )
        for season in range(2)
    )
    thresholds = ManagerEvidenceThresholds(
        minimum_independent_sources=1,
        minimum_seasons_per_source=2,
    )
    first = evaluate_manager_policy(
        policy_version="policy",
        observations=pairs,
        thresholds=thresholds,
    )
    second = evaluate_manager_policy(
        policy_version="policy",
        observations=tuple(reversed(pairs)),
        thresholds=thresholds,
    )
    assert first == second
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_manager_policy(
            policy_version="policy",
            observations=(*pairs, pairs[0]),
            thresholds=thresholds,
        )


def test_exact_pairing_and_contract_validation() -> None:
    with pytest.raises(ValueError, match="exact source"):
        PairedManagerOutcome(
            outcome("source-a", 1, shadow=False),
            outcome("source-b", 1, shadow=True),
        )
    with pytest.raises(ValueError, match="sum to one"):
        ManagerEvaluationWeights(win_rate=1)
    with pytest.raises(ValueError, match="metrics"):
        ManagerOutcome("source", 1, 2028, "home", 1.1, 0, 0, 0)
    empty = evaluate_manager_policy(
        policy_version="policy",
        observations=(),
        thresholds=ManagerEvidenceThresholds(
            minimum_independent_sources=1,
            minimum_seasons_per_source=1,
        ),
    )
    assert not empty.recommended
    assert "insufficient-independent-sources" in empty.hard_rejections
    source_a = outcome("source-a", 1, shadow=False)
    source_b = replace(outcome("source-b", 1, shadow=False), master_seed=source_a.master_seed)
    with pytest.raises(ValueError, match="distinct master seeds"):
        evaluate_manager_policy(
            policy_version="policy",
            observations=(
                PairedManagerOutcome(
                    source_a,
                    outcome("source-a", 1, shadow=True),
                ),
                PairedManagerOutcome(
                    source_b,
                    replace(
                        outcome("source-b", 1, shadow=True),
                        master_seed=source_a.master_seed,
                    ),
                ),
            ),
            thresholds=ManagerEvidenceThresholds(
                minimum_independent_sources=2,
                minimum_seasons_per_source=1,
            ),
        )


def test_release_registry_requires_evidence_and_supports_rollback() -> None:
    passed = evidence()
    failed = evidence(improvement=0)
    registry = ManagerReleaseRegistry().register("manager-policy-v1")
    with pytest.raises(ValueError, match="does not pass"):
        registry.activate(failed)
    registry = registry.activate(passed)
    assert registry.active_version == "manager-policy-v1"
    assert registry.releases[0].status is ManagerPolicyReleaseStatus.ACTIVE
    registry = registry.register(
        "manager-policy-v2",
        parent_version="manager-policy-v1",
    )
    rejected = registry.reject("manager-policy-v2", "holdout regression")
    assert rejected.releases[1].status is ManagerPolicyReleaseStatus.REJECTED

    registry = registry.register(
        "manager-policy-v3",
        parent_version="manager-policy-v1",
    )
    v3_evidence = evaluate_manager_policy(
        policy_version="manager-policy-v3",
        observations=tuple(
            PairedManagerOutcome(
                outcome(f"source-{source}", season, shadow=False),
                outcome(f"source-{source}", season, shadow=True),
            )
            for source in range(3)
            for season in range(2)
        ),
        thresholds=ManagerEvidenceThresholds(
            minimum_independent_sources=3,
            minimum_seasons_per_source=2,
        ),
    )
    registry = registry.activate(v3_evidence)
    assert registry.releases[0].status is ManagerPolicyReleaseStatus.RETIRED
    registry = registry.rollback("manager-policy-v1", "live safety regression")
    assert registry.active_version == "manager-policy-v1"
    assert registry.releases[-1].status is ManagerPolicyReleaseStatus.RETIRED


def test_release_registry_json_round_trip_and_tamper_rejection() -> None:
    registry = ManagerReleaseRegistry().register("manager-policy-v1").activate(evidence())
    payload = manager_release_registry_to_json(registry)
    assert manager_release_registry_from_json(payload) == registry
    raw = json.loads(payload)
    raw["extra"] = True
    with pytest.raises(SerializationError, match="keys"):
        manager_release_registry_from_json(json.dumps(raw))
    raw = json.loads(payload)
    raw["releases"][0]["status"] = "unknown"
    with pytest.raises(SerializationError, match="unknown"):
        manager_release_registry_from_json(json.dumps(raw))


def test_release_registry_rejects_invalid_transitions() -> None:
    registry = ManagerReleaseRegistry().register("manager-policy-v1")
    with pytest.raises(ValueError, match="already registered"):
        registry.register("manager-policy-v1")
    with pytest.raises(ValueError, match="not registered"):
        registry.register("manager-policy-v2", parent_version="missing")
    with pytest.raises(ValueError, match="not registered"):
        registry.reject("missing", "reason")
    with pytest.raises(ValueError, match="retired"):
        registry.rollback("manager-policy-v1", "reason")
