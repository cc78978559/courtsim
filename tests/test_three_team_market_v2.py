import pytest
from test_phase19_three_team_trades import circular_offer, rules, state

from courtsim.three_team_market_v2 import (
    ContractConditionKind,
    ThreeTeamContractCondition,
    build_three_team_contract_negotiation_tree,
    execute_three_team_contract_negotiation,
    inspect_three_team_contract_negotiation,
)


def _conditions() -> tuple[ThreeTeamContractCondition, ...]:
    return (
        ThreeTeamContractCondition(
            1,
            1,
            "B",
            ContractConditionKind.MAXIMUM_ANNUAL_SALARY,
            4_000_000,
        ),
        ThreeTeamContractCondition(
            2,
            11,
            "C",
            ContractConditionKind.MINIMUM_YEARS_REMAINING,
            3,
        ),
        ThreeTeamContractCondition(
            3,
            21,
            "A",
            ContractConditionKind.MAXIMUM_ANNUAL_SALARY,
            6_000_000,
        ),
    )


def test_v2_builds_complete_bounded_contract_condition_tree() -> None:
    tree = build_three_team_contract_negotiation_tree(
        circular_offer(),
        state(),
        _conditions(),
        maximum_rounds=4,
    )
    root = tree.nodes[0]
    assert root.status == "countered"
    assert root.rejections == (
        "condition:1:MAXIMUM_ANNUAL_SALARY",
        "condition:2:MINIMUM_YEARS_REMAINING",
    )
    accepted = [item for item in tree.nodes if item.status == "accepted"]
    assert accepted
    assert all(item.condition_ids == (3,) for item in accepted)
    audit = inspect_three_team_contract_negotiation(tree)
    assert audit["version"] == "three-team-market-v2"
    assert audit["tree_complete"] is True


def test_v2_executes_only_accepted_node_and_revalidates_native_trade() -> None:
    offer = circular_offer()
    tree = build_three_team_contract_negotiation_tree(offer, state(), _conditions())
    accepted = next(item for item in tree.nodes if item.status == "accepted")
    result = execute_three_team_contract_negotiation(
        tree,
        accepted.node_id,
        state(),
        (),
        offer,
        rules(),
    )
    assert result.offer == offer
    with pytest.raises(ValueError, match="accepted node"):
        execute_three_team_contract_negotiation(
            tree,
            tree.nodes[0].node_id,
            state(),
            (),
            offer,
            rules(),
        )


def test_v2_rejects_condition_for_wrong_destination() -> None:
    condition = ThreeTeamContractCondition(
        1,
        1,
        "C",
        ContractConditionKind.MAXIMUM_ANNUAL_SALARY,
        5_000_000,
    )
    with pytest.raises(ValueError, match="destination"):
        build_three_team_contract_negotiation_tree(circular_offer(), state(), (condition,))
