"""White-box thirty-team manager draft execution."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from courtsim.career import (
    CareerPlayer,
    CareerStatus,
    DraftResult,
    DraftRules,
    apply_draft,
)
from courtsim.management import ContractRules, LeagueManagementState
from courtsim.manager_ai import (
    DraftShadowResult,
    ManagerProfile,
    generate_draft_shadow,
)
from courtsim.nba_draft_lottery import NBADraftAssetSettlement
from courtsim.scouting import (
    ScoutingReport,
    ScoutingRules,
    generate_scouting_reports,
)

NBA_DRAFT_OFFSEASON_VERSION = "nba-draft-offseason-v1"


@dataclass(frozen=True, slots=True)
class NBAManagerDraftExecution:
    asset_settlement: NBADraftAssetSettlement
    scouting_reports: tuple[ScoutingReport, ...]
    shadow: DraftShadowResult
    draft: DraftResult
    version: str = NBA_DRAFT_OFFSEASON_VERSION

    def __post_init__(self) -> None:
        if self.version != NBA_DRAFT_OFFSEASON_VERSION:
            raise ValueError("unsupported NBA manager draft execution version")
        if self.shadow.plan.selections != self.draft.selections:
            raise ValueError("NBA executed draft differs from white-box manager plan")


def execute_nba_manager_draft(
    *,
    management: LeagueManagementState,
    players: tuple[CareerPlayer, ...],
    asset_settlement: NBADraftAssetSettlement,
    profiles: Mapping[str, ManagerProfile],
    contract_rules: ContractRules,
    draft_rules: DraftRules,
    master_seed: int,
    exposures: Mapping[tuple[str, int], int] | None = None,
    scouting_rules: ScoutingRules | None = None,
    maximum_payroll: int | None = None,
) -> NBAManagerDraftExecution:
    team_ids = tuple(roster.team_id for roster in management.rosters)
    if len(team_ids) != 30 or team_ids != tuple(sorted(set(team_ids))):
        raise ValueError("NBA manager draft requires thirty ordered teams")
    if set(profiles) != set(team_ids):
        raise ValueError("NBA manager draft requires one profile per team")
    picks = asset_settlement.assets.picks
    if (
        len(picks) != 30
        or tuple(pick.selection_number for pick in picks) != tuple(range(1, 31))
        or any(pick.round_number != 1 for pick in picks)
    ):
        raise ValueError("NBA manager draft requires one contiguous first-round pick per team")
    prospects = tuple(player for player in players if player.status is CareerStatus.PROSPECT)
    if len(prospects) < len(picks):
        raise ValueError("NBA manager draft requires at least one prospect per pick")
    reports = generate_scouting_reports(
        prospects=prospects,
        scouts={team_id: profiles[team_id].manager_id for team_id in team_ids},
        master_seed=master_seed,
        exposures=exposures,
        rules=scouting_rules,
    )
    shadow = generate_draft_shadow(
        management=management,
        players=players,
        picks=picks,
        profiles=profiles,
        contract_rules=contract_rules,
        rookie_salary=draft_rules.rookie_salary,
        scouted_potential={
            (report.team_id, report.player_id): report.estimated_potential for report in reports
        },
    )
    draft = apply_draft(
        management,
        players,
        picks,
        shadow.plan,
        season_year=management.season_year,
        contract_rules=contract_rules,
        draft_rules=draft_rules,
        maximum_payroll=maximum_payroll,
    )
    return NBAManagerDraftExecution(
        asset_settlement,
        reports,
        shadow,
        draft,
    )
