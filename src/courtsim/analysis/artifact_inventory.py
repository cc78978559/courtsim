"""Read-only inventory for locally generated work artifacts."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any


class ArtifactInventoryError(ValueError):
    pass


def build_artifact_inventory(
    root: str | Path,
    *,
    largest: int = 10,
) -> dict[str, Any]:
    if not isinstance(largest, int) or isinstance(largest, bool) or largest < 1:
        raise ArtifactInventoryError("largest must be a positive integer")
    directory = Path(root)
    if not directory.is_dir():
        raise ArtifactInventoryError(f"artifact root is not a directory: {directory}")

    files: list[tuple[Path, int]] = []
    bytes_by_extension: dict[str, int] = defaultdict(int)
    files_by_extension: dict[str, int] = defaultdict(int)
    bytes_by_top_directory: dict[str, int] = defaultdict(int)
    files_by_top_directory: dict[str, int] = defaultdict(int)
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(directory)
        size = path.stat().st_size
        files.append((relative, size))
        extension = path.suffix.lower() or "<none>"
        top_directory = relative.parts[0] if len(relative.parts) > 1 else "."
        bytes_by_extension[extension] += size
        files_by_extension[extension] += 1
        bytes_by_top_directory[top_directory] += size
        files_by_top_directory[top_directory] += 1

    ordered_largest = sorted(files, key=lambda item: (-item[1], item[0].as_posix()))[:largest]
    total_bytes = sum(size for _, size in files)
    return {
        "format_version": 1,
        "kind": "courtsim-artifact-inventory",
        "root": directory.as_posix(),
        "summary": {
            "files": len(files),
            "bytes": total_bytes,
            "mib": total_bytes / (1024 * 1024),
        },
        "by_extension": [
            {
                "extension": extension,
                "files": files_by_extension[extension],
                "bytes": bytes_by_extension[extension],
            }
            for extension in sorted(files_by_extension)
        ],
        "by_top_directory": [
            {
                "directory": name,
                "files": files_by_top_directory[name],
                "bytes": bytes_by_top_directory[name],
            }
            for name in sorted(files_by_top_directory)
        ],
        "largest_files": [
            {"path": path.as_posix(), "bytes": size} for path, size in ordered_largest
        ],
    }
