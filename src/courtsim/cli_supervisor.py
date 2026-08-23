from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from courtsim.artifacts import write_json
from courtsim.formal_supervisor import (
    FormalSupervisorError,
    collect_launch_samples,
    evaluate_launch_resources,
    load_formal_supervisor_spec,
    run_formal_supervisor,
    validate_frozen_workspace,
)

SUPERVISOR_COMMANDS = frozenset({"nba-manager-supervisor-check", "nba-manager-supervisor-run"})


def register_supervisor_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    check = subparsers.add_parser(
        "nba-manager-supervisor-check",
        help="validate a frozen supervisor binding and sample the launch resource gate",
    )
    check.add_argument("spec", type=Path)
    check.add_argument("--root", type=Path, default=Path("."))
    check.add_argument("--output", type=Path)

    run = subparsers.add_parser(
        "nba-manager-supervisor-run",
        help="run one frozen source under effect-blind cell-atomic resource supervision",
    )
    run.add_argument("spec", type=Path)
    run.add_argument("output", type=Path)
    run.add_argument("--root", type=Path, default=Path("."))
    run.add_argument(
        "--execute",
        action="store_true",
        help="required acknowledgement that the frozen formal command may be launched",
    )


def run_supervisor_command(arguments: argparse.Namespace) -> int:
    spec = load_formal_supervisor_spec(arguments.spec)
    root = arguments.root.resolve()
    if arguments.command == "nba-manager-supervisor-check":
        binding = validate_frozen_workspace(root, spec)
        samples = collect_launch_samples(root, spec)
        decision = evaluate_launch_resources(samples, spec.thresholds)
        payload = {
            "version": "nba-manager-formal-supervisor-preflight-v2",
            "binding": binding,
            "samples": [asdict(sample) for sample in samples],
            "allowed": decision.allowed,
            "reasons": list(decision.reasons),
            "effects_read": False,
        }
        if arguments.output is not None:
            write_json(arguments.output, payload)
        print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
        return 0 if decision.allowed else 20

    if arguments.command == "nba-manager-supervisor-run":
        if not arguments.execute:
            raise FormalSupervisorError("supervisor run requires explicit --execute")
        payload = run_formal_supervisor(root, spec)
        write_json(arguments.output, payload)
        print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
        return 0 if payload["child_exit_code"] == 0 else 21

    raise ValueError(f"unsupported supervisor command: {arguments.command}")
