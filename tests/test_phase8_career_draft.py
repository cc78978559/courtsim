import json
from dataclasses import fields, replace

import pytest
from test_game_runtime import player

from courtsim.career import (
    AbilityChange,
    CareerPlayer,
    CareerRules,
    CareerStatus,
    DevelopmentTraits,
    DraftPickAsset,
    DraftPlan,
    DraftRules,
    DraftSelection,
    OffseasonResult,
    PlayerSeasonSummary,
    advance_careers,
    advance_offseason,
    apply_draft,
    audit_offseason,
    offseason_result_from_json,
    offseason_result_to_json,
)
from courtsim.domain.player import AbilityRatings
from courtsim.domain.serialization import SerializationError
from courtsim.management import (
    ContractRules,
    LeagueManagementState,
    MarketAction,
    MarketActionKind,
    MarketPlan,
    PlayerContract,
)
from courtsim.rosters import RosterSnapshot


def potential(value: int = 100) -> AbilityRatings:
    return AbilityRatings(**{item.name: value for item in fields(AbilityRatings)})


def career_player(
    player_id: int,
    *,
    age: int = 22,
    status: CareerStatus = CareerStatus.ACTIVE,
    traits: DevelopmentTraits | None = None,
    injury_burden: int = 0,
) -> CareerPlayer:
    profile = player(player_id)
    return CareerPlayer(
        profile,
        age,
        max(0, age - 20),
        traits or DevelopmentTraits(consistency=100),
        potential(),
        status,
        injury_burden=injury_burden,
    )


def summary(player_id: int, *, minutes: int = 24, injury_days: int = 0) -> PlayerSeasonSummary:
    return PlayerSeasonSummary(player_id, 82, 82, 82 * minutes * 60, injury_days)


def contract_rules() -> ContractRules:
    return ContractRules(
        salary_cap=20_000_000,
        minimum_salary=1_000_000,
        maximum_salary=5_000_000,
        maximum_years=3,
        maximum_roster_players=5,
    )


def management() -> LeagueManagementState:
    return LeagueManagementState(
        2027,
        (
            RosterSnapshot("away", (11, 12)),
            RosterSnapshot("home", (1, 2)),
        ),
        (),
        (
            PlayerContract(1, "home", 2_000_000, 2),
            PlayerContract(2, "home", 2_000_000, 1),
            PlayerContract(11, "away", 2_000_000, 2),
            PlayerContract(12, "away", 2_000_000, 2),
        ),
    )


def players() -> tuple[CareerPlayer, ...]:
    return (
        career_player(1, age=44),
        career_player(2),
        career_player(11, age=29),
        career_player(12, age=35),
        career_player(100, age=19, status=CareerStatus.PROSPECT),
    )


def summaries() -> tuple[PlayerSeasonSummary, ...]:
    return (summary(1), summary(2), summary(11), summary(12))


def pick() -> tuple[DraftPickAsset, ...]:
    return (DraftPickAsset(1, 1, 1, "away", "home"),)


def plan() -> DraftPlan:
    return DraftPlan((DraftSelection(1, "home", 100),))


def offseason() -> OffseasonResult:
    return advance_offseason(
        season_year=2027,
        master_seed=991,
        management=management(),
        players=players(),
        summaries=summaries(),
        picks=pick(),
        draft_plan=plan(),
        market_plan=MarketPlan(
            (
                MarketAction(
                    1,
                    MarketActionKind.SIGN,
                    2,
                    "home",
                    1_000_000,
                    1,
                ),
            )
        ),
        career_rules=CareerRules(maximum_player_age=45),
        contract_rules=contract_rules(),
        draft_rules=DraftRules(
            rounds=1,
            rookie_salary=1_000_000,
            rookie_contract_years=2,
        ),
    )


def test_career_contracts_reject_invalid_state() -> None:
    with pytest.raises(ValueError, match="peak ages"):
        DevelopmentTraits(peak_start_age=31, peak_end_age=30)
    with pytest.raises(ValueError, match="age bounds"):
        CareerRules(minimum_retirement_age=45, maximum_player_age=45)
    with pytest.raises(ValueError, match="potential"):
        CareerPlayer(
            player(1),
            22,
            2,
            DevelopmentTraits(),
            potential(0),
            CareerStatus.ACTIVE,
        )
    with pytest.raises(ValueError, match="undrafted"):
        replace(
            career_player(100, status=CareerStatus.PROSPECT),
            draft_year=2027,
            draft_round=1,
            draft_pick=1,
        )
    with pytest.raises(ValueError, match="games_played"):
        PlayerSeasonSummary(1, 10, 11, 0)


def test_young_player_growth_is_deterministic_and_player_addressed() -> None:
    young = career_player(
        1,
        age=19,
        traits=DevelopmentTraits(growth_rate=100, consistency=100),
    )
    first = advance_careers(
        (young,),
        (summary(1, minutes=30),),
        season_year=2027,
        master_seed=44,
    )
    second = advance_careers(
        (young, career_player(2, status=CareerStatus.PROSPECT)),
        (summary(1, minutes=30),),
        season_year=2027,
        master_seed=44,
    )
    assert first.final_players[0] == second.final_players[0]
    assert all(change.delta > 0 for change in first.changes[0].ability_changes)
    assert first.final_players[0].age == 20
    assert first.final_players[0].seasons_pro == young.seasons_pro + 1


