from collections import Counter
from itertools import pairwise

import pytest

from courtsim.nba_league import (
    NBAConferenceAlignment,
    NBASeriesResult,
    PlayInGame,
    _nba_unscheduled_matchups,
    generate_nba_schedule,
    nba_alignment_from_dict,
    nba_alignment_to_dict,
    nba_series_home_court_order,
    resolve_nba_playoffs,
    resolve_play_in,
)
from courtsim.playoffs import PlayoffSeed


def team_ids() -> tuple[str, ...]:
    return tuple(f"T{index:02d}" for index in range(1, 31))


def _pair(first: str, second: str) -> tuple[str, str]:
    return (first, second) if first < second else (second, first)


def test_series_home_court_uses_record_for_finals_and_seed_within_conference() -> None:
    seeds = {"E1": 1, "W4": 4, "W1": 1, "E2": 2}
    records = {"E1": (50, 300), "W4": (60, 100), "W1": (50, 200), "E2": (50, 200)}
    assert nba_series_home_court_order(
        "E1", "W4", conference="nba", seed_by_team=seeds, regular_season_records=records
    ) == ("W4", "E1")
    assert nba_series_home_court_order(
        "W4", "W1", conference="west", seed_by_team=seeds, regular_season_records=records
    ) == ("W1", "W4")
    assert nba_series_home_court_order(
        "W1", "E2", conference="nba", seed_by_team=seeds, regular_season_records=records
    ) == ("E2", "W1")


@pytest.mark.slow
@pytest.mark.nba
def test_thirty_team_schedule_has_1230_games_and_82_per_team() -> None:
    schedule = generate_nba_schedule(team_ids())
    assert schedule == generate_nba_schedule(team_ids())
    assert len(schedule.games) == 1_230
    appearances = Counter(
        team_id for game in schedule.games for team_id in (game.home_team_id, game.away_team_id)
    )
    assert set(appearances.values()) == {82}
    assert Counter(game.home_team_id for game in schedule.games) == Counter(
        {team_id: 41 for team_id in team_ids()}
    )
    for day in range(1, max(game.day for game in schedule.games) + 1):
        games = [game for game in schedule.games if game.day == day]
        participants = {
            team_id for game in games for team_id in (game.home_team_id, game.away_team_id)
        }
        assert len(games) <= 15
        assert len(participants) == len(games) * 2


@pytest.mark.slow
@pytest.mark.nba
def test_thirty_team_schedule_passes_calendar_distribution_gates() -> None:
    schedule = generate_nba_schedule(team_ids())
    assert schedule.games[0].day == 1
    assert schedule.games[-1].day == 174
    games_by_day = Counter(game.day for game in schedule.games)
    assert 158 <= len(games_by_day) <= 166
    assert 8 <= 174 - len(games_by_day) <= 16
    assert sum(6 <= games <= 9 for games in games_by_day.values()) >= 140
    assert sum(games >= 14 for games in games_by_day.values()) <= 12
    off_days = tuple(day for day in range(1, 175) if day not in games_by_day)
    off_day_runs: list[list[int]] = []
    for day in off_days:
        if not off_day_runs or day != off_day_runs[-1][-1] + 1:
            off_day_runs.append([])
        off_day_runs[-1].append(day)
    assert sorted(map(len, off_day_runs)) == [1, 1, 1, 7]
    for team_id in team_ids():
        days = tuple(
            game.day for game in schedule.games if team_id in (game.home_team_id, game.away_team_id)
        )
        gaps = tuple(second - first for first, second in pairwise(days))
        assert 12 <= sum(gap == 1 for gap in gaps) <= 20
        assert 50 <= sum(gap == 2 for gap in gaps) <= 72
        assert 7 <= max(gap - 1 for gap in gaps) <= 14
        assert all(
            not (first == second == third == 1)
            for first, second, third in zip(gaps, gaps[1:], gaps[2:], strict=False)
        )


def _assert_series_weights(
    pair_games: Counter[tuple[str, str]],
    alignment: NBAConferenceAlignment,
    teams: tuple[str, ...],
) -> None:
    for conference, divisions in (
        (set(alignment.east_team_ids), alignment.east_divisions),
        (set(alignment.west_team_ids), alignment.west_divisions),
    ):
        for team_id in conference:
            division = next(set(item) for item in divisions if team_id in item)
            division_counts = Counter(
                pair_games[_pair(team_id, opponent_id)] for opponent_id in division - {team_id}
            )
            conference_counts = Counter(
                pair_games[_pair(team_id, opponent_id)] for opponent_id in conference - division
            )
            other_counts = Counter(
                pair_games[_pair(team_id, opponent_id)] for opponent_id in set(teams) - conference
            )
            assert division_counts == {4: 4}
            assert conference_counts == {3: 4, 4: 6}
            assert other_counts == {2: 15}


