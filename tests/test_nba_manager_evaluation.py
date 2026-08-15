import pytest

from courtsim.nba_manager_evaluation import (
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
