import json
import math
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

import courtsim.analysis.nba_player_evaluation as evaluation_module
from courtsim.analysis.nba_player_evaluation import (
    NbaPlayerEvaluationError,
    aggregate_nba_player_evaluation_files,
    aggregate_nba_player_evaluations,
    audit_nba_player_results,
    build_nba_player_audit_from_bundle,
    evaluate_nba_player_audit,
    evaluate_nba_player_audit_files,
    load_courtsim_identity_map,
)
from courtsim.analysis.nba_player_targets import (
    NBAPlayerSourceReceipt,
    NBAPlayerTarget,
    NBAPlayerTargetSet,
    nba_player_target_set_to_dict,
)
from courtsim.artifacts import write_json
from courtsim.domain.enums import (
    ContestLevel,
    Coverage,
    FinisherRoute,
    GameEndReason,
    PossessionEndReason,
    ShotZone,
)
from courtsim.domain.game import GamePossessionRecord, GameResult, PlayerPlayingTime
from courtsim.domain.interaction import FinisherSelection
from courtsim.domain.plans import IsolationPlan
from courtsim.domain.results import (
    BlockedShotSegmentResult,
    DefensiveRebound,
    MadeShotSegmentResult,
    MissedShotSegmentResult,
    PossessionResult,
    ShootingFoulSegmentResult,
)
from courtsim.stats.attribution import PlayerStatDelta, StatCode


def _targets() -> NBAPlayerTargetSet:
    return NBAPlayerTargetSet(
        "players-v1",
        "2024-25",
        "fixture",
        1,
        1.0,
        (NBAPlayerSourceReceipt("box", "box.json", "a" * 64),),
        (
            NBAPlayerTarget(
                100,
                "Player",
                "A",
                1,
                48.0,
                0.2,
                0.6,
                0.25,
                (0.4, 0.2, 0.4),
                (0.7, 0.4, 0.38),
            ),
        ),
    )


def _result() -> GameResult:
    stats = [
        PlayerStatDelta(1, StatCode.FGA, 10),
        PlayerStatDelta(1, StatCode.FTA, 2),
        PlayerStatDelta(1, StatCode.TOV, 1),
        PlayerStatDelta(1, StatCode.PTS, 15),
        PlayerStatDelta(2, StatCode.FGA, 30),
        PlayerStatDelta(2, StatCode.FTA, 8),
        PlayerStatDelta(2, StatCode.TOV, 9),
    ]
    playing_time = [
        *(PlayerPlayingTime("A", player_id, 2880) for player_id in range(1, 6)),
        *(PlayerPlayingTime("B", player_id, 2880) for player_id in range(11, 16)),
    ]
    return GameResult(
        "A",
        "B",
        (),
        100,
        90,
        tuple(stats),
        GameEndReason.REGULATION,
        playing_time=tuple(playing_time),
    )


def test_player_audit_computes_minutes_usage_efficiency_and_share() -> None:
    audit = audit_nba_player_results((_result(),), _targets(), {100: 1})
    rows = cast(list[dict[str, Any]], audit["players"])
    row = rows[0]
    assert row["minutes_per_game"] == 48.0
    assert row["field_goal_attempt_share"] == 0.25
    assert row["true_shooting_percentage"] == pytest.approx(15 / (2 * 10.88))
    assert row["usage_rate"] == pytest.approx((10 + 0.44 * 2 + 1) / (40 + 0.44 * 10 + 10))
    assert row["shot_zone_shares"] == {"RIM": 0.0, "MIDRANGE": 0.0, "THREE": 0.0}


def test_player_evaluation_and_batch_pool_metric_errors() -> None:
    targets = _targets()
    audit = audit_nba_player_results((_result(),), targets, {100: 1})
    evaluation = evaluate_nba_player_audit(audit, targets)
    metrics = cast(list[dict[str, Any]], evaluation["metrics"])
    by_name = {item["metric"]: item for item in metrics}
    assert by_name["minutes_per_game"]["rmse"] == 0.0
    assert by_name["field_goal_attempt_share"]["rmse"] == 0.0
    batch = aggregate_nba_player_evaluations((evaluation, evaluation))
    assert batch["runs"] == 2
    pooled = cast(list[dict[str, Any]], batch["metrics"])
    assert {item["metric"] for item in pooled} == set(by_name)


def test_identity_loader_requires_explicit_courtsim_assignment(tmp_path: Path) -> None:
    identity = tmp_path / "identity.json"
    write_json(
        identity,
        {
            "version": "nba-player-identity-v1",
            "mappings": [{"nba_player_id": 100, "courtsim_player_id": None}],
        },
    )
    with pytest.raises(NbaPlayerEvaluationError, match="courtsim_player_id"):
        load_courtsim_identity_map(identity, _targets())


