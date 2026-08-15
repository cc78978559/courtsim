"""Versioned multi-season comparison for basketball quick-simulation outputs."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from statistics import fmean, pstdev
from typing import cast

from courtsim.nba_league import NBAPostseasonResult
from courtsim.playoffs import PlayoffResult
from courtsim.season import SeasonResult

QUICK_SIM_COMPARISON_VERSION = "quick-sim-comparison-v1"
QUICK_SIM_METRICS = (
    "win-rate-stddev",
    "pace-possessions-per-team",
    "offensive-rating",
    "point-differential-stddev",
    "playoff-upset-rate",
    "champion-seed-mean",
)


class QuickSimComparisonError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class QuickSimSeasonSummary:
    season_id: str
    team_count: int
    games: int
    win_rate_stddev: float
    pace_possessions_per_team: float
    offensive_rating: float
    point_differential_stddev: float
    playoff_upset_rate: float | None
    champion_seed: int | None
    team_rank_order: tuple[str, ...] | None = None
    home_win_rate: float | None = None

    def __post_init__(self) -> None:
        if not self.season_id.strip() or self.team_count < 2 or self.games < 1:
            raise ValueError("quick-sim season identity or size is invalid")
        metrics = (
            self.win_rate_stddev,
            self.pace_possessions_per_team,
            self.offensive_rating,
            self.point_differential_stddev,
        )
        if any(not math.isfinite(value) or value < 0 for value in metrics):
            raise ValueError("quick-sim season metrics must be finite and non-negative")
        if self.playoff_upset_rate is not None and not 0 <= self.playoff_upset_rate <= 1:
            raise ValueError("quick-sim playoff upset rate is invalid")
        if self.champion_seed is not None and self.champion_seed < 1:
            raise ValueError("quick-sim champion seed is invalid")
        if (self.playoff_upset_rate is None) != (self.champion_seed is None):
            raise ValueError("quick-sim postseason metrics must be present together")
        if self.team_rank_order is not None and (
            len(self.team_rank_order) != self.team_count
            or len(set(self.team_rank_order)) != self.team_count
            or any(not team_id.strip() for team_id in self.team_rank_order)
        ):
            raise ValueError("quick-sim team rank order must contain every unique team")
        if self.home_win_rate is not None and not 0 <= self.home_win_rate <= 1:
            raise ValueError("quick-sim home win rate is invalid")


@dataclass(frozen=True, slots=True)
class QuickSimMetricRange:
    metric: str
    minimum: float | None
    maximum: float | None

    def __post_init__(self) -> None:
        if self.metric not in QUICK_SIM_METRICS:
            raise ValueError("unsupported quick-sim metric")
        if (self.minimum is None) != (self.maximum is None):
            raise ValueError("quick-sim metric bounds must both be present or absent")
        if (
            self.minimum is not None
            and self.maximum is not None
            and (
                not math.isfinite(self.minimum)
                or not math.isfinite(self.maximum)
                or self.minimum > self.maximum
            )
        ):
            raise ValueError("quick-sim metric bounds are invalid")

    @property
    def complete(self) -> bool:
        return self.minimum is not None


@dataclass(frozen=True, slots=True)
class QuickSimReference:
    reference_id: str
    source_label: str
    game_version: str
    roster_date: str
    team_count: int
    observed_seasons: int
    source_status: str
    metrics: tuple[QuickSimMetricRange, ...]
    version: str = QUICK_SIM_COMPARISON_VERSION

    def __post_init__(self) -> None:
        if not all(
            value.strip()
            for value in (
                self.reference_id,
                self.source_label,
                self.game_version,
                self.roster_date,
            )
        ):
            raise ValueError("quick-sim reference identity must not be blank")
        if self.team_count < 2 or self.observed_seasons < 0:
            raise ValueError("quick-sim reference sample size is invalid")
        if self.source_status not in {"template", "observed"}:
            raise ValueError("quick-sim reference status is invalid")
        if tuple(item.metric for item in self.metrics) != QUICK_SIM_METRICS:
            raise ValueError("quick-sim reference metrics must use canonical order")
        if self.source_status == "template" and (
            self.observed_seasons != 0 or any(item.complete for item in self.metrics)
        ):
            raise ValueError("quick-sim template cannot contain observed targets")
        if self.source_status == "observed" and (
            self.observed_seasons < 1 or not all(item.complete for item in self.metrics)
        ):
            raise ValueError("observed quick-sim reference must be complete")
        if self.version != QUICK_SIM_COMPARISON_VERSION:
            raise ValueError("unsupported quick-sim comparison version")


@dataclass(frozen=True, slots=True)
class QuickSimMetricComparison:
    metric: str
    observed: float
    target_minimum: float
    target_maximum: float
    passed: bool


@dataclass(frozen=True, slots=True)
class QuickSimComparisonReport:
    reference_id: str
    seasons: int
    team_count: int
    comparisons: tuple[QuickSimMetricComparison, ...]
    passed: bool
    version: str = QUICK_SIM_COMPARISON_VERSION


def summarize_quick_sim_season(
    season_id: str,
    season: SeasonResult,
    postseason: PlayoffResult | NBAPostseasonResult | None = None,
) -> QuickSimSeasonSummary:
    team_count = len(season.schedule.team_ids)
    completed = tuple(record for record in season.games if record.result is not None)
    if not completed:
        raise QuickSimComparisonError("quick-sim season has no completed games")
    standings_games = tuple(row.wins + row.losses + row.ties for row in season.standings)
    if any(games < 1 for games in standings_games):
        raise QuickSimComparisonError("quick-sim standings include a team without games")
    win_rates = tuple(
        (row.wins + row.ties * 0.5) / games
        for row, games in zip(season.standings, standings_games, strict=True)
    )
    point_differentials = tuple(
        row.point_differential / games
        for row, games in zip(season.standings, standings_games, strict=True)
    )
    possessions = sum(
        (
            record.result.home_possessions + record.result.away_possessions
            if record.result.possessions_omitted
            else len(record.result.possessions)
        )
        for record in completed
        if record.result is not None
    )
    points = sum(record.home_score + record.away_score for record in completed)
    home_win_rate = sum(record.home_score > record.away_score for record in completed) / len(
        completed
    )
    upset_rate, champion_seed = _postseason_metrics(postseason)
    return QuickSimSeasonSummary(
        season_id,
        team_count,
        len(completed),
        pstdev(win_rates),
        possessions / (2 * len(completed)),
        points * 100 / possessions,
        pstdev(point_differentials),
        upset_rate,
        champion_seed,
        tuple(row.team_id for row in season.standings),
        home_win_rate,
    )


def compare_quick_sim_summaries(
    summaries: tuple[QuickSimSeasonSummary, ...],
    reference: QuickSimReference,
) -> QuickSimComparisonReport:
    if reference.source_status != "observed":
        raise QuickSimComparisonError("quick-sim comparison requires observed reference data")
    if not summaries:
        raise QuickSimComparisonError("quick-sim comparison requires at least one season")
    if any(summary.team_count != reference.team_count for summary in summaries):
        raise QuickSimComparisonError("quick-sim team count does not match the reference")
    if len({summary.season_id for summary in summaries}) != len(summaries):
        raise QuickSimComparisonError("quick-sim season ids must be unique")
    values = _aggregate_metric_values(summaries)
    comparisons = tuple(
        QuickSimMetricComparison(
            target.metric,
            values[target.metric],
            cast(float, target.minimum),
            cast(float, target.maximum),
            cast(float, target.minimum) <= values[target.metric] <= cast(float, target.maximum),
        )
        for target in reference.metrics
    )
    return QuickSimComparisonReport(
        reference.reference_id,
        len(summaries),
        reference.team_count,
        comparisons,
        all(item.passed for item in comparisons),
    )


def build_quick_sim_reference(
    summaries: tuple[QuickSimSeasonSummary, ...],
    *,
    reference_id: str,
    source_label: str,
    game_version: str,
    roster_date: str,
) -> QuickSimReference:
    if not summaries:
        raise QuickSimComparisonError("quick-sim reference requires observed seasons")
    team_count = summaries[0].team_count
    if any(item.team_count != team_count for item in summaries):
        raise QuickSimComparisonError("quick-sim reference seasons must use one team count")
    if len({item.season_id for item in summaries}) != len(summaries):
        raise QuickSimComparisonError("quick-sim reference season ids must be unique")
    per_season = tuple(_season_metric_values(item) for item in summaries)
    metrics = tuple(
        QuickSimMetricRange(
            metric,
            min(values[metric] for values in per_season),
            max(values[metric] for values in per_season),
        )
        for metric in QUICK_SIM_METRICS
    )
    return QuickSimReference(
        reference_id,
        source_label,
        game_version,
        roster_date,
        team_count,
        len(summaries),
        "observed",
        metrics,
    )


def _aggregate_metric_values(
    summaries: tuple[QuickSimSeasonSummary, ...],
) -> dict[str, float]:
    return {
        "win-rate-stddev": fmean(item.win_rate_stddev for item in summaries),
        "pace-possessions-per-team": fmean(item.pace_possessions_per_team for item in summaries),
        "offensive-rating": fmean(item.offensive_rating for item in summaries),
        "point-differential-stddev": fmean(item.point_differential_stddev for item in summaries),
        "playoff-upset-rate": fmean(
            cast(float, _required_postseason(item).playoff_upset_rate) for item in summaries
        ),
        "champion-seed-mean": fmean(
            cast(int, _required_postseason(item).champion_seed) for item in summaries
        ),
    }


def _season_metric_values(summary: QuickSimSeasonSummary) -> dict[str, float]:
    postseason = _required_postseason(summary)
    return {
        "win-rate-stddev": summary.win_rate_stddev,
        "pace-possessions-per-team": summary.pace_possessions_per_team,
        "offensive-rating": summary.offensive_rating,
        "point-differential-stddev": summary.point_differential_stddev,
        "playoff-upset-rate": cast(float, postseason.playoff_upset_rate),
        "champion-seed-mean": float(cast(int, postseason.champion_seed)),
    }


def load_quick_sim_reference(payload: str) -> QuickSimReference:
    try:
        raw = json.loads(payload)
    except json.JSONDecodeError as error:
        raise QuickSimComparisonError("invalid quick-sim reference JSON") from error
    if not isinstance(raw, dict) or set(raw) != {
        "version",
        "reference_id",
        "source_label",
        "game_version",
        "roster_date",
        "team_count",
        "observed_seasons",
        "source_status",
        "metrics",
    }:
        raise QuickSimComparisonError("invalid quick-sim reference keys")
    metrics_raw = raw["metrics"]
    if not isinstance(metrics_raw, list):
        raise QuickSimComparisonError("quick-sim reference metrics must be a list")
    metrics = []
    for item in metrics_raw:
        if not isinstance(item, dict) or set(item) != {"metric", "minimum", "maximum"}:
            raise QuickSimComparisonError("invalid quick-sim metric target")
        minimum = item["minimum"]
        maximum = item["maximum"]
        metrics.append(
            QuickSimMetricRange(
                str(item["metric"]),
                None if minimum is None else float(minimum),
                None if maximum is None else float(maximum),
            )
        )
    return QuickSimReference(
        str(raw["reference_id"]),
        str(raw["source_label"]),
        str(raw["game_version"]),
        str(raw["roster_date"]),
        int(raw["team_count"]),
        int(raw["observed_seasons"]),
        str(raw["source_status"]),
        tuple(metrics),
        str(raw["version"]),
    )


def quick_sim_reference_to_json(reference: QuickSimReference) -> str:
    return json.dumps(
        {
            "version": reference.version,
            "reference_id": reference.reference_id,
            "source_label": reference.source_label,
            "game_version": reference.game_version,
            "roster_date": reference.roster_date,
            "team_count": reference.team_count,
            "observed_seasons": reference.observed_seasons,
            "source_status": reference.source_status,
            "metrics": [
                {
                    "metric": item.metric,
                    "minimum": item.minimum,
                    "maximum": item.maximum,
                }
                for item in reference.metrics
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def quick_sim_report_to_json(report: QuickSimComparisonReport) -> str:
    return json.dumps(
        {
            "version": report.version,
            "reference_id": report.reference_id,
            "seasons": report.seasons,
            "team_count": report.team_count,
            "passed": report.passed,
            "comparisons": [
                {
                    "metric": item.metric,
                    "observed": item.observed,
                    "target_minimum": item.target_minimum,
                    "target_maximum": item.target_maximum,
                    "passed": item.passed,
                }
                for item in report.comparisons
            ],
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _required_postseason(summary: QuickSimSeasonSummary) -> QuickSimSeasonSummary:
    if summary.playoff_upset_rate is None or summary.champion_seed is None:
        raise QuickSimComparisonError("quick-sim comparison requires postseason metrics")
    return summary


def _postseason_metrics(
    postseason: PlayoffResult | NBAPostseasonResult | None,
) -> tuple[float | None, int | None]:
    if postseason is None:
        return None, None
    if isinstance(postseason, PlayoffResult):
        seed_by_team = {item.team_id: item.seed for item in postseason.seeds}
        upsets = sum(
            seed_by_team[series.winner_team_id]
            > min(series.higher_seed.seed, series.lower_seed.seed)
            for series in postseason.series
        )
        return upsets / len(postseason.series), seed_by_team[postseason.champion_team_id]
    seed_by_team = {
        item.team_id: item.seed for item in (*postseason.east_seeds, *postseason.west_seeds)
    }
    upsets = sum(
        seed_by_team[series.winner_team_id]
        > min(seed_by_team[series.first_team_id], seed_by_team[series.second_team_id])
        for series in postseason.series
    )
    return upsets / len(postseason.series), seed_by_team[postseason.champion_team_id]
