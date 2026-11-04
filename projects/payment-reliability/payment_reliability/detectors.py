"""Anomaly detectors on KPI time series (stage-d-spec.md section 4).

Input is KPI tables only. This module never reads ground-truth labels; a test checks that.

Each series is one KPI of one target, with a count `k` and a size `n` per 15-minute bucket:

| metric                   | target            | value                | anomalous when |
| ------------------------ | ----------------- | -------------------- | -------------- |
| `technical_failure_rate` | provider or `ALL` | k / n                | higher         |
| `latency_p50`            | provider or `ALL` | log(median latency)  | higher         |
| `method_share`           | payment method    | k / n of new payments| lower          |

Two detectors give a score per bucket (larger = more anomalous, already sign-adjusted):

- D-A `robust_z`: (value - median) / (1.4826 * MAD) of the previous `baseline_buckets` values.
  Simple, but blind to how many attempts a value is based on.
- D-B `pooled`: pools the last `pool_buckets` buckets. Rates: binomial z-score of the pooled count
  against the rate of the baseline window before it. Latency: n-weighted mean of log medians,
  scaled by sqrt(pooled n). Fewer attempts give a smaller score for the same rate change.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

MAD_TO_SD = 1.4826
EPS = 1e-4


@dataclass(frozen=True)
class Series:
    """One KPI of one target, aligned on consecutive 15-minute buckets."""

    target_type: str  # "provider" or "method"
    target: str
    metric: str
    direction: int  # +1: anomalous when higher, -1: when lower
    buckets: pd.DatetimeIndex
    k: np.ndarray  # count (rates) or NaN (latency)
    n: np.ndarray  # attempts the value is based on
    value: np.ndarray  # NaN when n == 0


def build_series(kpis: dict[str, pd.DataFrame]) -> list[Series]:
    """All series of one simulation from the KPI tables written by `make kpi`."""
    out = []
    prov = kpis["provider_15m"]
    for target, g in prov.groupby("provider_id", sort=True):
        g = g.sort_values("bucket_start")
        buckets = pd.DatetimeIndex(g["bucket_start"])
        n = g["attempts"].to_numpy(float)
        k = g["technical_failures"].to_numpy(float)
        rate = np.where(n > 0, k / np.where(n > 0, n, 1), np.nan)
        out.append(Series("provider", target, "technical_failure_rate", 1, buckets, k, n, rate))
        n_lat = g["latency_attempts"].to_numpy(float)
        p50 = g["latency_p50_ms"].to_numpy(float)
        log_p50 = np.where(n_lat > 0, np.log(np.where(n_lat > 0, p50, 1)), np.nan)
        nan_k = np.full(len(g), np.nan)
        out.append(Series("provider", target, "latency_p50", 1, buckets, nan_k, n_lat, log_p50))
    method = kpis["method_15m"]
    for target, g in method.groupby("payment_method", sort=True):
        g = g.sort_values("bucket_start")
        n = g["all_first_attempts"].to_numpy(float)
        k = g["first_attempts"].to_numpy(float)
        share = np.where(n > 0, k / np.where(n > 0, n, 1), np.nan)
        out.append(
            Series("method", target, "method_share", -1, pd.DatetimeIndex(g["bucket_start"]),
                   k, n, share)
        )  # fmt: skip
    return out


def robust_z(s: Series, baseline_buckets: int, min_history: int) -> np.ndarray:
    """D-A: robust z-score of each bucket against the previous `baseline_buckets` values."""
    score = np.full(len(s.value), np.nan)
    for t in range(len(s.value)):
        if np.isnan(s.value[t]):
            continue
        hist = s.value[max(0, t - baseline_buckets) : t]
        hist = hist[~np.isnan(hist)]
        if len(hist) < min_history:
            continue
        med = np.median(hist)
        spread = max(MAD_TO_SD * np.median(np.abs(hist - med)), EPS)
        score[t] = s.direction * (s.value[t] - med) / spread
    return score


def pooled(s: Series, baseline_buckets: int, min_history: int, pool_buckets: int) -> np.ndarray:
    """D-B: score of the last `pool_buckets` buckets against the baseline window before them."""
    score = np.full(len(s.value), np.nan)
    is_rate = s.metric != "latency_p50"
    for t in range(len(s.value)):
        w0 = t - pool_buckets + 1
        b0 = w0 - baseline_buckets
        if b0 < 0:
            continue
        wn, bn = s.n[w0 : t + 1], s.n[b0:w0]
        if wn.sum() == 0 or (bn > 0).sum() < min_history:
            continue
        if is_rate:
            p0 = min(max(s.k[b0:w0].sum() / bn.sum(), EPS), 1 - EPS)
            big_k, big_n = s.k[w0 : t + 1].sum(), wn.sum()
            z = (big_k - big_n * p0) / np.sqrt(big_n * p0 * (1 - p0))
        else:
            wv, bv = s.value[w0 : t + 1], s.value[b0:w0]
            wm, bm = wn > 0, bn > 0
            level = np.sum(wn[wm] * wv[wm]) / wn[wm].sum()
            base = np.median(bv[bm])
            spread = MAD_TO_SD * np.median(np.abs((bv[bm] - base) * np.sqrt(bn[bm])))
            z = (level - base) * np.sqrt(wn[wm].sum()) / max(spread, EPS)
        score[t] = s.direction * z
    return score


def detect(kpis: dict[str, pd.DataFrame], params: dict) -> pd.DataFrame:
    """Scores and alerts of both detectors for every series and bucket (long format).

    `params` is the `detectors` section of the detector config.
    """
    base, hist = params["baseline_buckets"], params["min_history_buckets"]
    rows = []
    for s in build_series(kpis):
        scores = {
            "robust_z": (robust_z(s, base, hist), params["robust_z"]["threshold"]),
            "pooled": (
                pooled(s, base, hist, params["pooled"]["pool_buckets"]),
                params["pooled"]["threshold"],
            ),
        }
        for name, (score, threshold) in scores.items():
            rows.append(
                pd.DataFrame(
                    {
                        "detector": name,
                        "target_type": s.target_type,
                        "target": s.target,
                        "metric": s.metric,
                        "bucket_start": s.buckets,
                        "score": score,
                        "alert": np.nan_to_num(score, nan=-np.inf) > threshold,
                    }
                )
            )
    return pd.concat(rows, ignore_index=True)
