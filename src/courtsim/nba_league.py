"""Thirty-team schedules, conference play-in, and a sixteen-team NBA bracket."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import pairwise

from courtsim.playoffs import PlayoffSeed
from courtsim.season import ScheduledGame, SeasonSchedule

NBA_LEAGUE_VERSION = "nba-league-v1"


@dataclass(frozen=True, slots=True)
class NBARegularSeasonRules:
    team_count: int = 30
    games_per_team: int = 82
    season_span_days: int = 174
    back_to_back_windows: int = 15
    minimum_team_back_to_backs: int = 12
    maximum_team_back_to_backs: int = 16
    maximum_consecutive_game_days: int = 2
    minimum_one_day_rest_intervals: int = 55
    maximum_one_day_rest_intervals: int = 70
    minimum_longest_rest_days: int = 7
    maximum_longest_rest_days: int = 14
    version: str = NBA_LEAGUE_VERSION

    def __post_init__(self) -> None:
        if self.team_count != 30 or self.games_per_team != 82:
            raise ValueError("nba-league-v1 requires thirty teams and eighty-two games")
        if (
            self.season_span_days < self.games_per_team
            or self.back_to_back_windows < 1
            or not 0 <= self.minimum_team_back_to_backs <= self.maximum_team_back_to_backs
            or self.maximum_consecutive_game_days < 2
            or not 0 <= self.minimum_one_day_rest_intervals <= self.maximum_one_day_rest_intervals
            or not 0 <= self.minimum_longest_rest_days <= self.maximum_longest_rest_days
        ):
            raise ValueError("NBA calendar gate rules are invalid")
        if self.version != NBA_LEAGUE_VERSION:
            raise ValueError("unsupported NBA league version")


@dataclass(frozen=True, slots=True)
class NBAConferenceAlignment:
    east_team_ids: tuple[str, ...]
    west_team_ids: tuple[str, ...]
    version: str = NBA_LEAGUE_VERSION
    east_divisions: tuple[tuple[str, ...], ...] = ()
    west_divisions: tuple[tuple[str, ...], ...] = ()

    def __post_init__(self) -> None:
        if (
            len(self.east_team_ids) != 15
            or len(self.west_team_ids) != 15
            or self.east_team_ids != tuple(sorted(set(self.east_team_ids)))
            or self.west_team_ids != tuple(sorted(set(self.west_team_ids)))
            or set(self.east_team_ids) & set(self.west_team_ids)
        ):
            raise ValueError("NBA alignment requires two distinct ordered 15-team conferences")
        if not self.east_divisions:
            object.__setattr__(
                self,
                "east_divisions",
                _default_divisions(self.east_team_ids),
            )
        if not self.west_divisions:
            object.__setattr__(
                self,
                "west_divisions",
                _default_divisions(self.west_team_ids),
            )
        _validate_divisions(self.east_divisions, self.east_team_ids, "east")
        _validate_divisions(self.west_divisions, self.west_team_ids, "west")
        if self.version != NBA_LEAGUE_VERSION:
            raise ValueError("unsupported NBA alignment version")


def nba_alignment_to_dict(value: NBAConferenceAlignment) -> dict[str, object]:
    return {
        "version": value.version,
        "east_team_ids": list(value.east_team_ids),
        "west_team_ids": list(value.west_team_ids),
        "east_divisions": [list(division) for division in value.east_divisions],
        "west_divisions": [list(division) for division in value.west_divisions],
    }


def nba_alignment_from_dict(value: object) -> NBAConferenceAlignment:
    if not isinstance(value, dict) or frozenset(value) not in {
        frozenset({"version", "east_team_ids", "west_team_ids"}),
        frozenset(
            {
                "version",
                "east_team_ids",
                "west_team_ids",
                "east_divisions",
                "west_divisions",
            }
        ),
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
    if "east_divisions" not in value:
        return NBAConferenceAlignment(
            tuple(east),
            tuple(west),
            version=str(value["version"]),
        )
    east_divisions = _division_tuple(value["east_divisions"], "east")
    west_divisions = _division_tuple(value["west_divisions"], "west")
    return NBAConferenceAlignment(
        tuple(east),
        tuple(west),
        version=str(value["version"]),
        east_divisions=east_divisions,
        west_divisions=west_divisions,
    )


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
    alignment: NBAConferenceAlignment | None = None,
) -> SeasonSchedule:
    active_rules = rules or NBARegularSeasonRules()
    if team_ids != tuple(sorted(set(team_ids))) or len(team_ids) != active_rules.team_count:
        raise ValueError("NBA team ids must contain thirty ordered unique teams")
    active_alignment = alignment or NBAConferenceAlignment(team_ids[:15], team_ids[15:])
    if set((*active_alignment.east_team_ids, *active_alignment.west_team_ids)) != set(team_ids):
        raise ValueError("NBA alignment must cover the scheduled teams exactly")
    three_game_home = _three_game_home_teams(active_alignment)
    divisions = (*active_alignment.east_divisions, *active_alignment.west_divisions)
    division_by_team = {
        team_id: division_index
        for division_index, division in enumerate(divisions)
        for team_id in division
    }
    conference_by_team = {
        team_id: conference
        for conference, conference_teams in (
            ("east", active_alignment.east_team_ids),
            ("west", active_alignment.west_team_ids),
        )
        for team_id in conference_teams
    }
    unscheduled: list[tuple[int, str, str, str, str]] = []
    for first_index, first in enumerate(team_ids):
        for second in team_ids[first_index + 1 :]:
            same_conference = conference_by_team[first] == conference_by_team[second]
            same_division = division_by_team[first] == division_by_team[second]
            pair = frozenset((first, second))
            count = (
                4
                if same_division
                else 3
                if pair in three_game_home
                else 4
                if same_conference
                else 2
            )
            preferred_home = three_game_home.get(pair)
            for copy_index in range(count):
                if count == 3:
                    assert preferred_home is not None
                    home = (
                        preferred_home
                        if copy_index < 2
                        else second
                        if preferred_home == first
                        else first
                    )
                else:
                    home = first if copy_index % 2 == 0 else second
                away = second if home == first else first
                unscheduled.append((copy_index, first, second, home, away))
    days: list[tuple[list[tuple[str, str]], set[str]]] = []
    for _, _, _, home, away in sorted(unscheduled):
        for games, occupied in days:
            if home not in occupied and away not in occupied:
                games.append((home, away))
                occupied.update((home, away))
                break
        else:
            days.append(([(home, away)], {home, away}))
    calendar_days = _nba_calendar_days(len(days), active_rules)
    scheduled_games: list[ScheduledGame] = []
    for day, (matchups, _) in zip(calendar_days, days, strict=True):
        for home, away in sorted(matchups):
            scheduled_games.append(ScheduledGame(len(scheduled_games) + 1, day, home, away))
    schedule = SeasonSchedule(team_ids, tuple(scheduled_games))
    appearances = Counter(
        team_id for game in schedule.games for team_id in (game.home_team_id, game.away_team_id)
    )
    if set(appearances.values()) != {active_rules.games_per_team}:
        raise ValueError("generated NBA schedule does not contain eighty-two games per team")
    home_games = Counter(game.home_team_id for game in schedule.games)
    if set(home_games.values()) != {active_rules.games_per_team // 2}:
        raise ValueError("generated NBA schedule does not balance home games")
    _validate_nba_calendar_gate(schedule, active_rules)
    return schedule


def _nba_calendar_days(
    slot_count: int,
    rules: NBARegularSeasonRules,
) -> tuple[int, ...]:
    """Map conflict-free matchup slots onto a deterministic NBA-style calendar."""
    if slot_count < 52:
        raise ValueError("NBA matchup slots cannot support the calendar gate")
    transition_count = slot_count - 1
    back_to_back_after = {1 + 5 * index for index in range(rules.back_to_back_windows)}
    all_star_break_after = 50
    if (
        max(back_to_back_after, default=0) > transition_count
        or all_star_break_after > transition_count
        or all_star_break_after in back_to_back_after
    ):
        raise ValueError("NBA matchup slots cannot support the frozen calendar layout")
    gaps = {
        transition: (
            8
            if transition == all_star_break_after
            else 1
            if transition in back_to_back_after
            else 2
        )
        for transition in range(1, transition_count + 1)
    }
    extra_days = rules.season_span_days - 1 - sum(gaps.values())
    if extra_days < 0:
        raise ValueError("NBA matchup slots exceed the configured season span")
    ordinary = tuple(
        transition
        for transition in gaps
        if transition not in back_to_back_after and transition != all_star_break_after
    )
    if extra_days > len(ordinary):
        raise ValueError("NBA season span requires unsupported calendar padding")
    for extra_index in range(extra_days):
        ordinary_index = (extra_index + 1) * len(ordinary) // (extra_days + 1)
        gaps[ordinary[ordinary_index]] += 1
    calendar = [1]
    for transition in range(1, transition_count + 1):
        calendar.append(calendar[-1] + gaps[transition])
    if calendar[-1] != rules.season_span_days:
        raise ValueError("NBA calendar does not reach the configured season span")
    return tuple(calendar)


def _validate_nba_calendar_gate(
    schedule: SeasonSchedule,
    rules: NBARegularSeasonRules,
) -> None:
    if not schedule.games or schedule.games[0].day != 1:
        raise ValueError("NBA calendar must begin on day one")
    if schedule.games[-1].day != rules.season_span_days:
        raise ValueError("NBA calendar span differs")
    days_by_team = {
        team_id: tuple(
            game.day for game in schedule.games if team_id in (game.home_team_id, game.away_team_id)
        )
        for team_id in schedule.team_ids
    }
    for team_id, days_played in days_by_team.items():
        gaps = tuple(second - first for first, second in pairwise(days_played))
        back_to_backs = sum(gap == 1 for gap in gaps)
        one_day_rest = sum(gap == 2 for gap in gaps)
        longest_rest = max((gap - 1 for gap in gaps), default=0)
        consecutive = 1
        longest_consecutive = 1
        for gap in gaps:
            consecutive = consecutive + 1 if gap == 1 else 1
            longest_consecutive = max(longest_consecutive, consecutive)
        if (
            not rules.minimum_team_back_to_backs
            <= back_to_backs
            <= rules.maximum_team_back_to_backs
        ):
            raise ValueError(f"NBA back-to-back gate differs: {team_id}")
        if longest_consecutive > rules.maximum_consecutive_game_days:
            raise ValueError(f"NBA consecutive-game gate differs: {team_id}")
        if not (
            rules.minimum_one_day_rest_intervals
            <= one_day_rest
            <= rules.maximum_one_day_rest_intervals
        ):
            raise ValueError(f"NBA one-day-rest gate differs: {team_id}")
        if not rules.minimum_longest_rest_days <= longest_rest <= rules.maximum_longest_rest_days:
            raise ValueError(f"NBA long-rest gate differs: {team_id}")


def _default_divisions(team_ids: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    return tuple(tuple(team_ids[index : index + 5]) for index in range(0, 15, 5))


def _validate_divisions(
    divisions: tuple[tuple[str, ...], ...],
    conference_team_ids: tuple[str, ...],
    conference: str,
) -> None:
    if (
        len(divisions) != 3
        or any(len(division) != 5 for division in divisions)
        or any(division != tuple(sorted(set(division))) for division in divisions)
        or divisions != tuple(sorted(divisions))
        or {team_id for division in divisions for team_id in division} != set(conference_team_ids)
    ):
        raise ValueError(f"{conference} divisions must be three ordered five-team groups")


def _division_tuple(value: object, conference: str) -> tuple[tuple[str, ...], ...]:
    if not isinstance(value, list) or any(
        not isinstance(division, list) or any(not isinstance(team_id, str) for team_id in division)
        for division in value
    ):
        raise ValueError(f"{conference} divisions must be string lists")
    return tuple(tuple(division) for division in value)


def _three_game_home_teams(
    alignment: NBAConferenceAlignment,
) -> dict[frozenset[str], str]:
    result: dict[frozenset[str], str] = {}
    for divisions in (alignment.east_divisions, alignment.west_divisions):
        for left_index, right_index in ((0, 1), (0, 2), (1, 2)):
            left = divisions[left_index]
            right = divisions[right_index]
            for offset in (0, 1):
                for index, left_team in enumerate(left):
                    right_team = right[(index + offset) % 5]
                    result[frozenset((left_team, right_team))] = (
                        left_team if offset == 0 else right_team
                    )
    return result


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
