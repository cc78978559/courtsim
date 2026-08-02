from dataclasses import replace
from typing import cast

import pytest
from test_game_runtime import PARAMETERS, player
from test_phase12_manager_league_adapter import career_player

from courtsim.analysis.nba_quick_sim_executor import (
    NBA_QUICK_SIM_EXECUTOR_LEGACY_VERSION,
    NBA_QUICK_SIM_EXECUTOR_VERSION,
    NBAQuickSimExecutor,
    build_nba_player_season_summaries,
)
from courtsim.domain.game import GameClockConfig
from courtsim.domain.plans import Lineup
from courtsim.model.game_runtime import GameTeam
from courtsim.model.interaction_compiler import ProfileLineup
from courtsim.nba_league import NBAConferenceAlignment
from courtsim.season import SeasonConfig

pytestmark = [pytest.mark.slow, pytest.mark.nba]


def _teams() -> tuple[GameTeam, ...]:
    teams = []
    for team_index in range(30):
        lineup = cast(
            Lineup,
            tuple(team_index * 5 + offset for offset in range(1, 6)),
        )
        teams.append(
            GameTeam(
                f"T{team_index + 1:02d}",
                lineup,
                cast(ProfileLineup, tuple(player(player_id) for player_id in lineup)),
            )
        )
    return tuple(teams)


def test_executor_runs_complete_nba_path_deterministically() -> None:
    teams = _teams()
    team_ids = tuple(team.team_id for team in teams)
    executor = NBAQuickSimExecutor(
        PARAMETERS,
        GameClockConfig(1, 5, 5, 5, 8, True),
        teams,
        NBAConferenceAlignment(team_ids[:15], team_ids[15:]),
        season_config=SeasonConfig(injury_probability_bps=0),
    )
    first = executor.execute("nba-season", 20260726)
    second = executor.execute("nba-season", 20260726)
    assert first == second
    assert len(first.season.games) == 1_230
    assert len(first.east_play_in.games) == 3
    assert len(first.west_play_in.games) == 3
    assert len(first.postseason.series) == 15
    assert first.postseason_state.initial_player_states == first.season.final_player_states
    assert len(first.postseason_state.games) >= 66
    assert len(first.postseason_state.learning_totals) == (len(first.postseason_state.games) * 2)
    assert sum(dict(first.postseason_state.team_games).values()) == (
        len(first.postseason_state.games) * 2
    )
    assert all(
        game.day <= following.day
        for game, following in zip(
            first.postseason_state.games,
            first.postseason_state.games[1:],
            strict=False,
        )
    )
    first_round_games = [
        game
        for game in first.postseason_state.games
        if len(game.address) >= 2 and game.address[1] == "1"
    ]
    first_game_by_series: dict[str, int] = {}
    for game in first_round_games:
        first_game_by_series.setdefault(game.address[2], game.day)
    assert len(first_game_by_series) == 8
    assert len(set(first_game_by_series.values())) == 1
    play_in_openers = [
        game.day
        for game in first.postseason_state.games
        if len(game.address) >= 3 and game.address[1] == "play-in" and game.address[2] in {"1", "2"}
    ]
    assert len(play_in_openers) == 4
    assert len(set(play_in_openers)) == 1
    assert first.version == NBA_QUICK_SIM_EXECUTOR_VERSION
    assert first.summary.team_count == 30
    assert first.summary.games == 1_230
    assert first.summary.champion_seed is not None
    career_summaries = build_nba_player_season_summaries(
        first,
        tuple(career_player(player_id) for player_id in range(1, 151)),
    )
    assert len(career_summaries) == 150
    assert all(summary.games_available >= 82 for summary in career_summaries)
    assert sum(summary.seconds_played for summary in career_summaries) > 0
    assert executor("nba-season", 20260726) == first.summary

    legacy = replace(executor, version=NBA_QUICK_SIM_EXECUTOR_LEGACY_VERSION).execute(
        "legacy-nba-season", 20260726
    )
    legacy_first_round_starts: dict[str, int] = {}
    for game in legacy.postseason_state.games:
        if len(game.address) >= 2 and game.address[1] == "1":
            legacy_first_round_starts.setdefault(game.address[2], game.day)
    assert legacy.version == NBA_QUICK_SIM_EXECUTOR_LEGACY_VERSION
    assert len(set(legacy_first_round_starts.values())) > 1

    injury_run = replace(
        executor,
        season_config=SeasonConfig(
            injury_probability_bps=10_000,
            minimum_days_out=2,
            maximum_days_out=2,
        ),
    ).execute("injury-season", 77)
    assert injury_run.postseason_state.injuries
    assert any(
        game.home_unavailable or game.away_unavailable for game in injury_run.postseason_state.games
    )
