"""Complete deterministic thirty-team manager offseason."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

from courtsim.career import (
    CareerPlayer,
    CareerRules,
    CareerStatus,
    DraftRules,
    OffseasonResult,
    PlayerSeasonSummary,
    advance_careers,
    advance_offseason,
    apply_draft,
)
from courtsim.draft_assets import DraftAssetLedger, seed_future_draft_picks
from courtsim.management import (
    ContractRules,
    LeagueManagementState,
    advance_contract_year,
)
from courtsim.manager_ai import (
    DraftShadowResult,
    ManagerProfile,
    MarketShadowResult,
    generate_draft_shadow,
    generate_market_shadow,
)
from courtsim.nba_draft_lottery import NBADraftAssetSettlement
from courtsim.rosters import RosterSnapshot
from courtsim.scouting import ScoutingReport, ScoutingRules, generate_scouting_reports

NBA_OFFSEASON_VERSION = "nba-offseason-v1"


@dataclass(frozen=True, slots=True)
class NBAOffseasonExecution:
    scouting_reports: tuple[ScoutingReport, ...]
    draft_shadow: DraftShadowResult
    market_shadow: MarketShadowResult
    offseason: OffseasonResult
    final_draft_assets: DraftAssetLedger
    version: str = NBA_OFFSEASON_VERSION

    def __post_init__(self) -> None:
        if self.version != NBA_OFFSEASON_VERSION:
            raise ValueError("unsupported NBA offseason version")
        if self.draft_shadow.plan.selections != self.offseason.selections:
            raise ValueError("NBA offseason draft execution differs from manager plan")
        if self.market_shadow.plan.actions != self.offseason.market_actions:
            raise ValueError("NBA offseason market execution differs from manager plan")
        if any(
            pick.draft_year <= self.offseason.final_management.season_year
            for pick in self.final_draft_assets.picks
        ):
            raise ValueError("NBA offseason final draft ledger contains an expired pick")


def execute_nba_offseason(
    *,
    management: LeagueManagementState,
    players: tuple[CareerPlayer, ...],
    summaries: tuple[PlayerSeasonSummary, ...],
    asset_settlement: NBADraftAssetSettlement,
    profiles: Mapping[str, ManagerProfile],
    contract_rules: ContractRules,
    draft_rules: DraftRules,
    master_seed: int,
    career_rules: CareerRules | None = None,
    scouting_rules: ScoutingRules | None = None,
    exposures: Mapping[tuple[str, int], int] | None = None,
    future_pick_horizon: int = 3,
) -> NBAOffseasonExecution:
    active_career_rules = career_rules or CareerRules()
    team_ids = tuple(roster.team_id for roster in management.rosters)
    if len(team_ids) != 30 or team_ids != tuple(sorted(set(team_ids))):
        raise ValueError("NBA offseason requires thirty ordered teams")
    if set(profiles) != set(team_ids):
        raise ValueError("NBA offseason requires one manager profile per team")
    draft_year = management.season_year + 1
    if asset_settlement.assets.draft_year != draft_year:
        raise ValueError("NBA offseason draft assets must target the next season")
    if (
        not isinstance(future_pick_horizon, int)
        or isinstance(future_pick_horizon, bool)
        or future_pick_horizon < 1
    ):
        raise ValueError("future_pick_horizon must be a positive integer")

    transition = advance_careers(
        players,
        summaries,
        season_year=management.season_year,
        master_seed=master_seed,
        rules=active_career_rules,
    )
    retired = set(transition.retired_player_ids)
    after_retirement = LeagueManagementState(
        management.season_year,
        tuple(
            RosterSnapshot(
                roster.team_id,
                tuple(player_id for player_id in roster.player_ids if player_id not in retired),
            )
            for roster in management.rosters
        ),
        tuple(player_id for player_id in management.free_agent_ids if player_id not in retired),
        tuple(contract for contract in management.contracts if contract.player_id not in retired),
    )
    contract_year = advance_contract_year(after_retirement, contract_rules)
    preview_players = _sync_statuses(transition.final_players, contract_year.final_state)
    prospects = tuple(
        player for player in preview_players if player.status is CareerStatus.PROSPECT
    )
    reports = generate_scouting_reports(
        prospects=prospects,
        scouts={team_id: profiles[team_id].manager_id for team_id in team_ids},
        master_seed=master_seed,
        exposures=exposures,
        rules=scouting_rules,
    )
    draft_shadow = generate_draft_shadow(
        management=contract_year.final_state,
        players=preview_players,
        picks=asset_settlement.assets.picks,
        profiles=profiles,
        contract_rules=contract_rules,
        rookie_salary=draft_rules.rookie_salary,
        scouted_potential={
            (report.team_id, report.player_id): report.estimated_potential for report in reports
        },
    )
    draft_preview = apply_draft(
        contract_year.final_state,
        preview_players,
        asset_settlement.assets.picks,
        draft_shadow.plan,
        season_year=draft_year,
        contract_rules=contract_rules,
        draft_rules=draft_rules,
    )
    market_shadow = generate_market_shadow(
        management=draft_preview.final_management,
        players=draft_preview.final_players,
        profiles=profiles,
        contract_rules=contract_rules,
    )
    offseason = advance_offseason(
        season_year=management.season_year,
        master_seed=master_seed,
        management=management,
        players=players,
        summaries=summaries,
        picks=asset_settlement.assets.picks,
        draft_plan=draft_shadow.plan,
        market_plan=market_shadow.plan,
        career_rules=active_career_rules,
        contract_rules=contract_rules,
        draft_rules=draft_rules,
    )
    final_assets = seed_future_draft_picks(
        asset_settlement.assets.final_ledger,
        team_ids=team_ids,
        draft_years=tuple(range(draft_year + 1, draft_year + future_pick_horizon + 1)),
        rounds=draft_rules.rounds,
    )
    return NBAOffseasonExecution(
        reports,
        draft_shadow,
        market_shadow,
        offseason,
        final_assets,
    )


def _sync_statuses(
    players: tuple[CareerPlayer, ...],
    management: LeagueManagementState,
) -> tuple[CareerPlayer, ...]:
    active = {player_id for roster in management.rosters for player_id in roster.player_ids}
    free_agents = set(management.free_agent_ids)
    result = []
    for player in players:
        if player.status in {CareerStatus.PROSPECT, CareerStatus.RETIRED}:
            result.append(player)
        elif player.player_id in active:
            result.append(replace(player, status=CareerStatus.ACTIVE))
        elif player.player_id in free_agents:
            result.append(replace(player, status=CareerStatus.FREE_AGENT))
        else:
            raise ValueError("NBA offseason career player is absent from management state")
    return tuple(result)
