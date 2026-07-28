"""Canonical thirty-team CourtSim quick-season execution."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import cast

from courtsim.analysis.quick_sim_comparison import (
    QuickSimSeasonSummary,
    summarize_quick_sim_season,
)
from courtsim.career import CareerPlayer, CareerStatus, PlayerSeasonSummary
from courtsim.domain.game import GameClockConfig
from courtsim.manager_learning import (
    OpponentObservationTotals,
    opponent_observation_totals_from_game,
)
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
from courtsim.season import (
    INJURY_VERSION,
    InjuryRecord,
    PlayerSeasonState,
    ScheduledGame,
    SeasonConfig,
    SeasonResult,
    available_game_team,
    sample_season,
)

NBA_QUICK_SIM_EXECUTOR_VERSION = "nba-quick-sim-executor-v5"


@dataclass(frozen=True, slots=True)
class NBAQuickSimMatchupTeam:
    opponent_team_id: str
    team: GameTeam

    def __post_init__(self) -> None:
        if not self.opponent_team_id.strip() or self.opponent_team_id == self.team.team_id:
            raise ValueError("NBA matchup team requires a distinct opponent")


@dataclass(frozen=True, slots=True)
class NBAQuickSimPostseasonGame:
    game_index: int
    day: int
    address: tuple[str, ...]
    home_team_id: str
    away_team_id: str
    home_score: int
    away_score: int
    home_unavailable: tuple[int, ...]
    away_unavailable: tuple[int, ...]
    forfeit_team_id: str | None


@dataclass(frozen=True, slots=True)
class NBAQuickSimPostseasonState:
    initial_player_states: tuple[PlayerSeasonState, ...]
    final_player_states: tuple[PlayerSeasonState, ...]
    injuries: tuple[InjuryRecord, ...]
    games: tuple[NBAQuickSimPostseasonGame, ...]
    player_seconds: tuple[tuple[int, int], ...]
    player_games: tuple[tuple[int, int], ...]
    team_games: tuple[tuple[str, int], ...]
    learning_totals: tuple[OpponentObservationTotals, ...]


@dataclass(frozen=True, slots=True)
class NBAQuickSimExecution:
    season: SeasonResult
    east_play_in: PlayInResult
    west_play_in: PlayInResult
    postseason: NBAPostseasonResult
    postseason_state: NBAQuickSimPostseasonState
    summary: QuickSimSeasonSummary
    matchup_team_count: int = 0
    version: str = NBA_QUICK_SIM_EXECUTOR_VERSION


@dataclass(frozen=True, slots=True)
class NBAQuickSimExecutor:
    parameters: ModelParameters
    game_config: GameClockConfig
    teams: tuple[GameTeam, ...]
    alignment: NBAConferenceAlignment
    matchup_teams: tuple[NBAQuickSimMatchupTeam, ...] = ()
    game_rules: GameRules = field(default_factory=GameRules)
    fatigue_config: FatigueConfig = field(default_factory=FatigueConfig)
    season_config: SeasonConfig = field(default_factory=SeasonConfig)
    playoff_config: PlayoffConfig = field(default_factory=PlayoffConfig)
    trace_mode: TraceMode = TraceMode.AGGREGATE_ONLY
    postseason_rest_days: int = 2
    playoff_game_rest_days: int = 1
    playoff_round_rest_days: int = 2
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
        matchup_keys = tuple(
            (item.team.team_id, item.opponent_team_id) for item in self.matchup_teams
        )
        if matchup_keys != tuple(sorted(set(matchup_keys))):
            raise ValueError("NBA matchup teams must use canonical unique order")
        team_map = {team.team_id: team for team in self.teams}
        for item in self.matchup_teams:
            base = team_map.get(item.team.team_id)
            if (
                base is None
                or item.opponent_team_id not in team_map
                or set(item.team.roster_order) != set(base.roster_order)
            ):
                raise ValueError("NBA matchup teams must preserve league identity and roster")
        if not self.game_config.overtime_enabled:
            raise ValueError("NBA quick simulation requires overtime")
        if self.playoff_config.best_of != 7:
            raise ValueError("NBA quick simulation requires best-of-seven series")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0
            for value in (
                self.postseason_rest_days,
                self.playoff_game_rest_days,
                self.playoff_round_rest_days,
            )
        ):
            raise ValueError("NBA quick simulation rest days must be non-negative integers")
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
        matchup_map = {
            (item.team.team_id, item.opponent_team_id): item.team for item in self.matchup_teams
        }

        def resolve_matchup(
            scheduled: ScheduledGame,
            team_map: Mapping[str, GameTeam],
        ) -> tuple[GameTeam, GameTeam]:
            home_team_id = scheduled.home_team_id
            away_team_id = scheduled.away_team_id
            return (
                matchup_map.get((home_team_id, away_team_id), team_map[home_team_id]),
                matchup_map.get((away_team_id, home_team_id), team_map[away_team_id]),
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
            team_resolver=resolve_matchup if matchup_map else None,
        )
        east_regular = _conference_seeds(season, self.alignment.east_team_ids)
        west_regular = _conference_seeds(season, self.alignment.west_team_ids)
        team_map = {team.team_id: team for team in self.teams}
        runtime = _PostseasonRuntime.from_season(
            season,
            team_map=team_map,
            matchup_map=matchup_map,
            master_seed=seed,
            parameters=self.parameters,
            config=self.game_config,
            rules=self.game_rules,
            fatigue_config=self.fatigue_config,
            season_config=self.season_config,
            trace_mode=self.trace_mode,
            postseason_rest_days=self.postseason_rest_days,
            game_rest_days=self.playoff_game_rest_days,
        )
        east_play_in = _sample_play_in(
            conference="east",
            seeds=east_regular,
            runtime=runtime,
        )
        west_play_in = _sample_play_in(
            conference="west",
            seeds=west_regular,
            runtime=runtime,
        )
        runtime.day += self.playoff_round_rest_days
        postseason = _sample_postseason(
            east_play_in.playoff_seeds,
            west_play_in.playoff_seeds,
            runtime=runtime,
            playoff_config=self.playoff_config,
            round_rest_days=self.playoff_round_rest_days,
        )
        postseason_state = runtime.result()
        return NBAQuickSimExecution(
            season,
            east_play_in,
            west_play_in,
            postseason,
            postseason_state,
            summarize_quick_sim_season(season_id, season, postseason),
            len(matchup_map),
        )


@dataclass(slots=True)
class _PostseasonRuntime:
    team_map: dict[str, GameTeam]
    matchup_map: dict[tuple[str, str], GameTeam]
    states: dict[tuple[str, int], PlayerSeasonState]
    initial_states: tuple[PlayerSeasonState, ...]
    last_game_day: dict[int, int]
    master_seed: int
    parameters: ModelParameters
    config: GameClockConfig
    rules: GameRules
    fatigue_config: FatigueConfig
    season_config: SeasonConfig
    trace_mode: TraceMode
    game_rest_days: int
    day: int
    injuries: list[InjuryRecord] = field(default_factory=list)
    games: list[NBAQuickSimPostseasonGame] = field(default_factory=list)
    player_seconds: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    player_games: dict[int, int] = field(default_factory=lambda: defaultdict(int))
    team_games: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    learning_totals: list[OpponentObservationTotals] = field(default_factory=list)

    @classmethod
    def from_season(
        cls,
        season: SeasonResult,
        *,
        team_map: dict[str, GameTeam],
        matchup_map: dict[tuple[str, str], GameTeam],
        master_seed: int,
        parameters: ModelParameters,
        config: GameClockConfig,
        rules: GameRules,
        fatigue_config: FatigueConfig,
        season_config: SeasonConfig,
        trace_mode: TraceMode,
        postseason_rest_days: int,
        game_rest_days: int,
    ) -> _PostseasonRuntime:
        last_game_day: dict[int, int] = {}
        for record in season.games:
            if record.result is None:
                continue
            for item in record.result.playing_time:
                if item.seconds > 0:
                    last_game_day[item.player_id] = record.scheduled_game.day
        initial = tuple(season.final_player_states)
        final_day = max(game.day for game in season.schedule.games)
        return cls(
            team_map,
            matchup_map,
            {(item.team_id, item.player_id): item for item in initial},
            initial,
            last_game_day,
            master_seed,
            parameters,
            config,
            rules,
            fatigue_config,
            season_config,
            trace_mode,
            game_rest_days,
            final_day + postseason_rest_days + 1,
        )

    def score(
        self,
        home_team_id: str,
        away_team_id: str,
        *,
        address: tuple[object, ...],
    ) -> tuple[int, int]:
        original_home = self.matchup_map.get(
            (home_team_id, away_team_id),
            self.team_map[home_team_id],
        )
        original_away = self.matchup_map.get(
            (away_team_id, home_team_id),
            self.team_map[away_team_id],
        )
        for team in (original_home, original_away):
            for player_id in team.roster_order:
                key = (team.team_id, player_id)
                state = self.states[key]
                rest_days = max(0, self.day - self.last_game_day.get(player_id, self.day) - 1)
                self.states[key] = replace(
                    state,
                    fatigue=max(
                        0,
                        state.fatigue - rest_days * self.season_config.daily_fatigue_recovery,
                    ),
                    unavailable_until_day=(
                        0
                        if state.unavailable_until_day and self.day >= state.unavailable_until_day
                        else state.unavailable_until_day
                    ),
                )
        home_unavailable = tuple(
            player_id
            for player_id in original_home.roster_order
            if self.day < self.states[(original_home.team_id, player_id)].unavailable_until_day
        )
        away_unavailable = tuple(
            player_id
            for player_id in original_away.roster_order
            if self.day < self.states[(original_away.team_id, player_id)].unavailable_until_day
        )
        home = available_game_team(original_home, frozenset(home_unavailable))
        away = available_game_team(original_away, frozenset(away_unavailable))
        forfeit_team_id: str | None = None
        sampled = None
        if home is None or away is None:
            if home is None:
                scores = (0, self.season_config.forfeit_score)
                forfeit_team_id = home_team_id
            else:
                scores = (self.season_config.forfeit_score, 0)
                forfeit_team_id = away_team_id
        else:
            scores = (0, 0)
            for attempt in range(100):
                game_seed = derive_seed(
                    self.master_seed,
                    NBA_QUICK_SIM_EXECUTOR_VERSION,
                    *address,
                    attempt,
                )
                candidate = sample_game(
                    parameters=self.parameters,
                    config=self.config,
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
                    rules=self.rules,
                    fatigue_config=self.fatigue_config,
                    initial_fatigue={
                        player_id: self.states[(team.team_id, player_id)].fatigue
                        for team in (home, away)
                        for player_id in team.roster_order
                    },
                    trace_mode=self.trace_mode,
                )
                if candidate.result.home_score != candidate.result.away_score:
                    sampled = candidate
                    scores = (candidate.result.home_score, candidate.result.away_score)
                    break
            if sampled is None:
                raise RuntimeError("NBA postseason game remained tied after deterministic retries")
            for snapshot in sampled.result.final_fatigue:
                team_id = home.team_id if snapshot.player_id in home.roster_order else away.team_id
                key = (team_id, snapshot.player_id)
                self.states[key] = replace(self.states[key], fatigue=snapshot.fatigue)
            participants = tuple(
                item.player_id for item in sampled.result.playing_time if item.seconds > 0
            )
            for item in sampled.result.playing_time:
                self.player_seconds[item.player_id] += item.seconds
                if item.seconds > 0:
                    self.player_games[item.player_id] += 1
            self._sample_injuries(
                (home, away),
                participants,
                game_index=len(self.games),
                address=address,
            )
            for player_id in participants:
                self.last_game_day[player_id] = self.day
        self.games.append(
            NBAQuickSimPostseasonGame(
                len(self.games),
                self.day,
                tuple(str(item) for item in address),
                home_team_id,
                away_team_id,
                *scores,
                home_unavailable,
                away_unavailable,
                forfeit_team_id,
            )
        )
        self.learning_totals.extend(
            opponent_observation_totals_from_game(
                home_team_id,
                away_team_id,
                *scores,
                sampled.result if sampled is not None else None,
            )
        )
        self.team_games[home_team_id] += 1
        self.team_games[away_team_id] += 1
        self.day += self.game_rest_days + 1
        return scores

    def _sample_injuries(
        self,
        teams: tuple[GameTeam, GameTeam],
        participants: tuple[int, ...],
        *,
        game_index: int,
        address: tuple[object, ...],
    ) -> None:
        for team in teams:
            for player_id in team.roster_order:
                if player_id not in participants:
                    continue
                roll = (
                    derive_seed(
                        self.master_seed,
                        INJURY_VERSION,
                        "nba-postseason",
                        *address,
                        player_id,
                        "roll",
                    )
                    % 10_000
                )
                if roll >= self.season_config.injury_probability_bps:
                    continue
                span = self.season_config.maximum_days_out - self.season_config.minimum_days_out + 1
                days_out = self.season_config.minimum_days_out + (
                    derive_seed(
                        self.master_seed,
                        INJURY_VERSION,
                        "nba-postseason",
                        *address,
                        player_id,
                        "duration",
                    )
                    % span
                )
                return_day = self.day + days_out + 1
                injury = InjuryRecord(
                    team.team_id,
                    player_id,
                    1_230 + game_index,
                    self.day,
                    return_day,
                )
                self.injuries.append(injury)
                key = (team.team_id, player_id)
                self.states[key] = replace(
                    self.states[key],
                    unavailable_until_day=return_day,
                )

    def result(self) -> NBAQuickSimPostseasonState:
        return NBAQuickSimPostseasonState(
            self.initial_states,
            tuple(self.states[key] for key in sorted(self.states)),
            tuple(self.injuries),
            tuple(self.games),
            tuple(sorted(self.player_seconds.items())),
            tuple(sorted(self.player_games.items())),
            tuple(sorted(self.team_games.items())),
            tuple(self.learning_totals),
        )


def build_nba_player_season_summaries(
    execution: NBAQuickSimExecution,
    players: tuple[CareerPlayer, ...],
) -> tuple[PlayerSeasonSummary, ...]:
    seconds: dict[int, int] = defaultdict(int)
    games_played: dict[int, int] = defaultdict(int)
    injury_days: dict[int, int] = defaultdict(int)
    scheduled_games: dict[str, int] = defaultdict(int)
    for game in execution.season.schedule.games:
        scheduled_games[game.home_team_id] += 1
        scheduled_games[game.away_team_id] += 1
    for record in execution.season.games:
        if record.result is None:
            continue
        for item in record.result.playing_time:
            seconds[item.player_id] += item.seconds
            if item.seconds > 0:
                games_played[item.player_id] += 1
    for injury in (*execution.season.injuries, *execution.postseason_state.injuries):
        injury_days[injury.player_id] += max(0, injury.return_day - injury.injury_day - 1)
    for player_id, value in execution.postseason_state.player_seconds:
        seconds[player_id] += value
    for player_id, value in execution.postseason_state.player_games:
        games_played[player_id] += value
    postseason_team_games = dict(execution.postseason_state.team_games)
    team_by_player = {
        player_id: roster.team_id
        for roster in execution.season.initial_rosters
        for player_id in roster.player_ids
    }
    return tuple(
        PlayerSeasonSummary(
            player.player_id,
            scheduled_games.get(team_by_player.get(player.player_id, ""), 0)
            + postseason_team_games.get(team_by_player.get(player.player_id, ""), 0),
            games_played[player.player_id],
            seconds[player.player_id],
            injury_days[player.player_id],
        )
        for player in players
        if player.status in {CareerStatus.ACTIVE, CareerStatus.FREE_AGENT}
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
    runtime: _PostseasonRuntime,
) -> PlayInResult:
    by_seed = {item.seed: item.team_id for item in seeds}
    first_score = runtime.score(
        by_seed[7],
        by_seed[8],
        address=(conference, "play-in", 1),
    )
    first = PlayInGame(1, by_seed[7], by_seed[8], *first_score)
    second_score = runtime.score(
        by_seed[9],
        by_seed[10],
        address=(conference, "play-in", 2),
    )
    second = PlayInGame(2, by_seed[9], by_seed[10], *second_score)
    third_score = runtime.score(
        first.loser_team_id,
        second.winner_team_id,
        address=(conference, "play-in", 3),
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
    runtime: _PostseasonRuntime,
    playoff_config: PlayoffConfig,
    round_rest_days: int,
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
            runtime=runtime,
            playoff_config=playoff_config,
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
    runtime.day += round_rest_days
    east_second = (
        series(2, 1, "east", east_first[0], east_first[1]),
        series(2, 2, "east", east_first[2], east_first[3]),
    )
    west_second = (
        series(2, 1, "west", west_first[0], west_first[1]),
        series(2, 2, "west", west_first[2], west_first[3]),
    )
    runtime.day += round_rest_days
    east_champion = series(3, 1, "east", *east_second)
    west_champion = series(3, 1, "west", *west_second)
    runtime.day += round_rest_days
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
    runtime: _PostseasonRuntime,
    playoff_config: PlayoffConfig,
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
        home_score, away_score = runtime.score(
            home,
            away,
            address=(conference, round_number, series_index, game_number),
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
