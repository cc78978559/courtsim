import hashlib
import json
from dataclasses import replace

from test_phase19_three_team_trades import circular_offer, state

from courtsim.draft_assets import (
    DraftAssetLedger,
    draft_asset_ledger_to_dict,
    seed_future_draft_picks,
)
from courtsim.draft_obligations import (
    build_draft_obligation_ledger_v3,
    draft_obligation_ledger_v3_from_dict,
    draft_obligation_ledger_v3_to_dict,
    inspect_draft_obligation_ledger_v3,
)
from courtsim.three_team_market_v2 import (
    ContractConditionKind,
    ThreeTeamContractCondition,
    build_three_team_contract_negotiation_tree,
    inspect_three_team_contract_negotiation,
)


def _asset_hash(assets: DraftAssetLedger) -> str:
    payload = json.dumps(
        draft_asset_ledger_to_dict(assets),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_obligation_freezes_remain_auditable_across_three_seasons() -> None:
    assets = seed_future_draft_picks(
        DraftAssetLedger(),
        team_ids=("A", "B"),
        draft_years=tuple(range(2029, 2038)),
        rounds=1,
    )
    outgoing = next(
        pick for pick in assets.picks if pick.original_team_id == "A" and pick.draft_year == 2031
    )
    assets = replace(
        assets,
        picks=tuple(
            replace(pick, owner_team_id="B", protected_top_n=4, deferrals_remaining=2)
            if pick.asset_id == outgoing.asset_id
            else pick
            for pick in assets.picks
        ),
    )
    audits = []
    for year in (2029, 2030, 2031):
        digest = _asset_hash(assets)
        ledger = build_draft_obligation_ledger_v3(
            assets,
            as_of_year=year,
            source_asset_sha256=digest,
        )
        restored = draft_obligation_ledger_v3_from_dict(draft_obligation_ledger_v3_to_dict(ledger))
        assert restored == ledger
        audits.append(
            inspect_draft_obligation_ledger_v3(
                ledger,
                assets,
                actual_asset_sha256=digest,
            )
        )
    assert all(audit["source_verified"] is True for audit in audits)
    assert all(audit["blocked_trade_assets"] for audit in audits)


def test_contract_condition_tree_rebuilds_from_each_seasons_contract_ledger() -> None:
    initial = state()
    condition = ThreeTeamContractCondition(
        1,
        1,
        "B",
        ContractConditionKind.MINIMUM_YEARS_REMAINING,
        3,
    )
    audits = []
    for season_offset, years_remaining in enumerate((4, 3, 2)):
        management = replace(
            initial,
            season_year=initial.season_year + season_offset,
            contracts=tuple(
                replace(contract, years_remaining=years_remaining) for contract in initial.contracts
            ),
        )
        tree = build_three_team_contract_negotiation_tree(
            circular_offer(),
            management,
            (condition,),
            maximum_rounds=4,
        )
        audits.append(inspect_three_team_contract_negotiation(tree))
    assert audits[0]["accepted_nodes"] == [1]
    assert audits[1]["accepted_nodes"] == [1]
    assert audits[2]["accepted_nodes"]
    assert audits[2]["accepted_nodes"] != [1]
    assert all(audit["tree_complete"] is True for audit in audits)
