"""Complete deterministic thirty-team manager offseason."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import astuple, dataclass, replace

from courtsim.cap_mechanics import CapLedger, CapMechanicsRules
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
    MarketAction,
    MarketActionKind,
    MarketPlan,
    advance_contract_year,
    apply_market_plan,
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
    cap_ledger: CapLedger | None = None,
    cap_rules: CapMechanicsRules | None = None,
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
    maximum_payroll = cap_rules.second_apron if cap_rules is not None else None
    contract_year = advance_contract_year(
        after_retirement,
        contract_rules,
        maximum_payroll=maximum_payroll,
    )
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
        maximum_payroll=maximum_payroll,
    )
    market_shadow = generate_market_shadow(
        management=draft_preview.final_management,
        players=draft_preview.final_players,
        profiles=profiles,
        contract_rules=contract_rules,
    )
    market_shadow = replace(
        market_shadow,
        plan=_ensure_minimum_rosters(
            draft_preview.final_management,
            draft_preview.final_players,
            contract_rules,
            market_shadow.plan,
            cap_ledger=cap_ledger,
            cap_rules=cap_rules,
        ),
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
        cap_ledger=cap_ledger,
        cap_rules=cap_rules,
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


def _ensure_minimum_rosters(
    management: LeagueManagementState,
    players: tuple[CareerPlayer, ...],
    rules: ContractRules,
    plan: MarketPlan,
    *,
    cap_ledger: CapLedger | None,
    cap_rules: CapMechanicsRules | None,
    minimum_players: int = 5,
) -> MarketPlan:
    """Append deterministic minimum-salary signings until every team can play."""
    preview = apply_market_plan(
        management,
        plan,
        rules,
        cap_ledger=cap_ledger,
        cap_rules=cap_rules,
    ).final_state
    actions = list(plan.actions)
    player_map = {player.player_id: player for player in players}
    next_action_id = max((action.action_id for action in actions), default=0) + 1
    for roster in preview.rosters:
        current = next(item for item in preview.rosters if item.team_id == roster.team_id)
        while len(current.player_ids) < minimum_players:
            candidates = sorted(
                (
                    player_map[player_id]
                    for player_id in preview.free_agent_ids
                    if player_id in player_map
                    and player_map[player_id].status is CareerStatus.FREE_AGENT
                ),
                key=lambda player: (-sum(astuple(player.profile.abilities)), player.player_id),
            )
            selected_action: MarketAction | None = None
            selected_preview: LeagueManagementState | None = None
            for candidate in candidates:
                action = MarketAction(
                    next_action_id,
                    MarketActionKind.SIGN,
                    candidate.player_id,
                    roster.team_id,
                    rules.minimum_salary,
                    1,
                )
                try:
                    trial = apply_market_plan(
                        preview,
                        MarketPlan((action,)),
                        rules,
                        cap_ledger=cap_ledger,
                        cap_rules=cap_rules,
                    ).final_state
                except ValueError:
                    continue
                selected_action = action
                selected_preview = trial
                break
            if selected_action is None or selected_preview is None:
                raise ValueError(
                    f"free-agent pool cannot restore a playable NBA roster: {roster.team_id}"
                )
            actions.append(selected_action)
            next_action_id += 1
            preview = selected_preview
            current = next(item for item in preview.rosters if item.team_id == roster.team_id)
    return MarketPlan(tuple(actions))


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
