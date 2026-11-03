"""Evaluation metrics for imbalanced fraud labels.

Headline metric is PR-AUC (average precision) with a seeded bootstrap 95% CI.
Accuracy is deliberately not reported: with ~3.5% fraud, predicting "never fraud"
already scores ~96.5% accuracy.
"""

from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import average_precision_score


def _arrays(y_true: Any, scores: Any) -> tuple[np.ndarray, np.ndarray]:
    y = np.asarray(y_true).astype(int)
    s = np.asarray(scores).astype(float)
    if y.shape != s.shape or y.ndim != 1:
        raise ValueError("y_true and scores must be 1-D and the same length")
    if not set(np.unique(y)) <= {0, 1}:
        raise ValueError("y_true must be 0/1")
    return y, s


def pr_auc(y_true: Any, scores: Any) -> float:
    """Average precision (area under the precision-recall curve)."""
    y, s = _arrays(y_true, scores)
    return float(average_precision_score(y, s))


def threshold_metrics(y_true: Any, scores: Any, threshold: float) -> dict[str, float | int]:
    """Precision, recall, F1 and false positive rate, predicting fraud when score >= threshold."""
    y, s = _arrays(y_true, scores)
    pred = s >= threshold
    tp = int((pred & (y == 1)).sum())
    fp = int((pred & (y == 0)).sum())
    fn = int((~pred & (y == 1)).sum())
    tn = int((~pred & (y == 0)).sum())
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "threshold": float(threshold),
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "false_positive_rate": fp / (fp + tn) if fp + tn else 0.0,
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "alerts": tp + fp,
    }


def _cumulative_counts(y: np.ndarray, s: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Distinct thresholds (descending) with TP and FP counts when predicting score >= threshold."""
    order = np.argsort(-s, kind="stable")
    s_sorted, y_sorted = s[order], y[order]
    tp_cum = np.cumsum(y_sorted)
    fp_cum = np.cumsum(1 - y_sorted)
    last_of_value = np.r_[s_sorted[1:] != s_sorted[:-1], True]
    return s_sorted[last_of_value], tp_cum[last_of_value], fp_cum[last_of_value]


def pr_table(y_true: Any, scores: Any) -> pd.DataFrame:
    """Precision/recall/F1 for every distinct score used as threshold (descending)."""
    y, s = _arrays(y_true, scores)
    thresholds, tp, fp = _cumulative_counts(y, s)
    positives = max(int(y.sum()), 1)
    precision = tp / (tp + fp)
    recall = tp / positives
    with np.errstate(invalid="ignore", divide="ignore"):
        f1 = np.where(precision + recall > 0, 2 * precision * recall / (precision + recall), 0.0)
    return pd.DataFrame(
        {
            "threshold": thresholds,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }
    )


def recall_at_precision(y_true: Any, scores: Any, target: float = 0.5) -> dict[str, Any]:
    """Highest recall among thresholds whose precision >= target (ties: highest threshold)."""
    table = pr_table(y_true, scores)
    ok = table[table["precision"] >= target]
    if ok.empty:
        return {"precision_target": target, "recall": 0.0, "threshold": None, "reachable": False}
    best = ok.loc[ok["recall"] == ok["recall"].max()].iloc[0]  # table is threshold-descending
    return {
        "precision_target": target,
        "recall": float(best["recall"]),
        "threshold": float(best["threshold"]),
        "reachable": True,
    }


def recall_at_fpr(y_true: Any, scores: Any, target: float = 0.05) -> dict[str, Any]:
    """Highest recall among thresholds with false positive rate <= target (ties: highest threshold).

    Unlike precision, FPR does not depend on the fraud rate, so this number stays comparable
    across partitions whose prevalence differs. It also reads as an alert budget: at most
    `target` of legitimate transactions are flagged.
    """
    y, s = _arrays(y_true, scores)
    thresholds, tp, fp = _cumulative_counts(y, s)
    positives, negatives = int(y.sum()), int((y == 0).sum())
    fpr = fp / negatives if negatives else np.zeros(len(fp))
    recall = tp / positives if positives else np.zeros(len(tp))
    ok = np.flatnonzero(fpr <= target)
    if ok.size == 0:
        return {
            "fpr_target": target,
            "recall": 0.0,
            "threshold": None,
            "fpr": 0.0,
            "reachable": False,
        }
    best = ok[int(np.argmax(recall[ok]))]  # first max = highest threshold (fewer alerts)
    return {
        "fpr_target": target,
        "recall": float(recall[best]),
        "threshold": float(thresholds[best]),
        "fpr": float(fpr[best]),
        "reachable": True,
    }


def select_threshold(
    y_valid: Any, scores_valid: Any, method: str = "max_f1", precision_target: float = 0.5
) -> float:
    """Choose a decision threshold on VALIDATION data only.

    `max_f1`: threshold with the highest F1 (ties: the highest threshold, i.e. fewer alerts).
    `precision_target`: highest recall with precision >= target; falls back to max F1 if
    the target cannot be reached.
    """
    if method == "precision_target":
        result = recall_at_precision(y_valid, scores_valid, precision_target)
        if result["reachable"]:
            return float(result["threshold"])
    elif method != "max_f1":
        raise ValueError(f"unknown threshold method: {method}")
    table = pr_table(y_valid, scores_valid)
    return float(table.loc[table["f1"].idxmax(), "threshold"])


def bootstrap_pr_auc_ci(
    y_true: Any, scores: Any, n_resamples: int = 200, seed: int = 0, level: float = 0.95
) -> dict[str, Any]:
    """Percentile bootstrap CI for PR-AUC. Resamples with a single class are skipped and counted."""
    y, s = _arrays(y_true, scores)
    rng = np.random.default_rng(seed)
    values, skipped = [], 0
    for _ in range(n_resamples):
        idx = rng.integers(0, len(y), len(y))
        if y[idx].min() == y[idx].max():
            skipped += 1
            continue
        values.append(average_precision_score(y[idx], s[idx]))
    alpha = (1 - level) / 2
    low, high = np.quantile(values, [alpha, 1 - alpha]) if values else (np.nan, np.nan)
    return {
        "level": level,
        "low": float(low),
        "high": float(high),
        "n_resamples": n_resamples,
        "n_skipped": skipped,
        "seed": seed,
    }


def evaluate(
    y_true: Any,
    scores: Any,
    threshold: float,
    *,
    precision_target: float = 0.5,
    fpr_target: float = 0.05,
    n_resamples: int = 200,
    seed: int = 0,
) -> dict[str, Any]:
    """All Stage B metrics for one model on one partition."""
    y, s = _arrays(y_true, scores)
    return {
        "rows": len(y),
        "positives": int(y.sum()),
        "prevalence": float(y.mean()),  # PR-AUC of a random scorer
        "pr_auc": pr_auc(y, s),
        "pr_auc_ci": bootstrap_pr_auc_ci(y, s, n_resamples=n_resamples, seed=seed),
        "at_threshold": threshold_metrics(y, s, threshold),
        "recall_at_precision": recall_at_precision(y, s, precision_target),
        "recall_at_fpr": recall_at_fpr(y, s, fpr_target),
    }
