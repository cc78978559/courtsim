from dataclasses import replace

from courtsim.draft_assets import (
    DraftAssetLedger,
    DraftPickSwapRight,
    seed_future_draft_picks,
)
from courtsim.nba_draft_lottery import (
    resolve_nba_draft_lottery,
    settle_nba_draft_assets,
)


def test_nba_lottery_settles_protection_rollover_and_swap_across_thirty_teams() -> None:
    non_playoff = tuple(f"L{index:02d}" for index in range(1, 15))
    playoff = tuple(f"P{index:02d}" for index in range(1, 17))
    teams = tuple(sorted((*non_playoff, *playoff)))
    lottery = resolve_nba_draft_lottery(
        draft_year=2029,
        master_seed=20260726,
        non_playoff_order=non_playoff,
        playoff_order=playoff,
    )
    ledger = seed_future_draft_picks(
        DraftAssetLedger(),
        team_ids=teams,
        draft_years=(2029, 2030),
        rounds=1,
    )
    protected_team = lottery.final_order[0]
    protected_pick = next(
        pick
        for pick in ledger.picks
        if pick.draft_year == 2029 and pick.original_team_id == protected_team
    )
    future_owner = next(team for team in teams if team != protected_team)
    controller = lottery.final_order[-1]
    target = lottery.final_order[1]
    ledger = replace(
        ledger,
        picks=tuple(
            replace(
                pick,
                owner_team_id=future_owner,
                protected_top_n=4,
                deferrals_remaining=1,
            )
            if pick.asset_id == protected_pick.asset_id
            else pick
            for pick in ledger.picks
        ),
        swaps=(
            DraftPickSwapRight(
                1,
                2029,
                1,
                controller,
                target,
            ),
        ),
    )
    result = settle_nba_draft_assets(ledger, lottery)
    assert len(result.assets.picks) == 30
    protected = next(
        pick for pick in result.assets.picks if pick.original_team_id == protected_team
    )
    assert protected.round_pick == 1
    assert protected.owner_team_id == protected_team
    assert result.assets.protected_asset_ids == (protected_pick.asset_id,)
    assert result.assets.rolled_asset_ids == (protected_pick.asset_id,)
    rolled = next(
        pick
        for pick in result.assets.final_ledger.picks
        if pick.draft_year == 2030 and pick.original_team_id == protected_team
    )
    assert rolled.owner_team_id == future_owner
    assert result.assets.exercised_swap_ids == (1,)
    target_pick = next(pick for pick in result.assets.picks if pick.original_team_id == target)
    assert target_pick.owner_team_id == controller
