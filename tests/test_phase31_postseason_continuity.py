import json
from dataclasses import replace

from test_phase12_manager_league_adapter import adapter, request

from courtsim.manager_experiment import ManagerExperimentArm
from courtsim.playoffs import PlayoffConfig
from courtsim.season import SeasonConfig


def test_postseason_starts_from_regular_season_fatigue_and_recovers_between_games() -> None:
    configured = replace(
        adapter(),
        playoff_config=PlayoffConfig(3, (True, False, True)),
        season_config=SeasonConfig(
            injury_probability_bps=0,
            daily_fatigue_recovery=0,
        ),
        postseason_rest_days=0,
        playoff_game_rest_days=0,
        playoff_round_rest_days=0,
    )
    execution = configured(request(ManagerExperimentArm.INCUMBENT))
    audit = json.loads(execution.audit_payload)
    continuity = audit["postseason_continuity"]

    assert continuity["initial_player_states"] == audit["season"]["final_player_states"]
    assert max(state["fatigue"] for state in continuity["initial_player_states"]) > 0
    assert continuity["players_with_fatigue_change"] > 0
    assert len(continuity["games"]) >= 6
    assert all(game["maximum_initial_fatigue"] > 0 for game in continuity["games"])

    by_series: dict[tuple[int, int], list[int]] = {}
    for game in continuity["games"]:
        by_series.setdefault(
            (game["round_number"], game["series_index"]),
            [],
        ).append(game["day"])
    assert all(days == list(range(days[0], days[0] + len(days))) for days in by_series.values())


def test_postseason_injuries_make_players_unavailable_in_later_series_games() -> None:
    configured = replace(
        adapter(),
        playoff_config=PlayoffConfig(3, (True, False, True)),
        season_config=SeasonConfig(
            injury_probability_bps=10_000,
            minimum_days_out=2,
            maximum_days_out=2,
            daily_fatigue_recovery=0,
        ),
        postseason_rest_days=10,
        playoff_game_rest_days=1,
        playoff_round_rest_days=2,
    )
    execution = configured(request(ManagerExperimentArm.INCUMBENT))
    continuity = json.loads(execution.audit_payload)["postseason_continuity"]

    assert continuity["postseason_injuries"] > 0
    assert continuity["injuries"]
    assert any(
        game["game_number"] > 1 and (game["home_unavailable"] or game["away_unavailable"])
        for game in continuity["games"]
    )
    assert any(game["forfeit_team_id"] is not None for game in continuity["games"])
