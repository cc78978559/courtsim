"""Canonical game-level configuration and event ledger."""

from __future__ import annotations

from dataclasses import dataclass

from courtsim.domain.enums import GameEndReason, SubstitutionReason
from courtsim.domain.plans import Lineup, validate_lineup
from courtsim.domain.results import PossessionResult, validate_possession_result
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
    offense_lineup: Lineup | None = None
    defense_lineup: Lineup | None = None
    offense_fatigue: tuple[PlayerFatigueSnapshot, ...] = ()
    defense_fatigue: tuple[PlayerFatigueSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class PlayerFatigueSnapshot:
    player_id: int
    fatigue: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.player_id, int)
            or isinstance(self.player_id, bool)
            or self.player_id < 0
        ):
            raise ValueError("fatigue player_id must be non-negative")
        if not isinstance(self.fatigue, int) or isinstance(self.fatigue, bool) or self.fatigue < 0:
            raise ValueError("fatigue must be non-negative")


@dataclass(frozen=True, slots=True)
class SubstitutionRecord:
    team_id: str
    period: int
    clock_seconds: int
    reason: SubstitutionReason
    outgoing_player_id: int
    incoming_player_id: int

    def __post_init__(self) -> None:
        if not isinstance(self.team_id, str) or not self.team_id.strip():
            raise ValueError("substitution team_id must not be blank")
        values = (
            self.period,
            self.clock_seconds,
            self.outgoing_player_id,
            self.incoming_player_id,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise ValueError("substitution values must be integers")
        if self.period < 1 or self.clock_seconds < 0:
            raise ValueError("substitution period and clock are invalid")
        if self.outgoing_player_id < 0 or self.incoming_player_id < 0:
            raise ValueError("substitution player ids must be non-negative")
        if not isinstance(self.reason, SubstitutionReason):
            raise ValueError("substitution reason must be SubstitutionReason")
        if self.outgoing_player_id == self.incoming_player_id:
            raise ValueError("substitution players must be distinct")


@dataclass(frozen=True, slots=True)
class PlayerPlayingTime:
    team_id: str
    player_id: int
    seconds: int

    def __post_init__(self) -> None:
        if not isinstance(self.team_id, str) or not self.team_id.strip():
            raise ValueError("playing-time team_id must not be blank")
        if any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in (self.player_id, self.seconds)
        ):
            raise ValueError("playing-time values must be integers")
        if self.player_id < 0 or self.seconds < 0:
            raise ValueError("playing-time values must be non-negative")


@dataclass(frozen=True, slots=True)
class GameResult:
    home_team_id: str
    away_team_id: str
    possessions: tuple[GamePossessionRecord, ...]
    home_score: int
    away_score: int
    player_stats: tuple[PlayerStatDelta, ...]
    end_reason: GameEndReason
    substitutions: tuple[SubstitutionRecord, ...] = ()
    playing_time: tuple[PlayerPlayingTime, ...] = ()
    final_fatigue: tuple[PlayerFatigueSnapshot, ...] = ()
    rotation_version: str | None = None
    fatigue_version: str | None = None

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
    expected_playing_time: dict[tuple[str, int], int] = {}
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
        if (possession.offense_lineup is None) != (possession.defense_lineup is None):
            raise ValueError("possession lineups must either both be present or both be absent")
        if possession.offense_lineup is not None and possession.defense_lineup is not None:
            validate_lineup(possession.offense_lineup)
            validate_lineup(possession.defense_lineup)
            if set(possession.offense_lineup) & set(possession.defense_lineup):
                raise ValueError("possession lineups must be disjoint")
            validate_possession_result(
                possession.result,
                possession.offense_lineup,
                possession.defense_lineup,
            )
            duration = possession.clock_start_seconds - possession.clock_end_seconds
            for player_id in possession.offense_lineup:
                playing_key = (possession.offense_team_id, player_id)
                expected_playing_time[playing_key] = (
                    expected_playing_time.get(playing_key, 0) + duration
                )
            for player_id in possession.defense_lineup:
                playing_key = (possession.defense_team_id, player_id)
                expected_playing_time[playing_key] = (
                    expected_playing_time.get(playing_key, 0) + duration
                )
            for snapshots, lineup in (
                (possession.offense_fatigue, possession.offense_lineup),
                (possession.defense_fatigue, possession.defense_lineup),
            ):
                if snapshots and {item.player_id for item in snapshots} != set(lineup):
                    raise ValueError("fatigue snapshots must cover the active lineup")
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
    if result.playing_time:
        actual_playing_time = {
            (item.team_id, item.player_id): item.seconds for item in result.playing_time
        }
        if (
            len(actual_playing_time) != len(result.playing_time)
            or actual_playing_time != expected_playing_time
        ):
            raise ValueError("playing time does not match the possession ledger")
    substitution_addresses = tuple(
        (item.period, -item.clock_seconds) for item in result.substitutions
    )
    if substitution_addresses != tuple(sorted(substitution_addresses)):
        raise ValueError("substitutions must be in chronological order")
    if any(
        item.team_id not in {result.home_team_id, result.away_team_id}
        or item.clock_seconds > config.seconds_for_period(item.period)
        for item in result.substitutions
    ):
        raise ValueError("substitution team or clock is invalid")
    substitution_facts = {
        (
            item.team_id,
            item.period,
            item.clock_seconds,
            item.outgoing_player_id,
            item.incoming_player_id,
        )
        for item in result.substitutions
    }
    if len(substitution_facts) != len(result.substitutions):
        raise ValueError("substitution facts must be unique")
    known_players = {item.player_id for item in result.playing_time}
    if not known_players:
        known_players = {
            player_id
            for possession in result.possessions
            for lineup in (possession.offense_lineup, possession.defense_lineup)
            if lineup is not None
            for player_id in lineup
        }
    if known_players and any(
        item.outgoing_player_id not in known_players or item.incoming_player_id not in known_players
        for item in result.substitutions
    ):
        raise ValueError("substitution players must belong to the game roster")
    if len({item.player_id for item in result.final_fatigue}) != len(result.final_fatigue):
        raise ValueError("final fatigue player ids must be unique")
    for version in (result.rotation_version, result.fatigue_version):
        if version is not None and (not isinstance(version, str) or not version.strip()):
            raise ValueError("state versions must be non-empty strings")
