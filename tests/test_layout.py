"""Smoke tests: repository layout, .gitignore rules and import paths (T01)."""

import importlib
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

REQUIRED_DIRS = [
    "contracts/payment-event",
    "contracts/risk-context",
    "shared/synthetic-generator",
    "shared/data-validation",
    "shared/dataset-management",
    "shared/common",
    "datasets/manifests",
    "projects/payment-reliability",
    "projects/fraud-risk/fraud_risk/adapters",
    "projects/fraud-risk/fraud_risk/features",
    "projects/fraud-risk/fraud_risk/eda",
    "projects/fraud-risk/fraud_risk/evaluation",
    "projects/fraud-risk/fraud_risk/baselines",
    "projects/fraud-risk/fraud_risk/scripts",
    "projects/fraud-risk/configs",
    "projects/fraud-risk/tests",
    "infrastructure/docker",
    "infrastructure/database",
    "docs/architecture",
    "docs/product",
    "docs/data-governance",
    "docs/data-analysis",
    "docs/decisions",
    "tests",
]

REQUIRED_FILES = [
    "docs/decisions/0001-package-layout.md",
    "compose.yaml",
    ".env.example",
    ".gitignore",
    "Makefile",
    "pyproject.toml",
    "README.md",
    "datasets/README.md",
]

MUST_BE_IGNORED = [
    "datasets/raw/x.csv",
    "datasets/raw/ieee-cis/train_transaction.csv",
    "artifacts/runs/abc/metrics.json",
    "some/where/data.parquet",
    "some/where/data.csv",
    "artifacts/eda/02_missing.csv",
    ".env",
    "model.joblib",
    "model.pkl",
]

MUST_NOT_BE_IGNORED = [
    ".env.example",
    "projects/fraud-risk/tests/fixtures/mini.csv",
    "projects/fraud-risk/configs/baseline.yaml",
]


@pytest.mark.parametrize("rel", REQUIRED_DIRS)
def test_required_dir_exists(rel: str) -> None:
    assert (ROOT / rel).is_dir(), f"missing folder: {rel}"


@pytest.mark.parametrize("rel", REQUIRED_FILES)
def test_required_file_exists(rel: str) -> None:
    assert (ROOT / rel).is_file(), f"missing file: {rel}"


@pytest.mark.parametrize("rel", REQUIRED_DIRS)
def test_folder_without_code_has_readme(rel: str) -> None:
    folder = ROOT / rel
    has_content = any(p.name != "README.md" for p in folder.iterdir())
    assert has_content or (folder / "README.md").is_file(), f"empty folder without README: {rel}"


def _git_ignored(rel: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "-q", rel],
        cwd=ROOT,
        check=False,
    )
    if result.returncode not in (0, 1):
        pytest.fail(f"git check-ignore failed for {rel} (code {result.returncode})")
    return result.returncode == 0


@pytest.fixture(scope="module", autouse=False)
def git_repo() -> None:
    if shutil.which("git") is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout; .gitignore rules cannot be checked")


@pytest.mark.parametrize("rel", MUST_BE_IGNORED)
def test_path_is_ignored(git_repo: None, rel: str) -> None:
    assert _git_ignored(rel), f"{rel} must be git-ignored"


@pytest.mark.parametrize("rel", MUST_NOT_BE_IGNORED)
def test_path_is_not_ignored(git_repo: None, rel: str) -> None:
    assert not _git_ignored(rel), f"{rel} must NOT be git-ignored"


@pytest.mark.parametrize("module", ["fraud_risk", "dataset_management"])
def test_package_importable(module: str) -> None:
    importlib.import_module(module)
