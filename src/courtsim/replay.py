"""Read and render canonical JSONL events without running the simulator."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any


class ReplayError(ValueError):
    pass


def read_event_records(path: str | Path) -> Iterator[dict[str, Any]]:
    source = Path(path)
    previous_sequence = 0
    try:
        with source.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ReplayError(f"{source}:{line_number}: invalid JSON: {exc.msg}") from exc
                if not isinstance(record, dict):
                    raise ReplayError(f"{source}:{line_number}: expected an object")
                sequence = record.get("sequence")
                if type(sequence) is not int or sequence <= previous_sequence:
                    raise ReplayError(
                        f"{source}:{line_number}: sequence must be a strictly increasing integer"
                    )
                previous_sequence = sequence
                yield record
    except OSError as exc:
        raise ReplayError(f"cannot read {source}: {exc}") from exc


def render_event(record: dict[str, Any]) -> str:
    sequence = record.get("sequence", "?")
    possession = record.get("possession", "?")
    action = record.get("action", "?")
    offense = record.get("offense", "?")
    kind = record.get("kind", "unknown")
    actor = f" actor={record['actor']}" if record.get("actor") else ""
    target = f" target={record['target']}" if record.get("target") else ""
    zone = f" zone={record['zone']}" if record.get("zone") else ""
    data = record.get("data")
    details = f" data={json.dumps(data, ensure_ascii=False, sort_keys=True)}" if data else ""
    return f"#{sequence} P{possession} A{action} [{offense}] {kind}{actor}{target}{zone}{details}"


def replay_lines(
    path: str | Path, *, possession: int | None = None, limit: int | None = None
) -> tuple[str, ...]:
    if limit is not None and limit < 1:
        raise ReplayError("limit must be at least 1")
    lines: list[str] = []
    for record in read_event_records(path):
        if possession is not None and record.get("possession") != possession:
            continue
        lines.append(render_event(record))
        if limit is not None and len(lines) >= limit:
            break
    return tuple(lines)
