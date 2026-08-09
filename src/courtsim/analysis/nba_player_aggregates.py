"""Compact player-season aggregates for low-memory NBA simulation."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import cast

from courtsim.domain.enums import ShotZone
from courtsim.season import SeasonResult
from courtsim.stats.attribution import StatCode

NBA_PLAYER_AGGREGATE_VERSION = "nba-player-aggregate-v1"


@dataclass(frozen=True, slots=True)
class NBAPlayerSeasonAggregate:
    team_id: str
    player_id: int
    games_available: int
    games_played: int
    seconds_played: int
    usage_rate: float
    true_shooting_percentage: float
    field_goal_attempt_share: float
    shot_zone_shares: tuple[float, float, float]
    shot_zone_percentages: tuple[float, float, float]
    assists: int
    turnovers: int
    rebounds: int
    steals: int
    blocks: int
    defensive_proxy_per_36: float
    rotation_coverage: float
    version: str = NBA_PLAYER_AGGREGATE_VERSION

    @property
    def minutes(self) -> float:
        return self.seconds_played / 60.0

    @property
    def minutes_per_game(self) -> float:
        return _ratio(self.minutes, self.games_played)


def build_nba_player_season_aggregates(
    season: SeasonResult,
) -> tuple[NBAPlayerSeasonAggregate, ...]:
    team_by_player = {
        player_id: roster.team_id
        for roster in season.initial_rosters
        for player_id in roster.player_ids
    }
    games_available: dict[str, int] = defaultdict(int)
    for game in season.schedule.games:
        games_available[game.home_team_id] += 1
        games_available[game.away_team_id] += 1
    seconds: dict[int, int] = defaultdict(int)
    appearances: dict[int, int] = defaultdict(int)
    stats: dict[tuple[int, StatCode], int] = defaultdict(int)
    team_stats: dict[tuple[str, StatCode], int] = defaultdict(int)
    team_seconds: dict[str, int] = defaultdict(int)
    zone_attempts: dict[tuple[int, ShotZone], int] = defaultdict(int)
    zone_makes: dict[tuple[int, ShotZone], int] = defaultdict(int)
    for record in season.games:
        result = record.result
        if result is None:
            continue
        game_team_by_player = {item.player_id: item.team_id for item in result.playing_time}
        for playing_time in result.playing_time:
            seconds[playing_time.player_id] += playing_time.seconds
            team_seconds[playing_time.team_id] += playing_time.seconds
            if playing_time.seconds > 0:
                appearances[playing_time.player_id] += 1
        for stat_delta in result.player_stats:
            stats[(stat_delta.player_id, stat_delta.stat)] += stat_delta.amount
            team_id = game_team_by_player.get(stat_delta.player_id)
            if team_id is not None:
                team_stats[(team_id, stat_delta.stat)] += stat_delta.amount
        for zone_stat in result.player_shot_zones:
            zone_attempts[(zone_stat.player_id, zone_stat.zone)] += zone_stat.attempts
            zone_makes[(zone_stat.player_id, zone_stat.zone)] += zone_stat.makes
    aggregates = []
    for player_id, team_id in sorted(team_by_player.items()):
        fga = stats[(player_id, StatCode.FGA)]
        fta = stats[(player_id, StatCode.FTA)]
        turnovers = stats[(player_id, StatCode.TOV)]
        points = stats[(player_id, StatCode.PTS)]
        player_seconds = seconds[player_id]
        team_usage = (
            team_stats[(team_id, StatCode.FGA)]
            + 0.44 * team_stats[(team_id, StatCode.FTA)]
            + team_stats[(team_id, StatCode.TOV)]
        )
        usage = _ratio(
            (fga + 0.44 * fta + turnovers) * (team_seconds[team_id] / 5.0),
            player_seconds * team_usage,
        )
        attempts = tuple(zone_attempts[(player_id, zone)] for zone in ShotZone)
        makes = tuple(zone_makes[(player_id, zone)] for zone in ShotZone)
        total_attempts = sum(attempts)
        defensive_events = (
            stats[(player_id, StatCode.STL)]
            + stats[(player_id, StatCode.BLK)]
            + 0.25 * stats[(player_id, StatCode.DREB)]
        )
        available = games_available[team_id]
        played = appearances[player_id]
        aggregates.append(
            NBAPlayerSeasonAggregate(
                team_id,
                player_id,
                available,
                played,
                player_seconds,
                usage,
                _ratio(points, 2.0 * (fga + 0.44 * fta)),
                _ratio(fga, team_stats[(team_id, StatCode.FGA)]),
                cast(
                    tuple[float, float, float],
                    tuple(_ratio(value, total_attempts) for value in attempts),
                ),
                cast(
                    tuple[float, float, float],
                    tuple(
                        _ratio(made, attempt) for made, attempt in zip(makes, attempts, strict=True)
                    ),
                ),
                stats[(player_id, StatCode.AST)],
                turnovers,
                stats[(player_id, StatCode.REB)],
                stats[(player_id, StatCode.STL)],
                stats[(player_id, StatCode.BLK)],
                _ratio(defensive_events * 36 * 60, player_seconds),
                _ratio(played, available),
            )
        )
    return tuple(aggregates)


def _ratio(numerator: float, denominator: float) -> float:
    return 0.0 if denominator == 0 else numerator / denominator