def test_player_audit_tracks_supported_shot_segments() -> None:
    selection = FinisherSelection(FinisherRoute.INITIATOR_SELF, 1)
    plan = IsolationPlan(1)
    segments = (
        MadeShotSegmentResult(plan, Coverage.BASE, selection, ShotZone.RIM, ContestLevel.NORMAL),
        MissedShotSegmentResult(
            plan,
            Coverage.BASE,
            selection,
            ShotZone.MIDRANGE,
            ContestLevel.HEAVY,
            DefensiveRebound(11),
        ),
        BlockedShotSegmentResult(
            plan, Coverage.BLITZ, selection, ShotZone.THREE, 11, DefensiveRebound(12)
        ),
        ShootingFoulSegmentResult(
            plan,
            Coverage.BASE,
            selection,
            ShotZone.RIM,
            ContestLevel.NORMAL,
            11,
            False,
            (True, False),
            DefensiveRebound(11),
        ),
        ShootingFoulSegmentResult(
            plan,
            Coverage.BASE,
            selection,
            ShotZone.RIM,
            ContestLevel.NORMAL,
            11,
            True,
            (True,),
            None,
        ),
    )
    possession = GamePossessionRecord(
        0,
        1,
        24,
        0,
        "A",
        "B",
        PossessionResult(segments, PossessionEndReason.MADE_SHOT),
    )
    audit = audit_nba_player_results(
        (replace(_result(), possessions=(possession,)),), _targets(), {100: 1}
    )
    row = cast(list[dict[str, Any]], audit["players"])[0]
    assert row["shot_zone_attempts"] == {"RIM": 2, "MIDRANGE": 1, "THREE": 1}
    assert row["shot_zone_percentages"] == {"RIM": 1.0, "MIDRANGE": 0.0, "THREE": 0.0}


def test_player_audit_rejects_incomplete_identity_trade_and_unassigned_stats() -> None:
    incomplete = replace(_result(), end_reason=GameEndReason.POSSESSION_TRUNCATED)
    with pytest.raises(NbaPlayerEvaluationError, match="completed games"):
        audit_nba_player_results((incomplete,), _targets(), {100: 1})
    with pytest.raises(NbaPlayerEvaluationError, match="exactly cover"):
        audit_nba_player_results((_result(),), _targets(), {})
    with pytest.raises(NbaPlayerEvaluationError, match="unique non-negative"):
        audit_nba_player_results((_result(),), _targets(), {100: True})
    with pytest.raises(NbaPlayerEvaluationError, match="playing-time team"):
        audit_nba_player_results((replace(_result(), playing_time=()),), _targets(), {100: 1})

    traded_time = tuple(
        replace(item, team_id="B") if item.player_id == 1 else item
        for item in _result().playing_time
    )
    with pytest.raises(NbaPlayerEvaluationError, match="in-batch trades"):
        audit_nba_player_results(
            (_result(), replace(_result(), playing_time=traded_time)), _targets(), {100: 1}
        )


def test_player_evaluation_rejects_identity_rows_and_batch_drift() -> None:
    targets = _targets()
    audit = audit_nba_player_results((_result(),), targets, {100: 1})
    with pytest.raises(NbaPlayerEvaluationError, match="identity differs"):
        evaluate_nba_player_audit({**audit, "season": "other"}, targets)
    with pytest.raises(NbaPlayerEvaluationError, match="rows are invalid"):
        evaluate_nba_player_audit({**audit, "players": {}}, targets)
    with pytest.raises(NbaPlayerEvaluationError, match="coverage differs"):
        evaluate_nba_player_audit({**audit, "players": []}, targets)

    evaluation = evaluate_nba_player_audit(audit, targets)
    with pytest.raises(NbaPlayerEvaluationError, match="must not be empty"):
        aggregate_nba_player_evaluations(())
    with pytest.raises(NbaPlayerEvaluationError, match="identity differs"):
        aggregate_nba_player_evaluations((evaluation, {**evaluation, "season": "other"}))
    with pytest.raises(NbaPlayerEvaluationError, match="metrics are invalid"):
        aggregate_nba_player_evaluations(({**evaluation, "metrics": {}},))
    with pytest.raises(NbaPlayerEvaluationError, match="metrics differ"):
        aggregate_nba_player_evaluations(({**evaluation, "metrics": []},))


def test_player_evaluation_file_adapters_round_trip(tmp_path: Path) -> None:
    targets = _targets()
    target_path = tmp_path / "targets.json"
    audit_path = tmp_path / "audit.json"
    evaluation_path = tmp_path / "evaluation.json"
    write_json(target_path, nba_player_target_set_to_dict(targets))
    write_json(audit_path, audit_nba_player_results((_result(),), targets, {100: 1}))
    evaluation = evaluate_nba_player_audit_files(audit_path, target_path)
    write_json(evaluation_path, evaluation)
    batch = aggregate_nba_player_evaluation_files((evaluation_path, evaluation_path))
    assert batch["runs"] == 2


