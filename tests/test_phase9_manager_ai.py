from dataclasses import fields, replace

import pytest
from test_game_runtime import player

from courtsim.career import (
    CareerPlayer,
    CareerStatus,
    DevelopmentTraits,
    DraftPickAsset,
    DraftPlan,
    DraftSelection,
)
from courtsim.domain.player import AbilityRatings
from courtsim.management import (
    ContractRules,
    LeagueManagementState,
    MarketAction,
    MarketActionKind,
    MarketPlan,
    PlayerContract,
    apply_market_plan,
)
from courtsim.manager_ai import (
    DecisionContribution,
    ManagerCandidate,
    ManagerDecisionLedger,
    ManagerPolicyMode,
    ManagerProfile,
    evaluate_manager_decision,
    generate_draft_shadow,
    generate_market_shadow,
)
from courtsim.rosters import RosterSnapshot


def ratings(value: int) -> AbilityRatings:
    return AbilityRatings(**{item.name: value for item in fields(AbilityRatings)})


def career_player(
    player_id: int,
    value: int,
    *,
    age: int = 22,
    status: CareerStatus = CareerStatus.ACTIVE,
    ceiling: int | None = None,
) -> CareerPlayer:
    profile = replace(player(player_id), abilities=ratings(value))
    return CareerPlayer(
        profile,
        age,
        max(0, age - 20),
        DevelopmentTraits(),
        ratings(ceiling if ceiling is not None else value),
        status,
    )


def state(*, free_agents: tuple[int, ...] = ()) -> LeagueManagementState:
    return LeagueManagementState(
        2028,
        (RosterSnapshot("away", (11,)), RosterSnapshot("home", (1,))),
        free_agents,
        (
            PlayerContract(1, "home", 2_000_000, 2),
            PlayerContract(11, "away", 2_000_000, 2),
        ),
    )


def rules(**changes: int) -> ContractRules:
    values = {
        "salary_cap": 10_000_000,
        "minimum_salary": 1_000_000,
        "maximum_salary": 5_000_000,
        "maximum_years": 3,
        "maximum_roster_players": 5,
    }
    values.update(changes)
    return ContractRules(
        salary_cap=values["salary_cap"],
        minimum_salary=values["minimum_salary"],
        maximum_salary=values["maximum_salary"],
        maximum_years=values["maximum_years"],
        maximum_roster_players=values["maximum_roster_players"],
    )


def profiles() -> dict[str, ManagerProfile]:
    return {
        "away": ManagerProfile("manager-away", "away"),
        "home": ManagerProfile("manager-home", "home"),
    }


def contribution(contribution_id: str, value: float) -> DecisionContribution:
    return DecisionContribution(contribution_id, "test", "competence", value, "test signal")


def test_white_box_rejects_illegal_and_bounds_personality() -> None:
    trace = evaluate_manager_decision(
        decision_id="draft:1:home",
        reasonable_band=0.1,
        style_contribution_limit=0.04,
        incumbent="safe",
        candidates=(
            ManagerCandidate("illegal", ("salary-cap",), (contribution("quality", 99),)),
            ManagerCandidate(
                "safe",
                (),
                (contribution("quality", 0.8),),
                (contribution("style", 0.5),),
            ),
            ManagerCandidate(
                "close",
                (),
                (contribution("quality", 0.78),),
                (contribution("style", -0.5),),
            ),
            ManagerCandidate(
                "bad",
                (),
                (contribution("quality", 0.5),),
                (contribution("style", 10),),
            ),
        ),
    )
    assert trace.selected == "safe"
    assert trace.agrees_with_incumbent
    indexed = {candidate.candidate_id: candidate for candidate in trace.candidates}
    assert not indexed["illegal"].eligible
    assert indexed["safe"].applied_style_score == 0.04
    assert indexed["close"].applied_style_score == -0.04
    assert not indexed["bad"].reasonable
    assert indexed["bad"].final_score is None


def test_white_box_tie_breaking_and_ledger_are_deterministic() -> None:
    candidate = ManagerCandidate("b", (), (contribution("b-score", 1),))
    other = ManagerCandidate("a", (), (contribution("a-score", 1),))
    trace = evaluate_manager_decision(
        decision_id="same",
        candidates=(candidate, other),
    )
    assert trace.selected == "a"
    ledger = ManagerDecisionLedger().add(
        trace=trace,
        stage="draft",
        profile=ManagerProfile("manager-home", "home"),
    )
    assert ledger.records[0].sequence == 1
    assert ledger.records[0].alternatives == ("a", "b")


