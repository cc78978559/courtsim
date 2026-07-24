import json
from pathlib import Path

import pytest

from courtsim.verification import VerificationError, verify_manifest


def test_verification_reports_schema_and_missing_files(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "inputs": "wrong",
                "outputs": [None, {}, {"path": "missing.txt", "sha256": "abc"}],
            }
        ),
        encoding="utf-8",
    )
    report = verify_manifest(manifest)
    assert not report.ok
    assert report.checked == 0
    assert len(report.issues) == 4


def test_verification_detects_hash_mismatch(tmp_path: Path) -> None:
    output = tmp_path / "result.json"
    output.write_text("{}", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "inputs": [],
                "outputs": [{"path": output.name, "sha256": "0" * 64}],
            }
        ),
        encoding="utf-8",
    )
    report = verify_manifest(manifest)
    assert report.checked == 1
    assert report.issues == (f"hash mismatch: {output}",)


def test_verification_rejects_invalid_manifest(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(VerificationError, match="cannot read"):
        verify_manifest(missing)
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    with pytest.raises(VerificationError, match=r"invalid\.json"):
        verify_manifest(invalid)
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(VerificationError, match="root"):
        verify_manifest(invalid)
