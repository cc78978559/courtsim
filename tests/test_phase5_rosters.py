import json
from dataclasses import replace

import pytest
from test_game_runtime import AWAY, HOME, PARAMETERS, player
from test_phase4_season import CONFIG, FRAME, schedule

from courtsim.domain.serialization import SerializationError
from courtsim.model.game_runtime import GameTeam
from courtsim.rosters import (
    PlayerTransfer,
    RosterRules,
    TransferPlan,
    apply_player_transfer,
    roster_snapshots,
    validate_league_rosters,
)
from courtsim.rotations import RotationPlan, RotationStint
from courtsim.season import (
    SeasonConfig,
    SeasonResult,
    audit_season,
    sample_season,
    season_result_from_dict,
    season_result_from_json,
    season_result_to_dict,
    season_result_to_json,
)


def transaction_teams() -> tuple[GameTeam, GameTeam]:
    home = replace(
        HOME,
        bench_profiles=(player(6), player(7)),
        substitution_order=(1, 2, 3, 4, 5, 6, 7),
        rotation_plan=RotationPlan((RotationStint(1, 10, (1, 2, 3, 4, 6)),)),
    )
    away = replace(
        AWAY,
        bench_profiles=(player(16),),
        substitution_order=(11, 12, 13, 14, 15, 16),
    )
    return home, away


def transfer_plan() -> TransferPlan:
    return TransferPlan((PlayerTransfer(1, 2, 1, "home", "away"),))


def managed_season(*, injured: bool = False) -> SeasonResult:
    return sample_season(
        parameters=PARAMETERS,
        game_config=CONFIG,
        schedule=schedule(1, 2),
        teams=transaction_teams(),
        frame=FRAME,
        transaction_plan=transfer_plan(),
        season_config=SeasonConfig(
            injury_probability_bps=10_000 if injured else 0,
            minimum_days_out=2,
            maximum_days_out=2,
        ),
    )


def test_roster_contract_rejects_duplicate_ownership_and_size_bounds() -> None:
    home, away = transaction_teams()
    validate_league_rosters({"home": home, "away": away}, RosterRules())
    with pytest.raises(ValueError, match="exactly one"):
        validate_league_rosters(
            {
                "home": home,
                "away": replace(
                    away,
                    bench_profiles=(player(1),),
                    substitution_order=(11, 12, 13, 14, 15, 1),
                ),
            },
            RosterRules(),
        )
    with pytest.raises(ValueError, match="bounds"):
        RosterRules(minimum_players=4)
    with pytest.raises(ValueError, match="configured"):
        validate_league_rosters(
            {"home": home, "away": away},
            RosterRules(maximum_players=6),
        )


def test_transfer_plan_is_unique_and_chronological() -> None:
    first = PlayerTransfer(1, 2, 1, "home", "away")
    with pytest.raises(ValueError, match="unique"):
        TransferPlan((first, replace(first, effective_day=3)))
    with pytest.raises(ValueError, match="ordered"):
        TransferPlan((replace(first, transaction_id=2, effective_day=3), first))
    with pytest.raises(ValueError, match="distinct"):
        PlayerTransfer(1, 1, 1, "home", "home")


def test_transfer_rebuilds_source_lineup_and_rotation_deterministically() -> None:
    home, away = transaction_teams()
    updated = apply_player_transfer(
        {"home": home, "away": away},
        transfer_plan().transfers[0],
        RosterRules(),
    )
    assert updated["home"].lineup == (2, 3, 4, 5, 6)
    assert updated["home"].rotation_plan is not None
    assert updated["home"].rotation_plan.stints[0].lineup == (2, 3, 4, 6, 5)
    assert updated["away"].lineup == away.lineup
    assert updated["away"].roster_order[-1] == 1
    assert 1 not in updated["home"].roster_order
    assert (home, away) == transaction_teams()


def test_invalid_transfer_sequence_fails_before_season_execution() -> None:
    with pytest.raises(ValueError, match="does not own"):
        sample_season(
            parameters=PARAMETERS,
            game_config=CONFIG,
            schedule=schedule(1, 2),
            teams=transaction_teams(),
            frame=FRAME,
            transaction_plan=TransferPlan((PlayerTransfer(1, 2, 99, "home", "away"),)),
            season_config=SeasonConfig(injury_probability_bps=0),
        )
    _, away = transaction_teams()
    with pytest.raises(ValueError, match="minimum"):
        apply_player_transfer(
            {
                "home": HOME,
                "away": away,
            },
            PlayerTransfer(1, 1, 1, "home", "away"),
            RosterRules(),
        )


def test_season_applies_transfer_before_effective_day_game() -> None:
    result = managed_season()
    assert result.transfers == transfer_plan().transfers
    assert result.games[0].result is not None
    assert result.games[1].result is not None
    for record in result.games[1].result.possessions:
        if record.offense_team_id == "home":
            assert record.offense_lineup is not None and 1 not in record.offense_lineup
        if record.defense_team_id == "home":
            assert record.defense_lineup is not None and 1 not in record.defense_lineup
    final = {item.team_id: item.player_ids for item in result.final_rosters}
    assert 1 not in final["home"]
    assert final["away"][-1] == 1
    states = {item.player_id: item.team_id for item in result.final_player_states}
    assert states[1] == "away"


def test_injury_and_fatigue_state_follow_transferred_player() -> None:
    result = managed_season(injured=True)
    first_injury = next(item for item in result.injuries if item.player_id == 1)
    assert first_injury.team_id == "home"
    assert first_injury.return_day == 4
    assert 1 in result.games[1].home_unavailable
    state = next(item for item in result.final_player_states if item.player_id == 1)
    assert state.team_id == "away"
    assert state.fatigue > 0
    assert state.unavailable_until_day == 4


def test_season_schema_v2_round_trip_and_v1_read_compatibility() -> None:
    result = managed_season()
    assert season_result_from_json(season_result_to_json(result), CONFIG) == result
    raw = season_result_to_dict(result)
    raw["schema_version"] = 1
    for key in (
        "transfers",
        "initial_rosters",
        "final_rosters",
        "roster_version",
        "roster_rules",
    ):
        raw.pop(key)
    legacy = season_result_from_dict(json.loads(json.dumps(raw)), CONFIG)
    assert legacy.transfers == ()
    assert legacy.initial_rosters == ()
    assert legacy.final_rosters == ()
    assert legacy.roster_version is None
    assert legacy.roster_rules is None
    assert season_result_to_dict(legacy) == raw


def test_roster_audit_and_serialization_reject_final_ownership_tamper() -> None:
    result = managed_season()
    audit = audit_season(result, CONFIG)
    assert audit.transfers_applied == 1
    assert audit.final_roster_players == 13
    assert (
        roster_snapshots({team.team_id: team for team in transaction_teams()})
        == result.initial_rosters
    )
    raw = json.loads(season_result_to_json(result))
    raw["final_rosters"][0]["player_ids"].append(raw["final_rosters"][1]["player_ids"][0])
    with pytest.raises(SerializationError, match=r"final rosters|exactly one"):
        season_result_from_json(json.dumps(raw), CONFIG)
