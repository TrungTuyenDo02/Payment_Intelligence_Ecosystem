"""Stage G shared data: development rows, fixed models and role-tagged validation blocks.

Stage G (stage-g-spec.md, ADR 0009) asks how to turn scores into decisions, on development data
only. This module is the single place that

1. removes test rows (and their labels) before anything else is computed,
2. fits the FIXED models on train (no grid search) and checks they reproduce the Stage E numbers,
3. cuts validation into blocks that carry a role: V1 calibrate, V2 select, V3 evaluate.

Fitting a calibrator or choosing a threshold on a block with the wrong role raises
`BlockRoleError`, so "fit on V3" cannot happen silently.
"""

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from fraud_risk.baselines.logistic import LogisticBaseline
from fraud_risk.evaluation.metrics import pr_auc
from fraud_risk.evaluation.split import DAY_SECONDS, time_split
from fraud_risk.features.baseline_features import FeatureSpec, build_features
from fraud_risk.features.guards import check_label_leakage
from fraud_risk.models.gbm import GbmModel
from fraud_risk.scripts.config import DecisionBase

WEEK_SECONDS = 7 * DAY_SECONDS
ROLES = {"V1": "calibrate", "V2": "select", "V3": "evaluate"}
CONTEXT_COLUMNS = ["TransactionAmt", "card1", "ProductCD", "card6"]  # carried for G04/G05


class BlockRoleError(ValueError):
    """A block was used for a step its role does not allow (e.g. calibrating on V3)."""


class ReproductionError(ValueError):
    """The fixed models do not reproduce the Stage E validation numbers."""


@dataclass(frozen=True)
class Block:
    """Validation rows with a role: `calibrate`, `select` or `evaluate`."""

    name: str
    role: str
    index: pd.Index


def require_role(block: Block, role: str) -> None:
    """Raise unless `block` may be used for `role`."""
    if block.role != role:
        raise BlockRoleError(f"block {block.name} has role {block.role!r}, not {role!r}")


@dataclass(frozen=True)
class DevData:
    """Train + validation rows only. `frame` has labels, scores, time keys and context columns."""

    frame: pd.DataFrame
    features: pd.DataFrame
    train: pd.Index
    valid: pd.Index
    split_boundaries: dict[str, Any]
    train_prevalence: float
    models: dict[str, Any]
    fitted_gbm: GbmModel | None = field(default=None, compare=False, repr=False)  # G08 scorer


