"""Dataset manifests: SHA-256 checksums plus provenance for files the owner supplies."""

import hashlib
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

CHUNK_SIZE = 1024 * 1024


class DatasetFileNotFoundError(FileNotFoundError):
    """A dataset file listed for the manifest is not on disk."""


class ChecksumMismatchError(ValueError):
    """A file on disk no longer matches the checksum stored in the manifest."""


class ManifestFile(BaseModel):
    """One file of a dataset, path relative to the dataset folder."""

    model_config = ConfigDict(extra="forbid")

    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)


class DatasetManifest(BaseModel):
    """Provenance and integrity record for one dataset."""

    model_config = ConfigDict(extra="forbid")

    name: str
    source: str
    version: str | None = None
    license_note: str
    download_date: date
    files: list[ManifestFile] = Field(min_length=1)

    @property
    def checksum(self) -> str:
        """Single SHA-256 over all files (order-independent), used in run hashes."""
        lines = sorted(f"{f.path}:{f.sha256}" for f in self.files)
        return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    """Return the hex SHA-256 of a file, reading it in chunks."""
    if not path.is_file():
        raise DatasetFileNotFoundError(f"dataset file not found: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    *,
    name: str,
    source: str,
    base_dir: Path,
    files: list[str],
    license_note: str,
    download_date: date,
    version: str | None = None,
) -> DatasetManifest:
    """Hash each file under `base_dir` and return a manifest. Fails if any file is missing."""
    missing = [f for f in files if not (base_dir / f).is_file()]
    if missing:
        raise DatasetFileNotFoundError(
            "dataset file(s) not found: "
            + ", ".join(str(base_dir / f) for f in missing)
            + ". Place the files there yourself (agents never download data)."
        )
    entries = [
        ManifestFile(
            path=f, sha256=sha256_file(base_dir / f), size_bytes=(base_dir / f).stat().st_size
        )
        for f in sorted(files)
    ]
    return DatasetManifest(
        name=name,
        source=source,
        version=version,
        license_note=license_note,
        download_date=download_date,
        files=entries,
    )


def write_manifest(manifest: DatasetManifest, out_path: Path) -> None:
    """Write the manifest as YAML (stable key order)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    data = manifest.model_dump(mode="json")
    data["checksum"] = manifest.checksum
    out_path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), "utf-8")


def load_manifest(path: Path) -> DatasetManifest:
    """Read a manifest YAML and check its stored combined checksum."""
    if not path.is_file():
        raise DatasetFileNotFoundError(f"dataset manifest not found: {path}")
    data = yaml.safe_load(path.read_text("utf-8"))
    stored = data.pop("checksum", None)
    manifest = DatasetManifest.model_validate(data)
    if stored is not None and stored != manifest.checksum:
        raise ChecksumMismatchError(f"{path}: stored checksum does not match its file list")
    return manifest


def verify_files(manifest: DatasetManifest, base_dir: Path, paths: list[str]) -> None:
    """Check that the given files on disk still match the manifest."""
    by_path = {f.path: f for f in manifest.files}
    for rel in paths:
        if rel not in by_path:
            raise ChecksumMismatchError(f"{rel} is not listed in manifest '{manifest.name}'")
        actual = sha256_file(base_dir / rel)
        if actual != by_path[rel].sha256:
            raise ChecksumMismatchError(
                f"{base_dir / rel} changed since the manifest was written "
                f"(expected {by_path[rel].sha256[:12]}…, got {actual[:12]}…). "
                "Regenerate the manifest only if the change is intended."
            )
