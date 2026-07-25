"""Canonical game-level configuration and event ledger."""

from __future__ import annotations

from dataclasses import dataclass

from courtsim.domain.enums import GameEndReason
from courtsim.domain.results import PossessionResult
from courtsim.stats.attribution import PlayerStatDelta, StatCode, attribute_segment


@dataclass(frozen=True, slots=True)
class GameClockConfig:
    regulation_periods: int = 4
    period_seconds: int = 720
    possession_seconds: int = 15
    overtime_seconds: int = 300
    max_overtimes: int = 8
    overtime_enabled: bool = False

    def __post_init__(self) -> None:
        values = (
            self.regulation_periods,
            self.period_seconds,
            self.possession_seconds,
            self.overtime_seconds,
            self.max_overtimes,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise ValueError("game clock values must be integers")
        if self.regulation_periods < 1:
            raise ValueError("regulation_periods must be positive")
        if self.period_seconds < 1:
            raise ValueError("period_seconds must be positive")
        if not 1 <= self.possession_seconds <= self.period_seconds:
            raise ValueError("possession_seconds must be within the period")
        if self.overtime_seconds < 1:
            raise ValueError("overtime_seconds must be positive")
        if self.possession_seconds > self.overtime_seconds:
            raise ValueError("possession_seconds must be within overtime")
        if self.max_overtimes < 1:
            raise ValueError("max_overtimes must be positive")
        if not isinstance(self.overtime_enabled, bool):
            raise ValueError("overtime_enabled must be a boolean")

    def seconds_for_period(self, period: int) -> int:
        if period < 1:
            raise ValueError("period must be positive")
        return self.period_seconds if period <= self.regulation_periods else self.overtime_seconds


@dataclass(frozen=True, slots=True)
class GamePossessionRecord:
    possession_index: int
    period: int
    clock_start_seconds: int
    clock_end_seconds: int
    offense_team_id: str
    defense_team_id: str
    result: PossessionResult


@dataclass(frozen=True, slots=True)
class GameResult:
    home_team_id: str
    away_team_id: str
    possessions: tuple[GamePossessionRecord, ...]
    home_score: int
    away_score: int
    player_stats: tuple[PlayerStatDelta, ...]
    end_reason: GameEndReason

    @property
    def completed(self) -> bool:
        return self.end_reason in {GameEndReason.REGULATION, GameEndReason.OVERTIME}


def validate_game_result(
    result: GameResult,
    config: GameClockConfig,
    allowed_possession_seconds: tuple[int, ...] | None = None,
) -> None:
    if allowed_possession_seconds is not None and (
        not allowed_possession_seconds
        or any(
            not isinstance(value, int)
            or isinstance(value, bool)
            or not 1 <= value <= max(config.period_seconds, config.overtime_seconds)
            for value in allowed_possession_seconds
        )
        or tuple(sorted(set(allowed_possession_seconds))) != allowed_possession_seconds
    ):
        raise ValueError("allowed possession durations must be unique ascending integers")
    if not result.home_team_id or not result.away_team_id:
        raise ValueError("team ids must not be blank")
    if result.home_team_id == result.away_team_id:
        raise ValueError("team ids must be distinct")
    if result.home_score < 0 or result.away_score < 0:
        raise ValueError("scores must be non-negative")
    if not result.possessions:
        raise ValueError("game must contain at least one possession")
    expected_offense = result.home_team_id
    expected_period = 1
    expected_clock = config.period_seconds
    expected_score = {result.home_team_id: 0, result.away_team_id: 0}
    expected_stats: dict[tuple[int, StatCode], int] = {}
    for index, possession in enumerate(result.possessions):
        if possession.possession_index != index:
            raise ValueError("possession indexes must be contiguous")
        if possession.period != expected_period:
            raise ValueError("period sequence is invalid")
        if possession.clock_start_seconds != expected_clock:
            raise ValueError("game clock is not contiguous")
        if allowed_possession_seconds is None:
            expected_end = max(0, expected_clock - config.possession_seconds)
            if possession.clock_end_seconds != expected_end:
                raise ValueError("possession clock decrement is invalid")
        else:
            actual_duration = expected_clock - possession.clock_end_seconds
            if actual_duration not in allowed_possession_seconds and not (
                possession.clock_end_seconds == 0
                and 0 < actual_duration <= allowed_possession_seconds[-1]
            ):
                raise ValueError("possession clock decrement is not an allowed duration")
            expected_end = possession.clock_end_seconds
        if possession.offense_team_id != expected_offense:
            raise ValueError("offense must alternate after every completed possession")
        expected_defense = (
            result.away_team_id if expected_offense == result.home_team_id else result.home_team_id
        )
        if possession.defense_team_id != expected_defense:
            raise ValueError("defense team does not oppose the offense")
        for segment in possession.result.segments:
            attribution = attribute_segment(segment)
            expected_score[possession.offense_team_id] += attribution.score_delta
            expected_score[possession.defense_team_id] += attribution.opponent_score_delta
            for delta in attribution.player_deltas:
                key = (delta.player_id, delta.stat)
                expected_stats[key] = expected_stats.get(key, 0) + delta.amount
        if not possession.result.completed:
            if index != len(result.possessions) - 1:
                raise ValueError("a truncated possession must end the game")
            break
        expected_offense = expected_defense
        expected_clock = expected_end
        if expected_clock == 0 and index < len(result.possessions) - 1:
            expected_period += 1
            expected_clock = config.seconds_for_period(expected_period)
    last = result.possessions[-1]
    if result.end_reason is GameEndReason.POSSESSION_TRUNCATED:
        if last.result.completed:
            raise ValueError("truncated game requires a truncated final possession")
    elif result.end_reason is GameEndReason.NO_LEGAL_LINEUP:
        if not last.result.completed:
            raise ValueError("no-legal-lineup game requires a completed final possession")
    else:
        if not last.result.completed or last.clock_end_seconds != 0:
            raise ValueError("completed game must exhaust its final period")
        if result.end_reason is GameEndReason.REGULATION:
            if last.period != config.regulation_periods:
                raise ValueError("regulation game must end after regulation")
            if config.overtime_enabled and result.home_score == result.away_score:
                raise ValueError("a tied regulation game requires overtime")
        elif result.end_reason is GameEndReason.OVERTIME:
            if last.period <= config.regulation_periods:
                raise ValueError("overtime game must contain an overtime period")
            if result.home_score == result.away_score:
                raise ValueError("a completed overtime game cannot remain tied")
        elif result.end_reason is GameEndReason.OVERTIME_LIMIT:
            if last.period != config.regulation_periods + config.max_overtimes:
                raise ValueError("overtime-limit game must exhaust configured overtimes")
            if result.home_score != result.away_score:
                raise ValueError("overtime-limit game must remain tied")
    if (result.home_score, result.away_score) != (
        expected_score[result.home_team_id],
        expected_score[result.away_team_id],
    ):
        raise ValueError("game score does not match the possession ledger")
    actual_stats = {(delta.player_id, delta.stat): delta.amount for delta in result.player_stats}
    if len(actual_stats) != len(result.player_stats) or actual_stats != expected_stats:
        raise ValueError("player stats do not match the possession ledger")
