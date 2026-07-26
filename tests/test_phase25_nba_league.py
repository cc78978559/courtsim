from collections import Counter

import pytest

from courtsim.nba_league import (
    NBASeriesResult,
    PlayInGame,
    generate_nba_schedule,
    resolve_nba_playoffs,
    resolve_play_in,
)
from courtsim.playoffs import PlayoffSeed


def team_ids() -> tuple[str, ...]:
    return tuple(f"T{index:02d}" for index in range(1, 31))


def test_thirty_team_schedule_has_1230_games_and_82_per_team() -> None:
    schedule = generate_nba_schedule(team_ids())
    assert schedule == generate_nba_schedule(team_ids())
    assert len(schedule.games) == 1_230
    appearances = Counter(
        team_id for game in schedule.games for team_id in (game.home_team_id, game.away_team_id)
    )
    assert set(appearances.values()) == {82}
    for day in range(1, 83):
        games = [game for game in schedule.games if game.day == day]
        assert len(games) == 15
        assert (
            len({team_id for game in games for team_id in (game.home_team_id, game.away_team_id)})
            == 30
        )


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
