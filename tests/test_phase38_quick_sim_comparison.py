import json
from pathlib import Path

import pytest
from test_game_runtime import PARAMETERS
from test_phase4_season import CONFIG, FRAME, schedule, season_teams

from courtsim.analysis.quick_sim_comparison import (
    QUICK_SIM_COMPARISON_VERSION,
    QUICK_SIM_METRICS,
    QuickSimComparisonError,
    QuickSimMetricRange,
    QuickSimReference,
    QuickSimSeasonSummary,
    compare_quick_sim_summaries,
    load_quick_sim_reference,
    quick_sim_report_to_json,
    summarize_quick_sim_season,
)
from courtsim.season import SeasonConfig, sample_season

ROOT = Path(__file__).resolve().parents[1]


def _summary(season_id: str, *, offensive_rating: float = 112.0) -> QuickSimSeasonSummary:
    return QuickSimSeasonSummary(
        season_id,
        30,
        1_230,
        0.12,
        99.5,
        offensive_rating,
        4.5,
        0.28,
        2,
    )


def _reference() -> QuickSimReference:
    values = {
        "win-rate-stddev": (0.10, 0.14),
        "pace-possessions-per-team": (97.0, 102.0),
        "offensive-rating": (109.0, 115.0),
        "point-differential-stddev": (3.5, 5.5),
        "playoff-upset-rate": (0.20, 0.40),
        "champion-seed-mean": (1.0, 3.0),
    }
    return QuickSimReference(
        "2k-observed-test",
        "controlled test export",
        "2K-test",
        "2026-01-01",
        30,
        10,
        "observed",
        tuple(QuickSimMetricRange(metric, *values[metric]) for metric in QUICK_SIM_METRICS),
    )


def test_template_is_explicitly_incomplete_and_cannot_be_scored() -> None:
    template = load_quick_sim_reference(
        (ROOT / "experiments" / "2k-quick-sim-reference-template-v1.json").read_text(
            encoding="utf-8"
        )
    )
    assert template.source_status == "template"
    assert template.version == QUICK_SIM_COMPARISON_VERSION
    with pytest.raises(QuickSimComparisonError, match="observed"):
        compare_quick_sim_summaries((_summary("season-1"),), template)


def test_observed_reference_scores_every_metric_and_serializes_report() -> None:
    report = compare_quick_sim_summaries(
        (_summary("season-1"), _summary("season-2")),
        _reference(),
    )
    assert report.passed
    assert tuple(item.metric for item in report.comparisons) == QUICK_SIM_METRICS
    raw = json.loads(quick_sim_report_to_json(report))
    assert raw["reference_id"] == "2k-observed-test"
    assert raw["passed"]

    failed = compare_quick_sim_summaries(
        (_summary("season-3", offensive_rating=130.0),),
        _reference(),
    )
    assert not failed.passed
    assert not next(item for item in failed.comparisons if item.metric == "offensive-rating").passed


def test_summary_reads_canonical_season_possessions_and_scores() -> None:
    season = sample_season(
        parameters=PARAMETERS,
        game_config=CONFIG,
        schedule=schedule(1, 2, 3),
        teams=season_teams(),
        frame=FRAME,
        season_config=SeasonConfig(injury_probability_bps=0),
    )
    summary = summarize_quick_sim_season("canonical-season", season)
    assert summary.team_count == 2
    assert summary.games == 3
    assert summary.pace_possessions_per_team > 0
    assert summary.offensive_rating >= 0
    assert summary.playoff_upset_rate is None
