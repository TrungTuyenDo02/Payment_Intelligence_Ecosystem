"""Shared fixtures: a small synthetic dataset shaped like IEEE-CIS (no real data)."""

from collections.abc import Callable
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from dataset_management.manifest import build_manifest, write_manifest

SyntheticFactory = Callable[..., tuple[pd.DataFrame, pd.DataFrame]]


def make_synthetic_ieee(n: int = 2000, seed: int = 0) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (train_transaction, train_identity) frames with IEEE-CIS column names."""
    rng = np.random.default_rng(seed)
    dt = 86_400 + np.cumsum(rng.exponential(5_000, n)).round(-2).astype("int64")  # ties exist
    product = rng.choice(["W", "C", "R", "H", "S"], n, p=[0.6, 0.15, 0.1, 0.1, 0.05])
    amount = np.round(np.exp(rng.normal(4.0, 1.0, n)), 2)
    c_cols = {f"C{i}": rng.poisson(1 + i % 3, n).astype(float) for i in range(1, 15)}
    logit = -3.6 + 1.5 * (product == "C") + 0.9 * (np.log(amount) > 5.0) + 0.15 * c_cols["C1"]
    is_fraud = (rng.random(n) < 1 / (1 + np.exp(-logit))).astype(int)
    txn = pd.DataFrame(
        {
            "TransactionID": np.arange(2_987_000, 2_987_000 + n),
            "isFraud": is_fraud,
            "TransactionDT": dt,
            "TransactionAmt": amount,
            "ProductCD": product,
            "card1": rng.integers(1000, 18000, n),
            "card4": rng.choice(["visa", "mastercard", "american express", None], n),
            "card6": rng.choice(["debit", "credit", None], n, p=[0.7, 0.28, 0.02]),
            "P_emaildomain": rng.choice(["gmail.com", "yahoo.com", "rare.example", None], n),
            **c_cols,
            "D1": np.where(rng.random(n) < 0.2, np.nan, rng.integers(0, 600, n)),
            "M4": rng.choice(["M0", "M1", "M2", None], n),
            **{f"V{i}": np.where(rng.random(n) < 0.3, np.nan, rng.random(n)) for i in range(1, 6)},
        }
    )
    has_id = rng.random(n) < 0.3
    ident = pd.DataFrame(
        {
            "TransactionID": txn.loc[has_id, "TransactionID"].to_numpy(),
            "id_01": rng.normal(-5, 2, has_id.sum()).round(),
            "id_12": rng.choice(["Found", "NotFound"], has_id.sum()),
            "DeviceType": rng.choice(["desktop", "mobile"], has_id.sum()),
        }
    )
    order = rng.permutation(n)  # file rows are not sorted by time
    return txn.iloc[order].reset_index(drop=True), ident


@pytest.fixture
def synthetic_ieee() -> SyntheticFactory:
    """Factory fixture for synthetic IEEE-CIS-shaped frames."""
    return make_synthetic_ieee


def write_ieee_dir(directory: Path, txn: pd.DataFrame, ident: pd.DataFrame) -> Path:
    """Write the frames as CSV files plus a manifest; return the manifest path."""
    directory.mkdir(parents=True, exist_ok=True)
    txn.to_csv(directory / "train_transaction.csv", index=False)
    ident.to_csv(directory / "train_identity.csv", index=False)
    manifest = build_manifest(
        name="ieee-cis-synthetic",
        source="synthetic test fixture",
        base_dir=directory,
        files=["train_transaction.csv", "train_identity.csv"],
        license_note="synthetic, no licence restrictions",
        download_date=date(2026, 1, 1),
    )
    out = directory.parent / "manifests" / "ieee-cis.yaml"
    write_manifest(manifest, out)
    return out


@pytest.fixture
def ieee_dir(tmp_path: Path) -> Path:
    """A folder with synthetic train_transaction.csv / train_identity.csv and a manifest."""
    txn, ident = make_synthetic_ieee()
    directory = tmp_path / "raw" / "ieee-cis"
    write_ieee_dir(directory, txn, ident)
    return directory


@pytest.fixture(scope="module")
def ieee_dir_module(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Like `ieee_dir` but larger (3,000 rows) and shared by the tests of one module."""
    directory = tmp_path_factory.mktemp("ieee") / "raw" / "ieee-cis"
    write_ieee_dir(directory, *make_synthetic_ieee(n=3000, seed=3))
    return directory


STAGE_G_CONFIGS = Path(__file__).resolve().parents[1] / "configs"


def stage_g_synthetic_raw(time: pd.Series, base: str) -> dict:
    """A real Stage G config with blocks re-cut for the synthetic validation days."""
    import yaml
    from fraud_risk.evaluation.split import DAY_SECONDS, time_split

    raw = yaml.safe_load((STAGE_G_CONFIGS / base).read_text("utf-8"))
    split = time_split(time, raw["split"]["train_frac"], raw["split"]["valid_frac"])
    days = sorted(int(d) for d in (time.loc[split.valid] // DAY_SECONDS).unique())
    a, b = days[len(days) // 3], days[2 * len(days) // 3]
    raw["blocks"] = {"V1": [days[0], a - 1], "V2": [a, b - 1], "V3": [b, days[-1]]}
    raw["check"] = {}  # synthetic data: no Stage E numbers to reproduce
    raw["models"]["gbm"] = {"learning_rate": 0.1, "max_iter": 30, "max_leaf_nodes": 7}
    return raw


@pytest.fixture(scope="session")
def stage_g_raw() -> Callable[[pd.Series, str], dict]:
    """Factory: (time, config file name) -> synthetic Stage G config dict."""
    return stage_g_synthetic_raw
