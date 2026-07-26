"""Fourteen-team NBA draft lottery and complete thirty-team order."""

from __future__ import annotations

from dataclasses import dataclass

from courtsim.draft_lottery import (
    DraftLotteryResult,
    DraftLotteryRules,
    resolve_draft_lottery,
)
from courtsim.nba_league import NBAPostseasonResult
from courtsim.season import SeasonResult

NBA_DRAFT_LOTTERY_VERSION = "nba-draft-lottery-v1"
NBA_DRAFT_LOTTERY_RULES = DraftLotteryRules(
    drawn_slots=4,
    weight_bps=(
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
    ),
)


@dataclass(frozen=True, slots=True)
class NBADraftLotteryResult:
    draft_year: int
    non_playoff_order: tuple[str, ...]
    playoff_order: tuple[str, ...]
    lottery: DraftLotteryResult
    final_order: tuple[str, ...]
    version: str = NBA_DRAFT_LOTTERY_VERSION

    def __post_init__(self) -> None:
        if len(self.non_playoff_order) != 14 or len(self.playoff_order) != 16:
            raise ValueError(
                "NBA draft order requires fourteen non-playoff and sixteen playoff teams"
            )
        all_teams = (*self.non_playoff_order, *self.playoff_order)
        if len(set(all_teams)) != 30 or any(not team_id.strip() for team_id in all_teams):
            raise ValueError("NBA draft order must cover thirty unique teams")
        if self.lottery.base_order != self.non_playoff_order:
            raise ValueError("NBA lottery base order differs from non-playoff order")
        if self.final_order != (*self.lottery.final_order, *self.playoff_order):
            raise ValueError("NBA final draft order does not derive from lottery and playoff order")
        if self.version != NBA_DRAFT_LOTTERY_VERSION:
            raise ValueError("unsupported NBA draft lottery version")


def resolve_nba_draft_lottery(
    *,
    draft_year: int,
    master_seed: int,
    non_playoff_order: tuple[str, ...],
    playoff_order: tuple[str, ...],
) -> NBADraftLotteryResult:
    if len(non_playoff_order) != 14 or len(playoff_order) != 16:
        raise ValueError("NBA draft order requires fourteen non-playoff and sixteen playoff teams")
    if (
        len(set(non_playoff_order)) != 14
        or len(set(playoff_order)) != 16
        or any(not team_id.strip() for team_id in (*non_playoff_order, *playoff_order))
    ):
        raise ValueError("NBA draft order partitions must contain unique non-blank teams")
    if set(non_playoff_order) & set(playoff_order):
        raise ValueError("NBA lottery and playoff teams must be distinct")
    lottery = resolve_draft_lottery(
        draft_year=draft_year,
        master_seed=master_seed,
        base_order=non_playoff_order,
        rules=NBA_DRAFT_LOTTERY_RULES,
    )
    return NBADraftLotteryResult(
        draft_year,
        non_playoff_order,
        playoff_order,
        lottery,
        (*lottery.final_order, *playoff_order),
    )


def resolve_nba_draft_lottery_from_results(
    *,
    draft_year: int,
    master_seed: int,
    season: SeasonResult,
    postseason: NBAPostseasonResult,
) -> NBADraftLotteryResult:
    regular_worst_to_best = tuple(row.team_id for row in reversed(season.standings))
    playoff_teams = {item.team_id for item in (*postseason.east_seeds, *postseason.west_seeds)}
    if (
        len(regular_worst_to_best) != 30
        or len(set(regular_worst_to_best)) != 30
        or len(playoff_teams) != 16
        or not playoff_teams <= set(regular_worst_to_best)
    ):
        raise ValueError("NBA season and postseason must cover thirty teams and sixteen qualifiers")
    non_playoff_order = tuple(
        team_id for team_id in regular_worst_to_best if team_id not in playoff_teams
    )
    elimination_round = {team_id: 5 for team_id in playoff_teams}
    for series in postseason.series:
        loser = (
            series.second_team_id
            if series.winner_team_id == series.first_team_id
            else series.first_team_id
        )
        elimination_round[loser] = series.round_number
    regular_order = {team_id: index for index, team_id in enumerate(regular_worst_to_best)}
    playoff_order = tuple(
        sorted(
            playoff_teams,
            key=lambda team_id: (
                elimination_round[team_id],
                regular_order[team_id],
            ),
        )
    )
    return resolve_nba_draft_lottery(
        draft_year=draft_year,
        master_seed=master_seed,
        non_playoff_order=non_playoff_order,
        playoff_order=playoff_order,
    )
