"""Thirty-team schedules, conference play-in, and a sixteen-team NBA bracket."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from courtsim.playoffs import PlayoffSeed
from courtsim.season import ScheduledGame, SeasonSchedule

NBA_LEAGUE_VERSION = "nba-league-v1"


@dataclass(frozen=True, slots=True)
class NBARegularSeasonRules:
    team_count: int = 30
    games_per_team: int = 82
    version: str = NBA_LEAGUE_VERSION

    def __post_init__(self) -> None:
        if self.team_count != 30 or self.games_per_team != 82:
            raise ValueError("nba-league-v1 requires thirty teams and eighty-two games")
        if self.version != NBA_LEAGUE_VERSION:
            raise ValueError("unsupported NBA league version")


@dataclass(frozen=True, slots=True)
class NBAConferenceAlignment:
    east_team_ids: tuple[str, ...]
    west_team_ids: tuple[str, ...]
    version: str = NBA_LEAGUE_VERSION

    def __post_init__(self) -> None:
        if (
            len(self.east_team_ids) != 15
            or len(self.west_team_ids) != 15
            or self.east_team_ids != tuple(sorted(set(self.east_team_ids)))
            or self.west_team_ids != tuple(sorted(set(self.west_team_ids)))
            or set(self.east_team_ids) & set(self.west_team_ids)
        ):
            raise ValueError("NBA alignment requires two distinct ordered 15-team conferences")
        if self.version != NBA_LEAGUE_VERSION:
            raise ValueError("unsupported NBA alignment version")


def nba_alignment_to_dict(value: NBAConferenceAlignment) -> dict[str, object]:
    return {
        "version": value.version,
        "east_team_ids": list(value.east_team_ids),
        "west_team_ids": list(value.west_team_ids),
    }


def nba_alignment_from_dict(value: object) -> NBAConferenceAlignment:
    if not isinstance(value, dict) or set(value) != {
        "version",
        "east_team_ids",
        "west_team_ids",
    }:
        raise ValueError("invalid NBA alignment object")
    east = value["east_team_ids"]
    west = value["west_team_ids"]
    if (
        not isinstance(east, list)
        or not isinstance(west, list)
        or any(not isinstance(item, str) for item in (*east, *west))
    ):
        raise ValueError("NBA alignment teams must be string lists")
    return NBAConferenceAlignment(tuple(east), tuple(west), str(value["version"]))


@dataclass(frozen=True, slots=True)
class PlayInGame:
    game_number: int
    home_team_id: str
    away_team_id: str
    home_score: int
    away_score: int

    def __post_init__(self) -> None:
        if self.game_number not in {1, 2, 3}:
            raise ValueError("play-in game number must be one through three")
        if (
            not self.home_team_id.strip()
            or not self.away_team_id.strip()
            or self.home_team_id == self.away_team_id
        ):
            raise ValueError("play-in teams are invalid")
        if min(self.home_score, self.away_score) < 0 or self.home_score == self.away_score:
            raise ValueError("play-in games require non-negative, non-tied scores")

    @property
    def winner_team_id(self) -> str:
        return self.home_team_id if self.home_score > self.away_score else self.away_team_id

    @property
    def loser_team_id(self) -> str:
        return self.away_team_id if self.home_score > self.away_score else self.home_team_id


@dataclass(frozen=True, slots=True)
class PlayInResult:
    conference: str
    regular_season_seeds: tuple[PlayoffSeed, ...]
    games: tuple[PlayInGame, PlayInGame, PlayInGame]
    playoff_seeds: tuple[PlayoffSeed, ...]
    eliminated_team_ids: tuple[str, str]
    version: str = NBA_LEAGUE_VERSION


@dataclass(frozen=True, slots=True)
class NBASeriesResult:
    round_number: int
    series_index: int
    conference: str
    first_team_id: str
    second_team_id: str
    first_wins: int
    second_wins: int

    def __post_init__(self) -> None:
        if self.round_number not in {1, 2, 3, 4} or self.series_index < 1:
            raise ValueError("NBA series address is invalid")
        if self.conference not in {"east", "west", "nba"}:
            raise ValueError("NBA series conference is invalid")
        if self.first_team_id == self.second_team_id:
            raise ValueError("NBA series teams must differ")
        if max(self.first_wins, self.second_wins) != 4 or min(
            self.first_wins, self.second_wins
        ) not in {0, 1, 2, 3}:
            raise ValueError("NBA series must end with exactly four wins")

    @property
    def winner_team_id(self) -> str:
        return self.first_team_id if self.first_wins == 4 else self.second_team_id


@dataclass(frozen=True, slots=True)
class NBAPostseasonResult:
    east_seeds: tuple[PlayoffSeed, ...]
    west_seeds: tuple[PlayoffSeed, ...]
    series: tuple[NBASeriesResult, ...]
    east_champion_team_id: str
    west_champion_team_id: str
    champion_team_id: str
    version: str = NBA_LEAGUE_VERSION


def generate_nba_schedule(
    team_ids: tuple[str, ...],
    *,
    rules: NBARegularSeasonRules | None = None,
) -> SeasonSchedule:
    active_rules = rules or NBARegularSeasonRules()
    if team_ids != tuple(sorted(set(team_ids))) or len(team_ids) != active_rules.team_count:
        raise ValueError("NBA team ids must contain thirty ordered unique teams")
    rounds = _round_robin_pairs(team_ids)
    selected_rounds = (*rounds, *rounds, *rounds[:24])
    games: list[ScheduledGame] = []
    game_id = 1
    for day, pairs in enumerate(selected_rounds, start=1):
        cycle = (day - 1) // len(rounds)
        for pair_index, (first, second) in enumerate(pairs):
            flip = (cycle + pair_index + day) % 2 == 1
            home, away = (second, first) if flip else (first, second)
            games.append(ScheduledGame(game_id, day, home, away))
            game_id += 1
    schedule = SeasonSchedule(team_ids, tuple(games))
    appearances = Counter(
        team_id for game in schedule.games for team_id in (game.home_team_id, game.away_team_id)
    )
    if set(appearances.values()) != {active_rules.games_per_team}:
        raise ValueError("generated NBA schedule does not contain eighty-two games per team")
    return schedule


def resolve_play_in(
    *,
    conference: str,
    seeds: tuple[PlayoffSeed, ...],
    games: tuple[PlayInGame, PlayInGame, PlayInGame],
) -> PlayInResult:
    if conference not in {"east", "west"}:
        raise ValueError("play-in conference must be east or west")
    _validate_seed_set(seeds, 10)
    by_seed = {seed.seed: seed.team_id for seed in seeds}
    first, second, third = games
    _expect_play_in(first, 1, by_seed[7], by_seed[8])
    _expect_play_in(second, 2, by_seed[9], by_seed[10])
    _expect_play_in(third, 3, first.loser_team_id, second.winner_team_id)
    playoff_seeds = (
        *seeds[:6],
        PlayoffSeed(7, first.winner_team_id),
        PlayoffSeed(8, third.winner_team_id),
    )
    eliminated = tuple(sorted((second.loser_team_id, third.loser_team_id)))
    return PlayInResult(
        conference,
        seeds,
        games,
        playoff_seeds,
        (eliminated[0], eliminated[1]),
    )


def resolve_nba_playoffs(
    *,
    east_seeds: tuple[PlayoffSeed, ...],
    west_seeds: tuple[PlayoffSeed, ...],
    series: tuple[NBASeriesResult, ...],
) -> NBAPostseasonResult:
    _validate_seed_set(east_seeds, 8)
    _validate_seed_set(west_seeds, 8)
    if set(item.team_id for item in east_seeds) & set(item.team_id for item in west_seeds):
        raise ValueError("NBA conferences must contain distinct teams")
    index = 0
    east_winners, index = _resolve_conference_round_one("east", east_seeds, series, index, 1)
    west_winners, index = _resolve_conference_round_one("west", west_seeds, series, index, 5)
    east_second, index = _resolve_round(
        "east",
        2,
        ((east_winners[0], east_winners[1]), (east_winners[2], east_winners[3])),
        series,
        index,
    )
    west_second, index = _resolve_round(
        "west",
        2,
        ((west_winners[0], west_winners[1]), (west_winners[2], west_winners[3])),
        series,
        index,
    )
    east_final, index = _resolve_round(
        "east", 3, ((east_second[0], east_second[1]),), series, index
    )
    west_final, index = _resolve_round(
        "west", 3, ((west_second[0], west_second[1]),), series, index
    )
    champions, index = _resolve_round("nba", 4, ((east_final[0], west_final[0]),), series, index)
    if index != len(series):
        raise ValueError("NBA playoff ledger contains extra series")
    return NBAPostseasonResult(
        east_seeds,
        west_seeds,
        series,
        east_final[0],
        west_final[0],
        champions[0],
    )


def _round_robin_pairs(
    team_ids: tuple[str, ...],
) -> tuple[tuple[tuple[str, str], ...], ...]:
    rotating = list(team_ids)
    rounds = []
    for _ in range(len(team_ids) - 1):
        rounds.append(
            tuple((rotating[index], rotating[-index - 1]) for index in range(len(team_ids) // 2))
        )
        rotating = [rotating[0], rotating[-1], *rotating[1:-1]]
    return tuple(rounds)


def _validate_seed_set(seeds: tuple[PlayoffSeed, ...], count: int) -> None:
    if tuple(item.seed for item in seeds) != tuple(range(1, count + 1)):
        raise ValueError("conference seeds must be ordered and contiguous")
    if len({item.team_id for item in seeds}) != count:
        raise ValueError("conference seed teams must be unique")


def _expect_play_in(
    game: PlayInGame,
    number: int,
    first_team_id: str,
    second_team_id: str,
) -> None:
    if (
        game.game_number != number
        or game.home_team_id != first_team_id
        or game.away_team_id != second_team_id
    ):
        raise ValueError("play-in game does not match its derived bracket")


def _resolve_conference_round_one(
    conference: str,
    seeds: tuple[PlayoffSeed, ...],
    ledger: tuple[NBASeriesResult, ...],
    index: int,
    starting_series_index: int,
) -> tuple[tuple[str, ...], int]:
    teams = {item.seed: item.team_id for item in seeds}
    return _resolve_round(
        conference,
        1,
        (
            (teams[1], teams[8]),
            (teams[4], teams[5]),
            (teams[2], teams[7]),
            (teams[3], teams[6]),
        ),
        ledger,
        index,
        starting_series_index=starting_series_index,
    )


def _resolve_round(
    conference: str,
    round_number: int,
    matchups: tuple[tuple[str, str], ...],
    ledger: tuple[NBASeriesResult, ...],
    index: int,
    *,
    starting_series_index: int = 1,
) -> tuple[tuple[str, ...], int]:
    winners = []
    for offset, matchup in enumerate(matchups):
        if index >= len(ledger):
            raise ValueError("NBA playoff ledger ends before the champion is decided")
        result = ledger[index]
        if (
            result.round_number != round_number
            or result.series_index != starting_series_index + offset
            or result.conference != conference
            or (result.first_team_id, result.second_team_id) != matchup
        ):
            raise ValueError("NBA playoff series does not match its derived bracket")
        winners.append(result.winner_team_id)
        index += 1
    return tuple(winners), index
