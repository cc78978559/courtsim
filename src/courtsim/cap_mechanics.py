"""Bird rights, trade exceptions, aprons, and tiered salary matching."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import IntEnum

CAP_MECHANICS_VERSION = "cap-mechanics-v1"


class BirdRightsLevel(IntEnum):
    NON_BIRD = 1
    EARLY_BIRD = 2
    FULL_BIRD = 3


@dataclass(frozen=True, slots=True)
class CapMechanicsRules:
    salary_cap: int = 140_000_000
    first_apron: int = 178_000_000
    second_apron: int = 189_000_000
    small_outgoing_threshold: int = 7_500_000
    medium_outgoing_threshold: int = 29_000_000
    matching_buffer: int = 250_000
    medium_matching_allowance: int = 7_500_000
    exception_buffer: int = 100_000
    exception_lifetime_years: int = 1
    version: str = CAP_MECHANICS_VERSION

    def __post_init__(self) -> None:
        values = (
            self.salary_cap,
            self.first_apron,
            self.second_apron,
            self.small_outgoing_threshold,
            self.medium_outgoing_threshold,
            self.matching_buffer,
            self.medium_matching_allowance,
            self.exception_buffer,
            self.exception_lifetime_years,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values
        ):
            raise ValueError("cap mechanics rules must be non-negative integers")
        if not self.salary_cap < self.first_apron < self.second_apron:
            raise ValueError("salary cap and apron levels must be increasing")
        if not self.small_outgoing_threshold < self.medium_outgoing_threshold:
            raise ValueError("salary matching thresholds must be increasing")
        if self.exception_lifetime_years < 1:
            raise ValueError("trade exceptions must last at least one year")
        if self.version != CAP_MECHANICS_VERSION:
            raise ValueError("unsupported cap mechanics version")


@dataclass(frozen=True, slots=True)
class BirdRights:
    team_id: str
    player_id: int
    consecutive_seasons: int
    previous_salary: int

    def __post_init__(self) -> None:
        if not self.team_id.strip() or self.player_id < 0:
            raise ValueError("Bird-rights identity is invalid")
        if self.consecutive_seasons < 1 or self.previous_salary < 1:
            raise ValueError("Bird-rights service and salary must be positive")

    @property
    def level(self) -> BirdRightsLevel:
        if self.consecutive_seasons >= 3:
            return BirdRightsLevel.FULL_BIRD
        if self.consecutive_seasons == 2:
            return BirdRightsLevel.EARLY_BIRD
        return BirdRightsLevel.NON_BIRD


@dataclass(frozen=True, slots=True)
class TradeException:
    exception_id: int
    team_id: str
    remaining_amount: int
    expires_after_season: int

    def __post_init__(self) -> None:
        if self.exception_id < 1 or not self.team_id.strip():
            raise ValueError("trade exception identity is invalid")
        if self.remaining_amount < 1 or self.expires_after_season < 1:
            raise ValueError("trade exception amount and expiry must be positive")


@dataclass(frozen=True, slots=True)
class CapLedger:
    bird_rights: tuple[BirdRights, ...] = ()
    trade_exceptions: tuple[TradeException, ...] = ()
    next_exception_id: int = 1
    version: str = CAP_MECHANICS_VERSION

    def __post_init__(self) -> None:
        if self.bird_rights != tuple(
            sorted(self.bird_rights, key=lambda item: (item.team_id, item.player_id))
        ):
            raise ValueError("Bird rights must use canonical order")
        if self.trade_exceptions != tuple(
            sorted(self.trade_exceptions, key=lambda item: item.exception_id)
        ):
            raise ValueError("trade exceptions must use canonical order")
        ids = tuple(item.exception_id for item in self.trade_exceptions)
        if len(ids) != len(set(ids)) or self.next_exception_id < 1:
            raise ValueError("trade exception ids must be unique")
        if self.version != CAP_MECHANICS_VERSION:
            raise ValueError("unsupported cap ledger version")


@dataclass(frozen=True, slots=True)
class SalaryDecision:
    allowed: bool
    mechanism: str
    maximum_amount: int
    resulting_payroll: int
    rejections: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class TradeSalaryResult:
    decision: SalaryDecision
    final_ledger: CapLedger
    created_exception: TradeException | None = None
    consumed_exception_id: int | None = None


def evaluate_signing_salary(
    *,
    team_id: str,
    player_id: int,
    team_payroll: int,
    annual_salary: int,
    ledger: CapLedger,
    rules: CapMechanicsRules | None = None,
) -> SalaryDecision:
    active_rules = rules or CapMechanicsRules()
    resulting = team_payroll + annual_salary
    if annual_salary < 1:
        return SalaryDecision(False, "invalid", 0, resulting, ("salary-must-be-positive",))
    if resulting <= active_rules.salary_cap:
        return SalaryDecision(True, "cap-room", active_rules.salary_cap - team_payroll, resulting)
    right = next(
        (
            item
            for item in ledger.bird_rights
            if item.team_id == team_id and item.player_id == player_id
        ),
        None,
    )
    if right is None:
        return SalaryDecision(False, "none", 0, resulting, ("over-cap-without-rights",))
    if right.level is BirdRightsLevel.FULL_BIRD:
        maximum = active_rules.second_apron - team_payroll
        mechanism = "full-bird"
    elif right.level is BirdRightsLevel.EARLY_BIRD:
        maximum = min(
            max(right.previous_salary * 175 // 100, 11_000_000),
            active_rules.first_apron - team_payroll,
        )
        mechanism = "early-bird"
    else:
        maximum = min(
            right.previous_salary * 120 // 100,
            active_rules.first_apron - team_payroll,
        )
        mechanism = "non-bird"
    if annual_salary > maximum:
        return SalaryDecision(False, mechanism, max(0, maximum), resulting, ("rights-limit",))
    return SalaryDecision(True, mechanism, max(0, maximum), resulting)


def evaluate_trade_salary(
    *,
    team_id: str,
    team_payroll: int,
    outgoing_salary: int,
    incoming_salary: int,
    season_year: int,
    ledger: CapLedger,
    exception_id: int | None = None,
    rules: CapMechanicsRules | None = None,
) -> TradeSalaryResult:
    active_rules = rules or CapMechanicsRules()
    resulting = team_payroll - outgoing_salary + incoming_salary
    if min(team_payroll, outgoing_salary, incoming_salary) < 0:
        decision = SalaryDecision(False, "invalid", 0, resulting, ("negative-salary",))
        return TradeSalaryResult(decision, ledger)
    if exception_id is not None:
        exception = next(
            (
                item
                for item in ledger.trade_exceptions
                if item.exception_id == exception_id and item.team_id == team_id
            ),
            None,
        )
        if exception is None or exception.expires_after_season < season_year:
            decision = SalaryDecision(
                False, "trade-exception", 0, resulting, ("exception-invalid",)
            )
            return TradeSalaryResult(decision, ledger)
        maximum = exception.remaining_amount + active_rules.exception_buffer
        if outgoing_salary != 0 or incoming_salary > maximum:
            decision = SalaryDecision(
                False,
                "trade-exception",
                maximum,
                resulting,
                ("exception-cannot-aggregate",),
            )
            return TradeSalaryResult(decision, ledger)
        remaining = exception.remaining_amount - min(
            exception.remaining_amount,
            incoming_salary,
        )
        exceptions = tuple(
            item for item in ledger.trade_exceptions if item.exception_id != exception.exception_id
        )
        if remaining:
            exceptions = (*exceptions, replace(exception, remaining_amount=remaining))
        final_ledger = replace(
            ledger,
            trade_exceptions=tuple(sorted(exceptions, key=lambda item: item.exception_id)),
        )
        return TradeSalaryResult(
            SalaryDecision(True, "trade-exception", maximum, resulting),
            final_ledger,
            consumed_exception_id=exception.exception_id,
        )

    if team_payroll < active_rules.salary_cap:
        maximum = outgoing_salary + active_rules.salary_cap - team_payroll
        mechanism = "cap-room"
    elif outgoing_salary <= active_rules.small_outgoing_threshold:
        maximum = outgoing_salary * 2 + active_rules.matching_buffer
        mechanism = "matching-200-percent"
    elif outgoing_salary <= active_rules.medium_outgoing_threshold:
        maximum = outgoing_salary + active_rules.medium_matching_allowance
        mechanism = "matching-plus-allowance"
    else:
        maximum = outgoing_salary * 125 // 100 + active_rules.matching_buffer
        mechanism = "matching-125-percent"
    if incoming_salary > maximum or resulting > active_rules.second_apron:
        rejection = "second-apron" if resulting > active_rules.second_apron else "salary-match"
        return TradeSalaryResult(
            SalaryDecision(False, mechanism, maximum, resulting, (rejection,)),
            ledger,
        )

    created = None
    final_ledger = ledger
    difference = outgoing_salary - incoming_salary
    if difference > active_rules.exception_buffer:
        created = TradeException(
            ledger.next_exception_id,
            team_id,
            difference,
            season_year + active_rules.exception_lifetime_years,
        )
        final_ledger = replace(
            ledger,
            trade_exceptions=(*ledger.trade_exceptions, created),
            next_exception_id=ledger.next_exception_id + 1,
        )
    return TradeSalaryResult(
        SalaryDecision(True, mechanism, maximum, resulting),
        final_ledger,
        created_exception=created,
    )


def expire_cap_ledger(ledger: CapLedger, *, season_year: int) -> CapLedger:
    return replace(
        ledger,
        trade_exceptions=tuple(
            item for item in ledger.trade_exceptions if item.expires_after_season >= season_year
        ),
    )


def cap_ledger_to_dict(ledger: CapLedger) -> dict[str, object]:
    return {
        "version": ledger.version,
        "next_exception_id": ledger.next_exception_id,
        "bird_rights": [
            {
                "team_id": item.team_id,
                "player_id": item.player_id,
                "consecutive_seasons": item.consecutive_seasons,
                "previous_salary": item.previous_salary,
            }
            for item in ledger.bird_rights
        ],
        "trade_exceptions": [
            {
                "exception_id": item.exception_id,
                "team_id": item.team_id,
                "remaining_amount": item.remaining_amount,
                "expires_after_season": item.expires_after_season,
            }
            for item in ledger.trade_exceptions
        ],
    }


def cap_ledger_from_dict(value: object) -> CapLedger:
    if not isinstance(value, dict) or set(value) != {
        "version",
        "next_exception_id",
        "bird_rights",
        "trade_exceptions",
    }:
        raise ValueError("invalid cap ledger object")
    rights_raw = value["bird_rights"]
    exceptions_raw = value["trade_exceptions"]
    if not isinstance(rights_raw, list) or not isinstance(exceptions_raw, list):
        raise ValueError("cap ledger collections must be lists")
    rights = tuple(
        BirdRights(
            str(item["team_id"]),
            int(item["player_id"]),
            int(item["consecutive_seasons"]),
            int(item["previous_salary"]),
        )
        for item in rights_raw
        if isinstance(item, dict)
    )
    exceptions = tuple(
        TradeException(
            int(item["exception_id"]),
            str(item["team_id"]),
            int(item["remaining_amount"]),
            int(item["expires_after_season"]),
        )
        for item in exceptions_raw
        if isinstance(item, dict)
    )
    if len(rights) != len(rights_raw) or len(exceptions) != len(exceptions_raw):
        raise ValueError("cap ledger entries must be objects")
    return CapLedger(
        rights,
        exceptions,
        int(value["next_exception_id"]),
        str(value["version"]),
    )
