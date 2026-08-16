from dataclasses import replace
from typing import Any

import pytest

from courtsim.nba_manager_evaluation import (
    NBAFrontOfficeEvaluationWeights,
    NBAFrontOfficeEvidenceThresholds,
    NBAFrontOfficeOutcome,
    PairedNBAFrontOfficeOutcome,
    evaluate_nba_front_office_policy,
)


def outcome(
    source: str,
    seed: int,
    year: int,
    team: str,
    value: float,
    *,
    negotiations_opened: int = 0,
    negotiations_accepted: int = 0,
    negotiation_rounds: int = 0,
    stale_rejections: int = 0,
    positive_gain_transactions: int = 0,
    no_counteroffers: int = 0,
    round_exhaustions: int = 0,
    illegal_transactions: int = 0,
) -> NBAFrontOfficeOutcome:
    return NBAFrontOfficeOutcome(
        source,
        seed,
        year,
        team,
        value,
        value,
        value,
        value,
        value,
        value,
        negotiations_opened=negotiations_opened,
        negotiations_accepted=negotiations_accepted,
        negotiation_rounds=negotiation_rounds,
        stale_rejections=stale_rejections,
        positive_gain_transactions=positive_gain_transactions,
        no_counteroffers=no_counteroffers,
        round_exhaustions=round_exhaustions,
        illegal_transactions=illegal_transactions,
    )


def thresholds(sources: int = 2) -> NBAFrontOfficeEvidenceThresholds:
    return NBAFrontOfficeEvidenceThresholds(
        minimum_independent_sources=sources,
        minimum_seasons_per_source=5,
        minimum_mean_utility_delta=0.005,
        minimum_utility_ci_lower=-0.005,
        minimum_win_rate_delta=-0.002,
        minimum_postseason_delta=-0.010,
        minimum_terminal_asset_delta=-0.010,
        minimum_cap_health_delta=-0.010,
        maximum_loss_rate=0.45,
        minimum_worst_source_delta=-0.040,
    )


def paired_sources(*, safety_failure: bool = False) -> tuple[PairedNBAFrontOfficeOutcome, ...]:
    observations = []
    for source_index, team in enumerate(("A", "B"), start=1):
        for offset in range(5):
            control = outcome(
                f"source-{source_index:04d}",
                100 + source_index,
                2029 + offset,
                team,
                0.50,
                negotiations_opened=2,
                negotiations_accepted=1,
                negotiation_rounds=3,
                positive_gain_transactions=1,
                no_counteroffers=1,
                stale_rejections=1,
            )
            treatment = outcome(
                f"source-{source_index:04d}",
                100 + source_index,
                2029 + offset,
                team,
                0.53,
                negotiations_opened=4,
                negotiations_accepted=3,
                negotiation_rounds=8,
                positive_gain_transactions=2,
                round_exhaustions=1,
                stale_rejections=2,
                illegal_transactions=int(safety_failure and source_index == 1 and offset == 0),
            )
            observations.append(PairedNBAFrontOfficeOutcome(control, treatment))
    return tuple(observations)


def test_source_level_manager_evidence_passes_and_reports_negotiations() -> None:
    result = evaluate_nba_front_office_policy(
        baseline_policy_id="baseline",
        candidate_policy_id="candidate",
        observations=paired_sources(),
        thresholds=thresholds(),
    )
    assert result.recommended
    assert result.independent_sources == 2
    assert result.focal_teams == ("A", "B")
    assert result.metrics.mean_utility_delta == pytest.approx(0.03)
    assert result.metrics.control_negotiation_efficiency == pytest.approx(0.5)
    assert result.metrics.treatment_negotiation_efficiency == pytest.approx(0.75)
    assert result.metrics.control_positive_gain_transactions == 10
    assert result.metrics.treatment_positive_gain_transactions == 20
    assert result.metrics.control_no_counteroffers == 10
    assert result.metrics.treatment_round_exhaustions == 10
    assert result.metrics.control_stale_rejections == 10
    assert result.metrics.treatment_stale_rejections == 20


def test_macro_reality_gate_uses_batch_means_not_single_season_bounds() -> None:
    observations = tuple(
        PairedNBAFrontOfficeOutcome(
            replace(
                item.control,
                macro_metrics=(("champion-seed-mean", 1.0 if index < 5 else 5.0),),
            ),
            replace(
                item.treatment,
                macro_metrics=(("champion-seed-mean", 1.0 if index < 5 else 5.0),),
            ),
        )
        for index, item in enumerate(paired_sources())
    )
    result = evaluate_nba_front_office_policy(
        baseline_policy_id="baseline",
        candidate_policy_id="candidate",
        observations=observations,
        thresholds=thresholds(),
        macro_ranges=(("champion-seed-mean", 2.0, 4.0),),
    )
    assert result.recommended
    assert all(item.observed == pytest.approx(3.0) for item in result.macro_comparisons)
    assert all(item.passed for item in result.macro_comparisons)


