"""Resource-gated, effect-blind supervision for frozen formal manager studies."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast


class FormalSupervisorError(ValueError):
    """Raised when a supervisor spec or local resource boundary is invalid."""


@dataclass(frozen=True, slots=True)
class ResourceThresholds:
    launch_free_memory_gib: float = 3.0
    launch_maximum_cpu_percent: float = 35.0
    minimum_disk_free_gib: float = 65.0
    minimum_disk_free_percent: float = 15.0
    stop_free_memory_gib: float = 1.5
    emergency_free_memory_gib: float = 1.25
    stop_cpu_percent: float = 85.0
    heavy_process_gib: float = 2.5


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    observed_at: str
    cpu_percent: float
    free_memory_gib: float
    disk_free_gib: float
    disk_free_percent: float
    blocking_processes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ResourceDecision:
    allowed: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FormalSupervisorSpec:
    version: str
    frozen_commit: str
    protocol_path: Path
    protocol_sha256: str
    output_directory: Path
    stop_file: Path
    command: tuple[str, ...]
    thresholds: ResourceThresholds
    allowed_heavy_processes: tuple[str, ...] = ()
    launch_samples: int = 3
    launch_interval_seconds: float = 12.0
    monitor_interval_seconds: float = 30.0


def load_formal_supervisor_spec(path: str | Path) -> FormalSupervisorSpec:
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise FormalSupervisorError(f"supervisor spec cannot be read: {error}") from error
    if not isinstance(raw, dict):
        raise FormalSupervisorError("supervisor spec must be an object")
    values = cast(dict[str, Any], raw)
    thresholds_raw = values.get("thresholds", {})
    if not isinstance(thresholds_raw, dict):
        raise FormalSupervisorError("supervisor thresholds must be an object")
    try:
        command = tuple(str(item) for item in values["command"])
        thresholds = ResourceThresholds(
            **{key: float(value) for key, value in thresholds_raw.items()}
        )
        spec = FormalSupervisorSpec(
            version=str(values["version"]),
            frozen_commit=str(values["frozen_commit"]),
            protocol_path=Path(str(values["protocol_path"])),
            protocol_sha256=str(values["protocol_sha256"]),
            output_directory=Path(str(values["output_directory"])),
            stop_file=Path(str(values["stop_file"])),
            command=command,
            thresholds=thresholds,
            allowed_heavy_processes=tuple(
                str(item) for item in values.get("allowed_heavy_processes", [])
            ),
            launch_samples=int(values.get("launch_samples", 3)),
            launch_interval_seconds=float(values.get("launch_interval_seconds", 12.0)),
            monitor_interval_seconds=float(values.get("monitor_interval_seconds", 30.0)),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise FormalSupervisorError(f"supervisor spec fields are invalid: {error}") from error
    validate_formal_supervisor_spec(spec)
    return spec


def validate_formal_supervisor_spec(spec: FormalSupervisorSpec) -> None:
    if spec.version != "nba-manager-formal-supervisor-v2":
        raise FormalSupervisorError("supervisor version differs")
    if len(spec.frozen_commit) != 40 or any(
        character not in "0123456789abcdef" for character in spec.frozen_commit
    ):
        raise FormalSupervisorError("frozen commit must be a lowercase SHA-1")
    if len(spec.protocol_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in spec.protocol_sha256
    ):
        raise FormalSupervisorError("protocol hash must be a lowercase SHA-256")
    if spec.launch_samples != 3:
        raise FormalSupervisorError("formal launch requires exactly three samples")
    if spec.launch_interval_seconds < 10 or spec.monitor_interval_seconds < 10:
        raise FormalSupervisorError("resource sampling intervals must be at least ten seconds")
    if not spec.command:
        raise FormalSupervisorError("formal command is empty")
    command = spec.command
    if "nba-manager-study-run" not in command:
        raise FormalSupervisorError("formal command must run nba-manager-study-run")
    for forbidden in ("--development", "--sources", "--seasons", "--seed-start"):
        if forbidden in command:
            raise FormalSupervisorError(f"formal command cannot contain {forbidden}")
    _require_option(command, "--workers", "1")
    _require_option(command, "--maximum-new-sources", "1")
    _require_option(command, "--protocol", spec.protocol_path.as_posix())
    _require_option(command, "--stop-file", spec.stop_file.as_posix())
    if spec.output_directory.as_posix() not in command:
        raise FormalSupervisorError("formal output directory is not bound in the command")
    thresholds = spec.thresholds
    positive = asdict(thresholds).values()
    if any(not isinstance(value, (float, int)) or value <= 0 for value in positive):
        raise FormalSupervisorError("resource thresholds must be positive")
    if thresholds.emergency_free_memory_gib >= thresholds.stop_free_memory_gib:
        raise FormalSupervisorError("emergency memory must be below the repeated-stop boundary")


def evaluate_launch_resources(
    samples: tuple[ResourceSnapshot, ...],
    thresholds: ResourceThresholds,
) -> ResourceDecision:
    reasons: list[str] = []
    if len(samples) != 3:
        reasons.append("launch-requires-three-samples")
    for index, sample in enumerate(samples, start=1):
        if sample.free_memory_gib < thresholds.launch_free_memory_gib:
            reasons.append(f"sample-{index}-memory")
        if sample.cpu_percent > thresholds.launch_maximum_cpu_percent:
            reasons.append(f"sample-{index}-cpu")
        if (
            sample.disk_free_gib < thresholds.minimum_disk_free_gib
            or sample.disk_free_percent < thresholds.minimum_disk_free_percent
        ):
            reasons.append(f"sample-{index}-disk")
        if sample.blocking_processes:
            reasons.append(f"sample-{index}-blocking-process")
    return ResourceDecision(not reasons, tuple(reasons))


def evaluate_running_resources(
    samples: tuple[ResourceSnapshot, ...],
    thresholds: ResourceThresholds,
) -> ResourceDecision:
    if not samples:
        return ResourceDecision(False, ("missing-runtime-sample",))
    reasons: list[str] = []
    current = samples[-1]
    if current.free_memory_gib < thresholds.emergency_free_memory_gib:
        reasons.append("emergency-memory")
    if len(samples) >= 2 and all(
        sample.free_memory_gib < thresholds.stop_free_memory_gib for sample in samples[-2:]
    ):
        reasons.append("repeated-low-memory")
    if len(samples) >= 2 and all(
        sample.cpu_percent > thresholds.stop_cpu_percent for sample in samples[-2:]
    ):
        reasons.append("repeated-high-cpu")
    if (
        current.disk_free_gib < thresholds.minimum_disk_free_gib
        or current.disk_free_percent < thresholds.minimum_disk_free_percent
    ):
        reasons.append("disk-boundary")
    if current.blocking_processes:
        reasons.append("blocking-process")
    return ResourceDecision(not reasons, tuple(reasons))


def validate_frozen_workspace(root: Path, spec: FormalSupervisorSpec) -> dict[str, object]:
    workspace = root.resolve()
    protocol = _inside_workspace(workspace, spec.protocol_path)
    output = _inside_workspace(workspace, spec.output_directory)
    stop_file = _inside_workspace(workspace, spec.stop_file)
    if _sha256(protocol) != spec.protocol_sha256:
        raise FormalSupervisorError("frozen protocol hash differs")
    head = _git(workspace, "rev-parse", "HEAD")
    if head != spec.frozen_commit:
        raise FormalSupervisorError("workspace HEAD differs from frozen commit")
    if _git(workspace, "status", "--porcelain"):
        raise FormalSupervisorError("formal workspace is dirty")
    if stop_file.exists():
        raise FormalSupervisorError("formal STOP file already exists")
    return {
        "head": head,
        "protocol_sha256": spec.protocol_sha256,
        "output_directory": str(output),
        "stop_file": str(stop_file),
        "effects_read": False,
    }


def collect_resource_snapshot(
    root: Path,
    thresholds: ResourceThresholds,
    allowed_heavy_processes: tuple[str, ...] = (),
) -> ResourceSnapshot:
    if sys.platform != "win32":
        raise FormalSupervisorError(
            "formal supervisor resource collection currently requires Windows"
        )
    executable = shutil.which("pwsh.exe") or shutil.which("powershell.exe")
    if executable is None:
        raise FormalSupervisorError("PowerShell is unavailable for resource collection")
    allowed = ",".join(allowed_heavy_processes).replace("'", "''")
    script = (
        "$os=Get-CimInstance Win32_OperatingSystem;"
        "$cpu=(Get-Counter '\\Processor(_Total)\\% Processor Time').CounterSamples.CookedValue;"
        f"$limit={thresholds.heavy_process_gib * 1_073_741_824};"
        f"$allowed=@('{allowed}'.Split(','));"
        "$blocking=@(Get-Process | Where-Object {$_.WorkingSet64 -ge $limit -and "
        "$allowed -notcontains $_.ProcessName} | ForEach-Object {$_.ProcessName} | "
        "Sort-Object -Unique);"
        "$disk=Get-PSDrive -Name C;"
        "[pscustomobject]@{observed_at=(Get-Date).ToString('o');"
        "cpu_percent=$cpu;free_memory_gib=$os.FreePhysicalMemory/1MB;"
        "disk_free_gib=$disk.Free/1GB;disk_free_percent=100*$disk.Free/($disk.Free+$disk.Used);"
        "blocking_processes=$blocking}|ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        (executable, "-NoProfile", "-Command", script),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if completed.returncode != 0:
        raise FormalSupervisorError("resource collection failed")
    try:
        payload = json.loads(completed.stdout)
        blocking = payload.get("blocking_processes", [])
        if isinstance(blocking, str):
            blocking = [blocking]
        return ResourceSnapshot(
            str(payload["observed_at"]),
            float(payload["cpu_percent"]),
            float(payload["free_memory_gib"]),
            float(payload["disk_free_gib"]),
            float(payload["disk_free_percent"]),
            tuple(str(item) for item in blocking),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise FormalSupervisorError("resource snapshot is invalid") from error


def collect_launch_samples(root: Path, spec: FormalSupervisorSpec) -> tuple[ResourceSnapshot, ...]:
    samples: list[ResourceSnapshot] = []
    for index in range(spec.launch_samples):
        samples.append(
            collect_resource_snapshot(root, spec.thresholds, spec.allowed_heavy_processes)
        )
        if index + 1 < spec.launch_samples:
            time.sleep(spec.launch_interval_seconds)
    return tuple(samples)


def run_formal_supervisor(root: Path, spec: FormalSupervisorSpec) -> dict[str, object]:
    """Run the bound command and request a cell-atomic stop at a resource boundary."""
    binding = validate_frozen_workspace(root, spec)
    launch_samples = collect_launch_samples(root, spec)
    launch_decision = evaluate_launch_resources(launch_samples, spec.thresholds)
    if not launch_decision.allowed:
        raise FormalSupervisorError(
            f"formal launch resource gate failed: {','.join(launch_decision.reasons)}"
        )
    command = tuple(sys.executable if item == "{python}" else item for item in spec.command)
    process = subprocess.Popen(command, cwd=root)
    runtime_samples: list[ResourceSnapshot] = []
    stop_reasons: tuple[str, ...] = ()
    try:
        while process.poll() is None:
            time.sleep(spec.monitor_interval_seconds)
            runtime_samples.append(
                collect_resource_snapshot(root, spec.thresholds, spec.allowed_heavy_processes)
            )
            decision = evaluate_running_resources(tuple(runtime_samples[-2:]), spec.thresholds)
            if not decision.allowed and not stop_reasons:
                stop_reasons = decision.reasons
                create_stop_request(root, spec, stop_reasons)
    except KeyboardInterrupt:
        stop_reasons = ("operator-interrupt",)
        if not _inside_workspace(root.resolve(), spec.stop_file).exists():
            create_stop_request(root, spec, stop_reasons)
        process.wait()
    exit_code = process.wait()
    return {
        "version": "nba-manager-formal-supervisor-receipt-v2",
        "binding": binding,
        "launch_samples": [asdict(sample) for sample in launch_samples],
        "runtime_samples": [asdict(sample) for sample in runtime_samples],
        "stop_requested": bool(stop_reasons),
        "stop_reasons": list(stop_reasons),
        "child_exit_code": exit_code,
        "effects_read": False,
    }


def create_stop_request(root: Path, spec: FormalSupervisorSpec, reasons: tuple[str, ...]) -> Path:
    stop_file = _inside_workspace(root.resolve(), spec.stop_file)
    stop_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = stop_file.with_name(f".{stop_file.name}.tmp")
    if stop_file.exists() or temporary.exists():
        raise FormalSupervisorError("formal STOP path is not available")
    temporary.write_text(
        json.dumps(
            {"version": "formal-stop-request-v1", "reasons": list(reasons)},
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    temporary.replace(stop_file)
    return stop_file


def _require_option(command: tuple[str, ...], name: str, expected: str) -> None:
    positions = [index for index, value in enumerate(command) if value == name]
    if len(positions) != 1 or positions[0] + 1 >= len(command):
        raise FormalSupervisorError(f"formal command must contain one {name}")
    if command[positions[0] + 1].replace("\\", "/") != expected.replace("\\", "/"):
        raise FormalSupervisorError(f"formal command {name} differs")


def _inside_workspace(root: Path, relative: Path) -> Path:
    if relative.is_absolute():
        raise FormalSupervisorError("supervisor paths must be workspace-relative")
    resolved = (root / relative).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise FormalSupervisorError("supervisor path escapes the workspace") from error
    return resolved


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