def test_matchup_matrix_uses_division_conference_and_interconference_weights() -> None:
    teams = team_ids()
    alignment = NBAConferenceAlignment(teams[:15], teams[15:])
    matchups = _nba_unscheduled_matchups(teams, alignment)
    pair_games = Counter(_pair(first, second) for _, first, second, _, _ in matchups)
    appearances = Counter(
        team_id for _, first, second, _, _ in matchups for team_id in (first, second)
    )
    home_games = Counter(home for _, _, _, home, _ in matchups)
    assert len(matchups) == 1_230
    assert set(appearances.values()) == {82}
    assert set(home_games.values()) == {41}
    _assert_series_weights(pair_games, alignment, teams)


@pytest.mark.slow
@pytest.mark.nba
def test_schedule_preserves_division_conference_and_interconference_series_weights() -> None:
    teams = team_ids()
    alignment = NBAConferenceAlignment(teams[:15], teams[15:])
    schedule = generate_nba_schedule(teams, alignment=alignment)
    pair_games = Counter(_pair(game.home_team_id, game.away_team_id) for game in schedule.games)
    _assert_series_weights(pair_games, alignment, teams)


def test_explicit_divisions_round_trip_and_legacy_alignment_migrates() -> None:
    teams = team_ids()
    alignment = NBAConferenceAlignment(
        teams[:15],
        teams[15:],
        east_divisions=(teams[0:5], teams[5:10], teams[10:15]),
        west_divisions=(teams[15:20], teams[20:25], teams[25:30]),
    )
    assert nba_alignment_from_dict(nba_alignment_to_dict(alignment)) == alignment
    legacy = {
        "version": alignment.version,
        "east_team_ids": list(alignment.east_team_ids),
        "west_team_ids": list(alignment.west_team_ids),
    }
    assert nba_alignment_from_dict(legacy) == alignment


def test_play_in_derives_seventh_and_eighth_seeds() -> None:
    seeds = tuple(PlayoffSeed(index, f"E{index}") for index in range(1, 11))
    result = resolve_play_in(
        conference="east",
        seeds=seeds,
        games=(
            PlayInGame(1, "E7", "E8", 100, 90),
            PlayInGame(2, "E9", "E10", 90, 100),
            PlayInGame(3, "E8", "E10", 95, 99),
        ),
    )
    assert tuple(item.team_id for item in result.playoff_seeds) == (
        "E1",
        "E2",
        "E3",
        "E4",
        "E5",
        "E6",
        "E7",
        "E10",
    )
    assert result.eliminated_team_ids == ("E8", "E9")


def _favorite_sweep(
    round_number: int,
    series_index: int,
    conference: str,
    first: str,
    second: str,
) -> NBASeriesResult:
    return NBASeriesResult(
        round_number,
        series_index,
        conference,
        first,
        second,
        4,
        0,
    )


def test_sixteen_team_bracket_resolves_all_fifteen_series() -> None:
    east = tuple(PlayoffSeed(index, f"E{index}") for index in range(1, 9))
    west = tuple(PlayoffSeed(index, f"W{index}") for index in range(1, 9))
    ledger = (
        _favorite_sweep(1, 1, "east", "E1", "E8"),
        _favorite_sweep(1, 2, "east", "E4", "E5"),
        _favorite_sweep(1, 3, "east", "E2", "E7"),
        _favorite_sweep(1, 4, "east", "E3", "E6"),
        _favorite_sweep(1, 5, "west", "W1", "W8"),
        _favorite_sweep(1, 6, "west", "W4", "W5"),
        _favorite_sweep(1, 7, "west", "W2", "W7"),
        _favorite_sweep(1, 8, "west", "W3", "W6"),
        _favorite_sweep(2, 1, "east", "E1", "E4"),
        _favorite_sweep(2, 2, "east", "E2", "E3"),
        _favorite_sweep(2, 1, "west", "W1", "W4"),
        _favorite_sweep(2, 2, "west", "W2", "W3"),
        _favorite_sweep(3, 1, "east", "E1", "E2"),
        _favorite_sweep(3, 1, "west", "W1", "W2"),
        _favorite_sweep(4, 1, "nba", "E1", "W1"),
    )
    result = resolve_nba_playoffs(
        east_seeds=east,
        west_seeds=west,
        series=ledger,
    )
    assert len(result.series) == 15
    assert result.east_champion_team_id == "E1"
    assert result.west_champion_team_id == "W1"
    assert result.champion_team_id == "E1"


def test_play_in_and_playoff_ledgers_reject_wrong_addresses() -> None:
    seeds = tuple(PlayoffSeed(index, f"E{index}") for index in range(1, 11))
    with pytest.raises(ValueError, match="derived bracket"):
        resolve_play_in(
            conference="east",
            seeds=seeds,
            games=(
                PlayInGame(1, "E8", "E7", 100, 90),
                PlayInGame(2, "E9", "E10", 100, 90),
                PlayInGame(3, "E7", "E9", 100, 90),
            ),
        )
