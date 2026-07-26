"""Deterministic player careers, draft execution, and offseason replay."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, fields, replace
from enum import IntEnum
from typing import Any, NoReturn, cast

from courtsim.domain.player import AbilityRatings, PlayerProfile
from courtsim.domain.player_serialization import (
    player_profile_from_dict,
    player_profile_to_dict,
)
from courtsim.domain.serialization import SerializationError
from courtsim.management import (
    ContractRules,
    LeagueManagementState,
    MarketAction,
    MarketActionKind,
    MarketPlan,
    PlayerContract,
    advance_contract_year,
    apply_market_plan,
    validate_management_state,
)
from courtsim.randomness import derive_seed
from courtsim.rosters import RosterSnapshot

CAREER_VERSION = "career-v1"
DRAFT_VERSION = "draft-v1"
RETIREMENT_VERSION = "retirement-v1"
OFFSEASON_SCHEMA_VERSION = 1


class CareerStatus(IntEnum):
    PROSPECT = 0
    ACTIVE = 1
    FREE_AGENT = 2
    RETIRED = 3


@dataclass(frozen=True, slots=True)
class DevelopmentTraits:
    growth_rate: int = 70
    peak_start_age: int = 26
    peak_end_age: int = 30
    decline_resistance: int = 50
    consistency: int = 75

    def __post_init__(self) -> None:
        ratings = (self.growth_rate, self.decline_resistance, self.consistency)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100
            for value in ratings
        ):
            raise ValueError("development ratings must be integers from 0 through 100")
        if any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in (self.peak_start_age, self.peak_end_age)
        ):
            raise ValueError("peak ages must be integers")
        if not 18 <= self.peak_start_age <= self.peak_end_age <= 40:
            raise ValueError("peak ages must satisfy 18 <= start <= end <= 40")


@dataclass(frozen=True, slots=True)
class CareerRules:
    minimum_player_age: int = 18
    minimum_retirement_age: int = 32
    maximum_player_age: int = 45
    heavy_injury_days: int = 30
    low_minutes_per_game: int = 12
    version: str = CAREER_VERSION
    retirement_version: str = RETIREMENT_VERSION

    def __post_init__(self) -> None:
        values = (
            self.minimum_player_age,
            self.minimum_retirement_age,
            self.maximum_player_age,
            self.heavy_injury_days,
            self.low_minutes_per_game,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values
        ):
            raise ValueError("career rule values must be non-negative integers")
        if not (
            18 <= self.minimum_player_age <= self.minimum_retirement_age < self.maximum_player_age
        ):
            raise ValueError("career age bounds are invalid")
        if self.version != CAREER_VERSION:
            raise ValueError(f"unsupported career version: {self.version}")
        if self.retirement_version != RETIREMENT_VERSION:
            raise ValueError(f"unsupported retirement version: {self.retirement_version}")


@dataclass(frozen=True, slots=True)
class CareerPlayer:
    profile: PlayerProfile
    age: int
    seasons_pro: int
    development: DevelopmentTraits
    potential: AbilityRatings
    status: CareerStatus
    draft_year: int = 0
    draft_round: int = 0
    draft_pick: int = 0
    injury_burden: int = 0

    def __post_init__(self) -> None:
        values = (
            self.age,
            self.seasons_pro,
            self.draft_year,
            self.draft_round,
            self.draft_pick,
            self.injury_burden,
        )
        if any(not isinstance(value, int) or isinstance(value, bool) for value in values):
            raise ValueError("career player values must be integers")
        if not 18 <= self.age <= 60 or self.seasons_pro < 0:
            raise ValueError("career player age or seasons_pro is invalid")
        if not isinstance(self.development, DevelopmentTraits):
            raise ValueError("development must be DevelopmentTraits")
        if not isinstance(self.potential, AbilityRatings):
            raise ValueError("potential must be AbilityRatings")
        if not isinstance(self.status, CareerStatus):
            raise ValueError("status must be CareerStatus")
        if not 0 <= self.injury_burden <= 100:
            raise ValueError("injury_burden must be from 0 through 100")
        draft_values = (self.draft_year, self.draft_round, self.draft_pick)
        if any(value < 0 for value in draft_values):
            raise ValueError("draft values must be non-negative")
        if any(draft_values) and not all(draft_values):
            raise ValueError("draft values must be all zero or all positive")
        if self.status is CareerStatus.PROSPECT and any(draft_values):
            raise ValueError("an undrafted prospect cannot have draft values")
        for item in fields(AbilityRatings):
            if getattr(self.potential, item.name) < getattr(self.profile.abilities, item.name):
                raise ValueError("ability potential cannot be below current ability")

    @property
    def player_id(self) -> int:
        return self.profile.player_id


@dataclass(frozen=True, slots=True)
class PlayerSeasonSummary:
    player_id: int
    games_available: int
    games_played: int
    seconds_played: int
    injury_days: int = 0

    def __post_init__(self) -> None:
        values = (
            self.player_id,
            self.games_available,
            self.games_played,
            self.seconds_played,
            self.injury_days,
        )
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values
        ):
            raise ValueError("season summary values must be non-negative integers")
        if self.games_played > self.games_available:
            raise ValueError("games_played cannot exceed games_available")
        if self.games_played == 0 and self.seconds_played != 0:
            raise ValueError("seconds_played requires at least one game")


@dataclass(frozen=True, slots=True)
class AbilityChange:
    ability: str
    before: int
    after: int

    def __post_init__(self) -> None:
        valid = {item.name for item in fields(AbilityRatings)}
        if self.ability not in valid:
            raise ValueError("ability change references an unknown ability")
        if any(
            not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 100
            for value in (self.before, self.after)
        ):
            raise ValueError("ability change values must be ratings")

    @property
    def delta(self) -> int:
        return self.after - self.before


@dataclass(frozen=True, slots=True)
class PlayerCareerChange:
    player_id: int
    age_before: int
    age_after: int
    ability_changes: tuple[AbilityChange, ...]
    retirement_threshold_bps: int
    retirement_roll: int
    retired: bool

    def __post_init__(self) -> None:
        if any(
            not isinstance(value, int) or isinstance(value, bool)
            for value in (
                self.player_id,
                self.age_before,
                self.age_after,
                self.retirement_threshold_bps,
                self.retirement_roll,
            )
        ):
            raise ValueError("career change values must be integers")
        if self.player_id < 0 or self.age_after != self.age_before + 1:
            raise ValueError("career change identity or age transition is invalid")
        if not 0 <= self.retirement_threshold_bps <= 10_000:
            raise ValueError("retirement threshold must be basis points")
        if not 0 <= self.retirement_roll < 10_000:
            raise ValueError("retirement roll must be from 0 through 9999")


@dataclass(frozen=True, slots=True)
class CareerTransitionResult:
    season_year: int
    master_seed: int
    rules: CareerRules
    initial_players: tuple[CareerPlayer, ...]
    summaries: tuple[PlayerSeasonSummary, ...]
    changes: tuple[PlayerCareerChange, ...]
    final_players: tuple[CareerPlayer, ...]
    retired_player_ids: tuple[int, ...]
    version: str = CAREER_VERSION

    def __post_init__(self) -> None:
        if self.version != CAREER_VERSION:
            raise ValueError("unsupported career transition version")


@dataclass(frozen=True, slots=True)
class DraftRules:
    rounds: int = 2
    rookie_salary: int = 1_000_000
    rookie_contract_years: int = 2
    version: str = DRAFT_VERSION

    def __post_init__(self) -> None:
        values = (self.rounds, self.rookie_salary, self.rookie_contract_years)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in values
        ):
            raise ValueError("draft rule values must be positive integers")
        if self.version != DRAFT_VERSION:
            raise ValueError(f"unsupported draft version: {self.version}")


@dataclass(frozen=True, slots=True)
class DraftPickAsset:
    selection_number: int
    round_number: int
    round_pick: int
    original_team_id: str
    owner_team_id: str

    def __post_init__(self) -> None:
        values = (self.selection_number, self.round_number, self.round_pick)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 1 for value in values
        ):
            raise ValueError("draft pick numbers must be positive integers")
        if not self.original_team_id.strip() or not self.owner_team_id.strip():
            raise ValueError("draft pick team ids must not be blank")


@dataclass(frozen=True, slots=True)
class DraftSelection:
    selection_number: int
    team_id: str
    player_id: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.selection_number, int)
            or isinstance(self.selection_number, bool)
            or self.selection_number < 1
            or not isinstance(self.player_id, int)
            or isinstance(self.player_id, bool)
            or self.player_id < 0
        ):
            raise ValueError("draft selection identifiers are invalid")
        if not self.team_id.strip():
            raise ValueError("draft selection team_id must not be blank")


@dataclass(frozen=True, slots=True)
class DraftPlan:
    selections: tuple[DraftSelection, ...]
    version: str = DRAFT_VERSION

    def __post_init__(self) -> None:
        if self.version != DRAFT_VERSION:
            raise ValueError("unsupported draft plan version")
        numbers = tuple(item.selection_number for item in self.selections)
        if numbers != tuple(range(1, len(numbers) + 1)):
            raise ValueError("draft selections must be contiguous from one")
        player_ids = tuple(item.player_id for item in self.selections)
        if len(player_ids) != len(set(player_ids)):
            raise ValueError("a prospect cannot be drafted more than once")


@dataclass(frozen=True, slots=True)
class DraftResult:
    season_year: int
    rules: DraftRules
    picks: tuple[DraftPickAsset, ...]
    selections: tuple[DraftSelection, ...]
    initial_management: LeagueManagementState
    initial_players: tuple[CareerPlayer, ...]
    final_management: LeagueManagementState
    final_players: tuple[CareerPlayer, ...]
    version: str = DRAFT_VERSION

    def __post_init__(self) -> None:
        if self.version != DRAFT_VERSION:
            raise ValueError("unsupported draft result version")


@dataclass(frozen=True, slots=True)
class OffseasonResult:
    season_year: int
    master_seed: int
    career_rules: CareerRules
    contract_rules: ContractRules
    draft_rules: DraftRules
    initial_management: LeagueManagementState
    initial_players: tuple[CareerPlayer, ...]
    summaries: tuple[PlayerSeasonSummary, ...]
    picks: tuple[DraftPickAsset, ...]
    selections: tuple[DraftSelection, ...]
    market_actions: tuple[MarketAction, ...]
    changes: tuple[PlayerCareerChange, ...]
    retired_player_ids: tuple[int, ...]
    expired_player_ids: tuple[int, ...]
    final_management: LeagueManagementState
    final_players: tuple[CareerPlayer, ...]
    schema_version: int = OFFSEASON_SCHEMA_VERSION
    career_version: str = CAREER_VERSION
    draft_version: str = DRAFT_VERSION
    retirement_version: str = RETIREMENT_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != OFFSEASON_SCHEMA_VERSION:
            raise ValueError("unsupported offseason schema version")
        if self.career_version != CAREER_VERSION or self.draft_version != DRAFT_VERSION:
            raise ValueError("unsupported offseason component version")
        if self.retirement_version != RETIREMENT_VERSION:
            raise ValueError("unsupported offseason retirement version")


@dataclass(frozen=True, slots=True)
class OffseasonAudit:
    players_developed: int
    ratings_improved: int
    ratings_declined: int
    players_retired: int
    players_drafted: int
    contracts_expired: int
    signings: int
    waivers: int
    active_players: int
    free_agents: int


_EARLY_DECLINE = {
    "rim_finishing",
    "point_of_attack_defense",
    "steal_skill",
    "offensive_rebounding",
}
_LATE_DECLINE = {
    "playmaking",
    "midrange_shooting",
    "three_point_shooting",
    "free_throw_shooting",
    "offensive_decision",
    "defensive_awareness",
    "post_creation",
    "screen_setting",
}


def _ordered_players(players: tuple[CareerPlayer, ...]) -> tuple[CareerPlayer, ...]:
    ordered = tuple(sorted(players, key=lambda item: item.player_id))
    ids = tuple(item.player_id for item in ordered)
    if len(ids) != len(set(ids)):
        raise ValueError("career player ids must be unique")
    return ordered


def _ordered_summaries(
    summaries: tuple[PlayerSeasonSummary, ...],
) -> tuple[PlayerSeasonSummary, ...]:
    ordered = tuple(sorted(summaries, key=lambda item: item.player_id))
    ids = tuple(item.player_id for item in ordered)
    if len(ids) != len(set(ids)):
        raise ValueError("season summary player ids must be unique")
    return ordered


def _base_age_delta(age: int, ability: str, traits: DevelopmentTraits) -> int:
    if age < traits.peak_start_age:
        delta = 3 if age <= 21 else 2
    elif age <= traits.peak_end_age:
        delta = 1 if age == traits.peak_start_age else 0
    elif age <= 33:
        delta = -1 if ability in _EARLY_DECLINE else 0
    elif age <= 36:
        delta = -2 if ability in _EARLY_DECLINE else -1
    else:
        delta = -2
    if delta < 0 and ability in _LATE_DECLINE:
        delta += 1
    return delta


def _ability_delta(
    player: CareerPlayer,
    summary: PlayerSeasonSummary,
    season_year: int,
    master_seed: int,
    ability: str,
    rules: CareerRules,
) -> int:
    base = _base_age_delta(player.age + 1, ability, player.development)
    if base > 0:
        base = (base * player.development.growth_rate + 50) // 100
        if (
            player.age + 1 <= 25
            and summary.games_played > 0
            and summary.seconds_played // summary.games_played >= 20 * 60
        ):
            base += 1
    elif base < 0:
        resistance = player.development.decline_resistance
        magnitude = max(0, ((-base) * (150 - resistance) + 50) // 100)
        base = -magnitude
    if summary.injury_days >= rules.heavy_injury_days or player.injury_burden >= 70:
        base -= 1
    stream = random.Random(
        derive_seed(master_seed, "career", season_year, player.player_id, "ability", ability)
    )
    if stream.randrange(100) >= player.development.consistency:
        base += stream.randrange(3) - 1
    return base


def _retirement_threshold(
    player: CareerPlayer,
    summary: PlayerSeasonSummary,
    rules: CareerRules,
) -> int:
    age = player.age + 1
    if age < rules.minimum_retirement_age:
        return 0
    if age >= rules.maximum_player_age:
        return 10_000
    years = age - rules.minimum_retirement_age + 1
    threshold = years * years * 95
    threshold += player.injury_burden * 12 + summary.injury_days * 8
    if summary.games_played == 0:
        threshold += 900
    elif summary.seconds_played // summary.games_played < rules.low_minutes_per_game * 60:
        threshold += 450
    if player.status is CareerStatus.ACTIVE:
        threshold -= 300
    threshold -= player.development.decline_resistance * 7
    return min(10_000, max(0, threshold))


def advance_careers(
    players: tuple[CareerPlayer, ...],
    summaries: tuple[PlayerSeasonSummary, ...],
    *,
    season_year: int,
    master_seed: int,
    rules: CareerRules | None = None,
) -> CareerTransitionResult:
    rules = rules or CareerRules()
    ordered_players = _ordered_players(players)
    ordered_summaries = _ordered_summaries(summaries)
    eligible = {
        item.player_id
        for item in ordered_players
        if item.status in {CareerStatus.ACTIVE, CareerStatus.FREE_AGENT}
    }
    if {item.player_id for item in ordered_summaries} != eligible:
        raise ValueError("season summaries must cover every active and free-agent player")
    summary_by_id = {item.player_id: item for item in ordered_summaries}
    final: list[CareerPlayer] = []
    changes: list[PlayerCareerChange] = []
    retired: list[int] = []
    for player in ordered_players:
        if player.status not in {CareerStatus.ACTIVE, CareerStatus.FREE_AGENT}:
            final.append(player)
            continue
        summary = summary_by_id[player.player_id]
        ability_values: dict[str, int] = {}
        ability_changes: list[AbilityChange] = []
        for item in fields(AbilityRatings):
            before = getattr(player.profile.abilities, item.name)
            delta = _ability_delta(
                player,
                summary,
                season_year,
                master_seed,
                item.name,
                rules,
            )
            after = max(0, min(getattr(player.potential, item.name), before + delta))
            ability_values[item.name] = after
            ability_changes.append(AbilityChange(item.name, before, after))
        abilities = AbilityRatings(**ability_values)
        threshold = _retirement_threshold(player, summary, rules)
        roll = random.Random(
            derive_seed(master_seed, "career", season_year, player.player_id, "retirement")
        ).randrange(10_000)
        did_retire = roll < threshold
        if did_retire:
            retired.append(player.player_id)
        injury_burden = min(
            100,
            max(0, player.injury_burden - 5 + min(20, summary.injury_days // 3)),
        )
        updated = replace(
            player,
            profile=replace(player.profile, abilities=abilities),
            age=player.age + 1,
            seasons_pro=player.seasons_pro + 1,
            status=CareerStatus.RETIRED if did_retire else player.status,
            injury_burden=injury_burden,
        )
        final.append(updated)
        changes.append(
            PlayerCareerChange(
                player.player_id,
                player.age,
                updated.age,
                tuple(ability_changes),
                threshold,
                roll,
                did_retire,
            )
        )
    return CareerTransitionResult(
        season_year,
        master_seed,
        rules,
        ordered_players,
        ordered_summaries,
        tuple(changes),
        tuple(final),
        tuple(retired),
    )


def _remove_retired(
    state: LeagueManagementState,
    retired_player_ids: tuple[int, ...],
    rules: ContractRules,
) -> LeagueManagementState:
    retired = set(retired_player_ids)
    updated = LeagueManagementState(
        state.season_year,
        tuple(
            RosterSnapshot(
                roster.team_id,
                tuple(player_id for player_id in roster.player_ids if player_id not in retired),
            )
            for roster in state.rosters
        ),
        tuple(player_id for player_id in state.free_agent_ids if player_id not in retired),
        tuple(contract for contract in state.contracts if contract.player_id not in retired),
    )
    validate_management_state(updated, rules)
    return updated


def _sync_statuses(
    players: tuple[CareerPlayer, ...],
    state: LeagueManagementState,
) -> tuple[CareerPlayer, ...]:
    active = {player_id for roster in state.rosters for player_id in roster.player_ids}
    free_agents = set(state.free_agent_ids)
    known = {item.player_id for item in players}
    if not active | free_agents <= known:
        raise ValueError("management state references an unknown career player")
    unavailable = {
        item.player_id
        for item in players
        if item.status in {CareerStatus.PROSPECT, CareerStatus.RETIRED}
    }
    if (active | free_agents) & unavailable:
        raise ValueError("prospect or retired player cannot be rostered or a free agent")
    synced = []
    for player in players:
        if player.status in {CareerStatus.PROSPECT, CareerStatus.RETIRED}:
            synced.append(player)
        elif player.player_id in active:
            synced.append(replace(player, status=CareerStatus.ACTIVE))
        elif player.player_id in free_agents:
            synced.append(replace(player, status=CareerStatus.FREE_AGENT))
        else:
            raise ValueError("active career player is absent from management state")
    return tuple(synced)


def apply_draft(
    state: LeagueManagementState,
    players: tuple[CareerPlayer, ...],
    picks: tuple[DraftPickAsset, ...],
    plan: DraftPlan,
    *,
    season_year: int,
    contract_rules: ContractRules,
    draft_rules: DraftRules | None = None,
) -> DraftResult:
    draft_rules = draft_rules or DraftRules()
    validate_management_state(state, contract_rules)
    ordered_players = _ordered_players(players)
    ordered_picks = tuple(sorted(picks, key=lambda item: item.selection_number))
    if tuple(item.selection_number for item in ordered_picks) != tuple(
        range(1, len(ordered_picks) + 1)
    ):
        raise ValueError("draft picks must be contiguous from one")
    if any(item.round_number > draft_rules.rounds for item in ordered_picks):
        raise ValueError("draft pick exceeds configured rounds")
    if len(plan.selections) != len(ordered_picks):
        raise ValueError("draft plan must fill every pick")
    team_ids = {roster.team_id for roster in state.rosters}
    if any(
        item.owner_team_id not in team_ids or item.original_team_id not in team_ids
        for item in ordered_picks
    ):
        raise ValueError("draft pick team is not a league team")
    players_by_id = {item.player_id: item for item in ordered_players}
    final_state = state
    for pick, selection in zip(ordered_picks, plan.selections, strict=True):
        if (
            selection.selection_number != pick.selection_number
            or selection.team_id != pick.owner_team_id
        ):
            raise ValueError("draft selection does not match pick ownership")
        player = players_by_id.get(selection.player_id)
        if player is None or player.status is not CareerStatus.PROSPECT:
            raise ValueError("draft selection must reference an available prospect")
        roster = next(item for item in final_state.rosters if item.team_id == selection.team_id)
        if len(roster.player_ids) >= contract_rules.maximum_roster_players:
            raise ValueError("draft selection would exceed maximum roster size")
        updated_rosters = tuple(
            RosterSnapshot(item.team_id, (*item.player_ids, player.player_id))
            if item.team_id == selection.team_id
            else item
            for item in final_state.rosters
        )
        contract = PlayerContract(
            player.player_id,
            selection.team_id,
            draft_rules.rookie_salary,
            draft_rules.rookie_contract_years,
        )
        final_state = LeagueManagementState(
            final_state.season_year,
            updated_rosters,
            final_state.free_agent_ids,
            tuple(sorted((*final_state.contracts, contract), key=lambda item: item.player_id)),
        )
        validate_management_state(final_state, contract_rules)
        players_by_id[player.player_id] = replace(
            player,
            status=CareerStatus.ACTIVE,
            draft_year=season_year,
            draft_round=pick.round_number,
            draft_pick=pick.round_pick,
        )
    return DraftResult(
        season_year,
        draft_rules,
        ordered_picks,
        plan.selections,
        state,
        ordered_players,
        final_state,
        tuple(sorted(players_by_id.values(), key=lambda item: item.player_id)),
    )


def advance_offseason(
    *,
    season_year: int,
    master_seed: int,
    management: LeagueManagementState,
    players: tuple[CareerPlayer, ...],
    summaries: tuple[PlayerSeasonSummary, ...],
    picks: tuple[DraftPickAsset, ...],
    draft_plan: DraftPlan,
    market_plan: MarketPlan,
    career_rules: CareerRules | None = None,
    contract_rules: ContractRules | None = None,
    draft_rules: DraftRules | None = None,
) -> OffseasonResult:
    career_rules = career_rules or CareerRules()
    contract_rules = contract_rules or ContractRules()
    draft_rules = draft_rules or DraftRules(
        rookie_salary=contract_rules.minimum_salary,
        rookie_contract_years=min(2, contract_rules.maximum_years),
    )
    validate_management_state(management, contract_rules)
    if management.season_year != season_year:
        raise ValueError("offseason year must match management season year")
    transition = advance_careers(
        players,
        summaries,
        season_year=season_year,
        master_seed=master_seed,
        rules=career_rules,
    )
    after_retirement = _remove_retired(
        management,
        transition.retired_player_ids,
        contract_rules,
    )
    contract_year = advance_contract_year(after_retirement, contract_rules)
    synced = _sync_statuses(transition.final_players, contract_year.final_state)
    draft = apply_draft(
        contract_year.final_state,
        synced,
        picks,
        draft_plan,
        season_year=season_year + 1,
        contract_rules=contract_rules,
        draft_rules=draft_rules,
    )
    market = apply_market_plan(draft.final_management, market_plan, contract_rules)
    final_players = _sync_statuses(draft.final_players, market.final_state)
    return OffseasonResult(
        season_year,
        master_seed,
        career_rules,
        contract_rules,
        draft_rules,
        management,
        _ordered_players(players),
        _ordered_summaries(summaries),
        draft.picks,
        draft.selections,
        market.actions,
        transition.changes,
        transition.retired_player_ids,
        contract_year.expired_player_ids,
        market.final_state,
        final_players,
    )


def audit_offseason(result: OffseasonResult) -> OffseasonAudit:
    replayed = advance_offseason(
        season_year=result.season_year,
        master_seed=result.master_seed,
        management=result.initial_management,
        players=result.initial_players,
        summaries=result.summaries,
        picks=result.picks,
        draft_plan=DraftPlan(result.selections),
        market_plan=MarketPlan(result.market_actions),
        career_rules=result.career_rules,
        contract_rules=result.contract_rules,
        draft_rules=result.draft_rules,
    )
    if replayed != result:
        raise ValueError("offseason result does not derive from its ledgers")
    return OffseasonAudit(
        len(result.changes),
        sum(
            change.delta > 0
            for player_change in result.changes
            for change in player_change.ability_changes
        ),
        sum(
            change.delta < 0
            for player_change in result.changes
            for change in player_change.ability_changes
        ),
        len(result.retired_player_ids),
        len(result.selections),
        len(result.expired_player_ids),
        sum(action.kind is MarketActionKind.SIGN for action in result.market_actions),
        sum(action.kind is MarketActionKind.WAIVE for action in result.market_actions),
        sum(player.status is CareerStatus.ACTIVE for player in result.final_players),
        sum(player.status is CareerStatus.FREE_AGENT for player in result.final_players),
    )


def _abilities_to_dict(value: AbilityRatings) -> dict[str, int]:
    return {item.name: getattr(value, item.name) for item in fields(AbilityRatings)}


def _career_rules_to_dict(value: CareerRules) -> dict[str, object]:
    return {
        "minimum_player_age": value.minimum_player_age,
        "minimum_retirement_age": value.minimum_retirement_age,
        "maximum_player_age": value.maximum_player_age,
        "heavy_injury_days": value.heavy_injury_days,
        "low_minutes_per_game": value.low_minutes_per_game,
        "version": value.version,
        "retirement_version": value.retirement_version,
    }


def _contract_rules_to_dict(value: ContractRules) -> dict[str, object]:
    return {
        "salary_cap": value.salary_cap,
        "minimum_salary": value.minimum_salary,
        "maximum_salary": value.maximum_salary,
        "maximum_years": value.maximum_years,
        "maximum_roster_players": value.maximum_roster_players,
        "version": value.version,
    }


def _draft_rules_to_dict(value: DraftRules) -> dict[str, object]:
    return {
        "rounds": value.rounds,
        "rookie_salary": value.rookie_salary,
        "rookie_contract_years": value.rookie_contract_years,
        "version": value.version,
    }


def _player_to_dict(value: CareerPlayer) -> dict[str, object]:
    return {
        "profile": player_profile_to_dict(value.profile),
        "age": value.age,
        "seasons_pro": value.seasons_pro,
        "development": {
            "growth_rate": value.development.growth_rate,
            "peak_start_age": value.development.peak_start_age,
            "peak_end_age": value.development.peak_end_age,
            "decline_resistance": value.development.decline_resistance,
            "consistency": value.development.consistency,
        },
        "potential": _abilities_to_dict(value.potential),
        "status": int(value.status),
        "draft_year": value.draft_year,
        "draft_round": value.draft_round,
        "draft_pick": value.draft_pick,
        "injury_burden": value.injury_burden,
    }


def _management_to_dict(value: LeagueManagementState) -> dict[str, object]:
    return {
        "season_year": value.season_year,
        "contract_version": value.contract_version,
        "free_agency_version": value.free_agency_version,
        "rosters": [
            {"team_id": item.team_id, "player_ids": list(item.player_ids)} for item in value.rosters
        ],
        "free_agent_ids": list(value.free_agent_ids),
        "contracts": [
            {
                "player_id": item.player_id,
                "team_id": item.team_id,
                "annual_salary": item.annual_salary,
                "years_remaining": item.years_remaining,
            }
            for item in value.contracts
        ],
    }


def offseason_result_to_dict(result: OffseasonResult) -> dict[str, object]:
    return {
        "schema_version": result.schema_version,
        "career_version": result.career_version,
        "draft_version": result.draft_version,
        "retirement_version": result.retirement_version,
        "season_year": result.season_year,
        "master_seed": result.master_seed,
        "career_rules": _career_rules_to_dict(result.career_rules),
        "contract_rules": _contract_rules_to_dict(result.contract_rules),
        "draft_rules": _draft_rules_to_dict(result.draft_rules),
        "initial_management": _management_to_dict(result.initial_management),
        "initial_players": [_player_to_dict(item) for item in result.initial_players],
        "summaries": [
            {
                "player_id": item.player_id,
                "games_available": item.games_available,
                "games_played": item.games_played,
                "seconds_played": item.seconds_played,
                "injury_days": item.injury_days,
            }
            for item in result.summaries
        ],
        "picks": [
            {
                "selection_number": item.selection_number,
                "round_number": item.round_number,
                "round_pick": item.round_pick,
                "original_team_id": item.original_team_id,
                "owner_team_id": item.owner_team_id,
            }
            for item in result.picks
        ],
        "selections": [
            {
                "selection_number": item.selection_number,
                "team_id": item.team_id,
                "player_id": item.player_id,
            }
            for item in result.selections
        ],
        "market_actions": [
            {
                "action_id": item.action_id,
                "kind": int(item.kind),
                "player_id": item.player_id,
                "team_id": item.team_id,
                "annual_salary": item.annual_salary,
                "years": item.years,
            }
            for item in result.market_actions
        ],
        "changes": [
            {
                "player_id": item.player_id,
                "age_before": item.age_before,
                "age_after": item.age_after,
                "ability_changes": [
                    {
                        "ability": change.ability,
                        "before": change.before,
                        "after": change.after,
                    }
                    for change in item.ability_changes
                ],
                "retirement_threshold_bps": item.retirement_threshold_bps,
                "retirement_roll": item.retirement_roll,
                "retired": item.retired,
            }
            for item in result.changes
        ],
        "retired_player_ids": list(result.retired_player_ids),
        "expired_player_ids": list(result.expired_player_ids),
        "final_management": _management_to_dict(result.final_management),
        "final_players": [_player_to_dict(item) for item in result.final_players],
    }


def _fail(message: str) -> NoReturn:
    raise SerializationError(message)


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        _fail(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        _fail(f"{field} must be a list")
    return cast(list[object], value)


def _exact(value: dict[str, Any], keys: set[str], field: str) -> None:
    if set(value) != keys:
        _fail(f"{field} keys must be exactly {sorted(keys)}")


def _integer(value: dict[str, Any], key: str) -> int:
    item = value[key]
    if not isinstance(item, int) or isinstance(item, bool):
        _fail(f"{key} must be an integer")
    return item


def _string(value: dict[str, Any], key: str) -> str:
    item = value[key]
    if not isinstance(item, str):
        _fail(f"{key} must be a string")
    return item


def _integer_list(value: object, field: str) -> tuple[int, ...]:
    items = _list(value, field)
    if any(not isinstance(item, int) or isinstance(item, bool) for item in items):
        _fail(f"{field} must contain integers")
    return tuple(cast(list[int], items))


def _parse_abilities(value: object, field: str) -> AbilityRatings:
    raw = _object(value, field)
    names = {item.name for item in fields(AbilityRatings)}
    _exact(raw, names, field)
    return AbilityRatings(**{name: _integer(raw, name) for name in names})


def _parse_player(value: object) -> CareerPlayer:
    raw = _object(value, "career player")
    _exact(
        raw,
        {
            "profile",
            "age",
            "seasons_pro",
            "development",
            "potential",
            "status",
            "draft_year",
            "draft_round",
            "draft_pick",
            "injury_burden",
        },
        "career player",
    )
    development = _object(raw["development"], "development")
    _exact(
        development,
        {
            "growth_rate",
            "peak_start_age",
            "peak_end_age",
            "decline_resistance",
            "consistency",
        },
        "development",
    )
    try:
        return CareerPlayer(
            player_profile_from_dict(raw["profile"]),
            _integer(raw, "age"),
            _integer(raw, "seasons_pro"),
            DevelopmentTraits(
                _integer(development, "growth_rate"),
                _integer(development, "peak_start_age"),
                _integer(development, "peak_end_age"),
                _integer(development, "decline_resistance"),
                _integer(development, "consistency"),
            ),
            _parse_abilities(raw["potential"], "potential"),
            CareerStatus(_integer(raw, "status")),
            _integer(raw, "draft_year"),
            _integer(raw, "draft_round"),
            _integer(raw, "draft_pick"),
            _integer(raw, "injury_burden"),
        )
    except ValueError as error:
        raise SerializationError(str(error)) from error


def _parse_management(value: object) -> LeagueManagementState:
    raw = _object(value, "management state")
    _exact(
        raw,
        {
            "season_year",
            "contract_version",
            "free_agency_version",
            "rosters",
            "free_agent_ids",
            "contracts",
        },
        "management state",
    )
    rosters = []
    for value_item in _list(raw["rosters"], "rosters"):
        item = _object(value_item, "roster")
        _exact(item, {"team_id", "player_ids"}, "roster")
        rosters.append(
            RosterSnapshot(
                _string(item, "team_id"),
                _integer_list(item["player_ids"], "player_ids"),
            )
        )
    contracts = []
    for value_item in _list(raw["contracts"], "contracts"):
        item = _object(value_item, "contract")
        _exact(
            item,
            {"player_id", "team_id", "annual_salary", "years_remaining"},
            "contract",
        )
        contracts.append(
            PlayerContract(
                _integer(item, "player_id"),
                _string(item, "team_id"),
                _integer(item, "annual_salary"),
                _integer(item, "years_remaining"),
            )
        )
    state = LeagueManagementState(
        _integer(raw, "season_year"),
        tuple(rosters),
        _integer_list(raw["free_agent_ids"], "free_agent_ids"),
        tuple(contracts),
        _string(raw, "contract_version"),
        _string(raw, "free_agency_version"),
    )
    return state


def offseason_result_from_dict(value: object) -> OffseasonResult:
    raw = _object(value, "offseason result")
    _exact(
        raw,
        {
            "schema_version",
            "career_version",
            "draft_version",
            "retirement_version",
            "season_year",
            "master_seed",
            "career_rules",
            "contract_rules",
            "draft_rules",
            "initial_management",
            "initial_players",
            "summaries",
            "picks",
            "selections",
            "market_actions",
            "changes",
            "retired_player_ids",
            "expired_player_ids",
            "final_management",
            "final_players",
        },
        "offseason result",
    )
    career_raw = _object(raw["career_rules"], "career rules")
    _exact(
        career_raw,
        {
            "minimum_player_age",
            "minimum_retirement_age",
            "maximum_player_age",
            "heavy_injury_days",
            "low_minutes_per_game",
            "version",
            "retirement_version",
        },
        "career rules",
    )
    contract_raw = _object(raw["contract_rules"], "contract rules")
    _exact(
        contract_raw,
        {
            "salary_cap",
            "minimum_salary",
            "maximum_salary",
            "maximum_years",
            "maximum_roster_players",
            "version",
        },
        "contract rules",
    )
    draft_raw = _object(raw["draft_rules"], "draft rules")
    _exact(
        draft_raw,
        {"rounds", "rookie_salary", "rookie_contract_years", "version"},
        "draft rules",
    )
    summaries = []
    for value_item in _list(raw["summaries"], "summaries"):
        item = _object(value_item, "season summary")
        _exact(
            item,
            {
                "player_id",
                "games_available",
                "games_played",
                "seconds_played",
                "injury_days",
            },
            "season summary",
        )
        summaries.append(
            PlayerSeasonSummary(
                _integer(item, "player_id"),
                _integer(item, "games_available"),
                _integer(item, "games_played"),
                _integer(item, "seconds_played"),
                _integer(item, "injury_days"),
            )
        )
    picks = []
    for value_item in _list(raw["picks"], "picks"):
        item = _object(value_item, "draft pick")
        _exact(
            item,
            {
                "selection_number",
                "round_number",
                "round_pick",
                "original_team_id",
                "owner_team_id",
            },
            "draft pick",
        )
        picks.append(
            DraftPickAsset(
                _integer(item, "selection_number"),
                _integer(item, "round_number"),
                _integer(item, "round_pick"),
                _string(item, "original_team_id"),
                _string(item, "owner_team_id"),
            )
        )
    selections = []
    for value_item in _list(raw["selections"], "selections"):
        item = _object(value_item, "draft selection")
        _exact(item, {"selection_number", "team_id", "player_id"}, "draft selection")
        selections.append(
            DraftSelection(
                _integer(item, "selection_number"),
                _string(item, "team_id"),
                _integer(item, "player_id"),
            )
        )
    market_actions = []
    for value_item in _list(raw["market_actions"], "market actions"):
        item = _object(value_item, "market action")
        _exact(
            item,
            {"action_id", "kind", "player_id", "team_id", "annual_salary", "years"},
            "market action",
        )
        try:
            kind = MarketActionKind(_integer(item, "kind"))
        except ValueError as error:
            raise SerializationError("invalid market action kind") from error
        market_actions.append(
            MarketAction(
                _integer(item, "action_id"),
                kind,
                _integer(item, "player_id"),
                _string(item, "team_id"),
                _integer(item, "annual_salary"),
                _integer(item, "years"),
            )
        )
    changes = []
    for value_item in _list(raw["changes"], "changes"):
        item = _object(value_item, "career change")
        _exact(
            item,
            {
                "player_id",
                "age_before",
                "age_after",
                "ability_changes",
                "retirement_threshold_bps",
                "retirement_roll",
                "retired",
            },
            "career change",
        )
        retired = item["retired"]
        if not isinstance(retired, bool):
            _fail("retired must be a boolean")
        ability_changes = []
        for change_value in _list(item["ability_changes"], "ability changes"):
            change = _object(change_value, "ability change")
            _exact(change, {"ability", "before", "after"}, "ability change")
            ability_changes.append(
                AbilityChange(
                    _string(change, "ability"),
                    _integer(change, "before"),
                    _integer(change, "after"),
                )
            )
        changes.append(
            PlayerCareerChange(
                _integer(item, "player_id"),
                _integer(item, "age_before"),
                _integer(item, "age_after"),
                tuple(ability_changes),
                _integer(item, "retirement_threshold_bps"),
                _integer(item, "retirement_roll"),
                retired,
            )
        )
    try:
        result = OffseasonResult(
            _integer(raw, "season_year"),
            _integer(raw, "master_seed"),
            CareerRules(
                _integer(career_raw, "minimum_player_age"),
                _integer(career_raw, "minimum_retirement_age"),
                _integer(career_raw, "maximum_player_age"),
                _integer(career_raw, "heavy_injury_days"),
                _integer(career_raw, "low_minutes_per_game"),
                _string(career_raw, "version"),
                _string(career_raw, "retirement_version"),
            ),
            ContractRules(
                _integer(contract_raw, "salary_cap"),
                _integer(contract_raw, "minimum_salary"),
                _integer(contract_raw, "maximum_salary"),
                _integer(contract_raw, "maximum_years"),
                _integer(contract_raw, "maximum_roster_players"),
                _string(contract_raw, "version"),
            ),
            DraftRules(
                _integer(draft_raw, "rounds"),
                _integer(draft_raw, "rookie_salary"),
                _integer(draft_raw, "rookie_contract_years"),
                _string(draft_raw, "version"),
            ),
            _parse_management(raw["initial_management"]),
            tuple(_parse_player(item) for item in _list(raw["initial_players"], "initial players")),
            tuple(summaries),
            tuple(picks),
            tuple(selections),
            tuple(market_actions),
            tuple(changes),
            _integer_list(raw["retired_player_ids"], "retired_player_ids"),
            _integer_list(raw["expired_player_ids"], "expired_player_ids"),
            _parse_management(raw["final_management"]),
            tuple(_parse_player(item) for item in _list(raw["final_players"], "final players")),
            _integer(raw, "schema_version"),
            _string(raw, "career_version"),
            _string(raw, "draft_version"),
            _string(raw, "retirement_version"),
        )
        audit_offseason(result)
    except (TypeError, ValueError) as error:
        raise SerializationError(str(error)) from error
    return result


def offseason_result_to_json(result: OffseasonResult) -> str:
    return json.dumps(
        offseason_result_to_dict(result),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def offseason_result_from_json(payload: str) -> OffseasonResult:
    try:
        value: object = json.loads(payload)
    except json.JSONDecodeError as error:
        raise SerializationError(f"invalid offseason JSON: {error.msg}") from error
    return offseason_result_from_dict(value)
