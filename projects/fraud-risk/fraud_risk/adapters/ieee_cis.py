"""IEEE-CIS Fraud Detection adapter: CSV -> (X, y, time) with explicit dtypes.

Only the labelled `train_*` files are used. Kaggle's `test_*` files have no labels and
are never read here. The owner places the files; nothing is downloaded.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

LABEL = "isFraud"
TIME = "TransactionDT"
ID = "TransactionID"
TRANSACTION_FILE = "train_transaction.csv"
IDENTITY_FILE = "train_identity.csv"
DEFAULT_DIR = Path("datasets/raw/ieee-cis")
ENV_VAR = "IEEE_CIS_DIR"

REQUIRED_TRANSACTION_COLUMNS = [ID, LABEL, TIME, "TransactionAmt", "ProductCD"]

_TXN_CATEGORICAL = ["ProductCD", "card4", "card6", "P_emaildomain", "R_emaildomain"] + [
    f"M{i}" for i in range(1, 10)
]
_TXN_NUMERIC = (
    ["TransactionAmt", "card1", "card2", "card3", "card5", "addr1", "addr2", "dist1", "dist2"]
    + [f"C{i}" for i in range(1, 15)]
    + [f"D{i}" for i in range(1, 16)]
)
_ID_CATEGORICAL_NUMBERS = [12, 15, 16, 23, 27, 28, 29, 30, 31, 33, 34, 35, 36, 37, 38]
_ID_CATEGORICAL = [f"id_{i:02d}" for i in _ID_CATEGORICAL_NUMBERS] + ["DeviceType", "DeviceInfo"]
_ID_NUMERIC = [f"id_{i:02d}" for i in range(1, 39) if i not in _ID_CATEGORICAL_NUMBERS]

TRANSACTION_DTYPES: dict[str, str] = {
    ID: "int64",
    LABEL: "int8",
    TIME: "int64",
    **{c: "float64" for c in _TXN_NUMERIC},
    **{c: "object" for c in _TXN_CATEGORICAL},
    **{f"V{i}": "float32" for i in range(1, 340)},
}
IDENTITY_DTYPES: dict[str, str] = {
    ID: "int64",
    **{c: "float64" for c in _ID_NUMERIC},
    **{c: "object" for c in _ID_CATEGORICAL},
}


class DatasetNotFoundError(FileNotFoundError):
    """The IEEE-CIS files are not where the owner is expected to put them."""


class IeeeCisSchemaError(ValueError):
    """The CSV columns or values differ from what this adapter assumes."""


@dataclass(frozen=True)
class IeeeCisData:
    """Adapter output. `X` never contains the label column."""

    X: pd.DataFrame
    y: pd.Series
    time: pd.Series
    row_counts: dict[str, int]
    unexpected_columns: list[str] = field(default_factory=list)


def resolve_data_dir(data_dir: Path | str | None = None) -> Path:
    """Argument > `IEEE_CIS_DIR` env var > `datasets/raw/ieee-cis`."""
    if data_dir is not None:
        return Path(data_dir)
    return Path(os.environ.get(ENV_VAR, DEFAULT_DIR))


def required_files(use_identity: bool = False) -> list[str]:
    """File names needed for a load."""
    return [TRANSACTION_FILE, IDENTITY_FILE] if use_identity else [TRANSACTION_FILE]


def check_files(data_dir: Path, use_identity: bool = False) -> None:
    """Raise `DatasetNotFoundError` naming each missing file and where to put it."""
    missing = [f for f in required_files(use_identity) if not (data_dir / f).is_file()]
    if missing:
        raise DatasetNotFoundError(
            f"dataset not found: missing {', '.join(missing)} in '{data_dir}'. "
            f"Download IEEE-CIS from Kaggle yourself (login + competition terms), place the "
            f"files in '{DEFAULT_DIR}/' or set {ENV_VAR}. Only train_* files are used."
        )


def _read_csv(path: Path, known_dtypes: dict[str, str]) -> tuple[pd.DataFrame, list[str]]:
    header = pd.read_csv(path, nrows=0).columns.tolist()
    dtypes = {c: t for c, t in known_dtypes.items() if c in header}
    unexpected = [c for c in header if c not in known_dtypes]
    try:
        frame = pd.read_csv(path, dtype=dtypes)
    except (ValueError, TypeError) as err:
        raise IeeeCisSchemaError(
            f"{path.name}: values do not match expected dtypes: {err}"
        ) from err
    return frame, unexpected


def read_transactions(path: Path | str) -> pd.DataFrame:
    """One transaction CSV read with the same dtypes as `load_ieee_cis` (G08 batch scoring)."""
    frame, _ = _read_csv(Path(path), TRANSACTION_DTYPES)
    return frame


def load_ieee_cis(
    data_dir: Path | str | None = None,
    *,
    use_identity: bool = False,
    parquet_dir: Path | None = None,
) -> IeeeCisData:
    """Read IEEE-CIS train files and split them into features, label and time.

    The identity join is optional and off by default. When `parquet_dir` is given the
    joined frame (with label) is also written there as Parquet.
    """
    directory = resolve_data_dir(data_dir)
    check_files(directory, use_identity)

    txn, unexpected = _read_csv(directory / TRANSACTION_FILE, TRANSACTION_DTYPES)
    missing = [c for c in REQUIRED_TRANSACTION_COLUMNS if c not in txn.columns]
    if missing:
        raise IeeeCisSchemaError(f"{TRANSACTION_FILE}: missing required columns {missing}")
    if txn[ID].duplicated().any():
        raise IeeeCisSchemaError(f"{TRANSACTION_FILE}: duplicate {ID} values")
    if txn[[LABEL, TIME]].isna().any().any():
        raise IeeeCisSchemaError(f"{TRANSACTION_FILE}: missing values in {LABEL} or {TIME}")
    if not set(txn[LABEL].unique()) <= {0, 1}:
        raise IeeeCisSchemaError(f"{TRANSACTION_FILE}: {LABEL} must be 0/1")

    counts = {"transaction_rows": len(txn), "fraud_rows": int(txn[LABEL].sum())}
    frame = txn
    if use_identity:
        ident, unexpected_id = _read_csv(directory / IDENTITY_FILE, IDENTITY_DTYPES)
        if ID not in ident.columns:
            raise IeeeCisSchemaError(f"{IDENTITY_FILE}: missing required column {ID}")
        unexpected += unexpected_id
        counts["identity_rows"] = len(ident)
        frame = txn.merge(ident, on=ID, how="left", validate="one_to_one")
        counts["transaction_rows_with_identity"] = int(txn[ID].isin(ident[ID]).sum())
    counts["output_rows"] = len(frame)

    if parquet_dir is not None:
        parquet_dir.mkdir(parents=True, exist_ok=True)
        name = "train_joined.parquet" if use_identity else "train_transaction.parquet"
        frame.to_parquet(parquet_dir / name, index=False)

    frame = frame.set_index(ID)
    y = frame[LABEL].astype("int8")
    X = frame.drop(columns=[LABEL])
    return IeeeCisData(
        X=X, y=y, time=frame[TIME].copy(), row_counts=counts, unexpected_columns=unexpected
    )
