from dataclasses import fields

import pytest
from test_game_runtime import player

from courtsim.career import CareerStatus
from courtsim.domain.player import AbilityRatings
from courtsim.prospects import generate_prospect_class
from courtsim.scouting import ScoutingRules, generate_scouting_reports


def prospects():
    return generate_prospect_class(
        draft_year=2030,
        master_seed=77,
        templates=(player(1), player(2)),
    ).players


def test_scouting_is_team_specific_deterministic_and_hides_truth() -> None:
    first = generate_scouting_reports(
        prospects=prospects(),
        scouts={"A": "manager-A", "B": "manager-B"},
        master_seed=91,
    )
    second = generate_scouting_reports(
        prospects=prospects(),
        scouts={"B": "manager-B", "A": "manager-A"},
        master_seed=91,
    )
    assert first == second
    report_a = next(report for report in first if report.team_id == "A")
    report_b = next(
        report
        for report in first
        if report.team_id == "B" and report.player_id == report_a.player_id
    )
    assert report_a.estimated_potential != report_b.estimated_potential
    truth = next(item.potential for item in prospects() if item.player_id == report_a.player_id)
    assert report_a.estimated_potential != truth


def test_repeated_exposure_reduces_error_bound_and_increases_confidence() -> None:
    target = prospects()[0]
    rules = ScoutingRules()
    reports = generate_scouting_reports(
        prospects=(target,),
        scouts={"A": "manager-A"},
        master_seed=91,
        exposures={("A", target.player_id): rules.maximum_exposures},
        rules=rules,
    )
    report = reports[0]
    expected_uncertainty = max(
        rules.minimum_uncertainty,
        rules.base_uncertainty - rules.maximum_exposures * rules.uncertainty_reduction_per_exposure,
    )
    assert report.uncertainty == expected_uncertainty
    assert report.confidence == 100 - expected_uncertainty * 4
    for item in fields(AbilityRatings):
        estimate = getattr(report.estimated_potential, item.name)
        truth = getattr(target.potential, item.name)
        assert abs(estimate - truth) <= expected_uncertainty


def test_scouting_rejects_non_prospects_and_invalid_exposure() -> None:
    active = prospects()[0]
    with pytest.raises(ValueError, match="only evaluate prospects"):
        generate_scouting_reports(
            prospects=(
                active.__class__(
                    active.profile,
                    active.age,
                    active.seasons_pro,
                    active.development,
                    active.potential,
                    CareerStatus.ACTIVE,
                ),
            ),
            scouts={"A": "manager-A"},
            master_seed=1,
        )
    with pytest.raises(ValueError, match="exposure"):
        generate_scouting_reports(
            prospects=(active,),
            scouts={"A": "manager-A"},
            master_seed=1,
            exposures={("A", active.player_id): 99},
        )
