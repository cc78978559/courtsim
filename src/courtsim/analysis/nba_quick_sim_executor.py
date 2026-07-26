"""Canonical thirty-team CourtSim quick-season execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import cast

from courtsim.analysis.quick_sim_comparison import (
    QuickSimSeasonSummary,
    summarize_quick_sim_season,
)
from courtsim.domain.game import GameClockConfig
from courtsim.model.game_runtime import GameMatchups, GameTeam, sample_game
from courtsim.model.interaction_compiler import DefensiveMatchups, Matchup
from courtsim.model.trace_mode import TraceMode
from courtsim.nba_league import (
    NBAConferenceAlignment,
    NBAPostseasonResult,
    NBASeriesResult,
    PlayInGame,
    PlayInResult,
    generate_nba_schedule,
    resolve_nba_playoffs,
    resolve_play_in,
)
from courtsim.parameters import ModelParameters
from courtsim.playoffs import PlayoffConfig, PlayoffSeed
from courtsim.randomness import RandomFrame, RandomFrameAddress, derive_seed
from courtsim.rotations import FatigueConfig
from courtsim.rules import GameRules
from courtsim.season import SeasonConfig, SeasonResult, sample_season

NBA_QUICK_SIM_EXECUTOR_VERSION = "nba-quick-sim-executor-v1"


@dataclass(frozen=True, slots=True)
class NBAQuickSimExecution:
    season: SeasonResult
    east_play_in: PlayInResult
    west_play_in: PlayInResult
    postseason: NBAPostseasonResult
    summary: QuickSimSeasonSummary
    version: str = NBA_QUICK_SIM_EXECUTOR_VERSION


@dataclass(frozen=True, slots=True)
class NBAQuickSimExecutor:
    parameters: ModelParameters
    game_config: GameClockConfig
    teams: tuple[GameTeam, ...]
    alignment: NBAConferenceAlignment
    game_rules: GameRules = field(default_factory=GameRules)
    fatigue_config: FatigueConfig = field(default_factory=FatigueConfig)
    season_config: SeasonConfig = field(default_factory=SeasonConfig)
    playoff_config: PlayoffConfig = field(default_factory=PlayoffConfig)
    trace_mode: TraceMode = TraceMode.AGGREGATE_ONLY
    version: str = NBA_QUICK_SIM_EXECUTOR_VERSION

    def __post_init__(self) -> None:
        team_ids = tuple(team.team_id for team in self.teams)
        if len(self.teams) != 30 or team_ids != tuple(sorted(set(team_ids))):
            raise ValueError("NBA quick simulation requires thirty ordered unique teams")
        if set((*self.alignment.east_team_ids, *self.alignment.west_team_ids)) != set(team_ids):
            raise ValueError("NBA quick simulation alignment must cover every team")
        player_ids = tuple(player_id for team in self.teams for player_id in team.roster_order)
        if len(player_ids) != len(set(player_ids)):
            raise ValueError("NBA quick simulation player ids must be league-unique")
        if not self.game_config.overtime_enabled:
            raise ValueError("NBA quick simulation requires overtime")
        if self.playoff_config.best_of != 7:
            raise ValueError("NBA quick simulation requires best-of-seven series")
        if self.version != NBA_QUICK_SIM_EXECUTOR_VERSION:
            raise ValueError("unsupported NBA quick simulation executor version")

    def __call__(self, season_id: str, seed: int) -> QuickSimSeasonSummary:
        return self.execute(season_id, seed).summary

    def execute(self, season_id: str, seed: int) -> NBAQuickSimExecution:
        if not season_id.strip():
            raise ValueError("NBA quick simulation season_id must not be blank")
        schedule = generate_nba_schedule(
            tuple(team.team_id for team in self.teams),
            alignment=self.alignment,
        )
        season = sample_season(
            parameters=self.parameters,
            game_config=self.game_config,
            schedule=schedule,
            teams=self.teams,
            frame=RandomFrame(seed, RandomFrameAddress(season_id, 0, 0, 0, 0)),
            rules=self.game_rules,
            fatigue_config=self.fatigue_config,
            season_config=self.season_config,
            trace_mode=self.trace_mode,
        )
        east_regular = _conference_seeds(season, self.alignment.east_team_ids)
        west_regular = _conference_seeds(season, self.alignment.west_team_ids)
        team_map = {team.team_id: team for team in self.teams}
        east_play_in = _sample_play_in(
            conference="east",
            seeds=east_regular,
            team_map=team_map,
            master_seed=seed,
            parameters=self.parameters,
            config=self.game_config,
            rules=self.game_rules,
            fatigue_config=self.fatigue_config,
            trace_mode=self.trace_mode,
        )
        west_play_in = _sample_play_in(
            conference="west",
            seeds=west_regular,
            team_map=team_map,
            master_seed=seed,
            parameters=self.parameters,
            config=self.game_config,
            rules=self.game_rules,
            fatigue_config=self.fatigue_config,
            trace_mode=self.trace_mode,
        )
        postseason = _sample_postseason(
            east_play_in.playoff_seeds,
            west_play_in.playoff_seeds,
            team_map=team_map,
            master_seed=seed,
            parameters=self.parameters,
            config=self.game_config,
            rules=self.game_rules,
            fatigue_config=self.fatigue_config,
            playoff_config=self.playoff_config,
            trace_mode=self.trace_mode,
        )
        return NBAQuickSimExecution(
            season,
            east_play_in,
            west_play_in,
            postseason,
            summarize_quick_sim_season(season_id, season, postseason),
        )


def _conference_seeds(
    season: SeasonResult,
    team_ids: tuple[str, ...],
) -> tuple[PlayoffSeed, ...]:
    conference = set(team_ids)
    rows = sorted(
        (row for row in season.standings if row.team_id in conference),
        key=lambda row: (
            -(row.wins * 2 + row.ties),
            -row.point_differential,
            row.team_id,
        ),
    )
    return tuple(PlayoffSeed(index + 1, row.team_id) for index, row in enumerate(rows[:10]))


def _sample_play_in(
    *,
    conference: str,
    seeds: tuple[PlayoffSeed, ...],
    team_map: dict[str, GameTeam],
    master_seed: int,
    parameters: ModelParameters,
    config: GameClockConfig,
    rules: GameRules,
    fatigue_config: FatigueConfig,
    trace_mode: TraceMode,
) -> PlayInResult:
    by_seed = {item.seed: item.team_id for item in seeds}
    first_score = _decisive_score(
        by_seed[7],
        by_seed[8],
        address=(conference, "play-in", 1),
        team_map=team_map,
        master_seed=master_seed,
        parameters=parameters,
        config=config,
        rules=rules,
        fatigue_config=fatigue_config,
        trace_mode=trace_mode,
    )
    first = PlayInGame(1, by_seed[7], by_seed[8], *first_score)
    second_score = _decisive_score(
        by_seed[9],
        by_seed[10],
        address=(conference, "play-in", 2),
        team_map=team_map,
        master_seed=master_seed,
        parameters=parameters,
        config=config,
        rules=rules,
        fatigue_config=fatigue_config,
        trace_mode=trace_mode,
    )
    second = PlayInGame(2, by_seed[9], by_seed[10], *second_score)
    third_score = _decisive_score(
        first.loser_team_id,
        second.winner_team_id,
        address=(conference, "play-in", 3),
        team_map=team_map,
        master_seed=master_seed,
        parameters=parameters,
        config=config,
        rules=rules,
        fatigue_config=fatigue_config,
        trace_mode=trace_mode,
    )
    third = PlayInGame(
        3,
        first.loser_team_id,
        second.winner_team_id,
        *third_score,
    )
    return resolve_play_in(
        conference=conference,
        seeds=seeds,
        games=(first, second, third),
    )


def _sample_postseason(
    east_seeds: tuple[PlayoffSeed, ...],
    west_seeds: tuple[PlayoffSeed, ...],
    *,
    team_map: dict[str, GameTeam],
    master_seed: int,
    parameters: ModelParameters,
    config: GameClockConfig,
    rules: GameRules,
    fatigue_config: FatigueConfig,
    playoff_config: PlayoffConfig,
    trace_mode: TraceMode,
) -> NBAPostseasonResult:
    seed_numbers = {item.team_id: item.seed for item in (*east_seeds, *west_seeds)}
    ledger: list[NBASeriesResult] = []

    def series(
        round_number: int,
        series_index: int,
        conference: str,
        first: str,
        second: str,
    ) -> str:
        result = _sample_series(
            round_number,
            series_index,
            conference,
            first,
            second,
            seed_numbers=seed_numbers,
            team_map=team_map,
            master_seed=master_seed,
            parameters=parameters,
            config=config,
            rules=rules,
            fatigue_config=fatigue_config,
            playoff_config=playoff_config,
            trace_mode=trace_mode,
        )
        ledger.append(result)
        return result.winner_team_id

    east = {item.seed: item.team_id for item in east_seeds}
    west = {item.seed: item.team_id for item in west_seeds}
    east_first = (
        series(1, 1, "east", east[1], east[8]),
        series(1, 2, "east", east[4], east[5]),
        series(1, 3, "east", east[2], east[7]),
        series(1, 4, "east", east[3], east[6]),
    )
    west_first = (
        series(1, 5, "west", west[1], west[8]),
        series(1, 6, "west", west[4], west[5]),
        series(1, 7, "west", west[2], west[7]),
        series(1, 8, "west", west[3], west[6]),
    )
    east_second = (
        series(2, 1, "east", east_first[0], east_first[1]),
        series(2, 2, "east", east_first[2], east_first[3]),
    )
    west_second = (
        series(2, 1, "west", west_first[0], west_first[1]),
        series(2, 2, "west", west_first[2], west_first[3]),
    )
    east_champion = series(3, 1, "east", *east_second)
    west_champion = series(3, 1, "west", *west_second)
    series(4, 1, "nba", east_champion, west_champion)
    return resolve_nba_playoffs(
        east_seeds=east_seeds,
        west_seeds=west_seeds,
        series=tuple(ledger),
    )


def _sample_series(
    round_number: int,
    series_index: int,
    conference: str,
    first: str,
    second: str,
    *,
    seed_numbers: dict[str, int],
    team_map: dict[str, GameTeam],
    master_seed: int,
    parameters: ModelParameters,
    config: GameClockConfig,
    rules: GameRules,
    fatigue_config: FatigueConfig,
    playoff_config: PlayoffConfig,
    trace_mode: TraceMode,
) -> NBASeriesResult:
    higher, lower = sorted(
        (first, second),
        key=lambda team_id: (seed_numbers[team_id], team_id),
    )
    wins = {first: 0, second: 0}
    game_number = 1
    while max(wins.values()) < playoff_config.wins_required:
        higher_home = playoff_config.higher_seed_home[game_number - 1]
        home, away = (higher, lower) if higher_home else (lower, higher)
        home_score, away_score = _decisive_score(
            home,
            away,
            address=(conference, round_number, series_index, game_number),
            team_map=team_map,
            master_seed=master_seed,
            parameters=parameters,
            config=config,
            rules=rules,
            fatigue_config=fatigue_config,
            trace_mode=trace_mode,
        )
        wins[home if home_score > away_score else away] += 1
        game_number += 1
    return NBASeriesResult(
        round_number,
        series_index,
        conference,
        first,
        second,
        wins[first],
        wins[second],
    )


def _decisive_score(
    home_team_id: str,
    away_team_id: str,
    *,
    address: tuple[object, ...],
    team_map: dict[str, GameTeam],
    master_seed: int,
    parameters: ModelParameters,
    config: GameClockConfig,
    rules: GameRules,
    fatigue_config: FatigueConfig,
    trace_mode: TraceMode,
) -> tuple[int, int]:
    home = team_map[home_team_id]
    away = team_map[away_team_id]
    for attempt in range(100):
        game_seed = derive_seed(
            master_seed,
            NBA_QUICK_SIM_EXECUTOR_VERSION,
            *address,
            attempt,
        )
        sampled = sample_game(
            parameters=parameters,
            config=config,
            home=home,
            away=away,
            matchups=_matchups(home, away),
            frame=RandomFrame(
                game_seed,
                RandomFrameAddress(
                    f"nba-postseason:{address[0]}",
                    attempt,
                    0,
                    0,
                    0,
                ),
            ),
            rules=rules,
            fatigue_config=fatigue_config,
            trace_mode=trace_mode,
        )
        if sampled.result.home_score != sampled.result.away_score:
            return sampled.result.home_score, sampled.result.away_score
    raise RuntimeError("NBA postseason game remained tied after deterministic retries")


def _matchups(home: GameTeam, away: GameTeam) -> GameMatchups:
    return GameMatchups(
        DefensiveMatchups(
            cast(
                tuple[Matchup, Matchup, Matchup, Matchup, Matchup],
                tuple(
                    Matchup(offender, defender)
                    for offender, defender in zip(home.lineup, away.lineup, strict=True)
                ),
            )
        ),
        DefensiveMatchups(
            cast(
                tuple[Matchup, Matchup, Matchup, Matchup, Matchup],
                tuple(
                    Matchup(offender, defender)
                    for offender, defender in zip(away.lineup, home.lineup, strict=True)
                ),
            )
        ),
    )
