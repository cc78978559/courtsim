import json
from dataclasses import fields, replace
from pathlib import Path

import pytest
from test_game_runtime import PARAMETERS, player

from courtsim.career import (
    CareerPlayer,
    CareerStatus,
    DevelopmentTraits,
    DraftRules,
)
from courtsim.domain.game import GameClockConfig
from courtsim.domain.player import AbilityRatings
from courtsim.management import (
    ContractRules,
    LeagueManagementState,
    PlayerContract,
)
from courtsim.manager_ai import ManagerProfile
from courtsim.manager_evaluation import ManagerEvidenceThresholds
from courtsim.manager_experiment import (
    ManagerExperimentArm,
    ManagerExperimentSpec,
    ManagerSeasonRequest,
    run_manager_experiment,
)
from courtsim.manager_league_adapter import (
    CourtSimLeagueState,
    CourtSimManagerLeagueAdapter,
    ManagerLeagueAdapterError,
    league_state_from_json,
    league_state_to_json,
)
from courtsim.playoffs import PlayoffConfig
from courtsim.rosters import RosterSnapshot
from courtsim.season import SeasonConfig

TEAM_IDS = ("A", "B", "C", "D")


def ratings(value: int) -> AbilityRatings:
    return AbilityRatings(**{item.name: value for item in fields(AbilityRatings)})


def career_player(
    player_id: int,
    *,
    value: int = 60,
    potential: int = 80,
    status: CareerStatus = CareerStatus.ACTIVE,
) -> CareerPlayer:
    profile = replace(player(player_id), abilities=ratings(value))
    return CareerPlayer(
        profile,
        22 if status is CareerStatus.ACTIVE else 19,
        2 if status is CareerStatus.ACTIVE else 0,
        DevelopmentTraits(consistency=100),
        ratings(potential),
        status,
    )


def league_state() -> CourtSimLeagueState:
    rules = ContractRules(
        salary_cap=20_000_000,
        minimum_salary=1_000_000,
        maximum_salary=5_000_000,
        maximum_years=4,
        maximum_roster_players=10,
    )
    rosters = tuple(
        RosterSnapshot(team_id, tuple(range(index * 5 + 1, index * 5 + 6)))
        for index, team_id in enumerate(TEAM_IDS)
    )
    contracts = tuple(
        PlayerContract(player_id, roster.team_id, 1_000_000, 4)
        for roster in rosters
        for player_id in roster.player_ids
    )
    players = (
        *(career_player(player_id) for player_id in range(1, 21)),
        career_player(100, value=80, potential=80, status=CareerStatus.PROSPECT),
        career_player(101, value=70, potential=100, status=CareerStatus.PROSPECT),
        career_player(102, value=68, potential=95, status=CareerStatus.PROSPECT),
        career_player(103, value=65, potential=90, status=CareerStatus.PROSPECT),
    )
    return CourtSimLeagueState(
        rules,
        LeagueManagementState(2028, rosters, (), contracts),
        players,
    )


def adapter() -> CourtSimManagerLeagueAdapter:
    return CourtSimManagerLeagueAdapter(
        PARAMETERS,
        GameClockConfig(1, 20, 10, 10, 4, True),
        tuple(ManagerProfile(f"manager-{team_id}", team_id) for team_id in TEAM_IDS),
        draft_rules=DraftRules(
            rounds=1,
            rookie_salary=1_000_000,
            rookie_contract_years=2,
        ),
        season_config=SeasonConfig(injury_probability_bps=0),
        playoff_config=PlayoffConfig(1, (True,)),
        games_per_pair=1,
    )


def request(arm: ManagerExperimentArm) -> ManagerSeasonRequest:
    return ManagerSeasonRequest(
        "league-study",
        "manager-policy-v1",
        arm,
        "source-0001",
        991,
        2028,
        league_state_to_json(league_state()),
    )


def test_league_state_json_round_trip_and_tamper_rejection() -> None:
    state = league_state()
    payload = league_state_to_json(state)
    assert league_state_from_json(payload) == state
    raw = json.loads(payload)
    raw["extra"] = True
    with pytest.raises(ManagerLeagueAdapterError, match="keys"):
        league_state_from_json(json.dumps(raw))


