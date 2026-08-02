from courtsim.analysis.quick_sim_comparison import QuickSimSeasonSummary
from courtsim.analysis.quick_sim_consistency import (
    build_aggregate_sensitivity_report,
    compare_quick_sim_engines,
)


def _summary(season: str, pace: float, champion: int = 2) -> QuickSimSeasonSummary:
    return QuickSimSeasonSummary(season, 30, 1230, 0.14, pace, 115.0, 4.5, 0.35, champion)


def test_consistency_report_requires_a_frozen_accuracy_gate_for_promotion() -> None:
    aggregate = {seed: _summary(str(seed), 99.0) for seed in (1, 2)}
    full = {seed: _summary(str(seed), 98.0) for seed in (1, 2)}
    partial = compare_quick_sim_engines(aggregate, full)
    assert partial["paired_seasons"] == 2
    assert partial["sample_ready"] is False
    assert partial["promotion_ready"] is False
    aggregate[3] = _summary("3", 99.0)
    full[3] = _summary("3", 98.0)
    complete = compare_quick_sim_engines(aggregate, full)
    assert complete["sample_ready"] is True
    assert complete["accuracy_gate"] == {"configured": False, "passed": None}
    assert complete["promotion_ready"] is False


def test_sensitivity_report_is_paired_and_single_factor() -> None:
    baseline = {seed: _summary(str(seed), 99.0) for seed in (1, 2, 3)}
    report = build_aggregate_sensitivity_report(
        baseline,
        {
            "home-low": {seed: _summary(str(seed), 99.0, 3) for seed in baseline},
            "pace-sd-high": {seed: _summary(str(seed), 100.0) for seed in baseline},
        },
        changed_factors={
            "home-low": ("home_advantage_points", 1.5),
            "pace-sd-high": ("pace_standard_deviation", 5.0),
        },
    )
    assert report["single_factor_required"] is True
    variants = report["variants"]
    assert isinstance(variants, list)
    assert len(variants) == 2
