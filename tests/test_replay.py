import json
from pathlib import Path

import pytest

from courtsim.replay import ReplayError, replay_lines


def _write_records(path: Path, records: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")


def test_replay_can_filter_a_possession(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    _write_records(
        events,
        [
            {"sequence": 1, "possession": 0, "action": 0, "offense": "home", "kind": "start"},
            {"sequence": 2, "possession": 1, "action": 0, "offense": "away", "kind": "start"},
        ],
    )
    lines = replay_lines(events, possession=1)
    assert len(lines) == 1
    assert "P1" in lines[0]
    assert "away" in lines[0]


def test_replay_rejects_non_monotonic_sequence(tmp_path: Path) -> None:
    events = tmp_path / "events.jsonl"
    _write_records(
        events,
        [
            {"sequence": 2},
            {"sequence": 1},
        ],
    )
    with pytest.raises(ReplayError, match="strictly increasing"):
        tuple(replay_lines(events))


def test_replay_rejects_bad_json_and_non_object(tmp_path: Path) -> None:
    bad_json = tmp_path / "bad.jsonl"
    bad_json.write_text("{\n", encoding="utf-8")
    with pytest.raises(ReplayError, match="invalid JSON"):
        replay_lines(bad_json)

    non_object = tmp_path / "list.jsonl"
    non_object.write_text("[]\n", encoding="utf-8")
    with pytest.raises(ReplayError, match="expected an object"):
        replay_lines(non_object)


def test_replay_validates_limit_and_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ReplayError, match="limit"):
        replay_lines(tmp_path / "unused.jsonl", limit=0)
    with pytest.raises(ReplayError, match="cannot read"):
        replay_lines(tmp_path / "missing.jsonl")
