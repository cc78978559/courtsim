from __future__ import annotations

import argparse
from pathlib import Path

from courtsim.analysis.artifact_archive import (
    build_artifact_archive_plan,
    create_artifact_archive,
    restore_artifact_archive,
    verify_artifact_archive,
)
from courtsim.analysis.artifact_inventory import build_artifact_inventory
from courtsim.analysis.artifact_retention import (
    ArtifactRetentionError,
    build_archive_plan_from_retention_report,
    build_artifact_retention_report,
    compare_artifact_retention_reports,
)
from courtsim.artifacts import write_json

ARTIFACT_COMMANDS = frozenset(
    {
        "artifacts-audit",
        "artifacts-plan",
        "artifacts-archive",
        "artifacts-verify-archive",
        "artifacts-restore",
        "artifacts-retention-audit",
        "artifacts-retention-plan",
        "artifacts-retention-compare",
    }
)


def register_artifact_commands(
    subparsers: argparse._SubParsersAction[argparse.ArgumentParser],
) -> None:
    artifact_inventory = subparsers.add_parser(
        "artifacts-audit",
        help="inspect generated artifact count and disk usage without deleting files",
    )
    artifact_inventory.add_argument("root", type=Path, nargs="?", default=Path("work"))
    artifact_inventory.add_argument("--largest", type=int, default=10)
    artifact_inventory.add_argument("--output", type=Path)

    artifact_plan = subparsers.add_parser(
        "artifacts-plan",
        help="create a hash-addressed, non-destructive archive plan",
    )
    artifact_plan.add_argument("root", type=Path)
    artifact_plan.add_argument("output", type=Path)
    artifact_plan.add_argument("--include", action="append", required=True)
    artifact_plan.add_argument("--exclude", action="append", default=[])

    artifact_archive = subparsers.add_parser(
        "artifacts-archive",
        help="create and verify a ZIP from an unchanged archive plan",
    )
    artifact_archive.add_argument("plan", type=Path)
    artifact_archive.add_argument("output", type=Path)

    artifact_verify = subparsers.add_parser(
        "artifacts-verify-archive",
        help="verify an archive manifest, CRC, entry set, and content hashes",
    )
    artifact_verify.add_argument("archive", type=Path)

    artifact_restore = subparsers.add_parser(
        "artifacts-restore",
        help="verify and restore an archive into a new directory",
    )
    artifact_restore.add_argument("archive", type=Path)
    artifact_restore.add_argument("destination", type=Path)

    artifact_retention_audit = subparsers.add_parser(
        "artifacts-retention-audit",
        help="classify artifacts with a draft, read-only retention policy",
    )
    artifact_retention_audit.add_argument("root", type=Path)
    artifact_retention_audit.add_argument("policy", type=Path)
    artifact_retention_audit.add_argument("output", type=Path)

    artifact_retention_plan = subparsers.add_parser(
        "artifacts-retention-plan",
        help="turn a fresh retention report into a hash-addressed archive plan",
    )
    artifact_retention_plan.add_argument("report", type=Path)
    artifact_retention_plan.add_argument("output", type=Path)

    artifact_retention_compare = subparsers.add_parser(
        "artifacts-retention-compare",
        help="compare retention reports and detect protection regressions",
    )
    artifact_retention_compare.add_argument("baseline", type=Path)
    artifact_retention_compare.add_argument("candidate", type=Path)
    artifact_retention_compare.add_argument("output", type=Path)
    artifact_retention_compare.add_argument(
        "--fail-on-protection-loss",
        action="store_true",
    )


def run_artifact_command(arguments: argparse.Namespace) -> int:
    if arguments.command == "artifacts-audit":
        report = build_artifact_inventory(arguments.root, largest=arguments.largest)
        if arguments.output is not None:
            write_json(arguments.output, report)
            print(f"completed: {arguments.output}")
        else:
            summary = report["summary"]
            print(f"artifacts: {summary['files']} files, {summary['mib']:.2f} MiB")
        return 0

    if arguments.command == "artifacts-plan":
        plan = build_artifact_archive_plan(
            arguments.root,
            include=tuple(arguments.include),
            exclude=tuple(arguments.exclude),
        )
        write_json(arguments.output, plan)
        print(
            f"planned: {arguments.output} "
            f"({plan['summary']['files']} files, {plan['summary']['bytes']} bytes)"
        )
        return 0

    if arguments.command == "artifacts-archive":
        archive_result = create_artifact_archive(arguments.plan, arguments.output)
        print(
            f"archived: {archive_result.path} "
            f"({archive_result.files} files, {archive_result.archive_bytes} bytes, "
            f"{archive_result.sha256})"
        )
        return 0

    if arguments.command == "artifacts-verify-archive":
        verification_result = verify_artifact_archive(arguments.archive)
        print(
            f"verified archive: {verification_result.path} "
            f"({verification_result.files} files, "
            f"{verification_result.archive_bytes} bytes, "
            f"{verification_result.sha256})"
        )
        return 0

    if arguments.command == "artifacts-restore":
        restore_result = restore_artifact_archive(arguments.archive, arguments.destination)
        print(
            f"restored: {restore_result.path} "
            f"({restore_result.files} files, {restore_result.restored_bytes} bytes, "
            f"{restore_result.archive_sha256})"
        )
        return 0

    if arguments.command == "artifacts-retention-audit":
        report = build_artifact_retention_report(arguments.root, arguments.policy)
        root = Path(report["root"]).resolve()
        output = arguments.output.resolve()
        try:
            output.relative_to(root)
        except ValueError:
            pass
        else:
            raise ArtifactRetentionError("retention report must be stored outside its scanned root")
        write_json(output, report)
        summary = report["summary"]
        print(
            f"classified: {output} "
            f"({summary['total']['files']} files, "
            f"{summary['archive_candidate']['files']} archive candidates)"
        )
        return 0

    if arguments.command == "artifacts-retention-plan":
        plan = build_archive_plan_from_retention_report(arguments.report)
        write_json(arguments.output, plan)
        print(
            f"planned: {arguments.output} "
            f"({plan['summary']['files']} files, {plan['summary']['bytes']} bytes)"
        )
        return 0

    if arguments.command == "artifacts-retention-compare":
        comparison = compare_artifact_retention_reports(
            arguments.baseline,
            arguments.candidate,
        )
        write_json(arguments.output, comparison)
        summary = comparison["summary"]
        print(
            f"compared: {arguments.output} "
            f"({summary['changed_paths']} changed paths, "
            f"{summary['protection_losses']} protection losses)"
        )
        if arguments.fail_on_protection_loss and summary["protection_losses"]:
            return 10
        return 0

    raise ValueError(f"unsupported artifact command: {arguments.command}")