def test_draft_shadow_selects_best_available_and_never_executes() -> None:
    management = state()
    players = (
        career_player(1, 55),
        career_player(11, 55),
        career_player(100, 60, status=CareerStatus.PROSPECT, ceiling=90),
        career_player(101, 75, status=CareerStatus.PROSPECT, ceiling=80),
    )
    incumbent = DraftPlan((DraftSelection(1, "home", 100),))
    result = generate_draft_shadow(
        management=management,
        players=players,
        picks=(DraftPickAsset(1, 1, 1, "home", "home"),),
        profiles=profiles(),
        contract_rules=rules(),
        rookie_salary=1_000_000,
        incumbent=incumbent,
    )
    assert result.mode is ManagerPolicyMode.SHADOW
    assert result.plan.selections == (DraftSelection(1, "home", 101),)
    assert not result.traces[0].agrees_with_incumbent
    assert result.ledger.records[0].incumbent == "player:100"
    assert management == state()


def test_draft_shadow_respects_roster_and_cap_hard_constraints() -> None:
    management = replace(
        state(),
        contracts=(
            PlayerContract(1, "home", 5_000_000, 2),
            PlayerContract(11, "away", 2_000_000, 2),
        ),
    )
    with pytest.raises(ValueError, match="no eligible prospect"):
        generate_draft_shadow(
            management=management,
            players=(
                career_player(1, 55),
                career_player(11, 55),
                career_player(100, 80, status=CareerStatus.PROSPECT),
            ),
            picks=(DraftPickAsset(1, 1, 1, "home", "home"),),
            profiles=profiles(),
            contract_rules=rules(salary_cap=5_000_000),
            rookie_salary=1_000_000,
        )


def test_draft_shadow_updates_availability_between_multiple_picks() -> None:
    result = generate_draft_shadow(
        management=state(),
        players=(
            career_player(1, 55),
            career_player(11, 55),
            career_player(100, 80, status=CareerStatus.PROSPECT),
            career_player(101, 75, status=CareerStatus.PROSPECT),
        ),
        picks=(
            DraftPickAsset(1, 1, 1, "home", "home"),
            DraftPickAsset(2, 1, 2, "home", "home"),
        ),
        profiles=profiles(),
        contract_rules=rules(),
        rookie_salary=1_000_000,
    )
    assert tuple(item.player_id for item in result.plan.selections) == (100, 101)
    assert len(result.ledger.records) == 2


def test_market_shadow_generates_replayable_plan_and_trace() -> None:
    management = state(free_agents=(20, 21))
    players = (
        career_player(1, 55),
        career_player(11, 55),
        career_player(20, 85, status=CareerStatus.FREE_AGENT),
        career_player(21, 65, status=CareerStatus.FREE_AGENT),
    )
    incumbent = MarketPlan((MarketAction(1, MarketActionKind.SIGN, 21, "away", 1_000_000, 1),))
    result = generate_market_shadow(
        management=management,
        players=players,
        profiles=profiles(),
        contract_rules=rules(),
        incumbent=incumbent,
    )
    assert result.mode is ManagerPolicyMode.SHADOW
    assert result.plan.actions[0].player_id == 20
    assert len({action.player_id for action in result.plan.actions}) == len(result.plan.actions)
    assert result.traces[0].incumbent == "player:21"
    applied = apply_market_plan(management, result.plan, rules())
    assert 20 not in applied.final_state.free_agent_ids


def test_market_shadow_passes_when_team_has_no_legal_slot() -> None:
    full = LeagueManagementState(
        2028,
        (
            RosterSnapshot("away", (11, 12, 13, 14, 15)),
            RosterSnapshot("home", (1, 2, 3, 4, 5)),
        ),
        (20,),
        tuple(
            PlayerContract(player_id, team, 1_000_000, 1)
            for team, ids in (
                ("away", (11, 12, 13, 14, 15)),
                ("home", (1, 2, 3, 4, 5)),
            )
            for player_id in ids
        ),
    )
    players = (
        *(career_player(player_id, 50) for player_id in (1, 2, 3, 4, 5, 11, 12, 13, 14, 15)),
        career_player(20, 99, status=CareerStatus.FREE_AGENT),
    )
    result = generate_market_shadow(
        management=full,
        players=players,
        profiles=profiles(),
        contract_rules=rules(maximum_roster_players=5),
    )
    assert result.plan == MarketPlan(())
    assert all(trace.selected == "pass" for trace in result.traces)


def test_manager_contracts_reject_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="manager ratings"):
        ManagerProfile("manager", "home", win_now=101)
    with pytest.raises(ValueError, match="candidate ids"):
        evaluate_manager_decision(
            decision_id="duplicate",
            candidates=(
                ManagerCandidate("same", (), ()),
                ManagerCandidate("same", (), ()),
            ),
        )
    with pytest.raises(ValueError, match="cover every"):
        generate_market_shadow(
            management=state(),
            players=(career_player(1, 50), career_player(11, 50)),
            profiles={"home": ManagerProfile("manager-home", "home")},
            contract_rules=rules(),
        )
    with pytest.raises(ValueError, match="salary"):
        generate_market_shadow(
            management=state(),
            players=(career_player(1, 50), career_player(11, 50)),
            profiles=profiles(),
            contract_rules=rules(),
            annual_salary=0,
        )
