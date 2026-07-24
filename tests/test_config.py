import tempfile
import unittest
from pathlib import Path

from courtsim.config import ConfigError, load_scenario, parse_scenario


class ConfigTests(unittest.TestCase):
    @staticmethod
    def valid_raw() -> dict[str, object]:
        return {
            "schema_version": 1,
            "name": "test",
            "court": {"zones": ["top", "rim"]},
            "engine": {"min_action_budget": 1, "max_action_budget": 4},
        }

    def test_valid_config(self) -> None:
        config = parse_scenario(self.valid_raw())
        self.assertEqual(config.zones, ("top", "rim"))

    def test_duplicate_zone_is_rejected(self) -> None:
        raw = self.valid_raw()
        raw["court"] = {"zones": ["rim", "rim"]}
        with self.assertRaisesRegex(ConfigError, "unique"):
            parse_scenario(raw)

    def test_unknown_key_is_rejected(self) -> None:
        raw = self.valid_raw()
        raw["typo"] = True
        with self.assertRaisesRegex(ConfigError, "unknown"):
            parse_scenario(raw)

    def test_invalid_root_and_version_are_rejected(self) -> None:
        with self.assertRaisesRegex(ConfigError, "root"):
            parse_scenario([])
        raw = self.valid_raw()
        raw["schema_version"] = 2
        with self.assertRaisesRegex(ConfigError, "version 1"):
            parse_scenario(raw)

    def test_invalid_fields_are_rejected(self) -> None:
        mutations: tuple[tuple[str, object], ...] = (
            ("name", ""),
            ("court", []),
            ("court", {"zones": []}),
            ("court", {"zones": [""]}),
            ("engine", []),
            ("engine", {"min_action_budget": True, "max_action_budget": 2}),
            ("engine", {"min_action_budget": 3, "max_action_budget": 2}),
        )
        for field, value in mutations:
            with self.subTest(field=field, value=value):
                raw = self.valid_raw()
                raw[field] = value
                with self.assertRaises(ConfigError):
                    parse_scenario(raw)

    def test_load_scenario_reports_io_and_json_errors(self) -> None:
        with self.assertRaisesRegex(ConfigError, "cannot read"):
            load_scenario(Path("definitely-missing-scenario.json"))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid.json"
            path.write_text("{", encoding="utf-8")
            with self.assertRaisesRegex(ConfigError, "invalid.json"):
                load_scenario(path)


if __name__ == "__main__":
    unittest.main()
