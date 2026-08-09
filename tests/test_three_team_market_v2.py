from dataclasses import replace

import pytest
from test_phase19_three_team_trades import circular_offer, future_picks, rules, state

from courtsim.three_team_market_v2 import (
    ContractConditionKind,
    ThreeTeamContractCondition,
    ThreeTeamContractNegotiationNode,
    ThreeTeamContractNegotiationTree,
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


@pytest.mark.parametrize(
    ("condition", "message"),
    [
        (
            ThreeTeamContractCondition,
            "positive integers",
        ),
    ],
)
def test_v2_condition_contract_is_strict(condition: object, message: str) -> None:
    assert condition is ThreeTeamContractCondition
    with pytest.raises(ValueError, match=message):
        ThreeTeamContractCondition(0, 1, "A", ContractConditionKind.MAXIMUM_ANNUAL_SALARY, 1)
    with pytest.raises(ValueError, match="beneficiary"):
        ThreeTeamContractCondition(1, 1, "", ContractConditionKind.MAXIMUM_ANNUAL_SALARY, 1)
    with pytest.raises(ValueError, match="unsupported"):
        ThreeTeamContractCondition(1, 1, "A", 99, 1)  # type: ignore[arg-type]


def test_v2_node_and_tree_contracts_reject_corrupt_graphs() -> None:
    accepted = ThreeTeamContractNegotiationNode(1, None, 0, (), "accepted", ())
    invalid_nodes = (
        ((0, None, 0, (), "accepted", ()), "identity"),
        ((2, 2, 1, (), "accepted", ()), "parent must precede"),
        ((2, 1, 1, (2, 1), "accepted", ()), "canonical"),
        ((2, 1, 1, (), "pending", ()), "status is invalid"),
        ((2, 1, 1, (), "accepted", ("failed",)), "no rejections"),
    )
    for arguments, message in invalid_nodes:
        with pytest.raises(ValueError, match=message):
            ThreeTeamContractNegotiationNode(*arguments)

    base = ThreeTeamContractNegotiationTree(1, ("A", "B", "C"), (), (), (accepted,))
    with pytest.raises(ValueError, match="version or rounds"):
        replace(base, version="old")
    with pytest.raises(ValueError, match="ordered and unique"):
        duplicate = _conditions()[0]
        replace(base, conditions=(duplicate, duplicate))
    with pytest.raises(ValueError, match="contiguous"):
        replace(base, nodes=())
    with pytest.raises(ValueError, match="root is invalid"):
        replace(
            base,
            nodes=(ThreeTeamContractNegotiationNode(1, None, 1, (), "accepted", ()),),
        )
    orphan = ThreeTeamContractNegotiationNode(2, 1, 1, (), "accepted", ())
    with pytest.raises(ValueError, match="contiguous"):
        replace(base, nodes=(accepted, replace(orphan, node_id=3)))


def test_v2_builder_rejects_round_order_duplicate_count_and_missing_contract() -> None:
    offer = circular_offer()
    with pytest.raises(ValueError, match="one through eight"):
        build_three_team_contract_negotiation_tree(offer, state(), (), maximum_rounds=0)
    conditions = _conditions()
    with pytest.raises(ValueError, match="conditions must be ordered"):
        build_three_team_contract_negotiation_tree(offer, state(), tuple(reversed(conditions)))
    with pytest.raises(ValueError, match="ids must be unique"):
        build_three_team_contract_negotiation_tree(
            offer, state(), (conditions[0], replace(conditions[1], condition_id=1))
        )
    too_many = tuple(
        replace(conditions[2], condition_id=index, threshold=10_000_000) for index in range(1, 10)
    )
    with pytest.raises(ValueError, match="at most eight"):
        build_three_team_contract_negotiation_tree(offer, state(), too_many)
    missing = replace(conditions[0], player_id=999)
    missing_offer = replace(
        offer,
        player_routes=(replace(offer.player_routes[0], player_id=999), *offer.player_routes[1:]),
    )
    with pytest.raises(ValueError, match="missing player contract"):
        build_three_team_contract_negotiation_tree(missing_offer, state(), (missing,))


def test_v2_execution_rejects_offer_and_post_acceptance_contract_drift() -> None:
    offer = circular_offer()
    management = state()
    tree = build_three_team_contract_negotiation_tree(offer, management, _conditions())
    accepted = next(item for item in tree.nodes if item.status == "accepted")
    with pytest.raises(ValueError, match="differs from offer"):
        execute_three_team_contract_negotiation(
            tree, accepted.node_id, management, (), replace(offer, trade_id=999), rules()
        )

    drifted_contracts = tuple(
        replace(contract, annual_salary=10_000_000) if contract.player_id == 21 else contract
        for contract in management.contracts
    )
    with pytest.raises(ValueError, match="no longer match"):
        execute_three_team_contract_negotiation(
            tree,
            accepted.node_id,
            replace(management, contracts=drifted_contracts),
            (),
            offer,
            rules(),
        )


def test_v2_execution_revalidates_frozen_draft_assets() -> None:
    offer = circular_offer(with_picks=True)
    tree = build_three_team_contract_negotiation_tree(offer, state(), _conditions())
    accepted = next(item for item in tree.nodes if item.status == "accepted")
    with pytest.raises(ValueError, match="frozen"):
        execute_three_team_contract_negotiation(
            tree,
            accepted.node_id,
            state(),
            future_picks(),
            offer,
            rules(),
            frozen_pick_ids=frozenset({101}),
        )
