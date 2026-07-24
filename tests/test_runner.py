import json
import tempfile
import unittest
from pathlib import Path

from courtsim.artifacts import sha256_file
from courtsim.config import load_scenario
from courtsim.demo import FoundationDemoSimulator
from courtsim.runner import planned_run_seeds, run_batch_to_directory, run_to_directory
from courtsim.verification import verify_manifest

ROOT = Path(__file__).resolve().parents[1]
SCENARIO = ROOT / "examples" / "minimal_scenario.json"


class RunnerTests(unittest.TestCase):
    def test_invalid_batch_arguments_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "runs"):
            planned_run_seeds(1, 0)
        config = load_scenario(SCENARIO)
        with self.assertRaisesRegex(ValueError, "workers"):
            run_batch_to_directory(
                FoundationDemoSimulator(config),
                master_seed=1,
                runs=1,
                workers=0,
                scenario_path=SCENARIO,
                output_directory="unused",
            )

    def test_batch_seed_plan_is_stable_and_unique(self) -> None:
        seeds = planned_run_seeds(456, 4)
        self.assertEqual(seeds, planned_run_seeds(456, 4))
        self.assertEqual(len(seeds), len(set(seeds)))

    def test_same_seed_produces_identical_artifacts(self) -> None:
        config = load_scenario(SCENARIO)
        simulator = FoundationDemoSimulator(config, possessions=20)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_to_directory(
                simulator, seed=123, scenario_path=SCENARIO, output_directory=root / "a"
            )
            run_to_directory(
                simulator, seed=123, scenario_path=SCENARIO, output_directory=root / "b"
            )
            self.assertEqual(
                sha256_file(root / "a" / "events.jsonl"), sha256_file(root / "b" / "events.jsonl")
            )
            self.assertEqual(
                sha256_file(root / "a" / "summary.json"), sha256_file(root / "b" / "summary.json")
            )

    def test_manifest_hashes_match_outputs(self) -> None:
        config = load_scenario(SCENARIO)
        simulator = FoundationDemoSimulator(config)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manifest_path = run_to_directory(
                simulator, seed=123, scenario_path=SCENARIO, output_directory=root
            )
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            for output in manifest["outputs"]:
                self.assertEqual(output["sha256"], sha256_file(root / output["path"]))
            report = verify_manifest(manifest_path)
            self.assertTrue(report.ok, report.issues)

    def test_batch_manifest_tracks_every_run(self) -> None:
        config = load_scenario(SCENARIO)
        simulator = FoundationDemoSimulator(config, possessions=2)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch_path = run_batch_to_directory(
                simulator,
                master_seed=789,
                runs=3,
                workers=1,
                scenario_path=SCENARIO,
                output_directory=root,
            )
            batch = json.loads(batch_path.read_text(encoding="utf-8"))
            self.assertEqual(len(batch["runs"]), 3)
            for run in batch["runs"]:
                self.assertEqual(run["manifest_sha256"], sha256_file(root / run["manifest"]))


if __name__ == "__main__":
    unittest.main()