def test_macro_reality_gate_rejects_missing_metrics() -> None:
    result = evaluate_nba_front_office_policy(
        baseline_policy_id="baseline",
        candidate_policy_id="candidate",
        observations=paired_sources(),
        thresholds=thresholds(),
        macro_ranges=(("pace", 90.0, 110.0),),
    )
    assert not result.recommended
    assert "manager-macro-reality-gate-failed" in result.hard_rejections
    assert all(not item.passed for item in result.macro_comparisons)


def test_manager_evidence_rejects_invalid_macro_contracts() -> None:
    with pytest.raises(ValueError, match="macro ranges"):
        evaluate_nba_front_office_policy(
            baseline_policy_id="baseline",
            candidate_policy_id="candidate",
            observations=paired_sources(),
            thresholds=thresholds(),
            macro_ranges=(("pace", 110.0, 90.0),),
        )
    with pytest.raises(ValueError, match="macro metrics"):
        replace(outcome("source", 1, 2029, "A", 0.5), macro_metrics=(("pace", float("nan")),))


def test_manager_evidence_rejects_safety_failure() -> None:
    result = evaluate_nba_front_office_policy(
        baseline_policy_id="baseline",
        candidate_policy_id="candidate",
        observations=paired_sources(safety_failure=True),
        thresholds=thresholds(),
    )
    assert not result.recommended
    assert "manager-safety-invariant-failed" in result.hard_rejections


def test_single_source_development_evidence_uses_finite_conservative_ci() -> None:
    result = evaluate_nba_front_office_policy(
        baseline_policy_id="baseline",
        candidate_policy_id="candidate",
        observations=paired_sources()[:5],
        thresholds=thresholds(),
    )
    assert result.metrics.utility_ci_lower_95 == pytest.approx(-0.97)
    assert "insufficient-independent-sources" in result.hard_rejections


def test_manager_evidence_rejects_duplicate_focal_team_coverage() -> None:
    duplicate = tuple(
        PairedNBAFrontOfficeOutcome(
            outcome(
                item.control.source_id, item.control.master_seed, item.control.season_year, "A", 0.5
            ),
            outcome(
                item.control.source_id,
                item.control.master_seed,
                item.control.season_year,
                "A",
                0.53,
            ),
        )
        for item in paired_sources()
    )
    result = evaluate_nba_front_office_policy(
        baseline_policy_id="baseline",
        candidate_policy_id="candidate",
        observations=duplicate,
        thresholds=thresholds(),
    )
    assert "focal-team-coverage-is-not-unique" in result.hard_rejections


def test_outcome_rejects_invalid_counts() -> None:
    with pytest.raises(ValueError, match="accepted negotiations"):
        outcome("source", 1, 2029, "A", 0.5, negotiations_opened=1, negotiations_accepted=2)


@pytest.mark.parametrize(
    ("changes", "message"),
    (
        ({"source_id": ""}, "identity"),
        ({"master_seed": -1}, "seed and season"),
        ({"season_year": 0}, "seed and season"),
        ({"win_rate": float("nan")}, "finite values"),
        ({"negotiations_opened": -1}, "non-negative integers"),
        ({"macro_gate_passed": 1}, "must be boolean"),
        ({"macro_metrics": (("z", 1.0), ("a", 1.0))}, "finite and canonical"),
    ),
)
def test_outcome_rejects_invalid_contract(changes: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        replace(outcome("source", 1, 2029, "A", 0.5), **changes)


def test_evidence_value_objects_reject_invalid_configuration() -> None:
    with pytest.raises(ValueError, match="sum to one"):
        NBAFrontOfficeEvaluationWeights(win_rate=0.0)
    with pytest.raises(ValueError, match="positive integers"):
        NBAFrontOfficeEvidenceThresholds(minimum_independent_sources=0)
    with pytest.raises(ValueError, match="finite"):
        NBAFrontOfficeEvidenceThresholds(minimum_mean_utility_delta=float("nan"))
    with pytest.raises(ValueError, match="rate thresholds"):
        NBAFrontOfficeEvidenceThresholds(maximum_loss_rate=2.0)


def test_paired_outcome_requires_identical_address() -> None:
    with pytest.raises(ValueError, match="exact paired address"):
        PairedNBAFrontOfficeOutcome(
            outcome("source-1", 1, 2029, "A", 0.5),
            outcome("source-2", 1, 2029, "A", 0.5),
        )
