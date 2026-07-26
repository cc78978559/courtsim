from collections import Counter

import pytest

from courtsim.nba_draft_lottery import (
    NBA_DRAFT_LOTTERY_RULES,
    resolve_nba_draft_lottery,
    resolve_nba_draft_lottery_from_results,
)
from courtsim.nba_league import NBASeriesResult, resolve_nba_playoffs
from courtsim.playoffs import PlayoffSeed
from courtsim.season import SeasonResult, SeasonSchedule, SeasonStanding


def _orders() -> tuple[tuple[str, ...], tuple[str, ...]]:
    return (
        tuple(f"L{index:02d}" for index in range(1, 15)),
        tuple(f"P{index:02d}" for index in range(1, 17)),
    )


def test_nba_lottery_draws_four_of_fourteen_and_appends_playoff_order() -> None:
    lottery_order, playoff_order = _orders()
    first = resolve_nba_draft_lottery(
        draft_year=2029,
        master_seed=20260726,
        non_playoff_order=lottery_order,
        playoff_order=playoff_order,
    )
    second = resolve_nba_draft_lottery(
        draft_year=2029,
        master_seed=20260726,
        non_playoff_order=lottery_order,
        playoff_order=playoff_order,
    )
    assert first == second
    assert len(first.lottery.draws) == 4
    assert len(first.final_order) == 30
    assert first.final_order[14:] == playoff_order
    assert set(first.final_order[:14]) == set(lottery_order)
    assert tuple(draw.slot for draw in first.lottery.draws) == (1, 2, 3, 4)
    assert len({draw.selected_team_id for draw in first.lottery.draws}) == 4


def test_nba_lottery_odds_are_canonical_and_invalid_partitions_fail() -> None:
    assert NBA_DRAFT_LOTTERY_RULES.weight_bps == (
        1_400,
        1_400,
        1_400,
        1_250,
        1_050,
        900,
        750,
        600,
        450,
        300,
        200,
        150,
        100,
        50,
    )
    assert sum(NBA_DRAFT_LOTTERY_RULES.weight_bps) == 10_000
    assert Counter(NBA_DRAFT_LOTTERY_RULES.weight_bps)[1_400] == 3
    lottery_order, playoff_order = _orders()
    with pytest.raises(ValueError, match="distinct"):
        resolve_nba_draft_lottery(
            draft_year=2029,
            master_seed=1,
            non_playoff_order=lottery_order,
            playoff_order=(lottery_order[0], *playoff_order[1:]),
        )
    with pytest.raises(ValueError, match="fourteen"):
        resolve_nba_draft_lottery(
            draft_year=2029,
            master_seed=1,
            non_playoff_order=lottery_order[:-1],
            playoff_order=playoff_order,
        )


def _sweep(
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


def test_full_order_derives_non_playoff_and_elimination_groups() -> None:
    east = tuple(PlayoffSeed(index, f"E{index:02d}") for index in range(1, 9))
    west = tuple(PlayoffSeed(index, f"W{index:02d}") for index in range(1, 9))
    ledger = (
        _sweep(1, 1, "east", "E01", "E08"),
        _sweep(1, 2, "east", "E04", "E05"),
        _sweep(1, 3, "east", "E02", "E07"),
        _sweep(1, 4, "east", "E03", "E06"),
        _sweep(1, 5, "west", "W01", "W08"),
        _sweep(1, 6, "west", "W04", "W05"),
        _sweep(1, 7, "west", "W02", "W07"),
        _sweep(1, 8, "west", "W03", "W06"),
        _sweep(2, 1, "east", "E01", "E04"),
        _sweep(2, 2, "east", "E02", "E03"),
        _sweep(2, 1, "west", "W01", "W04"),
        _sweep(2, 2, "west", "W02", "W03"),
        _sweep(3, 1, "east", "E01", "E02"),
        _sweep(3, 1, "west", "W01", "W02"),
        _sweep(4, 1, "nba", "E01", "W01"),
    )
    postseason = resolve_nba_playoffs(
        east_seeds=east,
        west_seeds=west,
        series=ledger,
    )
    team_ids = tuple(
        team_id for index in range(1, 16) for team_id in (f"E{index:02d}", f"W{index:02d}")
    )
    standings = tuple(
        SeasonStanding(index, team_id, 31 - index, index, 0, 1000, 1000)
        for index, team_id in enumerate(team_ids, start=1)
    )
    season = SeasonResult(SeasonSchedule(team_ids, ()), (), standings, (), ())
    result = resolve_nba_draft_lottery_from_results(
        draft_year=2029,
        master_seed=5,
        season=season,
        postseason=postseason,
    )
    assert len(result.non_playoff_order) == 14
    assert len(result.playoff_order) == 16
    assert result.playoff_order[-2:] == ("W01", "E01")
    assert set(result.final_order) == set(team_ids)
