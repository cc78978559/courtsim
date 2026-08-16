"""Build source-pinned real-player franchise states for NBA manager studies."""

from __future__ import annotations

import hashlib
import json
import math
from collections import defaultdict
from dataclasses import dataclass, fields
from pathlib import Path
from statistics import median
from typing import Any, cast

from courtsim.analysis.nba_player_targets import NBAPlayerTargetSet
from courtsim.artifacts import sha256_file
from courtsim.cap_mechanics import BirdRights, CapLedger, cap_rules_for_salary_cap
from courtsim.career import CareerPlayer, CareerStatus, DevelopmentTraits
from courtsim.domain.player import AbilityRatings, PlayerProfile
from courtsim.draft_assets import DraftAssetLedger, seed_future_draft_picks
from courtsim.management import (
    ContractRules,
    LeagueManagementState,
    PlayerContract,
    validate_management_state,
)
from courtsim.model.game_runtime import GameTeam
from courtsim.nba_franchise import NBAFranchiseState
from courtsim.nba_franchise_artifacts import nba_franchise_state_to_json
from courtsim.nba_league import NBAConferenceAlignment
from courtsim.rosters import RosterSnapshot

NBA_MANAGER_STATE_SOURCE_VERSION = "nba-manager-state-source-v1"
NBA_MANAGER_STATE_BUILD_VERSION = "nba-manager-state-build-v1"
NBA_MANAGER_STATE_SOURCE_SCHEMA_VERSION = 1


class NBAManagerStateError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class NBAManagerPlayerSource:
    nba_player_id: int
    age: int | None = None
    annual_salary: int | None = None
    contract_years_remaining: int | None = None
    team_tenure_seasons: int | None = None

    def __post_init__(self) -> None:
        if self.nba_player_id < 1:
            raise ValueError("NBA manager player source identity is invalid")
        if self.age is not None and not 18 <= self.age <= 60:
            raise ValueError("NBA manager player source age is invalid")
        if self.annual_salary is not None and self.annual_salary < 1:
            raise ValueError("NBA manager player source salary is invalid")
        if self.contract_years_remaining is not None and self.contract_years_remaining < 1:
            raise ValueError("NBA manager player source contract term is invalid")
        if self.team_tenure_seasons is not None and self.team_tenure_seasons < 1:
            raise ValueError("NBA manager player source tenure is invalid")


@dataclass(frozen=True, slots=True)
class NBAManagerStateSource:
    dataset_id: str
    season: str
    source_sha256: str
    players: tuple[NBAManagerPlayerSource, ...]
    sources: tuple[tuple[str, str], ...] = ()
    version: str = NBA_MANAGER_STATE_SOURCE_VERSION

    def __post_init__(self) -> None:
        if not self.dataset_id.strip() or not self.season.strip():
            raise ValueError("NBA manager state source identity is invalid")
        if not _valid_sha256(self.source_sha256):
            raise ValueError("NBA manager state source hash is invalid")
        identities = tuple(item.nba_player_id for item in self.players)
        if identities != tuple(sorted(set(identities))):
            raise ValueError("NBA manager player sources must use ordered unique identities")
        roles = tuple(role for role, _ in self.sources)
        if roles != tuple(sorted(set(roles))) or any(
            not role.strip() or not _valid_sha256(digest) for role, digest in self.sources
        ):
            raise ValueError("NBA manager state source receipts are invalid")
        if self.version != NBA_MANAGER_STATE_SOURCE_VERSION:
            raise ValueError("unsupported NBA manager state source version")


@dataclass(frozen=True, slots=True)
class NBAManagerPlayerResolution:
    nba_player_id: int
    age: int
    age_source: str
    annual_salary: int
    salary_source: str
    contract_years_remaining: int
    contract_source: str
    bird_seasons: int
    bird_source: str


