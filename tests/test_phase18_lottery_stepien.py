from test_phase15_trades import (
    contract_rules,
    league_players,
    management,
)

from courtsim.draft_assets import (
    DraftAssetLedger,
    FutureDraftPickAsset,
    seed_future_draft_picks,
    settle_draft_assets,
)
from courtsim.draft_lottery import resolve_draft_lottery
from courtsim.manager_ai import ManagerProfile
from courtsim.trade_market import generate_trade_market_shadow
from courtsim.trades import TradeOffer, TradeRules, trade_rejections


def test_lottery_is_deterministic_unique_and_fully_audited() -> None:
    first = resolve_draft_lottery(
        draft_year=2029,
        master_seed=991,
        base_order=("A", "B", "C", "D"),
    )
    second = resolve_draft_lottery(
        draft_year=2029,
        master_seed=991,
        base_order=("A", "B", "C", "D"),
    )
    assert first == second
    assert set(first.final_order) == {"A", "B", "C", "D"}
    assert len(first.final_order) == len(set(first.final_order))
    assert len(first.draws) == 2
    for draw in first.draws:
        assert 0 <= draw.roll < draw.total_weight
        assert sum(weight for _, weight in draw.candidates) == draw.total_weight
        assert draw.selected_team_id in dict(draw.candidates)


def test_lottery_changes_only_first_round_order() -> None:
    ledger = seed_future_draft_picks(
        DraftAssetLedger(),
        team_ids=("A", "B", "C", "D"),
        draft_years=(2029,),
        rounds=2,
    )
    settlement = settle_draft_assets(
        ledger,
        draft_year=2029,
        original_team_order=("A", "B", "C", "D"),
        first_round_order=("C", "A", "D", "B"),
    )
    first_round = tuple(
        pick.original_team_id for pick in settlement.picks if pick.round_number == 1
    )
    second_round = tuple(
        pick.original_team_id for pick in settlement.picks if pick.round_number == 2
    )
    assert first_round == ("C", "A", "D", "B")
    assert second_round == ("A", "B", "C", "D")


def future_ledger() -> tuple[FutureDraftPickAsset, ...]:
    return (
        FutureDraftPickAsset(1, 2029, 1, "home", "home"),
        FutureDraftPickAsset(2, 2029, 1, "away", "away"),
        FutureDraftPickAsset(3, 2030, 1, "home", "away"),
        FutureDraftPickAsset(4, 2030, 1, "away", "away"),
        FutureDraftPickAsset(5, 2031, 1, "home", "home"),
        FutureDraftPickAsset(6, 2031, 1, "away", "away"),
        FutureDraftPickAsset(7, 2029, 2, "away", "away"),
    )


def test_stepien_rule_blocks_consecutive_future_first_round_gaps() -> None:
    offer = TradeOffer(
        30,
        "home",
        "away",
        picks_from_a=(1,),
        picks_from_b=(7,),
    )
    rejected = trade_rejections(
        management(),
        future_ledger(),
        offer,
        contract_rules(),
        TradeRules(),
    )
    assert "stepien-consecutive-firsts:home" in rejected

    disabled = trade_rejections(
        management(),
        future_ledger(),
        offer,
        contract_rules(),
        TradeRules(enforce_stepien_rule=False),
    )
    assert not any(reason.startswith("stepien-") for reason in disabled)


def test_stepien_rule_allows_trade_when_team_retains_another_first() -> None:
    offer = TradeOffer(
        31,
        "home",
        "away",
        picks_from_a=(1,),
        picks_from_b=(2,),
    )
    rejected = trade_rejections(
        management(),
        future_ledger(),
        offer,
        contract_rules(),
        TradeRules(),
    )
    assert not any(reason.startswith("stepien-") for reason in rejected)


def test_market_generates_bounded_two_for_one_packages() -> None:
    result = generate_trade_market_shadow(
        management=management(salary_a=5_000_000, salary_b=5_000_000),
        players=league_players(home_value=75, away_value=70),
        picks=(),
        profiles={
            "home": ManagerProfile("home-manager", "home"),
            "away": ManagerProfile("away-manager", "away"),
        },
        contract_rules=contract_rules(),
    )
    packages = [
        evaluation for evaluation in result.evaluations if evaluation.kind == "multi-player"
    ]
    assert packages
    assert len(result.evaluations) <= 96
    assert all(
        len(evaluation.shadow.offer.players_from_a) + len(evaluation.shadow.offer.players_from_b)
        == 3
        for evaluation in packages
    )
