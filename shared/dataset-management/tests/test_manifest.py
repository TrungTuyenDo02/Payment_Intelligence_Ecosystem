"""Tests for dataset manifest tooling (T03)."""

import hashlib
from datetime import date
from pathlib import Path

import pytest
import yaml
from dataset_management.cli import main
from dataset_management.manifest import (
    ChecksumMismatchError,
    DatasetFileNotFoundError,
    DatasetManifest,
    build_manifest,
    load_manifest,
    sha256_file,
    verify_files,
    write_manifest,
)

ABC_SHA256 = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
NOTE = "Kaggle competition terms, research use only, verify before any other use"


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    d = tmp_path / "raw"
    d.mkdir()
    (d / "a.csv").write_bytes(b"abc")
    (d / "b.csv").write_bytes(b"x,y\n1,2\n")
    return d


def _build(data_dir: Path, files: list[str]) -> DatasetManifest:
    return build_manifest(
        name="demo",
        source="unit test",
        base_dir=data_dir,
        files=files,
        license_note=NOTE,
        download_date=date(2026, 10, 1),
    )


def test_sha256_known_value(data_dir: Path) -> None:
    assert sha256_file(data_dir / "a.csv") == ABC_SHA256


def test_sha256_large_file_chunked(tmp_path: Path) -> None:
    payload = b"0123456789" * 300_000  # 3 MB, more than one chunk
    p = tmp_path / "big.bin"
    p.write_bytes(payload)
    assert sha256_file(p) == hashlib.sha256(payload).hexdigest()


def test_round_trip_and_checksum_stable(data_dir: Path, tmp_path: Path) -> None:
    m = _build(data_dir, ["b.csv", "a.csv"])
    out = tmp_path / "manifests" / "demo.yaml"
    write_manifest(m, out)
    loaded = load_manifest(out)
    assert loaded == m
    assert loaded.checksum == _build(data_dir, ["a.csv", "b.csv"]).checksum
    raw = yaml.safe_load(out.read_text())
    assert raw["license_note"] == NOTE
    assert raw["download_date"] == "2026-10-01"
    assert [f["path"] for f in raw["files"]] == ["a.csv", "b.csv"]


def test_missing_file_fails_clearly(data_dir: Path) -> None:
    with pytest.raises(DatasetFileNotFoundError, match="missing.csv"):
        _build(data_dir, ["a.csv", "missing.csv"])


def test_verify_detects_changed_file(data_dir: Path) -> None:
    m = _build(data_dir, ["a.csv"])
    verify_files(m, data_dir, ["a.csv"])
    (data_dir / "a.csv").write_bytes(b"abd")
    with pytest.raises(ChecksumMismatchError, match="changed since"):
        verify_files(m, data_dir, ["a.csv"])


def test_tampered_manifest_rejected(data_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "demo.yaml"
    write_manifest(_build(data_dir, ["a.csv"]), out)
    raw = yaml.safe_load(out.read_text())
    raw["files"][0]["sha256"] = "0" * 64
    out.write_text(yaml.safe_dump(raw))
    with pytest.raises(ChecksumMismatchError):
        load_manifest(out)


def test_cli_writes_manifest(data_dir: Path, tmp_path: Path) -> None:
    out = tmp_path / "m.yaml"
    args = ["--name", "demo", "--source", "s", "--base-dir", str(data_dir), "--file", "a.csv"]
    args += ["--download-date", "2026-10-01", "--license-note", NOTE, "--out", str(out)]
    assert main(args) == 0
    assert load_manifest(out).files[0].sha256 == ABC_SHA256


def test_cli_missing_file_exit_code(
    data_dir: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["--name", "demo", "--source", "s", "--base-dir", str(data_dir), "--file", "nope.csv"]
    args += ["--download-date", "2026-10-01", "--license-note", NOTE]
    args += ["--out", str(tmp_path / "m.yaml")]
    assert main(args) == 2
    assert "nope.csv" in capsys.readouterr().err
    assert not (tmp_path / "m.yaml").exists()
