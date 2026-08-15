from courtsim.cap_mechanics import (
    BirdRights,
    BirdRightsLevel,
    CapLedger,
    TradeException,
    evaluate_signing_salary,
    evaluate_trade_salary,
    expire_cap_ledger,
)


def test_bird_rights_levels_and_over_cap_signing_limits() -> None:
    rights = (
        BirdRights("A", 1, 1, 10_000_000),
        BirdRights("A", 2, 2, 10_000_000),
        BirdRights("A", 3, 3, 10_000_000),
    )
    assert tuple(item.level for item in rights) == (
        BirdRightsLevel.NON_BIRD,
        BirdRightsLevel.EARLY_BIRD,
        BirdRightsLevel.FULL_BIRD,
    )
    ledger = CapLedger(rights)
    assert not evaluate_signing_salary(
        team_id="A",
        player_id=1,
        team_payroll=139_000_000,
        annual_salary=13_000_000,
        ledger=ledger,
    ).allowed
    assert evaluate_signing_salary(
        team_id="A",
        player_id=3,
        team_payroll=139_000_000,
        annual_salary=30_000_000,
        ledger=ledger,
    ).allowed


def test_minimum_salary_exception_allows_over_cap_roster_completion() -> None:
    decision = evaluate_signing_salary(
        team_id="A",
        player_id=9,
        team_payroll=150_000_000,
        annual_salary=1_000_000,
        ledger=CapLedger(),
        minimum_salary=1_000_000,
    )
    assert decision.allowed
    assert decision.mechanism == "minimum-exception"


def test_tiered_salary_matching_and_second_apron() -> None:
    ledger = CapLedger()
    small = evaluate_trade_salary(
        team_id="A",
        team_payroll=150_000_000,
        outgoing_salary=7_000_000,
        incoming_salary=14_000_000,
        season_year=2030,
        ledger=ledger,
    )
    assert small.decision.allowed
    assert small.decision.mechanism == "matching-200-percent"
    medium = evaluate_trade_salary(
        team_id="A",
        team_payroll=170_000_000,
        outgoing_salary=20_000_000,
        incoming_salary=28_000_000,
        season_year=2030,
        ledger=ledger,
    )
    assert not medium.decision.allowed
    assert "salary-match" in medium.decision.rejections


def test_trade_exception_is_created_consumed_and_cannot_be_aggregated() -> None:
    created = evaluate_trade_salary(
        team_id="A",
        team_payroll=150_000_000,
        outgoing_salary=20_000_000,
        incoming_salary=10_000_000,
        season_year=2030,
        ledger=CapLedger(),
    )
    assert created.decision.allowed
    assert created.created_exception is not None
    exception_id = created.created_exception.exception_id
    consumed = evaluate_trade_salary(
        team_id="A",
        team_payroll=140_000_000,
        outgoing_salary=0,
        incoming_salary=6_000_000,
        season_year=2031,
        ledger=created.final_ledger,
        exception_id=exception_id,
    )
    assert consumed.decision.allowed
    assert consumed.consumed_exception_id == exception_id
    rejected = evaluate_trade_salary(
        team_id="A",
        team_payroll=140_000_000,
        outgoing_salary=1_000_000,
        incoming_salary=2_000_000,
        season_year=2031,
        ledger=created.final_ledger,
        exception_id=exception_id,
    )
    assert not rejected.decision.allowed
    assert "exception-cannot-aggregate" in rejected.decision.rejections


def test_expired_trade_exceptions_are_removed() -> None:
    ledger = CapLedger(
        trade_exceptions=(
            TradeException(1, "A", 5_000_000, 2030),
            TradeException(2, "A", 6_000_000, 2031),
        ),
        next_exception_id=3,
    )
    assert tuple(
        item.exception_id for item in expire_cap_ledger(ledger, season_year=2031).trade_exceptions
    ) == (2,)
