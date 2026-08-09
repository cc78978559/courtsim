"""Thirty-team schedules, conference play-in, and a sixteen-team NBA bracket."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from itertools import pairwise

from courtsim.playoffs import PlayoffSeed
from courtsim.season import ScheduledGame, SeasonSchedule

NBA_LEAGUE_VERSION = "nba-league-v1"


@dataclass(frozen=True, slots=True)
class NBARegularSeasonRules:
    team_count: int = 30
    games_per_team: int = 82
    season_span_days: int = 174
    minimum_team_back_to_backs: int = 12
    maximum_team_back_to_backs: int = 20
    maximum_consecutive_game_days: int = 3
    minimum_one_day_rest_intervals: int = 50
    maximum_one_day_rest_intervals: int = 72
    minimum_longest_rest_days: int = 7
    maximum_longest_rest_days: int = 14
    minimum_game_days: int = 158
    maximum_game_days: int = 166
    minimum_league_off_days: int = 8
    maximum_league_off_days: int = 16
    balanced_day_minimum_games: int = 6
    balanced_day_maximum_games: int = 9
    minimum_balanced_game_days: int = 140
    heavy_day_minimum_games: int = 14
    maximum_heavy_game_days: int = 12
    all_star_break_days: int = 7
    all_star_break_after_game_day: int = 100
    version: str = NBA_LEAGUE_VERSION

    def __post_init__(self) -> None:
        if self.team_count != 30 or self.games_per_team != 82:
            raise ValueError("nba-league-v1 requires thirty teams and eighty-two games")
        if (
            self.season_span_days < self.games_per_team
            or not 0 <= self.minimum_team_back_to_backs <= self.maximum_team_back_to_backs
            or self.maximum_consecutive_game_days < 2
            or not 0 <= self.minimum_one_day_rest_intervals <= self.maximum_one_day_rest_intervals
            or not 0 <= self.minimum_longest_rest_days <= self.maximum_longest_rest_days
            or not 1 <= self.minimum_game_days <= self.maximum_game_days <= self.season_span_days
            or not 0 <= self.minimum_league_off_days <= self.maximum_league_off_days
            or not 1 <= self.balanced_day_minimum_games <= self.balanced_day_maximum_games <= 15
            or self.minimum_balanced_game_days < 1
            or not 1 <= self.heavy_day_minimum_games <= 15
            or self.maximum_heavy_game_days < 0
            or self.all_star_break_days < 1
            or not 1 <= self.all_star_break_after_game_day < self.minimum_game_days
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


def nba_series_home_court_order(
    first_team_id: str,
    second_team_id: str,
    *,
    conference: str,
    seed_by_team: Mapping[str, int],
    regular_season_records: Mapping[str, tuple[int, int]],
) -> tuple[str, str]:
    """Return higher/lower home-court teams under one shared NBA rule."""
    teams = (first_team_id, second_team_id)
    if conference == "nba":
        if any(team_id not in regular_season_records for team_id in teams):
            raise ValueError("NBA Finals home court requires regular-season records")
        ordered = sorted(
            teams,
            key=lambda team_id: (
                -regular_season_records[team_id][0],
                -regular_season_records[team_id][1],
                team_id,
            ),
        )
        return ordered[0], ordered[1]
    if conference not in {"east", "west"} or any(team_id not in seed_by_team for team_id in teams):
        raise ValueError("NBA conference home court requires playoff seeds")
    ordered = sorted(teams, key=lambda team_id: (seed_by_team[team_id], team_id))
    return ordered[0], ordered[1]


@lru_cache(maxsize=16)
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
    calendar = _assign_nba_calendar(days, active_rules)
    scheduled_games: list[ScheduledGame] = []
    for day, matchups in calendar:
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


def _assign_nba_calendar(
    slots: list[tuple[list[tuple[str, str]], set[str]]],
    rules: NBARegularSeasonRules,
) -> tuple[tuple[int, tuple[tuple[str, str], ...]], ...]:
    """Split dense conflict-free rounds across a realistic 174-day calendar."""
    if len(slots) < 52:
        raise ValueError("NBA matchup slots cannot support the calendar gate")
    target_game_days = min(rules.maximum_game_days, 2 * len(slots))
    unsplit_count = 2 * len(slots) - target_game_days
    unsplit_candidates = tuple(index for index, (games, _) in enumerate(slots) if len(games) >= 2)
    unsplit_slots = {
        unsplit_candidates[(index + 1) * len(unsplit_candidates) // (unsplit_count + 1)]
        for index in range(unsplit_count)
    }
    active_groups: list[list[tuple[str, str]]] = []
    split_pairs: list[tuple[int, int]] = []
    for index, (games, _) in enumerate(slots):
        ordered = tuple(sorted(games))
        if index in unsplit_slots:
            active_groups.append(list(ordered))
            continue
        midpoint = len(ordered) // 2
        early = list(ordered[:midpoint])
        late = list(ordered[midpoint:])
        if early and late:
            early_index = len(active_groups)
            active_groups.extend((early, late))
            split_pairs.append((early_index, early_index + 1))
        else:
            active_groups.append(early or late)
    if not rules.minimum_game_days <= len(active_groups) <= rules.maximum_game_days:
        raise ValueError("NBA calendar game-day count differs")
    league_off_days = rules.season_span_days - len(active_groups)
    ordinary_off_days = league_off_days - rules.all_star_break_days
    if ordinary_off_days < 0:
        raise ValueError("NBA calendar cannot fit the All-Star break")
    ordinary_breaks = {
        (index + 1) * len(active_groups) // (ordinary_off_days + 1)
        for index in range(ordinary_off_days)
    }
    day_numbers = _nba_game_day_numbers(
        len(active_groups),
        ordinary_breaks,
        rules,
    )
    _optimize_nba_split_assignments(active_groups, split_pairs, day_numbers, rules)
    _rebalance_nba_daily_groups(active_groups, day_numbers, rules)
    if day_numbers[-1] != rules.season_span_days:
        raise ValueError("NBA calendar does not reach the configured season span")
    return tuple(
        (day, tuple(sorted(group))) for day, group in zip(day_numbers, active_groups, strict=True)
    )


def _rebalance_nba_daily_groups(
    groups: list[list[tuple[str, str]]],
    day_numbers: tuple[int, ...],
    rules: NBARegularSeasonRules,
) -> None:
    """Move games off dense dates while keeping dates conflict-free."""
    days_by_team: dict[str, list[int]] = {}
    for day, group in zip(day_numbers, groups, strict=True):
        for home, away in group:
            days_by_team.setdefault(home, []).append(day)
            days_by_team.setdefault(away, []).append(day)
    for _ in range(256):
        sources = [index for index, group in enumerate(groups) if len(group) > 9]
        if not sources:
            break
        targets = [index for index, group in enumerate(groups) if len(group) < 6] or [
            index for index, group in enumerate(groups) if len(group) < 9
        ]
        best: tuple[int, int, int, dict[str, list[int]]] | None = None
        best_score: tuple[int, int, int] | None = None
        for source_index in sources:
            source_day = day_numbers[source_index]
            for game_index, game in enumerate(groups[source_index]):
                for target_index in targets:
                    target_day = day_numbers[target_index]
                    target_teams = {
                        team_id for target_game in groups[target_index] for team_id in target_game
                    }
                    if target_teams.intersection(game):
                        continue
                    revised = {
                        team_id: _moved_team_calendar_days(
                            days_by_team[team_id], source_day, target_day
                        )
                        for team_id in game
                    }
                    back_to_backs = tuple(
                        _nba_team_gap_metrics(days)[0] for days in revised.values()
                    )
                    if any(
                        value < rules.minimum_team_back_to_backs
                        or value > rules.maximum_team_back_to_backs
                        for value in back_to_backs
                    ):
                        continue
                    score = (
                        sum(_nba_consecutive_violation_count(days) for days in revised.values()),
                        abs(target_day - source_day),
                        len(groups[target_index]),
                    )
                    if best_score is None or score < best_score:
                        best_score = score
                        best = source_index, game_index, target_index, revised
        if best is None:
            raise ValueError("NBA daily groups cannot be balanced within rest bounds")
        source_index, game_index, target_index, revised = best
        groups[target_index].append(groups[source_index].pop(game_index))
        days_by_team.update(revised)
    _repair_nba_consecutive_games(groups, [], day_numbers, days_by_team, rules)


def _nba_game_day_numbers(
    game_day_count: int,
    ordinary_breaks: set[int],
    rules: NBARegularSeasonRules,
) -> tuple[int, ...]:
    result: list[int] = []
    day = 0
    for game_day in range(1, game_day_count + 1):
        day += 1
        result.append(day)
        if game_day == rules.all_star_break_after_game_day:
            day += rules.all_star_break_days
        if game_day in ordinary_breaks:
            day += 1
    return tuple(result)


def _optimize_nba_split_assignments(
    groups: list[list[tuple[str, str]]],
    split_pairs: list[tuple[int, int]],
    day_numbers: tuple[int, ...],
    rules: NBARegularSeasonRules,
) -> None:
    """Swap games between adjacent split days until team rest constraints converge."""
    days_by_team: dict[str, list[int]] = {}
    for day, group in zip(day_numbers, groups, strict=True):
        for home, away in group:
            days_by_team.setdefault(home, []).append(day)
            days_by_team.setdefault(away, []).append(day)
    penalties = {
        team_id: _nba_single_team_calendar_penalty(days, rules)
        for team_id, days in days_by_team.items()
    }
    for _ in range(256):
        best_swap: tuple[int, int, int, int] | None = None
        best_delta = 0
        for early_index, late_index in split_pairs:
            early = groups[early_index]
            late = groups[late_index]
            early_day = day_numbers[early_index]
            late_day = day_numbers[late_index]
            early_deltas = tuple(
                sum(
                    _moved_team_calendar_penalty(days_by_team[team_id], early_day, late_day, rules)
                    - penalties[team_id]
                    for team_id in game
                )
                for game in early
            )
            late_deltas = tuple(
                sum(
                    _moved_team_calendar_penalty(days_by_team[team_id], late_day, early_day, rules)
                    - penalties[team_id]
                    for team_id in game
                )
                for game in late
            )
            for first_index in range(len(early)):
                for second_index in range(len(late)):
                    delta = early_deltas[first_index] + late_deltas[second_index]
                    if delta < best_delta:
                        best_delta = delta
                        best_swap = (
                            early_index,
                            late_index,
                            first_index,
                            second_index,
                        )
        if best_swap is None:
            break
        early_index, late_index, first_index, second_index = best_swap
        early_day = day_numbers[early_index]
        late_day = day_numbers[late_index]
        first_game = groups[early_index][first_index]
        second_game = groups[late_index][second_index]
        for team_id in first_game:
            days_by_team[team_id].remove(early_day)
            days_by_team[team_id].append(late_day)
            days_by_team[team_id].sort()
            penalties[team_id] = _nba_single_team_calendar_penalty(days_by_team[team_id], rules)
        for team_id in second_game:
            days_by_team[team_id].remove(late_day)
            days_by_team[team_id].append(early_day)
            days_by_team[team_id].sort()
            penalties[team_id] = _nba_single_team_calendar_penalty(days_by_team[team_id], rules)
        groups[early_index][first_index], groups[late_index][second_index] = (
            second_game,
            first_game,
        )
    _repair_nba_consecutive_games(groups, split_pairs, day_numbers, days_by_team, rules)


def _moved_team_calendar_penalty(
    days: list[int],
    source_day: int,
    target_day: int,
    rules: NBARegularSeasonRules,
) -> int:
    revised = _moved_team_calendar_days(days, source_day, target_day)
    return _nba_single_team_calendar_penalty(revised, rules)


def _moved_team_calendar_days(days: list[int], source_day: int, target_day: int) -> list[int]:
    revised = list(days)
    revised[revised.index(source_day)] = target_day
    revised.sort()
    return revised


def _repair_nba_consecutive_games(
    groups: list[list[tuple[str, str]]],
    _split_pairs: list[tuple[int, int]],
    day_numbers: tuple[int, ...],
    days_by_team: dict[str, list[int]],
    rules: NBARegularSeasonRules,
) -> None:
    for _ in range(128):
        days_by_team = {}
        for day, group in zip(day_numbers, groups, strict=True):
            for home, away in group:
                days_by_team.setdefault(home, []).append(day)
                days_by_team.setdefault(away, []).append(day)
        offenders = tuple(
            team_id
            for team_id in sorted(days_by_team)
            if _nba_team_gap_metrics(days_by_team[team_id])[1] > rules.maximum_consecutive_game_days
        )
        if not offenders:
            return
        offender = offenders[0]
        repaired = False
        source_indices = [
            index for index, group in enumerate(groups) if any(offender in game for game in group)
        ]
        for source_index in source_indices:
            source = groups[source_index]
            source_game_index = next(index for index, game in enumerate(source) if offender in game)
            source_game = source[source_game_index]
            source_day = day_numbers[source_index]
            target_indices = sorted(
                (index for index in range(len(groups)) if index != source_index),
                key=lambda index: (abs(day_numbers[index] - source_day), index),
            )
            for target_index in target_indices:
                target = groups[target_index]
                target_day = day_numbers[target_index]
                target_teams = {team_id for game in target for team_id in game}
                if (
                    len(source) > rules.balanced_day_minimum_games
                    and len(target) < rules.balanced_day_maximum_games
                    and not target_teams.intersection(source_game)
                ):
                    moved_days = {
                        team_id: _moved_team_calendar_days(
                            days_by_team[team_id], source_day, target_day
                        )
                        for team_id in source_game
                    }
                    if _nba_calendar_repair_improves(moved_days, offender, days_by_team, rules):
                        source.pop(source_game_index)
                        target.append(source_game)
                        days_by_team.update(moved_days)
                        repaired = True
                        break
                source_other_teams = {
                    team_id
                    for index, game in enumerate(source)
                    if index != source_game_index
                    for team_id in game
                }
                for target_game_index, target_game in enumerate(target):
                    target_other_teams = {
                        team_id
                        for index, game in enumerate(target)
                        if index != target_game_index
                        for team_id in game
                    }
                    if source_other_teams.intersection(
                        target_game
                    ) or target_other_teams.intersection(source_game):
                        continue
                    revised_days: dict[str, list[int]] = {}
                    for team_id in source_game:
                        revised = list(days_by_team[team_id])
                        revised.remove(source_day)
                        revised.append(target_day)
                        revised.sort()
                        revised_days[team_id] = revised
                    for team_id in target_game:
                        revised = list(days_by_team[team_id])
                        revised.remove(target_day)
                        revised.append(source_day)
                        revised.sort()
                        revised_days[team_id] = revised
                    if not _nba_calendar_repair_improves(
                        revised_days, offender, days_by_team, rules
                    ):
                        continue
                    source[source_game_index], target[target_game_index] = (
                        target_game,
                        source_game,
                    )
                    days_by_team.update(revised_days)
                    repaired = True
                    break
                if repaired:
                    break
            if repaired:
                break
        if not repaired:
            return


def _nba_calendar_repair_improves(
    revised_days: Mapping[str, list[int]],
    offender: str,
    days_by_team: Mapping[str, list[int]],
    rules: NBARegularSeasonRules,
) -> bool:
    return (
        all(
            rules.minimum_team_back_to_backs
            <= _nba_team_gap_metrics(days)[0]
            <= rules.maximum_team_back_to_backs
            for days in revised_days.values()
        )
        and _nba_consecutive_violation_count(revised_days[offender])
        < _nba_consecutive_violation_count(days_by_team[offender])
        and sum(_nba_consecutive_violation_count(days) for days in revised_days.values())
        <= 1
        + sum(_nba_consecutive_violation_count(days_by_team[team_id]) for team_id in revised_days)
    )


def _nba_team_gap_metrics(days: list[int]) -> tuple[int, int]:
    gaps = tuple(second - first for first, second in pairwise(days))
    back_to_backs = sum(gap == 1 for gap in gaps)
    consecutive = 1
    longest_consecutive = 1
    for gap in gaps:
        consecutive = consecutive + 1 if gap == 1 else 1
        longest_consecutive = max(longest_consecutive, consecutive)
    return back_to_backs, longest_consecutive


def _nba_consecutive_violation_count(days: list[int]) -> int:
    return sum(
        second == first + 1 and third == second + 1
        for first, second, third in zip(days, days[1:], days[2:], strict=False)
    )


def _nba_single_team_calendar_penalty(
    days: list[int],
    rules: NBARegularSeasonRules,
) -> int:
    back_to_backs, longest_consecutive = _nba_team_gap_metrics(days)
    penalty = 0
    if back_to_backs < rules.minimum_team_back_to_backs:
        penalty += 100 * (rules.minimum_team_back_to_backs - back_to_backs) ** 2
    elif back_to_backs > rules.maximum_team_back_to_backs:
        penalty += 100 * (back_to_backs - rules.maximum_team_back_to_backs) ** 2
    penalty += (back_to_backs - 14) ** 2
    if longest_consecutive > rules.maximum_consecutive_game_days:
        penalty += 1_000 * (longest_consecutive - rules.maximum_consecutive_game_days) ** 2
    return penalty


def _validate_nba_calendar_gate(
    schedule: SeasonSchedule,
    rules: NBARegularSeasonRules,
) -> None:
    if not schedule.games or schedule.games[0].day != 1:
        raise ValueError("NBA calendar must begin on day one")
    if schedule.games[-1].day != rules.season_span_days:
        raise ValueError("NBA calendar span differs")
    games_by_day = Counter(game.day for game in schedule.games)
    game_days = len(games_by_day)
    off_days = rules.season_span_days - game_days
    balanced_days = sum(
        rules.balanced_day_minimum_games <= games <= rules.balanced_day_maximum_games
        for games in games_by_day.values()
    )
    heavy_days = sum(games >= rules.heavy_day_minimum_games for games in games_by_day.values())
    if not rules.minimum_game_days <= game_days <= rules.maximum_game_days:
        raise ValueError("NBA game-day gate differs")
    if not rules.minimum_league_off_days <= off_days <= rules.maximum_league_off_days:
        raise ValueError("NBA league-off-day gate differs")
    if balanced_days < rules.minimum_balanced_game_days:
        raise ValueError("NBA daily game-count distribution differs")
    if heavy_days > rules.maximum_heavy_game_days:
        raise ValueError("NBA heavy game-day gate differs")
    all_star_start = next(
        day + 1
        for index, day in enumerate(sorted(games_by_day), start=1)
        if index == rules.all_star_break_after_game_day
    )
    all_star_days = tuple(range(all_star_start, all_star_start + rules.all_star_break_days))
    if any(day in games_by_day for day in all_star_days):
        raise ValueError("NBA All-Star break contains a game")
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