def test_adapter_runs_real_season_playoffs_and_offseason_deterministically() -> None:
    first = adapter()(request(ManagerExperimentArm.INCUMBENT))
    second = adapter()(request(ManagerExperimentArm.INCUMBENT))
    assert first == second
    next_state = league_state_from_json(first.next_state_payload)
    assert next_state.management.season_year == 2029
    assert {pick.draft_year for pick in next_state.draft_assets.picks} == {2030, 2031}
    assert len(first.metrics) == 4
    assert all(0 <= metric.win_rate <= 1 for metric in first.metrics)
    audit = json.loads(first.audit_payload)
    assert set(audit) == {
        "adapter_version",
        "arm",
        "season",
        "playoffs",
        "offseason",
        "manager_decisions",
        "prospect_class",
        "rotations",
        "trade_market",
        "draft_assets",
        "draft_lottery",
    }
    assert audit["prospect_class"] is None
    assert audit["trade_market"] is None
    assert audit["draft_assets"]["draft_year"] == 2029
    assert len(audit["draft_lottery"]["draws"]) == 2
    assert audit["playoffs"]["champion_team_id"] in TEAM_IDS
    assert len(audit["offseason"]["selections"]) == 4
    assert set(audit["rotations"]) == set(TEAM_IDS)
    following = adapter()(
        replace(
            request(ManagerExperimentArm.INCUMBENT),
            season_year=2029,
            state_payload=first.next_state_payload,
        )
    )
    following_state = league_state_from_json(following.next_state_payload)
    assert following_state.management.season_year == 2030
    assert {pick.draft_year for pick in following_state.draft_assets.picks} == {2031, 2032}
    following_audit = json.loads(following.audit_payload)
    assert following_audit["prospect_class"]["draft_year"] == 2030
    assert len(following_audit["offseason"]["selections"]) == 4
    playing_ids = {
        item["player_id"]
        for game in following_audit["season"]["games"]
        if game["result"] is not None
        for item in game["result"]["playing_time"]
    }
    assert {100, 101, 102, 103} <= playing_ids


def test_shadow_uses_white_box_draft_and_market_ledgers() -> None:
    incumbent = adapter()(request(ManagerExperimentArm.INCUMBENT))
    shadow = adapter()(request(ManagerExperimentArm.SHADOW))
    incumbent_audit = json.loads(incumbent.audit_payload)
    shadow_audit = json.loads(shadow.audit_payload)
    assert incumbent_audit["manager_decisions"] == {}
    assert set(shadow_audit["manager_decisions"]) == {"draft", "market", "trade"}
    assert shadow_audit["trade_market"]["candidate_count"] > 0
    assert incumbent_audit["season"]["games"] == shadow_audit["season"]["games"]
    assert incumbent_audit["playoffs"] == shadow_audit["playoffs"]
    incumbent_picks = tuple(
        item["player_id"] for item in incumbent_audit["offseason"]["selections"]
    )
    shadow_picks = tuple(item["player_id"] for item in shadow_audit["offseason"]["selections"])
    assert incumbent_picks != shadow_picks


def test_adapter_drives_resumable_manager_experiment_end_to_end(tmp_path: Path) -> None:
    state = league_state()
    result = run_manager_experiment(
        spec=ManagerExperimentSpec(
            "league-study",
            "manager-policy-v1",
            (991,),
            2028,
            1,
            TEAM_IDS,
            league_state_to_json(state),
        ),
        executor=adapter(),
        output_directory=tmp_path / "league-study",
        thresholds=ManagerEvidenceThresholds(
            minimum_independent_sources=1,
            minimum_seasons_per_source=1,
            minimum_mean_utility_delta=-1,
            minimum_win_rate_delta=-1,
            maximum_loss_rate=1,
            minimum_worst_source_delta=-1,
        ),
    )
    assert result.evidence.observation_count == 4
    assert result.evidence.independent_sources == 1
    assert result.executed_cells == 2
    resumed = run_manager_experiment(
        spec=ManagerExperimentSpec(
            "league-study",
            "manager-policy-v1",
            (991,),
            2028,
            1,
            TEAM_IDS,
            league_state_to_json(state),
        ),
        executor=adapter(),
        output_directory=tmp_path / "league-study",
        thresholds=ManagerEvidenceThresholds(
            minimum_independent_sources=1,
            minimum_seasons_per_source=1,
            minimum_mean_utility_delta=-1,
            minimum_win_rate_delta=-1,
            maximum_loss_rate=1,
            minimum_worst_source_delta=-1,
        ),
    )
    assert resumed.executed_cells == 0
    assert resumed.reused_cells == 2


def test_adapter_rejects_wrong_season_or_unplayable_roster() -> None:
    wrong = replace(request(ManagerExperimentArm.INCUMBENT), season_year=2029)
    with pytest.raises(ManagerLeagueAdapterError, match="season"):
        adapter()(wrong)
    state = league_state()
    broken_management = replace(
        state.management,
        rosters=(
            RosterSnapshot("A", (1, 2, 3, 4)),
            *state.management.rosters[1:],
        ),
        contracts=tuple(
            contract for contract in state.management.contracts if contract.player_id != 5
        ),
        free_agent_ids=(5,),
    )
    broken = CourtSimLeagueState(state.contract_rules, broken_management, state.players)
    with pytest.raises(ManagerLeagueAdapterError, match="fewer than five"):
        adapter()(
            replace(
                request(ManagerExperimentArm.INCUMBENT),
                state_payload=league_state_to_json(broken),
            )
        )
