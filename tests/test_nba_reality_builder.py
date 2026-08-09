from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, cast

import pytest

from courtsim.analysis import nba_reality
from courtsim.analysis.nba_reality import NbaRealityError, build_nba_reality_payload
from courtsim.artifacts import sha256_file


def _row(
    season: int,
    *,
    game_id: int,
    season_type: int,
    team_id: int,
    opponent_id: int,
    winner: bool,
    game_date: str,
) -> dict[str, object]:
    return {
        "game_id": game_id,
        "season": season,
        "season_type": season_type,
        "game_date": game_date,
        "team_id": team_id,
        "team_abbreviation": f"T{team_id:02d}",
        "team_score": 110 if winner else 100,
        "team_winner": winner,
        "opponent_team_id": opponent_id,
        "opponent_team_score": 100 if winner else 110,
        "field_goals_attempted": 85,
        "free_throws_attempted": 20,
        "offensive_rebounds": 10,
        "turnovers": 12,
    }


def _season_rows(season: int) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for team_id in range(1, 31):
        wins = 83 - team_id
        for game_index in range(82):
            rows.append(
                _row(
                    season,
                    game_id=season * 100_000 + team_id * 100 + game_index,
                    season_type=2,
                    team_id=team_id,
                    opponent_id=team_id % 30 + 1,
                    winner=game_index < wins,
                    game_date=f"{season - 1}-10-01",
                )
            )
    for series_index in range(1, 16):
        first = series_index
        second = 31 - series_index
        for game_index in range(4):
            game_id = season * 1_000_000 + series_index * 10 + game_index
            game_date = f"{season}-05-{16 - series_index:02d}"
            rows.extend(
                (
                    _row(
                        season,
                        game_id=game_id,
                        season_type=3,
                        team_id=first,
                        opponent_id=second,
                        winner=True,
                        game_date=game_date,
                    ),
                    _row(
                        season,
                        game_id=game_id,
                        season_type=3,
                        team_id=second,
                        opponent_id=first,
                        winner=False,
                        game_date=game_date,
                    ),
                )
            )
    return rows


class _FakeTable:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows

    def to_pylist(self) -> list[dict[str, object]]:
        return self._rows


class _FakeParquet:
    def __init__(self, rows: dict[str, list[dict[str, object]]]) -> None:
        self._rows = rows

    def read_table(self, source: Path, *, columns: list[str]) -> _FakeTable:
        assert columns == list(nba_reality._COLUMNS)
        return _FakeTable(self._rows[source.name])


def _manifest(tmp_path: Path) -> tuple[Path, Path, dict[str, list[dict[str, object]]]]:
    cache = tmp_path / "cache"
    cache.mkdir()
    rows: dict[str, list[dict[str, object]]] = {}
    resources = []
    for season in (2023, 2024, 2025):
        filename = f"season-{season}.parquet"
        source = cache / filename
        source.write_bytes(f"fixture-{season}".encode())
        rows[filename] = _season_rows(season)
        resources.append(
            {
                "filename": filename,
                "url": f"https://example.invalid/{filename}",
                "sha256": sha256_file(source),
                "excluded_non_standings_game_ids": [],
            }
        )
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "dataset_id": "fixture-reality",
                "reference_id": "fixture-reference",
                "source_label": "local fixture",
                "frozen_at": "2026-08-09",
                "resources": resources,
            }
        ),
        encoding="utf-8",
    )
    return manifest, cache, rows


def test_build_reality_payload_from_three_verified_resources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, cache, rows = _manifest(tmp_path)
    monkeypatch.setattr(
        importlib,
        "import_module",
        lambda name: _FakeParquet(rows) if name == "pyarrow.parquet" else None,
    )

    payload, reference = build_nba_reality_payload(manifest, cache)

    assert payload["dataset_id"] == "fixture-reality"
    seasons = payload["seasons"]
    assert isinstance(seasons, list)
    assert [item["season_id"] for item in seasons] == ["2022-23", "2023-24", "2024-25"]
    assert all(len(item["standings"]) == 30 for item in seasons)
    assert all(len(item["playoff_series"]) == 15 for item in seasons)
    assert all(item["champion_team_id"] == 1 for item in seasons)
    metric_rows = cast(list[dict[str, Any]], reference["metrics"])
    metrics = {item["metric"]: item for item in metric_rows}
    assert metrics["playoff-upset-rate"]["maximum"] <= 1.0
    assert metrics["champion-seed-mean"]["minimum"] == 1.0
    assert reference["observed_seasons"] == 3


def test_build_season_rejects_incomplete_or_inconsistent_inputs() -> None:
    rows = _season_rows(2025)
    with pytest.raises(NbaRealityError, match="one season"):
        nba_reality._build_season([*rows, {**rows[0], "season": 2024}], ())
    with pytest.raises(NbaRealityError, match="30 x 82"):
        nba_reality._build_season(
            [row for row in rows if row["team_id"] != 30 or row["season_type"] != 2], ()
        )
    with pytest.raises(NbaRealityError, match="15 playoff series"):
        nba_reality._build_season(
            [
                row
                for row in rows
                if not (
                    row["season_type"] == 3
                    and {row["team_id"], row["opponent_team_id"]} == {15, 16}
                )
            ],
            (),
        )
    broken_series = [dict(row) for row in rows]
    winner_rows = [row for row in broken_series if row["season_type"] == 3 and row["team_id"] == 1]
    winner_rows[0]["team_winner"] = False
    with pytest.raises(NbaRealityError, match="lacks four wins"):
        nba_reality._build_season(broken_series, ())


def test_manifest_and_source_validation_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, cache, rows = _manifest(tmp_path)
    fake = _FakeParquet(rows)
    monkeypatch.setattr(importlib, "import_module", lambda _name: fake)
    raw = json.loads(manifest.read_text(encoding="utf-8"))

    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
    with pytest.raises(NbaRealityError, match="manifest schema"):
        build_nba_reality_payload(invalid, cache)

    raw["resources"][0]["sha256"] = "0" * 64
    invalid.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(NbaRealityError, match="missing or unverified"):
        build_nba_reality_payload(invalid, cache)


def test_reality_requires_optional_parquet_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, cache, _rows = _manifest(tmp_path)

    def missing(_name: str) -> object:
        raise ImportError("missing")

    monkeypatch.setattr(importlib, "import_module", missing)
    with pytest.raises(NbaRealityError, match="bootstrap-data"):
        build_nba_reality_payload(manifest, cache)


@pytest.mark.parametrize(
    ("function", "value", "message"),
    [
        (nba_reality._object, [], "must be an object"),
        (nba_reality._integer, True, "must be an integer"),
        (nba_reality._number, float("inf"), "finite numeric"),
        (nba_reality._boolean, 1, "must be a boolean"),
        (nba_reality._text, " ", "non-empty text"),
        (nba_reality._sha256, "x" * 64, "is invalid"),
        (nba_reality._integer_tuple, "bad", "must be a list"),
        (nba_reality._integer_tuple, [2, 1], "ordered and unique"),
    ],
)
def test_reality_scalar_validation(function: Any, value: object, message: str) -> None:
    with pytest.raises(NbaRealityError, match=message):
        function(value, "field")