@dataclass(frozen=True, slots=True)
class NBAManagerStateBuildReceipt:
    league_id: str
    season_year: int
    player_target_id: str
    player_source_dataset_id: str
    player_source_sha256: str
    initial_state_sha256: str
    rostered_players: int
    source_age_coverage: float
    minute_weighted_source_salary_coverage: float
    formal_source_eligible: bool
    proxy_age_player_ids: tuple[int, ...]
    proxy_salary_player_ids: tuple[int, ...]
    default_contract_player_ids: tuple[int, ...]
    non_bird_fallback_player_ids: tuple[int, ...]
    version: str = NBA_MANAGER_STATE_BUILD_VERSION

    def __post_init__(self) -> None:
        if (
            not self.league_id.strip()
            or self.season_year < 1
            or not self.player_target_id.strip()
            or not self.player_source_dataset_id.strip()
            or not _valid_sha256(self.player_source_sha256)
            or not _valid_sha256(self.initial_state_sha256)
            or self.rostered_players < 300
            or not 0 <= self.source_age_coverage <= 1
            or not 0 <= self.minute_weighted_source_salary_coverage <= 1
            or self.formal_source_eligible
            != (
                self.source_age_coverage >= 0.95
                and self.minute_weighted_source_salary_coverage >= 0.90
            )
            or self.version != NBA_MANAGER_STATE_BUILD_VERSION
        ):
            raise ValueError("NBA manager state-build receipt is invalid")
        for player_ids in (
            self.proxy_age_player_ids,
            self.proxy_salary_player_ids,
            self.default_contract_player_ids,
            self.non_bird_fallback_player_ids,
        ):
            if player_ids != tuple(sorted(set(player_ids))) or any(
                not isinstance(player_id, int) or isinstance(player_id, bool) or player_id < 1
                for player_id in player_ids
            ):
                raise ValueError("NBA manager state-build fallback identities are invalid")


@dataclass(frozen=True, slots=True)
class NBAManagerStateBuildResult:
    state: NBAFranchiseState
    contract_rules: ContractRules
    resolutions: tuple[NBAManagerPlayerResolution, ...]
    receipt: NBAManagerStateBuildReceipt


