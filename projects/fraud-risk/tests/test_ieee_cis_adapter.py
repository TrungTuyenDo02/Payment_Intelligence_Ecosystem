"""Tests for the IEEE-CIS adapter (T04), on synthetic data only."""

from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest
from fraud_risk.adapters.ieee_cis import (
    LABEL,
    TIME,
    DatasetNotFoundError,
    IeeeCisSchemaError,
    load_ieee_cis,
    resolve_data_dir,
)


def test_outputs_x_y_time(ieee_dir: Path) -> None:
    data = load_ieee_cis(ieee_dir)
    assert LABEL not in data.X.columns
    assert len(data.X) == len(data.y) == len(data.time) == 2000
    assert data.X.index.equals(data.y.index) and data.X.index.equals(data.time.index)
    assert data.time.name == TIME and data.y.dtype == "int8"
    assert data.row_counts == {
        "transaction_rows": 2000,
        "fraud_rows": int(data.y.sum()),
        "output_rows": 2000,
    }
    assert data.unexpected_columns == []


def test_explicit_dtypes(ieee_dir: Path) -> None:
    X = load_ieee_cis(ieee_dir).X
    assert X["TransactionAmt"].dtype == "float64"
    assert X["C1"].dtype == "float64"
    assert X["V1"].dtype == "float32"
    assert X["ProductCD"].dtype == object
    assert X["card4"].isna().any()  # missing kept as NaN, not the string "nan"


def test_identity_join_optional(ieee_dir: Path) -> None:
    plain = load_ieee_cis(ieee_dir)
    joined = load_ieee_cis(ieee_dir, use_identity=True)
    assert "DeviceType" not in plain.X.columns
    assert "DeviceType" in joined.X.columns
    assert len(joined.X) == len(plain.X)
    assert 0 < joined.row_counts["transaction_rows_with_identity"] < 2000


def test_parquet_written(ieee_dir: Path, tmp_path: Path) -> None:
    load_ieee_cis(ieee_dir, parquet_dir=tmp_path / "artifacts")
    frame = pd.read_parquet(tmp_path / "artifacts" / "train_transaction.parquet")
    assert len(frame) == 2000


def test_missing_file_clear_error(tmp_path: Path) -> None:
    with pytest.raises(DatasetNotFoundError, match="dataset not found.*train_transaction.csv"):
        load_ieee_cis(tmp_path)


def test_identity_missing_only_when_requested(ieee_dir: Path) -> None:
    (ieee_dir / "train_identity.csv").unlink()
    load_ieee_cis(ieee_dir)
    with pytest.raises(DatasetNotFoundError, match="train_identity.csv"):
        load_ieee_cis(ieee_dir, use_identity=True)


def test_env_var_override(monkeypatch: pytest.MonkeyPatch, ieee_dir: Path) -> None:
    monkeypatch.setenv("IEEE_CIS_DIR", str(ieee_dir))
    assert resolve_data_dir() == ieee_dir
    assert resolve_data_dir("other") == Path("other")


def test_missing_required_column(ieee_dir: Path) -> None:
    path = ieee_dir / "train_transaction.csv"
    pd.read_csv(path).drop(columns=["TransactionAmt"]).to_csv(path, index=False)
    with pytest.raises(IeeeCisSchemaError, match="TransactionAmt"):
        load_ieee_cis(ieee_dir)


def test_unexpected_column_reported(ieee_dir: Path) -> None:
    path = ieee_dir / "train_transaction.csv"
    pd.read_csv(path).assign(surprise=1).to_csv(path, index=False)
    assert load_ieee_cis(ieee_dir).unexpected_columns == ["surprise"]


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda df: pd.concat([df, df.head(1)]), "duplicate"),
        (lambda df: df.assign(isFraud=df["isFraud"].replace({1: 2})), "0/1"),
        (lambda df: df.assign(TransactionAmt="abc"), "dtypes"),
    ],
)
def test_bad_values_rejected(
    ieee_dir: Path, mutation: Callable[[pd.DataFrame], pd.DataFrame], message: str
) -> None:
    path = ieee_dir / "train_transaction.csv"
    mutation(pd.read_csv(path)).to_csv(path, index=False)
    with pytest.raises(IeeeCisSchemaError, match=message):
        load_ieee_cis(ieee_dir)
