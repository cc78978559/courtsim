import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

import courtsim.analysis.model_audit_runner as model_audit_runner
from courtsim.analysis import (
    AuditGate,
    AuditGateError,
    PlayerFoulShare,
    audit_game_results,
    audit_metric_map,
    compare_distribution_audits,
    distribution_audit_to_json,
    evaluate_audit_gates,
    load_audit_gates,
    load_distribution_audit,
    merge_batch_audit_shards,
    write_batch_audit_bundle,
)
from courtsim.analysis.model_audit_runner import (
    prepare_model_audit_context,
    run_model_audit_to_directory,
)
from courtsim.analysis.shard_merge import ShardMergeError
from courtsim.domain.game import GameClockConfig
from courtsim.domain.plans import Lineup, plan_ball_handler_id
from courtsim.domain.player import PlayerProfile
from courtsim.domain.player_serialization import player_profile_from_json
from courtsim.domain.results import (
    DefensiveRebound,
    NonShootingFoulSegmentResult,
)
from courtsim.model import (
    DefensiveMatchups,
    GameBatchSample,
    GameMatchups,
    GameTeam,
    Matchup,
    TraceMode,
    merge_game_batches,
    planned_game_seeds,
    sample_game_batch,
    sample_game_batch_indices,
)
from courtsim.model.interaction_compiler import ProfileLineup
from courtsim.parameters import load_model_parameters
from courtsim.randomness import RandomFrame, RandomFrameAddress
from courtsim.verification import verify_manifest

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "data" / "model_schema_demo_v1_3.json"
PARAMETER_FILE = ROOT / "data" / "model_parameters_demo_0.4.0.json"
PROFILE_FILE = ROOT / "examples" / "player_profile_v1.json"
PARAMETERS = load_model_parameters(SCHEMA, PARAMETER_FILE)
HOME_LINEUP: Lineup = (1, 2, 3, 4, 5)
AWAY_LINEUP: Lineup = (11, 12, 13, 14, 15)
CLOCK = GameClockConfig(2, 25, 10)


def player(player_id: int) -> PlayerProfile:
    template = player_profile_from_json(
        (ROOT / "examples" / "player_profile_v1.json").read_text(encoding="utf-8")
    )
    return replace(template, player_id=player_id, name=f"Player {player_id}")


def profiles(lineup: Lineup) -> ProfileLineup:
    return cast(ProfileLineup, tuple(player(player_id) for player_id in lineup))


HOME = GameTeam("home", HOME_LINEUP, profiles(HOME_LINEUP))
AWAY = GameTeam("away", AWAY_LINEUP, profiles(AWAY_LINEUP))
MATCHUPS = GameMatchups(
    DefensiveMatchups(
        (
            Matchup(1, 11),
            Matchup(2, 12),
            Matchup(3, 13),
            Matchup(4, 14),
            Matchup(5, 15),
        )
    ),
    DefensiveMatchups(
        (
            Matchup(11, 1),
            Matchup(12, 2),
            Matchup(13, 3),
            Matchup(14, 4),
            Matchup(15, 5),
        )
    ),
)
FRAME = RandomFrame(991, RandomFrameAddress("audit-tests", 0, 0, 0, 0))


def batch(indices: tuple[int, ...]) -> GameBatchSample:
    return sample_game_batch_indices(
        parameters=PARAMETERS,
        config=CLOCK,
        home=HOME,
        away=AWAY,
        matchups=MATCHUPS,
        frame=FRAME,
        game_indices=indices,
    )


def test_indexed_seeds_and_shard_merge_equal_a_monolithic_batch() -> None:
    whole = sample_game_batch(
        parameters=PARAMETERS,
        config=CLOCK,
        home=HOME,
        away=AWAY,
        matchups=MATCHUPS,
        frame=FRAME,
        games=6,
    )
    merged = merge_game_batches(batch((0, 2, 4)), batch((1, 3, 5)))
    assert merged == whole
    assert planned_game_seeds(991, 6) == whole.game_seeds

    with pytest.raises(ValueError):
        planned_game_seeds(1, 0)
    with pytest.raises(ValueError):
        sample_game_batch(
            parameters=PARAMETERS,
            config=CLOCK,
            home=HOME,
            away=AWAY,
            matchups=MATCHUPS,
            frame=FRAME,
            games=False,
        )
    with pytest.raises(ValueError):
        batch((1, 1))
    with pytest.raises(ValueError):
        merge_game_batches(batch((0,)), replace(batch((1,)), master_seed=2))


