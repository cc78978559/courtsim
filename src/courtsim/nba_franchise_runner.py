"""Resumable, hash-verified orchestration for multi-season NBA franchises."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

from courtsim.artifacts import sha256_file, write_json
from courtsim.management import ContractRules
from courtsim.nba_franchise import (
    NBAFranchiseSeasonExecution,
    NBAFranchiseState,
)
from courtsim.nba_franchise_artifacts import (
    NBAFranchiseArtifactError,
    load_nba_franchise_checkpoint,
    nba_franchise_state_to_json,
    write_nba_franchise_checkpoint,
)
from courtsim.randomness import derive_seed

NBA_FRANCHISE_RUNNER_VERSION = "nba-franchise-runner-v4"
NBA_FRANCHISE_RUNNER_SCHEMA_VERSION = 2
_LEGACY_RUNNER_VERSIONS = {
    "nba-franchise-runner-v2",
    "nba-franchise-runner-v3",
}
NBAFranchiseSeasonExecutor = Callable[
    [NBAFranchiseState, int],
    NBAFranchiseSeasonExecution,
]


class NBAFranchiseRunnerError(ValueError):
    """Raised when a franchise run prefix is invalid or incompatible."""


@dataclass(frozen=True, slots=True)
class NBAFranchiseRetentionPolicy:
    keep_last: int = 2
    keep_every: int = 5
    compress_after: int = 1

    def __post_init__(self) -> None:
        values = (self.keep_last, self.keep_every, self.compress_after)
        if any(
            not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in values
        ):
            raise ValueError("franchise retention values must be non-negative integers")
        if self.keep_last < 1 or self.keep_every < 1:
            raise ValueError("franchise retention must keep recent and periodic checkpoints")


@dataclass(frozen=True, slots=True)
class NBAFranchiseRunSpec:
    run_id: str
    master_seed: int
    seasons: int
    version: str = NBA_FRANCHISE_RUNNER_VERSION

    def __post_init__(self) -> None:
        if (
            not self.run_id.strip()
            or not isinstance(self.master_seed, int)
            or isinstance(self.master_seed, bool)
            or not isinstance(self.seasons, int)
            or isinstance(self.seasons, bool)
            or self.seasons < 1
            or self.version != NBA_FRANCHISE_RUNNER_VERSION
        ):
            raise ValueError("NBA franchise run spec is invalid")


@dataclass(frozen=True, slots=True)
class NBAFranchiseRunResult:
    spec: NBAFranchiseRunSpec
    state: NBAFranchiseState
    completed_before: int
    completed_after: int
    complete: bool
    executions: tuple[NBAFranchiseSeasonExecution, ...]
    manifest_path: str
    manifest_sha256: str
    version: str = NBA_FRANCHISE_RUNNER_VERSION


@dataclass(frozen=True, slots=True)
class NBAFranchiseRunInspection:
    run_id: str
    league_id: str
    completed_seasons: int
    target_seasons: int
    complete: bool
    retained_checkpoints: int
    compressed_checkpoints: int
    pruned_checkpoints: int
    latest_checkpoint: str
    manifest_sha256: str
    version: str = NBA_FRANCHISE_RUNNER_VERSION


def run_nba_franchise_checkpoint(
    spec: NBAFranchiseRunSpec,
    initial_state: NBAFranchiseState,
    contract_rules: ContractRules,
    executor: NBAFranchiseSeasonExecutor,
    run_directory: str | Path,
    *,
    maximum_new_seasons: int | None = None,
    retention_policy: NBAFranchiseRetentionPolicy | None = None,
) -> NBAFranchiseRunResult:
    if maximum_new_seasons is not None and (
        not isinstance(maximum_new_seasons, int)
        or isinstance(maximum_new_seasons, bool)
        or maximum_new_seasons < 1
    ):
        raise NBAFranchiseRunnerError("maximum_new_seasons must be positive")
    directory = Path(run_directory)
    directory.mkdir(parents=True, exist_ok=True)
    manifest_path = directory / "manifest.json"
    initial_sha256 = _state_sha256(initial_state, contract_rules)
    if manifest_path.exists():
        manifest, state = _load_verified_prefix(
            manifest_path,
            spec,
            initial_state,
            contract_rules,
        )
        stored_retention = _retention_from_value(manifest["retention"])
        if retention_policy is not None and retention_policy != stored_retention:
            raise NBAFranchiseRunnerError("franchise run retention policy differs")
        retention_policy = stored_retention
    else:
        initial_receipt = write_nba_franchise_checkpoint(
            initial_state,
            contract_rules,
            directory / _checkpoint_name(initial_state.completed_seasons),
        )
        manifest = {
            "schema_version": NBA_FRANCHISE_RUNNER_SCHEMA_VERSION,
            "version": NBA_FRANCHISE_RUNNER_VERSION,
            "spec": _spec_to_dict(spec),
            "league_id": initial_state.league_id,
            "initial_completed_seasons": initial_state.completed_seasons,
            "initial_state_sha256": initial_sha256,
            "retention": (asdict(retention_policy) if retention_policy is not None else None),
            "checkpoints": [
                _checkpoint_to_dict(
                    initial_state.completed_seasons,
                    None,
                    initial_receipt.state_sha256,
                    initial_receipt.file_sha256,
                    seed_version=NBA_FRANCHISE_RUNNER_VERSION,
                )
            ],
        }
        write_json(manifest_path, manifest)
        state = initial_state
    completed_before = state.completed_seasons - initial_state.completed_seasons
    remaining = spec.seasons - completed_before
    if remaining < 0:
        raise NBAFranchiseRunnerError("franchise run prefix exceeds its target")
    budget = remaining
    if maximum_new_seasons is not None:
        budget = min(budget, maximum_new_seasons)
    executions = []
    for _ in range(budget):
        next_completed = state.completed_seasons + 1
        seed = derive_seed(
            spec.master_seed,
            NBA_FRANCHISE_RUNNER_VERSION,
            spec.run_id,
            next_completed,
        )
        execution = executor(state, seed)
        if (
            execution.initial_state != state
            or execution.final_state.completed_seasons != next_completed
            or execution.final_state.league_id != initial_state.league_id
        ):
            raise NBAFranchiseRunnerError("franchise season executor broke state continuity")
        receipt = write_nba_franchise_checkpoint(
            execution.final_state,
            contract_rules,
            directory / _checkpoint_name(next_completed),
        )
        checkpoints = cast(list[object], manifest["checkpoints"])
        checkpoints.append(
            _checkpoint_to_dict(
                next_completed,
                seed,
                receipt.state_sha256,
                receipt.file_sha256,
                seed_version=NBA_FRANCHISE_RUNNER_VERSION,
            )
        )
        if retention_policy is not None:
            _apply_retention(
                directory,
                checkpoints,
                initial_completed_seasons=initial_state.completed_seasons,
                latest_completed_seasons=next_completed,
                policy=retention_policy,
            )
        write_json(manifest_path, manifest)
        executions.append(execution)
        state = execution.final_state
    completed_after = state.completed_seasons - initial_state.completed_seasons
    return NBAFranchiseRunResult(
        spec,
        state,
        completed_before,
        completed_after,
        completed_after == spec.seasons,
        tuple(executions),
        str(manifest_path.resolve()),
        sha256_file(manifest_path),
    )


def inspect_nba_franchise_manifest(
    manifest_path: str | Path,
) -> NBAFranchiseRunInspection:
    path = Path(manifest_path)
    if not path.is_file():
        raise NBAFranchiseRunnerError("NBA franchise run manifest must be a file")
    try:
        manifest = _migrate_manifest(
            _object(
                json.loads(path.read_text(encoding="utf-8")),
                "NBA franchise run manifest",
            )
        )
        _exact(
            manifest,
            {
                "schema_version",
                "version",
                "spec",
                "league_id",
                "initial_completed_seasons",
                "initial_state_sha256",
                "retention",
                "checkpoints",
            },
            "NBA franchise run manifest",
        )
        if (
            _integer(manifest, "schema_version") != NBA_FRANCHISE_RUNNER_SCHEMA_VERSION
            or _string(manifest, "version") != NBA_FRANCHISE_RUNNER_VERSION
        ):
            raise NBAFranchiseRunnerError("unsupported NBA franchise run manifest")
        spec = _spec_from_dict(manifest["spec"])
        league_id = _string(manifest, "league_id")
        initial_completed = _integer(manifest, "initial_completed_seasons")
        _string(manifest, "initial_state_sha256")
        _retention_from_value(manifest["retention"])
        checkpoints = _list(manifest["checkpoints"], "franchise checkpoints")
        if not checkpoints or len(checkpoints) > spec.seasons + 1:
            raise NBAFranchiseRunnerError("franchise checkpoint count is invalid")
        retained = 0
        compressed = 0
        pruned = 0
        latest_path = ""
        for index, value in enumerate(checkpoints):
            checkpoint = _object(value, "franchise checkpoint entry")
            _exact(
                checkpoint,
                {
                    "completed_seasons",
                    "seed",
                    "path",
                    "state_sha256",
                    "file_sha256",
                    "storage",
                    "seed_version",
                },
                "franchise checkpoint entry",
            )
            completed = initial_completed + index
            storage = _string(checkpoint, "storage")
            checkpoint_name = _string(checkpoint, "path")
            if (
                _integer(checkpoint, "completed_seasons") != completed
                or storage not in {"json", "gzip", "pruned"}
                or checkpoint_name
                not in {
                    _checkpoint_name(completed),
                    _checkpoint_name(completed, compressed=True),
                }
                or (index == 0 and checkpoint["seed"] is not None)
                or (
                    index > 0
                    and _optional_integer(checkpoint, "seed")
                    != derive_seed(
                        spec.master_seed,
                        _string(checkpoint, "seed_version"),
                        spec.run_id,
                        completed,
                    )
                )
            ):
                raise NBAFranchiseRunnerError("franchise run checkpoints are not contiguous")
            _string(checkpoint, "state_sha256")
            _string(checkpoint, "file_sha256")
            if storage == "pruned":
                pruned += 1
                continue
            restored, _, receipt = load_nba_franchise_checkpoint(
                path.parent / checkpoint_name,
                expected_file_sha256=_string(checkpoint, "file_sha256"),
            )
            if (
                restored.league_id != league_id
                or restored.completed_seasons != completed
                or receipt.state_sha256 != _string(checkpoint, "state_sha256")
                or (
                    index == 0 and receipt.state_sha256 != _string(manifest, "initial_state_sha256")
                )
                or receipt.compression != ("gzip" if storage == "gzip" else "none")
            ):
                raise NBAFranchiseRunnerError("franchise checkpoint differs from its manifest")
            retained += 1
            compressed += storage == "gzip"
            latest_path = checkpoint_name
        completed_seasons = len(checkpoints) - 1
        if (
            not latest_path
            or _string(
                _object(checkpoints[-1], "franchise checkpoint entry"),
                "storage",
            )
            == "pruned"
        ):
            raise NBAFranchiseRunnerError("latest franchise checkpoint must be retained")
        return NBAFranchiseRunInspection(
            spec.run_id,
            league_id,
            completed_seasons,
            spec.seasons,
            completed_seasons == spec.seasons,
            retained,
            compressed,
            pruned,
            latest_path,
            sha256_file(path),
        )
    except (
        NBAFranchiseArtifactError,
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        if isinstance(error, NBAFranchiseRunnerError):
            raise
        raise NBAFranchiseRunnerError(f"invalid NBA franchise run manifest: {error}") from error


def _load_verified_prefix(
    manifest_path: Path,
    spec: NBAFranchiseRunSpec,
    initial_state: NBAFranchiseState,
    contract_rules: ContractRules,
) -> tuple[dict[str, object], NBAFranchiseState]:
    try:
        manifest = _object(
            json.loads(manifest_path.read_text(encoding="utf-8")),
            "NBA franchise run manifest",
        )
        manifest = _migrate_manifest(manifest)
        _exact(
            manifest,
            {
                "schema_version",
                "version",
                "spec",
                "league_id",
                "initial_completed_seasons",
                "initial_state_sha256",
                "retention",
                "checkpoints",
            },
            "NBA franchise run manifest",
        )
        if (
            _integer(manifest, "schema_version") != NBA_FRANCHISE_RUNNER_SCHEMA_VERSION
            or _string(manifest, "version") != NBA_FRANCHISE_RUNNER_VERSION
            or _spec_from_dict(manifest["spec"]) != spec
            or _string(manifest, "league_id") != initial_state.league_id
            or _integer(manifest, "initial_completed_seasons") != initial_state.completed_seasons
            or _string(manifest, "initial_state_sha256")
            not in _compatible_state_hashes(initial_state, contract_rules)
        ):
            raise NBAFranchiseRunnerError("franchise run manifest differs")
        checkpoints = _list(manifest["checkpoints"], "franchise checkpoints")
        if not checkpoints:
            raise NBAFranchiseRunnerError("franchise run prefix is empty")
        restored = initial_state
        for index, value in enumerate(checkpoints):
            checkpoint = _object(value, "franchise checkpoint entry")
            _exact(
                checkpoint,
                {
                    "completed_seasons",
                    "seed",
                    "path",
                    "state_sha256",
                    "file_sha256",
                    "storage",
                    "seed_version",
                },
                "franchise checkpoint entry",
            )
            completed = initial_state.completed_seasons + index
            if (
                _integer(checkpoint, "completed_seasons") != completed
                or _string(checkpoint, "path")
                not in {_checkpoint_name(completed), _checkpoint_name(completed, compressed=True)}
                or (index == 0 and checkpoint["seed"] is not None)
                or (
                    index > 0
                    and _optional_integer(checkpoint, "seed")
                    != derive_seed(
                        spec.master_seed,
                        _string(checkpoint, "seed_version"),
                        spec.run_id,
                        completed,
                    )
                )
            ):
                raise NBAFranchiseRunnerError("franchise run checkpoints are not contiguous")
            storage = _string(checkpoint, "storage")
            if storage not in {"json", "gzip", "pruned"}:
                raise NBAFranchiseRunnerError("franchise checkpoint storage is invalid")
            if storage == "pruned":
                continue
            restored, restored_rules, receipt = load_nba_franchise_checkpoint(
                manifest_path.parent / _string(checkpoint, "path"),
                expected_file_sha256=_string(checkpoint, "file_sha256"),
            )
            if (
                restored_rules != contract_rules
                or restored.completed_seasons != completed
                or restored.league_id != initial_state.league_id
                or receipt.state_sha256 != _string(checkpoint, "state_sha256")
                or (
                    completed == initial_state.completed_seasons
                    and (
                        restored != initial_state
                        or receipt.state_sha256 != _string(manifest, "initial_state_sha256")
                    )
                )
            ):
                raise NBAFranchiseRunnerError("franchise checkpoint differs from its manifest")
        return manifest, restored
    except (
        json.JSONDecodeError,
        KeyError,
        TypeError,
        ValueError,
        NBAFranchiseArtifactError,
    ) as error:
        if isinstance(error, NBAFranchiseRunnerError):
            raise
        raise NBAFranchiseRunnerError(f"invalid NBA franchise run prefix: {error}") from error


def _checkpoint_to_dict(
    completed_seasons: int,
    seed: int | None,
    state_sha256: str,
    file_sha256: str,
    *,
    seed_version: str,
) -> dict[str, object]:
    return {
        "completed_seasons": completed_seasons,
        "seed": seed,
        "path": _checkpoint_name(completed_seasons),
        "state_sha256": state_sha256,
        "file_sha256": file_sha256,
        "storage": "json",
        "seed_version": seed_version,
    }


def _checkpoint_name(completed_seasons: int, *, compressed: bool = False) -> str:
    suffix = ".json.gz" if compressed else ".json"
    return f"season-{completed_seasons:05d}{suffix}"


def _state_sha256(
    state: NBAFranchiseState,
    contract_rules: ContractRules,
) -> str:
    payload = nba_franchise_state_to_json(state, contract_rules)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _compatible_state_hashes(
    state: NBAFranchiseState,
    contract_rules: ContractRules,
) -> set[str]:
    payload = json.loads(nba_franchise_state_to_json(state, contract_rules))
    result = {_state_sha256(state, contract_rules)}
    for legacy in ("nba-franchise-v3", "nba-franchise-v4", "nba-franchise-v5"):
        migrated = {**payload, "version": legacy, "schema_version": 1}
        canonical = json.dumps(
            migrated,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        result.add(hashlib.sha256(canonical.encode("utf-8")).hexdigest())
    return result


def _migrate_manifest(manifest: dict[str, Any]) -> dict[str, object]:
    schema = _integer(manifest, "schema_version")
    version = _string(manifest, "version")
    if schema == NBA_FRANCHISE_RUNNER_SCHEMA_VERSION and version == NBA_FRANCHISE_RUNNER_VERSION:
        return manifest
    if version not in _LEGACY_RUNNER_VERSIONS:
        raise NBAFranchiseRunnerError("unsupported NBA franchise run manifest")
    if schema == NBA_FRANCHISE_RUNNER_SCHEMA_VERSION and version == "nba-franchise-runner-v3":
        migrated = dict(manifest)
        migrated["version"] = NBA_FRANCHISE_RUNNER_VERSION
        spec = _object(migrated["spec"], "NBA franchise run spec")
        migrated["spec"] = {**spec, "version": NBA_FRANCHISE_RUNNER_VERSION}
        return migrated
    if schema != 1 or version != "nba-franchise-runner-v2":
        raise NBAFranchiseRunnerError("unsupported NBA franchise run manifest")
    migrated = dict(manifest)
    migrated["schema_version"] = NBA_FRANCHISE_RUNNER_SCHEMA_VERSION
    migrated["version"] = NBA_FRANCHISE_RUNNER_VERSION
    migrated["retention"] = None
    spec = _object(migrated["spec"], "NBA franchise run spec")
    migrated["spec"] = {**spec, "version": NBA_FRANCHISE_RUNNER_VERSION}
    migrated["checkpoints"] = [
        {
            **_object(item, "franchise checkpoint entry"),
            "storage": "json",
            "seed_version": "nba-franchise-runner-v2",
        }
        for item in _list(migrated["checkpoints"], "franchise checkpoints")
    ]
    return migrated


def _retention_from_value(value: object) -> NBAFranchiseRetentionPolicy | None:
    if value is None:
        return None
    raw = _object(value, "franchise retention policy")
    _exact(
        raw,
        {"keep_last", "keep_every", "compress_after"},
        "franchise retention policy",
    )
    try:
        return NBAFranchiseRetentionPolicy(
            _integer(raw, "keep_last"),
            _integer(raw, "keep_every"),
            _integer(raw, "compress_after"),
        )
    except ValueError as error:
        raise NBAFranchiseRunnerError(str(error)) from error


def _apply_retention(
    directory: Path,
    checkpoints: list[object],
    *,
    initial_completed_seasons: int,
    latest_completed_seasons: int,
    policy: NBAFranchiseRetentionPolicy,
) -> None:
    for value in checkpoints:
        checkpoint = _object(value, "franchise checkpoint entry")
        completed = _integer(checkpoint, "completed_seasons")
        age = latest_completed_seasons - completed
        retain = (
            completed == initial_completed_seasons
            or age < policy.keep_last
            or (completed - initial_completed_seasons) % policy.keep_every == 0
        )
        path = directory / _string(checkpoint, "path")
        storage = _string(checkpoint, "storage")
        if not retain:
            path.unlink(missing_ok=True)
            checkpoint["storage"] = "pruned"
            continue
        if age < policy.compress_after or storage != "json":
            continue
        state, rules, _ = load_nba_franchise_checkpoint(
            path,
            expected_file_sha256=_string(checkpoint, "file_sha256"),
        )
        compressed_name = _checkpoint_name(completed, compressed=True)
        receipt = write_nba_franchise_checkpoint(
            state,
            rules,
            directory / compressed_name,
            compress=True,
        )
        path.unlink(missing_ok=True)
        checkpoint["path"] = compressed_name
        checkpoint["file_sha256"] = receipt.file_sha256
        checkpoint["storage"] = "gzip"


def _spec_to_dict(spec: NBAFranchiseRunSpec) -> dict[str, object]:
    return {
        "run_id": spec.run_id,
        "master_seed": spec.master_seed,
        "seasons": spec.seasons,
        "version": spec.version,
    }


def _spec_from_dict(value: object) -> NBAFranchiseRunSpec:
    raw = _object(value, "NBA franchise run spec")
    _exact(raw, {"run_id", "master_seed", "seasons", "version"}, "NBA franchise run spec")
    return NBAFranchiseRunSpec(
        _string(raw, "run_id"),
        _integer(raw, "master_seed"),
        _integer(raw, "seasons"),
        _string(raw, "version"),
    )


def _object(value: object, field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
        raise NBAFranchiseRunnerError(f"{field} must be an object")
    return cast(dict[str, Any], value)


def _list(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise NBAFranchiseRunnerError(f"{field} must be a list")
    return cast(list[object], value)


def _exact(value: dict[str, Any], keys: set[str], field: str) -> None:
    if set(value) != keys:
        raise NBAFranchiseRunnerError(f"{field} keys must be exactly {sorted(keys)}")


def _integer(value: dict[str, Any], key: str) -> int:
    item = value[key]
    if not isinstance(item, int) or isinstance(item, bool):
        raise NBAFranchiseRunnerError(f"{key} must be an integer")
    return item


def _optional_integer(value: dict[str, Any], key: str) -> int | None:
    item = value[key]
    if item is None:
        return None
    return _integer(value, key)


def _string(value: dict[str, Any], key: str) -> str:
    item = value[key]
    if not isinstance(item, str) or not item:
        raise NBAFranchiseRunnerError(f"{key} must be a non-empty string")
    return item
