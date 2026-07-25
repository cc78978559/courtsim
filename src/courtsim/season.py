"""Deterministic multi-game schedules, injuries, and standings."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, NoReturn, cast

from courtsim.domain.game import GameClockConfig, GameResult, validate_game_result
from courtsim.domain.game_serialization import game_result_from_dict, game_result_to_dict
from courtsim.domain.plans import Lineup
from courtsim.domain.serialization import SerializationError
from courtsim.model.game_runtime import GameMatchups, GameTeam, sample_game
from courtsim.model.interaction_compiler import DefensiveMatchups, Matchup, ProfileLineup
from courtsim.model.trace_mode import TraceMode
from courtsim.parameters import ModelParameters
from courtsim.randomness import RandomFrame, derive_seed
from courtsim.rotations import FatigueConfig, RotationPlan, RotationStint
from courtsim.rules import GameRules

SEASON_VERSION = "season-v1"
INJURY_VERSION = "injury-v1"
SEASON_SCHEMA_VERSION = 1


def _identifier(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must not be blank")


@dataclass(frozen=True, slots=True)
class ScheduledGame:
    game_id: int
    day: int
    home_team_id: str
    away_team_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.game_id, int) or isinstance(self.game_id, bool) or self.game_id < 0:
            raise ValueError("game_id must be a non-negative integer")
        if not isinstance(self.day, int) or isinstance(self.day, bool) or self.day < 1:
            raise ValueError("day must be a positive integer")
        _identifier(self.home_team_id, "home_team_id")
        _identifier(self.away_team_id, "away_team_id")
        if self.home_team_id == self.away_team_id:
            raise ValueError("a scheduled team cannot play itself")


@dataclass(frozen=True, slots=True)
class SeasonSchedule:
    team_ids: tuple[str, ...]
    games: tuple[ScheduledGame, ...]
    version: str = SEASON_VERSION

    def __post_init__(self) -> None:
        if self.version != SEASON_VERSION:
            raise ValueError(f"unsupported season version: {self.version}")
        if len(self.team_ids) < 2 or len(self.team_ids) != len(set(self.team_ids)):
            raise ValueError("schedule must contain at least two unique teams")
        for team_id in self.team_ids:
            _identifier(team_id, "team_id")
        game_ids = tuple(game.game_id for game in self.games)
        if len(game_ids) != len(set(game_ids)):
            raise ValueError("scheduled game ids must be unique")
        if self.games != tuple(sorted(self.games, key=lambda game: (game.day, game.game_id))):
            raise ValueError("scheduled games must be ordered by day and game_id")
        if any(
            game.home_team_id not in self.team_ids or game.away_team_id not in self.team_ids
            for game in self.games
        ):
            raise ValueError("scheduled games must reference known teams")


@dataclass(frozen=True, slots=True)
class SeasonConfig:
    version: str = INJURY_VERSION
    injury_probability_bps: int = 35
    minimum_days_out: int = 1
    maximum_days_out: int = 7
    daily_fatigue_recovery: int = 2_500
    forfeit_score: int = 1

    def __post_init__(self) -> None:
        if self.version != INJURY_VERSION:
            raise ValueError(f"unsupported injury version: {self.version}")
        values = (
            self.injury_probability_bps,
            self.minimum_days_out,
            self.maximum_days_out,
            self.daily_fatigue_recovery,
            self.forfeit_score,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise ValueError("season configuration values must be integers")
        if not 0 <= self.injury_probability_bps <= 10_000:
            raise ValueError("injury_probability_bps must be from 0 through 10000")
        if self.minimum_days_out < 1 or self.maximum_days_out < self.minimum_days_out:
            raise ValueError("injury day bounds are invalid")
        if self.daily_fatigue_recovery < 0 or self.forfeit_score < 1:
            raise ValueError("recovery must be non-negative and forfeit_score positive")


@dataclass(frozen=True, slots=True)
class PlayerSeasonState:
    team_id: str
    player_id: int
    fatigue: int
    unavailable_until_day: int = 0

    def __post_init__(self) -> None:
        _identifier(self.team_id, "team_id")
        if (
            not isinstance(self.player_id, int)
            or isinstance(self.player_id, bool)
            or self.player_id < 0
        ):
            raise ValueError("player_id must be non-negative")
        if not isinstance(self.fatigue, int) or isinstance(self.fatigue, bool) or self.fatigue < 0:
            raise ValueError("fatigue must be non-negative")
        if (
            not isinstance(self.unavailable_until_day, int)
            or isinstance(self.unavailable_until_day, bool)
            or self.unavailable_until_day < 0
        ):
            raise ValueError("unavailable_until_day must be non-negative")


@dataclass(frozen=True, slots=True)
class InjuryRecord:
    team_id: str
    player_id: int
    game_id: int
    injury_day: int
    return_day: int

    def __post_init__(self) -> None:
        _identifier(self.team_id, "team_id")
        values = (self.player_id, self.game_id, self.injury_day, self.return_day)
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise ValueError("injury record values must be integers")
        if self.player_id < 0 or self.game_id < 0 or self.injury_day < 1:
            raise ValueError("injury record values are outside their valid range")
        if self.return_day <= self.injury_day:
            raise ValueError("return_day must follow injury_day")


@dataclass(frozen=True, slots=True)
class SeasonGameRecord:
    scheduled_game: ScheduledGame
    home_score: int
    away_score: int
    home_unavailable: tuple[int, ...]
    away_unavailable: tuple[int, ...]
    result: GameResult | None
    forfeit_team_id: str | None = None

    def __post_init__(self) -> None:
        if any(
            not isinstance(score, int) or isinstance(score, bool) or score < 0
            for score in (self.home_score, self.away_score)
        ):
            raise ValueError("season game scores must be non-negative")
        if any(
            not isinstance(player_id, int) or isinstance(player_id, bool) or player_id < 0
            for player_id in self.home_unavailable + self.away_unavailable
        ):
            raise ValueError("unavailable player ids must be non-negative integers")
        if len(self.home_unavailable) != len(set(self.home_unavailable)) or len(
            self.away_unavailable
        ) != len(set(self.away_unavailable)):
            raise ValueError("unavailable player ids must be unique")
        if self.result is None and self.forfeit_team_id is None:
            raise ValueError("a game without a result must identify the forfeiting team")
        if self.result is not None and self.forfeit_team_id is not None:
            raise ValueError("a completed game cannot also be a forfeit")
        if self.forfeit_team_id not in {
            None,
            self.scheduled_game.home_team_id,
            self.scheduled_game.away_team_id,
        }:
            raise ValueError("forfeit_team_id must participate in the scheduled game")


@dataclass(frozen=True, slots=True)
class SeasonStanding:
    rank: int
    team_id: str
    wins: int
    losses: int
    ties: int
    points_for: int
    points_against: int

    def __post_init__(self) -> None:
        _identifier(self.team_id, "team_id")
        values = (
            self.rank,
            self.wins,
            self.losses,
            self.ties,
            self.points_for,
            self.points_against,
        )
        if (
            any(
                not isinstance(value, int) or isinstance(value, bool) or value < 0
                for value in values
            )
            or self.rank < 1
        ):
            raise ValueError("standing values must be non-negative integers with a positive rank")

    @property
    def point_differential(self) -> int:
        return self.points_for - self.points_against


@dataclass(frozen=True, slots=True)
class SeasonResult:
    schedule: SeasonSchedule
    games: tuple[SeasonGameRecord, ...]
    standings: tuple[SeasonStanding, ...]
    injuries: tuple[InjuryRecord, ...]
    final_player_states: tuple[PlayerSeasonState, ...]
    version: str = SEASON_VERSION
    injury_version: str = INJURY_VERSION

    def __post_init__(self) -> None:
        if self.version != SEASON_VERSION or self.injury_version != INJURY_VERSION:
            raise ValueError("season result versions are unsupported")


@dataclass(frozen=True, slots=True)
class SeasonAudit:
    games_scheduled: int
    games_completed: int
    forfeits: int
    injuries: int
    player_games_missed: int
    standings_wins: int
    standings_losses: int


def _standing_rows(
    team_ids: tuple[str, ...], games: tuple[SeasonGameRecord, ...]
) -> tuple[SeasonStanding, ...]:
    totals = {team_id: [0, 0, 0, 0, 0] for team_id in team_ids}
    for record in games:
        home = totals[record.scheduled_game.home_team_id]
        away = totals[record.scheduled_game.away_team_id]
        home[3] += record.home_score
        home[4] += record.away_score
        away[3] += record.away_score
        away[4] += record.home_score
        if record.home_score > record.away_score:
            home[0] += 1
            away[1] += 1
        elif record.away_score > record.home_score:
            away[0] += 1
            home[1] += 1
        else:
            home[2] += 1
            away[2] += 1
    ordered = sorted(
        totals.items(),
        key=lambda item: (
            -item[1][0],
            item[1][1],
            -(item[1][3] - item[1][4]),
            -item[1][3],
            item[0],
        ),
    )
    return tuple(
        SeasonStanding(rank, team_id, *values)
        for rank, (team_id, values) in enumerate(ordered, start=1)
    )


def validate_season_result(result: SeasonResult, game_config: GameClockConfig) -> None:
    if result.version != SEASON_VERSION or result.injury_version != INJURY_VERSION:
        raise ValueError("season result versions are unsupported")
    if tuple(record.scheduled_game for record in result.games) != result.schedule.games:
        raise ValueError("season game records must cover the schedule exactly")
    if result.standings != _standing_rows(result.schedule.team_ids, result.games):
        raise ValueError("season standings do not derive from game records")
    state_keys = tuple((state.team_id, state.player_id) for state in result.final_player_states)
    if len(state_keys) != len(set(state_keys)):
        raise ValueError("final player states must be unique")
    if any(team_id not in result.schedule.team_ids for team_id, _ in state_keys):
        raise ValueError("final player states must reference scheduled teams")
    known_games = {game.game_id: game for game in result.schedule.games}
    known_players = set(state_keys)
    for record in result.games:
        for player_id in record.home_unavailable:
            if (record.scheduled_game.home_team_id, player_id) not in known_players:
                raise ValueError("home unavailable player is missing from final state")
        for player_id in record.away_unavailable:
            if (record.scheduled_game.away_team_id, player_id) not in known_players:
                raise ValueError("away unavailable player is missing from final state")
        if record.result is not None:
            validate_game_result(record.result, game_config)
            if (
                record.result.home_team_id != record.scheduled_game.home_team_id
                or record.result.away_team_id != record.scheduled_game.away_team_id
                or record.result.home_score != record.home_score
                or record.result.away_score != record.away_score
            ):
                raise ValueError("nested game result does not match its scheduled game")
    for injury in result.injuries:
        game = known_games.get(injury.game_id)
        if (
            game is None
            or game.day != injury.injury_day
            or injury.team_id not in {game.home_team_id, game.away_team_id}
            or (injury.team_id, injury.player_id) not in known_players
        ):
            raise ValueError("injury record does not match the season")


def audit_season(result: SeasonResult, game_config: GameClockConfig) -> SeasonAudit:
    validate_season_result(result, game_config)
    return SeasonAudit(
        len(result.schedule.games),
        sum(record.result is not None for record in result.games),
        sum(record.result is None for record in result.games),
        len(result.injuries),
        sum(len(record.home_unavailable) + len(record.away_unavailable) for record in result.games),
        sum(row.wins for row in result.standings),
        sum(row.losses for row in result.standings),
    )


def _filled_lineup(target: Lineup, available_order: tuple[int, ...]) -> Lineup:
    selected = [player_id for player_id in target if player_id in available_order]
    selected.extend(player_id for player_id in available_order if player_id not in selected)
    if len(selected) < 5:
        raise ValueError("fewer than five players are available")
    return cast(Lineup, tuple(selected[:5]))


def _available_team(team: GameTeam, unavailable: frozenset[int]) -> GameTeam | None:
    available_order = tuple(
        player_id for player_id in team.roster_order if player_id not in unavailable
    )
    if len(available_order) < 5:
        return None
    profiles = {profile.player_id: profile for profile in team.roster_profiles}
    lineup = _filled_lineup(team.lineup, available_order)
    rotation_plan = (
        RotationPlan(
            tuple(
                RotationStint(
                    stint.period,
                    stint.start_clock_seconds,
                    _filled_lineup(stint.lineup, available_order),
                )
                for stint in team.rotation_plan.stints
            )
        )
        if team.rotation_plan is not None
        else None
    )
    active = cast(ProfileLineup, tuple(profiles[item] for item in lineup))
    bench = tuple(profiles[item] for item in available_order if item not in lineup)
    return replace(
        team,
        lineup=lineup,
        profiles=active,
        bench_profiles=bench,
        substitution_order=available_order,
        rotation_plan=rotation_plan,
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


def sample_season(
    *,
    parameters: ModelParameters,
    game_config: GameClockConfig,
    schedule: SeasonSchedule,
    teams: tuple[GameTeam, ...],
    frame: RandomFrame,
    rules: GameRules | None = None,
    fatigue_config: FatigueConfig | None = None,
    season_config: SeasonConfig | None = None,
    trace_mode: TraceMode = TraceMode.FULL,
) -> SeasonResult:
    season_config = season_config or SeasonConfig()
    team_map = {team.team_id: team for team in teams}
    if set(team_map) != set(schedule.team_ids) or len(team_map) != len(teams):
        raise ValueError("teams must cover schedule team ids exactly")
    player_teams = [(team.team_id, player_id) for team in teams for player_id in team.roster_order]
    if len({player_id for _, player_id in player_teams}) != len(player_teams):
        raise ValueError("season player ids must be globally unique")
    effective_fatigue = fatigue_config or FatigueConfig()
    states = {key: PlayerSeasonState(key[0], key[1], 0) for key in player_teams}
    last_game_day: dict[str, int] = {}
    records: list[SeasonGameRecord] = []
    injuries: list[InjuryRecord] = []

    for scheduled in schedule.games:
        original_home = team_map[scheduled.home_team_id]
        original_away = team_map[scheduled.away_team_id]
        for team in (original_home, original_away):
            rest_days = max(0, scheduled.day - last_game_day.get(team.team_id, scheduled.day) - 1)
            for player_id in team.roster_order:
                key = (team.team_id, player_id)
                state = states[key]
                states[key] = replace(
                    state,
                    fatigue=max(
                        0,
                        state.fatigue - rest_days * season_config.daily_fatigue_recovery,
                    ),
                    unavailable_until_day=(
                        0
                        if state.unavailable_until_day
                        and scheduled.day >= state.unavailable_until_day
                        else state.unavailable_until_day
                    ),
                )
        home_unavailable = tuple(
            player_id
            for player_id in original_home.roster_order
            if scheduled.day < states[(original_home.team_id, player_id)].unavailable_until_day
        )
        away_unavailable = tuple(
            player_id
            for player_id in original_away.roster_order
            if scheduled.day < states[(original_away.team_id, player_id)].unavailable_until_day
        )
        home = _available_team(original_home, frozenset(home_unavailable))
        away = _available_team(original_away, frozenset(away_unavailable))
        if home is None or away is None:
            if home is None and away is not None:
                scores = (0, season_config.forfeit_score)
                forfeit_team_id = original_home.team_id
            elif away is None and home is not None:
                scores = (season_config.forfeit_score, 0)
                forfeit_team_id = original_away.team_id
            else:
                scores = (0, 0)
                forfeit_team_id = original_home.team_id
            records.append(
                SeasonGameRecord(
                    scheduled,
                    *scores,
                    home_unavailable,
                    away_unavailable,
                    None,
                    forfeit_team_id,
                )
            )
        else:
            game_seed = derive_seed(frame.master_seed, "season-game", scheduled.game_id)
            game_frame = RandomFrame(
                game_seed,
                replace(
                    frame.address,
                    game_id=scheduled.game_id,
                    possession_index=0,
                    segment_index=0,
                ),
            )
            initial_fatigue = {
                player_id: states[(team.team_id, player_id)].fatigue
                for team in (home, away)
                for player_id in team.roster_order
            }
            sampled = sample_game(
                parameters=parameters,
                config=game_config,
                home=home,
                away=away,
                matchups=_matchups(home, away),
                frame=game_frame,
                rules=rules,
                fatigue_config=effective_fatigue,
                initial_fatigue=initial_fatigue,
                trace_mode=trace_mode,
            )
            for snapshot in sampled.result.final_fatigue:
                team_id = home.team_id if snapshot.player_id in home.roster_order else away.team_id
                key = (team_id, snapshot.player_id)
                states[key] = replace(states[key], fatigue=snapshot.fatigue)
            records.append(
                SeasonGameRecord(
                    scheduled,
                    sampled.result.home_score,
                    sampled.result.away_score,
                    home_unavailable,
                    away_unavailable,
                    sampled.result,
                )
            )
            participants = tuple(item.player_id for item in sampled.result.playing_time)
            for team in (home, away):
                for player_id in team.roster_order:
                    if player_id not in participants:
                        continue
                    roll = (
                        derive_seed(
                            frame.master_seed,
                            INJURY_VERSION,
                            scheduled.game_id,
                            player_id,
                            "roll",
                        )
                        % 10_000
                    )
                    if roll >= season_config.injury_probability_bps:
                        continue
                    span = season_config.maximum_days_out - season_config.minimum_days_out + 1
                    days_out = season_config.minimum_days_out + (
                        derive_seed(
                            frame.master_seed,
                            INJURY_VERSION,
                            scheduled.game_id,
                            player_id,
                            "duration",
                        )
                        % span
                    )
                    return_day = scheduled.day + days_out + 1
                    injury = InjuryRecord(
                        team.team_id,
                        player_id,
                        scheduled.game_id,
                        scheduled.day,
                        return_day,
                    )
                    injuries.append(injury)
                    key = (team.team_id, player_id)
                    states[key] = replace(states[key], unavailable_until_day=return_day)
        last_game_day[original_home.team_id] = scheduled.day
        last_game_day[original_away.team_id] = scheduled.day

    game_records = tuple(records)
    result = SeasonResult(
        schedule,
        game_records,
        _standing_rows(schedule.team_ids, game_records),
        tuple(injuries),
        tuple(states[key] for key in sorted(states)),
    )
    validate_season_result(result, game_config)
    return result


def season_result_to_dict(result: SeasonResult) -> dict[str, object]:
    return {
        "schema_version": SEASON_SCHEMA_VERSION,
        "version": result.version,
        "injury_version": result.injury_version,
        "schedule": {
            "version": result.schedule.version,
            "team_ids": list(result.schedule.team_ids),
            "games": [
                {
                    "game_id": game.game_id,
                    "day": game.day,
                    "home_team_id": game.home_team_id,
                    "away_team_id": game.away_team_id,
                }
                for game in result.schedule.games
            ],
        },
        "games": [
            {
                "game_id": record.scheduled_game.game_id,
                "home_score": record.home_score,
                "away_score": record.away_score,
                "home_unavailable": list(record.home_unavailable),
                "away_unavailable": list(record.away_unavailable),
                "result": (
                    game_result_to_dict(record.result) if record.result is not None else None
                ),
                "forfeit_team_id": record.forfeit_team_id,
            }
            for record in result.games
        ],
        "standings": [
            {
                "rank": row.rank,
                "team_id": row.team_id,
                "wins": row.wins,
                "losses": row.losses,
                "ties": row.ties,
                "points_for": row.points_for,
                "points_against": row.points_against,
            }
            for row in result.standings
        ],
        "injuries": [
            {
                "team_id": item.team_id,
                "player_id": item.player_id,
                "game_id": item.game_id,
                "injury_day": item.injury_day,
                "return_day": item.return_day,
            }
            for item in result.injuries
        ],
        "final_player_states": [
            {
                "team_id": state.team_id,
                "player_id": state.player_id,
                "fatigue": state.fatigue,
                "unavailable_until_day": state.unavailable_until_day,
            }
            for state in result.final_player_states
        ],
    }


def _fail(message: str) -> NoReturn:
    raise SerializationError(message)


def _object(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _fail(f"{field} must be an object")
    return cast(Mapping[str, Any], value)


def _exact(value: Mapping[str, Any], keys: set[str], field: str) -> None:
    if set(value) != keys:
        _fail(f"{field} keys must be exactly {sorted(keys)}")


def _integer(value: Mapping[str, Any], key: str) -> int:
    raw = value[key]
    if not isinstance(raw, int) or isinstance(raw, bool):
        _fail(f"{key} must be an integer")
    return raw


def _string(value: Mapping[str, Any], key: str) -> str:
    raw = value[key]
    if not isinstance(raw, str) or not raw:
        _fail(f"{key} must be a non-empty string")
    return raw


def _integer_tuple(value: object, field: str) -> tuple[int, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, int) or isinstance(item, bool) for item in value
    ):
        _fail(f"{field} must be an integer list")
    return tuple(value)


def season_result_from_dict(value: object, game_config: GameClockConfig) -> SeasonResult:
    raw = _object(value, "season result")
    _exact(
        raw,
        {
            "schema_version",
            "version",
            "injury_version",
            "schedule",
            "games",
            "standings",
            "injuries",
            "final_player_states",
        },
        "season result",
    )
    if _integer(raw, "schema_version") != SEASON_SCHEMA_VERSION:
        _fail("unsupported season schema_version")
    schedule_raw = _object(raw["schedule"], "schedule")
    _exact(schedule_raw, {"version", "team_ids", "games"}, "schedule")
    team_ids_raw = schedule_raw["team_ids"]
    games_raw = schedule_raw["games"]
    if not isinstance(team_ids_raw, list) or not all(
        isinstance(item, str) for item in team_ids_raw
    ):
        _fail("team_ids must be a string list")
    if not isinstance(games_raw, list):
        _fail("schedule games must be a list")
    scheduled_games: list[ScheduledGame] = []
    for item_raw in games_raw:
        item = _object(item_raw, "scheduled game")
        _exact(item, {"game_id", "day", "home_team_id", "away_team_id"}, "scheduled game")
        scheduled_games.append(
            ScheduledGame(
                _integer(item, "game_id"),
                _integer(item, "day"),
                _string(item, "home_team_id"),
                _string(item, "away_team_id"),
            )
        )
    schedule = SeasonSchedule(
        tuple(team_ids_raw),
        tuple(scheduled_games),
        _string(schedule_raw, "version"),
    )
    schedule_by_id = {game.game_id: game for game in schedule.games}
    records_raw = raw["games"]
    if not isinstance(records_raw, list):
        _fail("games must be a list")
    records: list[SeasonGameRecord] = []
    for record_raw in records_raw:
        item = _object(record_raw, "season game")
        _exact(
            item,
            {
                "game_id",
                "home_score",
                "away_score",
                "home_unavailable",
                "away_unavailable",
                "result",
                "forfeit_team_id",
            },
            "season game",
        )
        game_id = _integer(item, "game_id")
        if game_id not in schedule_by_id:
            _fail("season game references an unknown game_id")
        forfeit_raw = item["forfeit_team_id"]
        if forfeit_raw is not None and not isinstance(forfeit_raw, str):
            _fail("forfeit_team_id must be null or a string")
        nested = (
            None if item["result"] is None else game_result_from_dict(item["result"], game_config)
        )
        records.append(
            SeasonGameRecord(
                schedule_by_id[game_id],
                _integer(item, "home_score"),
                _integer(item, "away_score"),
                _integer_tuple(item["home_unavailable"], "home_unavailable"),
                _integer_tuple(item["away_unavailable"], "away_unavailable"),
                nested,
                forfeit_raw,
            )
        )
    standings_raw = raw["standings"]
    if not isinstance(standings_raw, list):
        _fail("standings must be a list")
    standings: list[SeasonStanding] = []
    for standing_raw in standings_raw:
        item = _object(standing_raw, "standing")
        _exact(
            item,
            {"rank", "team_id", "wins", "losses", "ties", "points_for", "points_against"},
            "standing",
        )
        standings.append(
            SeasonStanding(
                _integer(item, "rank"),
                _string(item, "team_id"),
                _integer(item, "wins"),
                _integer(item, "losses"),
                _integer(item, "ties"),
                _integer(item, "points_for"),
                _integer(item, "points_against"),
            )
        )
    injuries_raw = raw["injuries"]
    if not isinstance(injuries_raw, list):
        _fail("injuries must be a list")
    injuries_list: list[InjuryRecord] = []
    for injury_raw in injuries_raw:
        item = _object(injury_raw, "injury")
        _exact(
            item,
            {"team_id", "player_id", "game_id", "injury_day", "return_day"},
            "injury",
        )
        injuries_list.append(
            InjuryRecord(
                _string(item, "team_id"),
                _integer(item, "player_id"),
                _integer(item, "game_id"),
                _integer(item, "injury_day"),
                _integer(item, "return_day"),
            )
        )
    injuries = tuple(injuries_list)
    states_raw = raw["final_player_states"]
    if not isinstance(states_raw, list):
        _fail("final_player_states must be a list")
    states_list: list[PlayerSeasonState] = []
    for state_raw in states_raw:
        item = _object(state_raw, "player state")
        _exact(
            item,
            {"team_id", "player_id", "fatigue", "unavailable_until_day"},
            "player state",
        )
        states_list.append(
            PlayerSeasonState(
                _string(item, "team_id"),
                _integer(item, "player_id"),
                _integer(item, "fatigue"),
                _integer(item, "unavailable_until_day"),
            )
        )
    states = tuple(states_list)
    result = SeasonResult(
        schedule,
        tuple(records),
        tuple(standings),
        injuries,
        states,
        _string(raw, "version"),
        _string(raw, "injury_version"),
    )
    try:
        validate_season_result(result, game_config)
    except ValueError as error:
        _fail(str(error))
    return result


def season_result_to_json(result: SeasonResult) -> str:
    return json.dumps(
        season_result_to_dict(result),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def season_result_from_json(payload: str, game_config: GameClockConfig) -> SeasonResult:
    try:
        value = json.loads(payload)
    except json.JSONDecodeError as error:
        raise SerializationError(f"invalid season JSON: {error.msg}") from error
    return season_result_from_dict(value, game_config)