def test_distribution_metrics_obey_count_and_share_identities() -> None:
    sampled = batch((0, 1, 2, 3, 4, 5))
    audit = audit_game_results(tuple(game.result for game in sampled.games))
    assert audit.games == 6
    assert audit.completed_games == 6
    assert audit.aborted_games == 0
    assert audit.completed_possessions == 36
    assert audit.mean_team_possessions == 3.0
    assert sum(item.count for item in audit.shot_zone_shares) > 0
    assert sum(item.share for item in audit.shot_zone_shares) == pytest.approx(1.0)
    assert sum(item.share for item in audit.play_family_shares) == pytest.approx(1.0)
    assert sum(item.share for item in audit.coverage_shares) == pytest.approx(1.0)
    assert sum(item.share for item in audit.route_shares) == pytest.approx(1.0)
    assert sum(item.share for item in audit.creation_mode_shares) == pytest.approx(1.0)
    assert sum(item.share for item in audit.tactical_action_shares) == pytest.approx(1.0)
    for team_id in ("home", "away"):
        assert sum(
            item.share for item in audit.player_usage_shares if item.team_id == team_id
        ) == pytest.approx(1.0)
    assert {team.team_id for team in audit.team_metrics} == {"home", "away"}
    assert sum(team.possessions for team in audit.team_metrics) == 36
    for team in audit.team_metrics:
        assert sum(zone.share for zone in team.shot_zone_shares) == pytest.approx(1.0)
        assert sum(item.share for item in team.route_shares) == pytest.approx(1.0)
        assert sum(item.share for item in team.creation_mode_shares) == pytest.approx(1.0)
        assert sum(item.share for item in team.tactical_action_shares) == pytest.approx(1.0)
    metrics = audit_metric_map(audit)
    assert metrics["team.home.mean_team_possessions"] == pytest.approx(3.0)
    assert metrics["team.away.mean_team_possessions"] == pytest.approx(3.0)
    assert "route_share.INITIATOR_SELF" in metrics
    assert "creation_mode_share.SELF_CREATED" in metrics
    assert "tactical_action_share.ISOLATION_ATTACK" in metrics
    assert distribution_audit_to_json(audit) == distribution_audit_to_json(audit)

    with pytest.raises(ValueError):
        audit_game_results(())


def test_distribution_audit_accounts_for_bonus_non_shooting_fouls() -> None:
    game = batch((0,)).games[0].result
    record = game.possessions[0]
    source = record.result.segments[0]
    fouler_id = AWAY_LINEUP[0]
    offended_player_id = plan_ball_handler_id(source.plan)
    non_bonus = NonShootingFoulSegmentResult(
        source.plan,
        source.coverage,
        offended_player_id,
        fouler_id,
    )
    bonus = NonShootingFoulSegmentResult(
        source.plan,
        source.coverage,
        offended_player_id,
        fouler_id,
        (True, False),
        DefensiveRebound(fouler_id),
    )
    possession = replace(record.result, segments=(non_bonus, bonus))
    synthetic = replace(game, possessions=(replace(record, result=possession),))

    audit = audit_game_results((synthetic,))

    assert audit.free_throw_percentage == pytest.approx(0.5)
    assert audit.free_throw_attempt_rate == 0.0
    assert audit.offensive_rebound_rate == 0.0
    assert audit.non_shooting_foul_rate == 2.0
    assert audit.bonus_non_shooting_foul_rate == 1.0
    assert audit.defensive_foul_rate == 2.0
    assert sum(item.usage_events for item in audit.player_usage_shares) == 2
    assert audit.player_foul_shares == (PlayerFoulShare("away", fouler_id, 2, 1.0, 200.0),)