def test_identity_loader_accepts_exact_map_and_rejects_artifact_drift(tmp_path: Path) -> None:
    identity = tmp_path / "identity.json"
    write_json(
        identity,
        {
            "version": "nba-player-identity-v1",
            "mappings": [{"nba_player_id": 100, "courtsim_player_id": 1}],
        },
    )
    assert load_courtsim_identity_map(identity, _targets()) == {100: 1}

    invalid_payloads = (
        ({"version": "old", "mappings": []}, "version differs"),
        ({"version": "nba-player-identity-v1", "mappings": {}}, "mappings are invalid"),
        (
            {
                "version": "nba-player-identity-v1",
                "mappings": [
                    {"nba_player_id": 100, "courtsim_player_id": 1},
                    {"nba_player_id": 100, "courtsim_player_id": 2},
                ],
            },
            "duplicate NBA ids",
        ),
        ({"version": "nba-player-identity-v1", "mappings": []}, "exactly cover"),
    )
    for payload, message in invalid_payloads:
        write_json(identity, payload)
        with pytest.raises(NbaPlayerEvaluationError, match=message):
            load_courtsim_identity_map(identity, _targets())

    identity.write_text("not-json", encoding="utf-8")
    with pytest.raises(NbaPlayerEvaluationError, match="cannot read"):
        load_courtsim_identity_map(identity, _targets())


def test_bundle_adapter_verifies_inputs_and_records_source_hashes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = tmp_path / "manifest.json"
    targets = tmp_path / "targets.json"
    identity = tmp_path / "identity.json"
    games = tmp_path / "games.jsonl"
    for path in (manifest, targets, identity, games):
        path.write_text("{}", encoding="utf-8")
    manifest_payload = {
        "kind": "courtsim-model-distribution-audit",
        "clock": {
            "regulation_periods": 4,
            "period_seconds": 720,
            "possession_seconds": 24,
            "overtime_enabled": False,
        },
        "outputs": [{"path": "games.jsonl"}],
    }
    monkeypatch.setattr(
        evaluation_module, "verify_manifest", lambda _path: SimpleNamespace(ok=True)
    )
    monkeypatch.setattr(
        evaluation_module, "_load_object_file", lambda _path, _label: manifest_payload
    )
    monkeypatch.setattr(evaluation_module, "load_nba_player_target_set", lambda _path: _targets())
    monkeypatch.setattr(evaluation_module, "load_courtsim_identity_map", lambda *_args: {100: 1})
    monkeypatch.setattr(evaluation_module, "_read_game_results", lambda *_args: (_result(),))
    report = build_nba_player_audit_from_bundle(manifest, targets, identity)
    assert set(cast(dict[str, object], report["sources"])) == {
        "manifest",
        "games",
        "targets",
        "identity",
    }

    monkeypatch.setattr(
        evaluation_module, "verify_manifest", lambda _path: SimpleNamespace(ok=False)
    )
    with pytest.raises(NbaPlayerEvaluationError, match="verification failed"):
        build_nba_player_audit_from_bundle(manifest, targets, identity)


def test_private_file_and_scalar_guards_are_strict(tmp_path: Path) -> None:
    with pytest.raises(NbaPlayerEvaluationError, match="must be an object"):
        evaluation_module._object([], "value")
    with pytest.raises(NbaPlayerEvaluationError, match="non-negative integer"):
        evaluation_module._integer(-1, "value")
    with pytest.raises(NbaPlayerEvaluationError, match="finite numeric"):
        evaluation_module._number(math.nan, "value")
    with pytest.raises(NbaPlayerEvaluationError, match="boolean"):
        evaluation_module._boolean(1, "value")

    manifest = tmp_path / "manifest.json"
    with pytest.raises(NbaPlayerEvaluationError, match="outputs are invalid"):
        evaluation_module._declared_games_path(manifest, {})
    with pytest.raises(NbaPlayerEvaluationError, match="full-trace"):
        evaluation_module._declared_games_path(manifest, [])
    with pytest.raises(NbaPlayerEvaluationError, match=r"games\.jsonl is missing"):
        evaluation_module._declared_games_path(manifest, [{"path": "games.jsonl"}])

    clock = evaluation_module._game_clock(
        {
            "regulation_periods": 4,
            "period_seconds": 720,
            "possession_seconds": 24,
            "overtime_enabled": False,
        }
    )
    empty = tmp_path / "empty.jsonl"
    empty.write_text("", encoding="utf-8")
    with pytest.raises(NbaPlayerEvaluationError, match="games are empty"):
        evaluation_module._read_game_results(empty, clock)
    invalid = tmp_path / "invalid.jsonl"
    invalid.write_text(json.dumps({"game_index": 0}), encoding="utf-8")
    with pytest.raises(NbaPlayerEvaluationError, match="line 1 is invalid"):
        evaluation_module._read_game_results(invalid, clock)
