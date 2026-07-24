import json
from pathlib import Path

import pytest

from courtsim.analysis.performance import run_model_benchmark
from courtsim.domain.game import GameClockConfig
from courtsim.model import TraceMode
from courtsim.verification import verify_manifest

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "data" / "model_schema_demo_v1_3.json"
PARAMETERS = ROOT / "data" / "model_parameters_demo_0.4.0.json"
PROFILE = ROOT / "examples" / "player_profile_v1.json"


def test_benchmark_repeats_have_one_audit_hash_and_verified_manifests(
    tmp_path: Path,
) -> None:
    report_path = run_model_benchmark(
        schema_path=SCHEMA,
        parameters_path=PARAMETERS,
        profile_path=PROFILE,
        output_directory=tmp_path / "benchmark",
        master_seed=818,
        games=2,
        workers=1,
        repeats=2,
        warmups=0,
        clock=GameClockConfig(1, 20, 10),
        trace_mode=TraceMode.AGGREGATE_ONLY,
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["kind"] == "courtsim-model-performance-benchmark"
    assert report["configuration"]["trace_mode"] == "aggregate-only"
    assert report["summary"]["gate_passed"] is None
    assert report["summary"]["median_games_per_second"] > 0
    assert len({trial["audit_sha256"] for trial in report["trials"]}) == 1
    for trial in report["trials"]:
        manifest = report_path.parent / trial["manifest"]
        assert verify_manifest(manifest).ok
        assert not (manifest.parent / "games.jsonl").exists()


def test_benchmark_rejects_invalid_or_existing_run(tmp_path: Path) -> None:
    arguments = {
        "schema_path": SCHEMA,
        "parameters_path": PARAMETERS,
        "profile_path": PROFILE,
        "output_directory": tmp_path / "benchmark",
        "master_seed": 1,
        "games": 1,
        "workers": 1,
        "repeats": 1,
        "warmups": 0,
        "clock": GameClockConfig(1, 10, 10),
    }
    with pytest.raises(ValueError):
        run_model_benchmark(**{**arguments, "games": 0})  # type: ignore[arg-type]
    report = run_model_benchmark(**arguments)  # type: ignore[arg-type]
    assert report.is_file()
    with pytest.raises(ValueError, match="already exists"):
        run_model_benchmark(**arguments)  # type: ignore[arg-type]
