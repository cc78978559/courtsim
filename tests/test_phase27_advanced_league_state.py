import json
from dataclasses import replace

from test_phase12_manager_league_adapter import adapter, league_state, request

from courtsim.cap_mechanics import CapLedger, TradeException
from courtsim.manager_experiment import ManagerExperimentArm
from courtsim.manager_league_adapter import (
    league_state_from_json,
    league_state_to_json,
)
from courtsim.manager_learning import ManagerLearningState
from courtsim.nba_league import (
    NBAConferenceAlignment,
    nba_alignment_from_dict,
    nba_alignment_to_dict,
)


def test_schema_three_round_trips_cap_and_manager_memory() -> None:
    initial = replace(
        league_state(),
        cap_ledger=CapLedger(
            trade_exceptions=(TradeException(1, "A", 5_000_000, 2029),),
            next_exception_id=2,
        ),
        manager_learning=(ManagerLearningState("manager-A", "A", 2027),),
    )
    payload = league_state_to_json(initial)
    assert json.loads(payload)["schema_version"] == 3
    assert league_state_from_json(payload) == initial


def test_schema_two_migrates_to_empty_advanced_state() -> None:
    raw = json.loads(league_state_to_json(league_state()))
    raw["schema_version"] = 2
    del raw["cap_ledger"]
    del raw["manager_learning"]
    del raw["nba_alignment"]
    migrated = league_state_from_json(json.dumps(raw))
    assert migrated.cap_ledger == CapLedger()
    assert migrated.manager_learning == ()
    assert migrated.nba_alignment is None


def test_real_season_expires_exceptions_and_persists_opponent_memory() -> None:
    initial = replace(
        league_state(),
        cap_ledger=CapLedger(
            trade_exceptions=(TradeException(1, "A", 5_000_000, 2028),),
            next_exception_id=2,
        ),
    )
    execution = adapter()(
        replace(
            request(ManagerExperimentArm.INCUMBENT),
            state_payload=league_state_to_json(initial),
        )
    )
    advanced = league_state_from_json(execution.next_state_payload)
    assert advanced.cap_ledger.trade_exceptions == ()
    assert len(advanced.manager_learning) == 4
    assert all(item.last_completed_season == 2028 for item in advanced.manager_learning)
    assert all(item.seasons_observed == 1 for item in advanced.manager_learning)
    assert all(len(item.opponents) == 3 for item in advanced.manager_learning)


def test_thirty_team_alignment_has_strict_json_round_trip() -> None:
    alignment = NBAConferenceAlignment(
        tuple(f"E{index:02d}" for index in range(1, 16)),
        tuple(f"W{index:02d}" for index in range(1, 16)),
    )
    assert nba_alignment_from_dict(nba_alignment_to_dict(alignment)) == alignment
