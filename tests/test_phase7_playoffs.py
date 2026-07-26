import json
from dataclasses import replace

import pytest

from courtsim.domain.serialization import SerializationError
from courtsim.playoffs import (
    PlayoffConfig,
    PlayoffGame,
    PlayoffResult,
    PlayoffSeed,
    audit_playoffs,
    playoff_result_from_json,
    playoff_result_to_json,
    resolve_playoffs,
)

CONFIG = PlayoffConfig(3, (True, False, True))
SEEDS = (
    PlayoffSeed(1, "A"),
    PlayoffSeed(2, "B"),
    PlayoffSeed(3, "C"),
    PlayoffSeed(4, "D"),
)


def game(
    round_number: int,
    series_index: int,
    game_number: int,
    home: str,
    away: str,
    winner: str,
) -> PlayoffGame:
    return PlayoffGame(
        round_number,
        series_index,
        game_number,
        home,
        away,
        100 if winner == home else 90,
        100 if winner == away else 90,
    )


def ledger() -> tuple[PlayoffGame, ...]:
    return (
        game(1, 1, 1, "A", "D", "A"),
        game(1, 1, 2, "D", "A", "A"),
        game(1, 2, 1, "B", "C", "C"),
        game(1, 2, 2, "C", "B", "B"),
        game(1, 2, 3, "B", "C", "B"),
        game(2, 1, 1, "A", "B", "B"),
        game(2, 1, 2, "B", "A", "A"),
        game(2, 1, 3, "A", "B", "A"),
    )


def result() -> PlayoffResult:
    return resolve_playoffs(seeds=SEEDS, games=ledger(), config=CONFIG)


def test_playoff_config_and_seed_contracts_are_strict() -> None:
    with pytest.raises(ValueError, match="best_of"):
        PlayoffConfig(2, (True, False))
    with pytest.raises(ValueError, match="one boolean"):
        PlayoffConfig(3, (True, False))
    with pytest.raises(ValueError, match="exactly four"):
        resolve_playoffs(seeds=SEEDS[:2], games=(), config=CONFIG)
    with pytest.raises(ValueError, match="contiguous"):
        resolve_playoffs(
            seeds=(SEEDS[0], replace(SEEDS[1], seed=3), SEEDS[2], SEEDS[3]),
            games=(),
            config=CONFIG,
        )


def test_bracket_resolves_series_advancement_and_champion() -> None:
    resolved = result()
    assert resolved.champion_team_id == "A"
    assert len(resolved.series) == 3
    assert resolved.series[0].winner_team_id == "A"
    assert resolved.series[1].winner_team_id == "B"
    assert resolved.series[2].higher_seed.team_id == "A"
    assert resolved.series[2].lower_seed.team_id == "B"
    assert resolved.series[2].higher_seed_wins == 2
    assert resolved.series[2].lower_seed_wins == 1


def test_home_pattern_is_applied_to_every_series() -> None:
    resolved = result()
    for series in resolved.series:
        for index, item in enumerate(series.games):
            expected_home = (
                series.higher_seed.team_id
                if CONFIG.higher_seed_home[index]
                else series.lower_seed.team_id
            )
            assert item.home_team_id == expected_home


def test_game_address_and_home_team_tampering_are_rejected() -> None:
    games = ledger()
    with pytest.raises(ValueError, match="address"):
        resolve_playoffs(
            seeds=SEEDS,
            games=(replace(games[0], game_number=2), *games[1:]),
            config=CONFIG,
        )
    with pytest.raises(ValueError, match="home/away"):
        resolve_playoffs(
            seeds=SEEDS,
            games=(
                replace(games[0], home_team_id="D", away_team_id="A"),
                *games[1:],
            ),
            config=CONFIG,
        )


def test_incomplete_and_post_championship_games_are_rejected() -> None:
    games = ledger()
    with pytest.raises(ValueError, match="ends before"):
        resolve_playoffs(seeds=SEEDS, games=games[:-1], config=CONFIG)
    with pytest.raises(ValueError, match="after the championship"):
        resolve_playoffs(
            seeds=SEEDS,
            games=(*games, replace(games[-1], game_number=4)),
            config=CONFIG,
        )


def test_playoff_audit_counts_sweeps_and_elimination_games() -> None:
    audit = audit_playoffs(result())
    assert audit.teams == 4
    assert audit.series_completed == 3
    assert audit.games_played == 8
    assert audit.sweeps == 1
    assert audit.elimination_games == 2
    assert audit.champion_team_id == "A"


def test_playoff_json_round_trip_and_champion_tamper_detection() -> None:
    resolved = result()
    payload = playoff_result_to_json(resolved)
    assert playoff_result_from_json(payload) == resolved
    raw = json.loads(payload)
    raw["champion_team_id"] = "B"
    with pytest.raises(SerializationError, match="champion"):
        playoff_result_from_json(json.dumps(raw))
    raw = json.loads(payload)
    raw["extra"] = True
    with pytest.raises(SerializationError, match="keys"):
        playoff_result_from_json(json.dumps(raw))


def test_playoff_game_rejects_ties_and_invalid_scores() -> None:
    with pytest.raises(ValueError, match="tie"):
        PlayoffGame(1, 1, 1, "A", "D", 90, 90)
    with pytest.raises(ValueError, match="non-negative"):
        PlayoffGame(1, 1, 1, "A", "D", -1, 90)