def prepare(X: pd.DataFrame, y: pd.Series, time: pd.Series, cfg: DecisionBase) -> DevData:
    """Drop test rows, fit the fixed models on train, score train + validation, check them.

    Only TransactionDT of test rows is read (to place the frozen split boundaries exactly as in
    Stage E); test features and labels are never touched.
    """
    split = time_split(time, cfg.split.train_frac, cfg.split.valid_frac, cfg.split.gap_days)
    valid_max = int(time.loc[split.valid].max())
    if cfg.check.valid_max_time is not None and valid_max != cfg.check.valid_max_time:
        raise ReproductionError(
            f"validation ends at {valid_max}, expected {cfg.check.valid_max_time}"
        )
    dev = split.train.append(split.valid)
    X_dev, y_dev, t_dev = X.loc[dev], y.loc[dev], time.loc[dev]

    spec = FeatureSpec.from_config(cfg.features.model_dump())
    features = build_features(X_dev, spec)
    check_label_leakage(features.loc[split.train], y_dev.loc[split.train])
    y_train = y_dev.loc[split.train]

    gbm = GbmModel(spec.numeric_out, spec.categorical_out, seed=cfg.seed, params=cfg.models.gbm)
    gbm.fit(features.loc[split.train], y_train)
    scores = {"gbm": gbm.score(features)}
    described: dict[str, Any] = {"gbm": gbm.describe()}
    if cfg.models.logistic is not None:
        lr = LogisticBaseline(
            spec.numeric_out, spec.categorical_out, seed=cfg.seed,
            C=cfg.models.logistic.C, max_iter=cfg.models.logistic.max_iter,
        )  # fmt: skip
        lr.fit(features.loc[split.train], y_train)
        scores["logistic"] = lr.score(features)
        described["logistic"] = {"C": cfg.models.logistic.C}

    day = (t_dev // DAY_SECONDS).astype("int64")
    frame = pd.DataFrame(
        {
            "time": t_dev,
            "day": day,
            "part": np.where(t_dev.index.isin(split.valid), "valid", "train"),
            "y": y_dev.astype(int),
            **{c: X_dev[c] for c in CONTEXT_COLUMNS if c in X_dev},
            **{f"score_{m}": s for m, s in scores.items()},
        },
        index=dev,
    )
    t_valid = t_dev.loc[split.valid]
    frame["week"] = -1
    frame.loc[split.valid, "week"] = ((t_valid - t_valid.min()) // WEEK_SECONDS).astype("int64")
    t_train = t_dev.loc[split.train]
    frame["train_week"] = -1
    frame.loc[split.train, "train_week"] = ((t_train - t_train.min()) // WEEK_SECONDS).astype(
        "int64"
    )
    frame["block"] = assign_blocks(frame, cfg)

    data = DevData(
        frame=frame,
        features=features,
        train=split.train,
        valid=split.valid,
        split_boundaries=split.boundaries,
        train_prevalence=float(y_train.mean()),
        models=described,
        fitted_gbm=gbm,
    )
    check_reproduction(data, cfg)
    return data


def assign_blocks(frame: pd.DataFrame, cfg: DecisionBase) -> pd.Series:
    """V1/V2/V3 per validation row ("" for train). Blocks must tile the validation days."""
    out = pd.Series("", index=frame.index, dtype=object)
    valid = frame["part"] == "valid"
    days = frame.loc[valid, "day"]
    ranges = cfg.blocks.model_dump()
    previous_end = None
    for name in ("V1", "V2", "V3"):
        lo, hi = ranges[name]
        if lo > hi or (previous_end is not None and lo != previous_end + 1):
            raise ValueError(f"block {name} {lo}-{hi} must follow the previous block without gap")
        previous_end = hi
        out.loc[days.index[(days >= lo) & (days <= hi)]] = name
    if (out.loc[valid] == "").any() or (out.loc[~valid] != "").any():
        raise ValueError(
            f"blocks {ranges} must cover validation days {days.min()}-{days.max()} exactly"
        )
    return out


def check_reproduction(data: DevData, cfg: DecisionBase) -> dict[str, float]:
    """Validation PR-AUC of each fixed model; raise if it differs from the expected value."""
    valid = data.frame.loc[data.valid]
    found = {}
    expected = {"gbm": cfg.check.gbm_valid_pr_auc, "logistic": cfg.check.logistic_valid_pr_auc}
    for model, target in expected.items():
        column = f"score_{model}"
        if column not in valid:
            continue
        found[model] = pr_auc(valid["y"], valid[column])
        if target is not None and abs(found[model] - target) > cfg.check.tolerance:
            raise ReproductionError(
                f"{model} validation PR-AUC {found[model]:.4f} differs from the expected "
                f"{target} by more than {cfg.check.tolerance}: not the Stage E model"
            )
    return found


def blocks(data: DevData) -> dict[str, Block]:
    """The three main blocks, tagged with their role."""
    frame = data.frame
    return {
        name: Block(name, role, frame.index[frame["block"] == name]) for name, role in ROLES.items()
    }


@dataclass(frozen=True)
class Window:
    """One rolling-origin window (sensitivity analysis, spec section 4)."""

    name: str
    calibrate: Block
    select: Block
    evaluate: Block


def rolling_windows(data: DevData) -> list[Window]:
    """Calibrate on validation week k, select on week k+1, evaluate on week k+2."""
    frame = data.frame.loc[data.valid]
    weeks = sorted(int(w) for w in frame["week"].unique())

    def block(week: int, role: str) -> Block:
        return Block(f"W{week}", role, frame.index[frame["week"] == week])

    return [
        Window(
            f"R{k + 1}",
            block(weeks[k], "calibrate"),
            block(weeks[k + 1], "select"),
            block(weeks[k + 2], "evaluate"),
        )  # fmt: skip
        for k in range(len(weeks) - 2)
    ]


def block_summary(data: DevData) -> list[dict[str, Any]]:
    """Rows, frauds, prevalence and day range per main block (for the report)."""
    rows = []
    for name, block in blocks(data).items():
        part = data.frame.loc[block.index]
        rows.append(
            {
                "block": name,
                "role": block.role,
                "first_day": int(part["day"].min()),
                "last_day": int(part["day"].max()),
                "rows": len(part),
                "frauds": int(part["y"].sum()),
                "prevalence": float(part["y"].mean()),
            }
        )
    return rows


def fmt(x: float | None, d: int = 4) -> str:
    """Number with a decimal comma (Vietnamese reports); `—` for missing."""
    return "—" if x is None else f"{x:.{d}f}".replace(".", ",")


def md_table(header: list[str], rows: list[list[Any]]) -> list[str]:
    """Markdown table lines."""
    out = ["| " + " | ".join(header) + " |", "|" + " --- |" * len(header)]
    return out + ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
