from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from courtsim import formal_supervisor
from courtsim.cli import main
from courtsim.formal_supervisor import (
    FormalSupervisorError,
    FormalSupervisorSpec,
    ResourceSnapshot,
    ResourceThresholds,
    create_stop_request,
    evaluate_launch_resources,
    evaluate_running_resources,
    run_formal_supervisor,
    validate_formal_supervisor_spec,
    validate_frozen_workspace,
)


def snapshot(
    memory: float = 4.0,
    cpu: float = 10.0,
    disk: float = 100.0,
    disk_percent: float = 20.0,
    blocking: tuple[str, ...] = (),
) -> ResourceSnapshot:
    return ResourceSnapshot("2026-08-23T00:00:00+08:00", cpu, memory, disk, disk_percent, blocking)


def spec() -> FormalSupervisorSpec:
    protocol = Path("experiments/promotion/nba-manager-policy-v1-protocol.json")
    output = Path("work/manager-promotion/formal-v1")
    stop = output / "STOP"
    return FormalSupervisorSpec(
        "nba-manager-formal-supervisor-v2",
        "d" * 40,
        protocol,
        "a" * 64,
        output,
        stop,
        (
            "{python}",
            "-m",
            "courtsim",
            "nba-manager-study-run",
            "initial.json.gz",
            "receipt.json",
            "shots.json",
            "macro.json",
            "profiles.json",
            output.as_posix(),
            "--protocol",
            protocol.as_posix(),
            "--stop-file",
            stop.as_posix(),
            "--workers",
            "1",
            "--maximum-new-sources",
            "1",
        ),
        ResourceThresholds(),
        launch_interval_seconds=10,
        monitor_interval_seconds=10,
    )


@pytest.mark.parametrize(
    "forbidden",
    ["--development", "--sources", "--seasons", "--seed-start"],
)
def test_supervisor_spec_rejects_scientific_protocol_overrides(forbidden: str) -> None:
    candidate = spec()
    with pytest.raises(FormalSupervisorError, match="cannot contain"):
        validate_formal_supervisor_spec(
            replace(candidate, command=(*candidate.command, forbidden, "1"))
        )


def test_resource_policy_requires_three_stable_samples_and_stops_conservatively() -> None:
    thresholds = ResourceThresholds()
    assert evaluate_launch_resources((snapshot(), snapshot(), snapshot()), thresholds).allowed
    launch_failure = evaluate_launch_resources(
        (snapshot(), snapshot(memory=2.9), snapshot()), thresholds
    )
    assert launch_failure.reasons == ("sample-2-memory",)
    assert not evaluate_running_resources((snapshot(memory=1.2),), thresholds).allowed
    repeated = evaluate_running_resources((snapshot(memory=1.4), snapshot(memory=1.4)), thresholds)
    assert repeated.reasons == ("repeated-low-memory",)
    blocked = evaluate_running_resources((snapshot(blocking=("builder",)),), thresholds)
    assert blocked.reasons == ("blocking-process",)


def test_frozen_workspace_binding_checks_commit_protocol_cleanliness_and_stop(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = spec()
    protocol = tmp_path / candidate.protocol_path
    protocol.parent.mkdir(parents=True)
    protocol.write_text("frozen", encoding="utf-8")
    digest = hashlib.sha256(b"frozen").hexdigest()
    candidate = replace(candidate, protocol_sha256=digest)

    def clean_git(_root: Path, *arguments: str) -> str:
        return candidate.frozen_commit if arguments == ("rev-parse", "HEAD") else ""

    monkeypatch.setattr(formal_supervisor, "_git", clean_git)
    binding = validate_frozen_workspace(tmp_path, candidate)
    assert binding["effects_read"] is False
    create_stop_request(tmp_path, candidate, ("test-boundary",))
    with pytest.raises(FormalSupervisorError, match="STOP"):
        validate_frozen_workspace(tmp_path, candidate)


def test_supervised_run_requests_stop_without_killing_child(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate = spec()
    polls = iter((None, 0))

    class FakeProcess:
        def poll(self) -> int | None:
            return next(polls)

        def wait(self) -> int:
            return 0

    monkeypatch.setattr(
        formal_supervisor,
        "validate_frozen_workspace",
        lambda _root, _spec: {"effects_read": False},
    )
    monkeypatch.setattr(
        formal_supervisor,
        "collect_launch_samples",
        lambda _root, _spec: (snapshot(), snapshot(), snapshot()),
    )
    monkeypatch.setattr(
        formal_supervisor,
        "collect_resource_snapshot",
        lambda *_args: snapshot(memory=1.2),
    )
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    popen_calls: list[tuple[tuple[str, ...], Path]] = []

    def fake_popen(command: tuple[str, ...], *, cwd: Path) -> Any:
        popen_calls.append((command, cwd))
        return FakeProcess()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    receipt = run_formal_supervisor(tmp_path, candidate)
    assert receipt["effects_read"] is False
    assert receipt["stop_requested"] is True
    assert receipt["stop_reasons"] == ["emergency-memory"]
    assert (tmp_path / candidate.stop_file).is_file()
    assert popen_calls[0][0][0] != "{python}"


def test_supervisor_cli_requires_explicit_execution(tmp_path: Path) -> None:
    candidate = spec()
    payload = {
        "version": candidate.version,
        "frozen_commit": candidate.frozen_commit,
        "protocol_path": candidate.protocol_path.as_posix(),
        "protocol_sha256": candidate.protocol_sha256,
        "output_directory": candidate.output_directory.as_posix(),
        "stop_file": candidate.stop_file.as_posix(),
        "command": list(candidate.command),
        "launch_interval_seconds": 10,
        "monitor_interval_seconds": 10,
    }
    spec_path = tmp_path / "supervisor.json"
    spec_path.write_text(json.dumps(payload), encoding="utf-8")
    assert (
        main(
            [
                "nba-manager-supervisor-run",
                str(spec_path),
                str(tmp_path / "receipt.json"),
            ]
        )
        == 2
    )
    assert not (tmp_path / "receipt.json").exists()
