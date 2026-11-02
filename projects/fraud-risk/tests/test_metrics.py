"""Tests for metrics (T06): handcrafted example, sklearn agreement, seeded bootstrap."""

import numpy as np
import pytest
from fraud_risk.evaluation.metrics import (
    bootstrap_pr_auc_ci,
    evaluate,
    pr_auc,
    recall_at_precision,
    select_threshold,
    threshold_metrics,
)
from sklearn.metrics import average_precision_score, f1_score, precision_score, recall_score

# Hand example: scores sorted descending, labels 1 0 1 0 0 1.
Y = [1, 0, 1, 0, 0, 1]
S = [0.9, 0.8, 0.7, 0.4, 0.3, 0.2]


def test_pr_auc_hand_computed() -> None:
    # AP = sum over positives of precision at that rank / 3 = (1 + 2/3 + 3/6) / 3
    assert pr_auc(Y, S) == pytest.approx((1 + 2 / 3 + 0.5) / 3)
    assert pr_auc(Y, S) == pytest.approx(average_precision_score(Y, S))


def test_threshold_metrics_hand_computed() -> None:
    m = threshold_metrics(Y, S, 0.5)  # predicts 1 1 1 0 0 0
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (2, 1, 1, 2)
    assert m["precision"] == pytest.approx(2 / 3)
    assert m["recall"] == pytest.approx(2 / 3)
    assert m["f1"] == pytest.approx(2 / 3)
    assert m["false_positive_rate"] == pytest.approx(1 / 3)


def test_threshold_metrics_match_sklearn_random() -> None:
    rng = np.random.default_rng(0)
    y = rng.integers(0, 2, 500)
    s = rng.random(500)
    pred = s >= 0.6
    m = threshold_metrics(y, s, 0.6)
    assert m["precision"] == pytest.approx(precision_score(y, pred))
    assert m["recall"] == pytest.approx(recall_score(y, pred))
    assert m["f1"] == pytest.approx(f1_score(y, pred))


def test_threshold_inclusive_and_no_alerts() -> None:
    assert threshold_metrics(Y, S, 0.7)["tp"] == 2  # score == threshold counts as alert
    m = threshold_metrics(Y, S, 2.0)
    assert (m["precision"], m["recall"], m["f1"], m["alerts"]) == (0.0, 0.0, 0.0, 0)


@pytest.mark.parametrize(
    ("target", "recall", "threshold"),
    [
        (0.5, 1.0, 0.2),  # at 0.2: precision 3/6 = 0.5, recall 1
        (0.6, 2 / 3, 0.7),  # at 0.7: precision 2/3, recall 2/3
        (0.9, 1 / 3, 0.9),  # only the top score keeps precision 1
    ],
)
def test_recall_at_precision_hand_computed(target: float, recall: float, threshold: float) -> None:
    r = recall_at_precision(Y, S, target)
    assert r["recall"] == pytest.approx(recall)
    assert r["threshold"] == pytest.approx(threshold)


def test_recall_at_precision_unreachable() -> None:
    r = recall_at_precision([0, 1, 0, 1], [0.9, 0.1, 0.8, 0.2], 0.9)
    assert r == {"precision_target": 0.9, "recall": 0.0, "threshold": None, "reachable": False}


def test_select_threshold() -> None:
    # F1 ties at 0.7 and 0.2 (both 2/3): the higher threshold wins (fewer alerts).
    assert select_threshold(Y, S, "max_f1") == pytest.approx(0.7)
    assert select_threshold(Y, S, "precision_target", 0.6) == pytest.approx(0.7)
    assert select_threshold(Y, S, "precision_target", 0.5) == pytest.approx(0.2)
    with pytest.raises(ValueError):
        select_threshold(Y, S, "accuracy")


def test_bootstrap_seeded_and_reproducible() -> None:
    rng = np.random.default_rng(1)
    y = rng.integers(0, 2, 300)
    s = y * 0.3 + rng.random(300)
    a = bootstrap_pr_auc_ci(y, s, n_resamples=200, seed=7)
    b = bootstrap_pr_auc_ci(y, s, n_resamples=200, seed=7)
    c = bootstrap_pr_auc_ci(y, s, n_resamples=200, seed=8)
    assert a == b
    assert a != c
    assert a["low"] < pr_auc(y, s) < a["high"]


def test_evaluate_has_no_accuracy() -> None:
    result = evaluate(Y, S, 0.5, n_resamples=20, seed=0)
    assert "accuracy" not in str(result)
    assert result["prevalence"] == 0.5
    assert set(result) >= {"pr_auc", "pr_auc_ci", "at_threshold", "recall_at_precision"}


def test_input_validation() -> None:
    with pytest.raises(ValueError):
        pr_auc([0, 1, 2], [0.1, 0.2, 0.3])
    with pytest.raises(ValueError):
        pr_auc([0, 1], [0.1])
