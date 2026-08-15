from courtsim.mixed_trade_market import (
    MixedTradeCandidate,
    select_mixed_trade_candidates,
)


def candidate(
    source: str,
    trade_id: int,
    teams: tuple[str, ...],
    gain: float,
    *,
    player_id: int,
) -> MixedTradeCandidate:
    return MixedTradeCandidate(source, trade_id, teams, (player_id,), (), gain)


def test_mixed_clearing_keeps_nonconflicting_bilateral_and_three_team_trades() -> None:
    selected = select_mixed_trade_candidates(
        (
            candidate("bilateral", 1, ("A", "B"), 4.0, player_id=1),
            candidate("three-team", 2, ("C", "D", "E"), 3.0, player_id=2),
        )
    )
    assert {(item.source, item.trade_id) for item in selected} == {
        ("bilateral", 1),
        ("three-team", 2),
    }


def test_mixed_clearing_prefers_gain_and_locks_teams_and_assets() -> None:
    selected = select_mixed_trade_candidates(
        (
            candidate("bilateral", 1, ("A", "B"), 5.0, player_id=1),
            candidate("three-team", 2, ("B", "C", "D"), 4.0, player_id=2),
            candidate("three-team", 3, ("E", "F", "G"), 3.0, player_id=1),
        )
    )
    assert selected == (candidate("bilateral", 1, ("A", "B"), 5.0, player_id=1),)