def load_nba_manager_state_source(path: str | Path) -> NBAManagerStateSource:
    source = Path(path).resolve()
    try:
        value: object = json.loads(source.read_text(encoding="utf-8"))
        root = _mapping(value, "NBA manager state source")
        if set(root) != {
            "schema_version",
            "version",
            "dataset_id",
            "season",
            "sources",
            "players",
        }:
            raise NBAManagerStateError("NBA manager state source root is invalid")
        if root["schema_version"] != NBA_MANAGER_STATE_SOURCE_SCHEMA_VERSION:
            raise NBAManagerStateError("NBA manager state source schema differs")
        raw_players = root["players"]
        if not isinstance(raw_players, list):
            raise NBAManagerStateError("NBA manager state source players are invalid")
        raw_sources = root["sources"]
        if not isinstance(raw_sources, list):
            raise NBAManagerStateError("NBA manager state source receipts are invalid")
        players = tuple(
            _player_source_from_object(item)
            for item in sorted(
                raw_players,
                key=lambda item: _integer(
                    _mapping(item, "NBA manager player source").get("nba_player_id"),
                    "nba_player_id",
                ),
            )
        )
        return NBAManagerStateSource(
            _text(root["dataset_id"], "dataset_id"),
            _text(root["season"], "season"),
            sha256_file(source),
            players,
            tuple(
                sorted(
                    (
                        _text(_mapping(item, "NBA manager source receipt")["role"], "role"),
                        _text(_mapping(item, "NBA manager source receipt")["sha256"], "sha256"),
                    )
                    for item in raw_sources
                )
            ),
            _text(root["version"], "version"),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
        raise NBAManagerStateError(f"cannot load NBA manager state source: {source}") from error


def build_nba_manager_initial_state(
    *,
    league_id: str,
    season_year: int,
    teams: tuple[GameTeam, ...],
    alignment: NBAConferenceAlignment,
    player_targets: NBAPlayerTargetSet,
    player_source: NBAManagerStateSource,
    contract_rules: ContractRules,
) -> NBAManagerStateBuildResult:
    """Build a formal franchise state while marking every source fallback explicitly."""
    if not league_id.strip() or season_year < 1:
        raise NBAManagerStateError("NBA manager initial-state identity is invalid")
    if len(teams) != 30 or tuple(team.team_id for team in teams) != tuple(
        sorted(team.team_id for team in teams)
    ):
        raise NBAManagerStateError("NBA manager initial teams must be thirty and canonical")
    if player_source.season != player_targets.season:
        raise NBAManagerStateError("NBA manager state sources use different seasons")
    roster_profiles = tuple(profile for team in teams for profile in team.roster_profiles)
    roster_ids = tuple(profile.player_id for profile in roster_profiles)
    if len(roster_ids) != len(set(roster_ids)) or len(roster_ids) < 300:
        raise NBAManagerStateError("NBA manager real rosters are incomplete or duplicated")
    target_by_id = {item.nba_player_id: item for item in player_targets.players}
    if any(player_id not in target_by_id for player_id in roster_ids):
        raise NBAManagerStateError("NBA manager roster identity lacks a player target")
    source_by_id = {item.nba_player_id: item for item in player_source.players}
    sourced_ages = [item.age for item in player_source.players if item.age is not None]
    league_age = round(median(sourced_ages)) if sourced_ages else 26
    role_ages: dict[str, list[int]] = defaultdict(list)
    profile_by_id = {item.player_id: item for item in roster_profiles}
    for item in player_source.players:
        profile = profile_by_id.get(item.nba_player_id)
        if profile is not None and item.age is not None:
            role_ages[_role(profile)].append(item.age)
    resolved_ages = {
        player_id: _resolved_age(
            source_by_id.get(player_id),
            role_ages.get(_role(profile_by_id[player_id]), [league_age]),
        )
        for player_id in roster_ids
    }
    proxy_salaries = _proxy_salaries(roster_profiles, player_targets, contract_rules)
    resolutions = tuple(
        _resolve_player(
            profile_by_id[player_id],
            resolved_ages[player_id],
            source_by_id.get(player_id),
            proxy_salaries[player_id],
            contract_rules,
        )
        for player_id in sorted(roster_ids)
    )
    resolution_by_id = {item.nba_player_id: item for item in resolutions}
    players = tuple(
        _career_player(profile, resolution_by_id[profile.player_id])
        for profile in sorted(roster_profiles, key=lambda item: item.player_id)
    )
    rosters = tuple(RosterSnapshot(team.team_id, team.roster_order) for team in teams)
    contracts = tuple(
        PlayerContract(
            item.nba_player_id,
            next(team.team_id for team in teams if item.nba_player_id in team.roster_order),
            item.annual_salary,
            item.contract_years_remaining,
        )
        for item in resolutions
    )
    management = LeagueManagementState(season_year, rosters, (), contracts)
    cap_rules = cap_rules_for_salary_cap(contract_rules.salary_cap)
    team_ids = tuple(team.team_id for team in teams)
    maximum_team_payroll = max(
        (
            sum(item.annual_salary for item in contracts if item.team_id == team_id)
            for team_id in team_ids
        ),
        default=cap_rules.second_apron,
    )
    validate_management_state(
        management,
        contract_rules,
        maximum_payroll=max(cap_rules.second_apron, maximum_team_payroll),
    )
    rights = tuple(
        sorted(
            (
                BirdRights(
                    contract.team_id,
                    contract.player_id,
                    resolution_by_id[contract.player_id].bird_seasons,
                    contract.annual_salary,
                )
                for contract in contracts
            ),
            key=lambda item: (item.team_id, item.player_id),
        )
    )
    draft_assets = seed_future_draft_picks(
        DraftAssetLedger(),
        team_ids=team_ids,
        draft_years=tuple(range(season_year + 1, season_year + 8)),
        rounds=2,
    )
    state = NBAFranchiseState(
        league_id,
        management,
        players,
        draft_assets,
        teams,
        alignment,
        CapLedger(rights),
    )
    state_json = nba_franchise_state_to_json(state, contract_rules)
    age_source_ids = {item.nba_player_id for item in player_source.players if item.age is not None}
    salary_source_ids = {
        item.nba_player_id
        for item in player_source.players
        if item.annual_salary is not None
        and contract_rules.minimum_salary <= item.annual_salary <= contract_rules.maximum_salary
    }
    roster_set = set(roster_ids)
    total_minutes = math.fsum(target_by_id[item].minutes_per_game for item in roster_ids)
    salary_minutes = math.fsum(
        target_by_id[item].minutes_per_game for item in roster_ids if item in salary_source_ids
    )
    age_coverage = len(roster_set & age_source_ids) / len(roster_ids)
    salary_coverage = salary_minutes / total_minutes
    receipt = NBAManagerStateBuildReceipt(
        league_id,
        season_year,
        player_targets.target_id,
        player_source.dataset_id,
        player_source.source_sha256,
        hashlib.sha256(state_json.encode("utf-8")).hexdigest(),
        len(roster_ids),
        age_coverage,
        salary_coverage,
        age_coverage >= 0.95 and salary_coverage >= 0.90,
        tuple(item.nba_player_id for item in resolutions if item.age_source != "source"),
        tuple(item.nba_player_id for item in resolutions if item.salary_source != "source"),
        tuple(item.nba_player_id for item in resolutions if item.contract_source != "source"),
        tuple(item.nba_player_id for item in resolutions if item.bird_source != "source"),
    )
    return NBAManagerStateBuildResult(state, contract_rules, resolutions, receipt)


def _resolve_player(
    profile: PlayerProfile,
    age: int,
    source: NBAManagerPlayerSource | None,
    proxy_salary: int,
    rules: ContractRules,
) -> NBAManagerPlayerResolution:
    sourced_age = source is not None and source.age is not None
    raw_salary = source.annual_salary if source is not None else None
    salary = (
        raw_salary
        if raw_salary is not None and rules.minimum_salary <= raw_salary <= rules.maximum_salary
        else None
    )
    raw_term = source.contract_years_remaining if source is not None else None
    term = raw_term if raw_term is not None and raw_term <= rules.maximum_years else None
    tenure = source.team_tenure_seasons if source is not None else None
    return NBAManagerPlayerResolution(
        profile.player_id,
        age,
        "source" if sourced_age else f"proxy-role-median:{_role(profile)}",
        salary if salary is not None else proxy_salary,
        (
            "source"
            if salary is not None
            else f"proxy-invalid-source:{_role(profile)}"
            if raw_salary is not None
            else f"proxy-role-performance:{_role(profile)}"
        ),
        term if term is not None else 1,
        (
            "source"
            if term is not None
            else "proxy-invalid-source-one-year"
            if raw_term is not None
            else "proxy-one-year"
        ),
        tenure if tenure is not None else 1,
        "source" if tenure is not None else "proxy-non-bird",
    )


def _career_player(profile: PlayerProfile, resolution: NBAManagerPlayerResolution) -> CareerPlayer:
    upside = max(0, min(12, (28 - resolution.age) * 2))
    potential = AbilityRatings(
        **{
            item.name: min(100, cast(int, getattr(profile.abilities, item.name)) + upside)
            for item in fields(AbilityRatings)
        }
    )
    return CareerPlayer(
        profile,
        resolution.age,
        max(0, resolution.age - 19),
        DevelopmentTraits(),
        potential,
        CareerStatus.ACTIVE,
    )


def _proxy_salaries(
    profiles: tuple[PlayerProfile, ...],
    targets: NBAPlayerTargetSet,
    rules: ContractRules,
) -> dict[int, int]:
    target_by_id = {item.nba_player_id: item for item in targets.players}
    grouped: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for profile in profiles:
        target = target_by_id[profile.player_id]
        ability = sum(
            cast(int, getattr(profile.abilities, item.name)) for item in fields(AbilityRatings)
        ) / len(fields(AbilityRatings))
        performance = (
            0.45 * ability / 100
            + 0.25 * target.true_shooting_percentage
            + 0.20 * min(1.0, target.minutes_per_game / 36)
            + 0.10 * target.usage_rate
        )
        grouped[_role(profile)].append((performance, profile.player_id))
    salaries: dict[int, int] = {}
    span = max(
        0,
        min(
            rules.maximum_salary - rules.minimum_salary,
            rules.salary_cap // 5 - rules.minimum_salary,
        ),
    )
    for values in grouped.values():
        ordered = sorted(values, key=lambda item: (item[0], item[1]))
        denominator = max(1, len(ordered) - 1)
        for index, (_, player_id) in enumerate(ordered):
            percentile = index / denominator
            salaries[player_id] = rules.minimum_salary + round(span * percentile**2)
    return salaries


def _role(profile: PlayerProfile) -> str:
    return profile.nominal_role_tags[0] if profile.nominal_role_tags else profile.size_class.name


def _resolved_age(source: NBAManagerPlayerSource | None, peer_ages: list[int]) -> int:
    return source.age if source is not None and source.age is not None else round(median(peer_ages))


def _player_source_from_object(value: object) -> NBAManagerPlayerSource:
    raw = _mapping(value, "NBA manager player source")
    allowed = {
        "nba_player_id",
        "age",
        "annual_salary",
        "contract_years_remaining",
        "team_tenure_seasons",
    }
    if not set(raw) <= allowed or "nba_player_id" not in raw:
        raise NBAManagerStateError("NBA manager player source row is invalid")
    return NBAManagerPlayerSource(
        _integer(raw["nba_player_id"], "nba_player_id"),
        _optional_integer(raw.get("age"), "age"),
        _optional_integer(raw.get("annual_salary"), "annual_salary"),
        _optional_integer(raw.get("contract_years_remaining"), "contract_years_remaining"),
        _optional_integer(raw.get("team_tenure_seasons"), "team_tenure_seasons"),
    )


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise NBAManagerStateError(f"{label} must be an object")
    return cast(dict[str, Any], value)


def _integer(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise NBAManagerStateError(f"{label} must be an integer")
    return value


def _optional_integer(value: object, label: str) -> int | None:
    return None if value is None else _integer(value, label)


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NBAManagerStateError(f"{label} must be text")
    return value


def _valid_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