def test_audit_bundle_is_hash_verified_and_byte_stable(tmp_path: Path) -> None:
    sampled = batch((3, 4))
    first = write_batch_audit_bundle(
        batch=sampled,
        parameters=PARAMETERS,
        config=CLOCK,
        home=HOME,
        away=AWAY,
        output_directory=tmp_path / "first",
        schema_path=SCHEMA,
        parameters_path=PARAMETER_FILE,
        profile_path=PROFILE_FILE,
    )
    second = write_batch_audit_bundle(
        batch=sampled,
        parameters=PARAMETERS,
        config=CLOCK,
        home=HOME,
        away=AWAY,
        output_directory=tmp_path / "second",
        schema_path=SCHEMA,
        parameters_path=PARAMETER_FILE,
        profile_path=PROFILE_FILE,
    )
    assert verify_manifest(first).ok
    assert verify_manifest(second).ok
    assert (tmp_path / "first" / "games.jsonl").read_bytes() == (
        tmp_path / "second" / "games.jsonl"
    ).read_bytes()
    assert (tmp_path / "first" / "audit.json").read_bytes() == (
        tmp_path / "second" / "audit.json"
    ).read_bytes()
    manifest = json.loads(first.read_text(encoding="utf-8"))
    assert manifest["game_indices"] == [3, 4]
    assert manifest["model"]["parameter_hash"] == PARAMETERS.parameter_hash
    assert len(manifest["inputs"]) == 3
    assert manifest["inputs"][2]["sha256"] == hashlib.sha256(PROFILE_FILE.read_bytes()).hexdigest()


def test_checked_in_regression_baseline_matches_its_experiment_registry() -> None:
    experiment_paths = sorted(
        path
        for path in (ROOT / "experiments").glob("model-audit-demo-*.json")
        if not path.name.endswith("-regression-gates.json")
    )
    assert experiment_paths
    for experiment_path in experiment_paths:
        baseline_path = ROOT / "data" / "baselines" / experiment_path.name
        gates_path = experiment_path.with_name(f"{experiment_path.stem}-regression-gates.json")
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        experiment = json.loads(experiment_path.read_text(encoding="utf-8"))
        assert (
            hashlib.sha256(baseline_path.read_bytes()).hexdigest()
            == experiment["acceptance"]["audit_sha256"]
        )
        assert baseline["completed_games"] == experiment["acceptance"]["completed_games"]
        assert baseline["aborted_games"] == experiment["acceptance"]["aborted_games"]
        kind, gates = load_audit_gates(gates_path)
        assert evaluate_audit_gates(load_distribution_audit(baseline_path), kind, gates).passed
    assert (
        json.loads(
            (ROOT / "experiments" / "model-audit-demo-0.4.0.json").read_text(encoding="utf-8")
        )["model"]["parameter_hash"]
        == PARAMETERS.parameter_hash
    )


def test_baseline_difference_and_explicit_regression_gates() -> None:
    baseline_path = ROOT / "data" / "baselines" / "model-audit-demo-0.4.0.json"
    gates_path = ROOT / "experiments" / "model-audit-demo-0.4.0-regression-gates.json"
    baseline = load_distribution_audit(baseline_path)
    comparison = compare_distribution_audits(baseline, baseline)
    assert all(item.absolute_delta == 0.0 for item in comparison.differences)
    kind, gates = load_audit_gates(gates_path)
    report = evaluate_audit_gates(baseline, kind, gates)
    assert report.passed
    assert report.gate_kind == "regression-not-realism"

    failing = evaluate_audit_gates(
        baseline,
        kind,
        (AuditGate("points_per_100_possessions", 0.0, 100.0),),
    )
    assert not failing.passed
    assert failing.findings[0].metric == "points_per_100_possessions"
    with pytest.raises(AuditGateError):
        evaluate_audit_gates(baseline, kind, (AuditGate("unknown", 0.0, 1.0),))
    assert audit_metric_map(baseline)["shot_zone_share.THREE"] == pytest.approx(0.9045932603562996)

    common_foul_baseline = load_distribution_audit(
        ROOT / "data" / "baselines" / "model-audit-demo-0.8.0.json"
    )
    common_foul_kind, common_foul_gates = load_audit_gates(
        ROOT / "experiments" / "model-audit-demo-0.8.0-regression-gates.json"
    )
    assert evaluate_audit_gates(
        common_foul_baseline,
        common_foul_kind,
        common_foul_gates,
    ).passed
    assert audit_metric_map(common_foul_baseline)["non_shooting_foul_rate"] > 0.0

    instrumented = replace(
        baseline,
        player_foul_shares=(PlayerFoulShare("home", 1, 2, 1.0, 2.0),),
    )
    dynamic_comparison = compare_distribution_audits(baseline, instrumented)
    dynamic = next(
        item for item in dynamic_comparison.differences if item.metric == "player_foul_share.home.1"
    )
    assert dynamic.baseline == 0.0
    assert dynamic.current == 1.0
    assert dynamic.relative_delta is None


