from typing import cast

from test_game_runtime import PARAMETERS, player

from courtsim.analysis.nba_quick_sim_executor import NBAQuickSimExecutor
from courtsim.domain.game import GameClockConfig
from courtsim.domain.plans import Lineup
from courtsim.model.game_runtime import GameTeam
from courtsim.model.interaction_compiler import ProfileLineup
from courtsim.nba_league import NBAConferenceAlignment
from courtsim.season import SeasonConfig


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
    assert first.summary.team_count == 30
    assert first.summary.games == 1_230
    assert first.summary.champion_seed is not None
    assert executor("nba-season", 20260726) == first.summary