def test_decline_is_ability_specific_and_injury_sensitive() -> None:
    veteran = career_player(
        1,
        age=37,
        traits=DevelopmentTraits(
            growth_rate=0,
            peak_start_age=25,
            peak_end_age=29,
            decline_resistance=0,
            consistency=100,
        ),
        injury_burden=80,
    )
    result = advance_careers(
        (veteran,),
        (summary(1, injury_days=45),),
        season_year=2027,
        master_seed=1,
        rules=CareerRules(maximum_player_age=50),
    )
    changes = {item.ability: item.delta for item in result.changes[0].ability_changes}
    assert changes["rim_finishing"] < changes["three_point_shooting"] < 0
    assert result.final_players[0].injury_burden > veteran.injury_burden


def test_retirement_is_forced_at_maximum_age_and_replay_stable() -> None:
    veteran = career_player(1, age=44)
    first = advance_careers(
        (veteran,),
        (summary(1),),
        season_year=2027,
        master_seed=9,
        rules=CareerRules(maximum_player_age=45),
    )
    second = advance_careers(
        (veteran,),
        (summary(1),),
        season_year=2027,
        master_seed=9,
        rules=CareerRules(maximum_player_age=45),
    )
    assert first == second
    assert first.retired_player_ids == (1,)
    assert first.final_players[0].status is CareerStatus.RETIRED
    assert first.changes[0].retirement_threshold_bps == 10_000


def test_draft_adds_prospect_to_owner_roster_and_rookie_contract() -> None:
    state = management()
    result = apply_draft(
        state,
        players(),
        pick(),
        plan(),
        season_year=2028,
        contract_rules=contract_rules(),
        draft_rules=DraftRules(
            rounds=1,
            rookie_salary=1_000_000,
            rookie_contract_years=2,
        ),
    )
    home = next(item for item in result.final_management.rosters if item.team_id == "home")
    assert home.player_ids == (1, 2, 100)
    rookie = next(item for item in result.final_management.contracts if item.player_id == 100)
    assert (rookie.team_id, rookie.annual_salary, rookie.years_remaining) == (
        "home",
        1_000_000,
        2,
    )
    drafted = next(item for item in result.final_players if item.player_id == 100)
    assert drafted.status is CareerStatus.ACTIVE
    assert (drafted.draft_year, drafted.draft_round, drafted.draft_pick) == (2028, 1, 1)


def test_draft_rejects_wrong_owner_duplicate_or_incomplete_plan() -> None:
    with pytest.raises(ValueError, match="ownership"):
        apply_draft(
            management(),
            players(),
            pick(),
            DraftPlan((DraftSelection(1, "away", 100),)),
            season_year=2028,
            contract_rules=contract_rules(),
            draft_rules=DraftRules(rounds=1),
        )
    with pytest.raises(ValueError, match="fill every"):
        apply_draft(
            management(),
            players(),
            pick(),
            DraftPlan(()),
            season_year=2028,
            contract_rules=contract_rules(),
            draft_rules=DraftRules(rounds=1),
        )
    selection = DraftSelection(1, "home", 100)
    with pytest.raises(ValueError, match="more than once"):
        DraftPlan((selection, replace(selection, selection_number=2)))


def test_offseason_orders_retirement_expiration_draft_and_market() -> None:
    result = offseason()
    assert result.retired_player_ids == (1,)
    assert result.expired_player_ids == (2,)
    assert result.final_management.season_year == 2028
    home = next(item for item in result.final_management.rosters if item.team_id == "home")
    assert home.player_ids == (100, 2)
    assert 1 not in {item.player_id for item in result.final_management.contracts}
    statuses = {item.player_id: item.status for item in result.final_players}
    assert statuses[1] is CareerStatus.RETIRED
    assert statuses[2] is CareerStatus.ACTIVE
    assert statuses[100] is CareerStatus.ACTIVE


def test_offseason_audit_counts_derived_events() -> None:
    audit = audit_offseason(offseason())
    assert audit.players_developed == 4
    assert audit.players_retired == 1
    assert audit.players_drafted == 1
    assert audit.contracts_expired == 1
    assert audit.signings == 1
    assert audit.waivers == 0
    assert audit.active_players == 4
    assert audit.free_agents == 0
    assert audit.ratings_improved + audit.ratings_declined > 0


def test_offseason_json_round_trip_and_tamper_detection() -> None:
    result = offseason()
    payload = offseason_result_to_json(result)
    assert offseason_result_from_json(payload) == result
    raw = json.loads(payload)
    raw["final_players"][0]["age"] += 1
    with pytest.raises(SerializationError, match=r"derive|transition"):
        offseason_result_from_json(json.dumps(raw))
    raw = json.loads(payload)
    raw["extra"] = True
    with pytest.raises(SerializationError, match="keys"):
        offseason_result_from_json(json.dumps(raw))


def test_offseason_rejects_missing_summary_and_unknown_management_player() -> None:
    with pytest.raises(ValueError, match="cover every"):
        advance_careers(
            (career_player(1),),
            (),
            season_year=2027,
            master_seed=1,
        )
    unknown = replace(
        management(),
        free_agent_ids=(999,),
    )
    with pytest.raises(ValueError, match=r"rostered and a free agent|unknown"):
        advance_offseason(
            season_year=2027,
            master_seed=1,
            management=unknown,
            players=players(),
            summaries=summaries(),
            picks=pick(),
            draft_plan=plan(),
            market_plan=MarketPlan(()),
            contract_rules=contract_rules(),
            draft_rules=DraftRules(rounds=1),
        )


def test_ability_change_exposes_derived_delta() -> None:
    assert AbilityChange("playmaking", 50, 53).delta == 3