def test_verified_disk_shards_merge_to_monolithic_bytes(tmp_path: Path) -> None:
    def write(name: str, indices: tuple[int, ...]) -> Path:
        return write_batch_audit_bundle(
            batch=batch(indices),
            parameters=PARAMETERS,
            config=CLOCK,
            home=HOME,
            away=AWAY,
            output_directory=tmp_path / name,
            schema_path=SCHEMA,
            parameters_path=PARAMETER_FILE,
            profile_path=PROFILE_FILE,
        )

    shard_zero = write("shard-zero", (0, 1))
    shard_one = write("shard-one", (2, 3))
    write("whole", (0, 1, 2, 3))
    merged = merge_batch_audit_shards(
        shard_manifests=(shard_one, shard_zero),
        output_directory=tmp_path / "merged",
    )
    assert verify_manifest(merged).ok
    assert (tmp_path / "merged" / "games.jsonl").read_bytes() == (
        tmp_path / "whole" / "games.jsonl"
    ).read_bytes()
    assert (tmp_path / "merged" / "audit.json").read_bytes() == (
        tmp_path / "whole" / "audit.json"
    ).read_bytes()
    with pytest.raises(ShardMergeError, match="duplicate"):
        merge_batch_audit_shards(
            shard_manifests=(shard_zero, shard_zero),
            output_directory=tmp_path / "duplicate",
        )


def test_parallel_workers_produce_identical_canonical_artifacts(tmp_path: Path) -> None:
    def run(output: Path, workers: int) -> None:
        run_model_audit_to_directory(
            schema_path=SCHEMA,
            parameters_path=PARAMETER_FILE,
            profile_path=ROOT / "examples" / "player_profile_v1.json",
            master_seed=818,
            games=4,
            start_index=2,
            clock=GameClockConfig(1, 20, 10),
            output_directory=output,
            workers=workers,
        )

    run(tmp_path / "single", 1)
    run(tmp_path / "parallel", 2)
    assert (tmp_path / "single" / "games.jsonl").read_bytes() == (
        tmp_path / "parallel" / "games.jsonl"
    ).read_bytes()
    assert (tmp_path / "single" / "audit.json").read_bytes() == (
        tmp_path / "parallel" / "audit.json"
    ).read_bytes()


def test_parallel_worker_reuses_its_prepared_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(model_audit_runner, "_PARALLEL_CONTEXT", None)
    with pytest.raises(RuntimeError, match="not initialized"):
        model_audit_runner._parallel_game_job((CLOCK, 818, 2, TraceMode.FULL))

    model_audit_runner._initialize_parallel_worker(
        str(SCHEMA),
        str(PARAMETER_FILE),
        str(PROFILE_FILE),
    )
    prepared = model_audit_runner._PARALLEL_CONTEXT
    assert prepared is not None
    first = model_audit_runner._parallel_game_job((CLOCK, 818, 2, TraceMode.FULL))
    second = model_audit_runner._parallel_game_job((CLOCK, 818, 3, TraceMode.FULL))
    assert model_audit_runner._PARALLEL_CONTEXT is prepared
    assert first[0:2] != second[0:2]


def test_prepared_model_audit_context_loads_both_teams_once() -> None:
    context = prepare_model_audit_context(SCHEMA, PARAMETER_FILE, PROFILE_FILE)
    assert context.parameters.parameter_hash == PARAMETERS.parameter_hash
    assert context.home.lineup == HOME_LINEUP
    assert context.away.lineup == AWAY_LINEUP
    assert context.matchups == MATCHUPS


def test_aggregate_only_matches_full_audit_without_event_artifact(tmp_path: Path) -> None:
    def run(name: str, trace_mode: TraceMode) -> Path:
        return run_model_audit_to_directory(
            schema_path=SCHEMA,
            parameters_path=PARAMETER_FILE,
            profile_path=PROFILE_FILE,
            master_seed=919,
            games=4,
            start_index=0,
            clock=CLOCK,
            output_directory=tmp_path / name,
            workers=2,
            trace_mode=trace_mode,
        )

    run("full", TraceMode.FULL)
    aggregate_manifest = run("aggregate", TraceMode.AGGREGATE_ONLY)
    assert (tmp_path / "aggregate" / "audit.json").read_bytes() == (
        tmp_path / "full" / "audit.json"
    ).read_bytes()
    assert not (tmp_path / "aggregate" / "games.jsonl").exists()
    assert verify_manifest(aggregate_manifest).ok
    manifest = json.loads(aggregate_manifest.read_text(encoding="utf-8"))
    assert manifest["artifact_mode"] == "aggregate-only"
    assert [item["path"] for item in manifest["outputs"]] == ["audit.json"]
