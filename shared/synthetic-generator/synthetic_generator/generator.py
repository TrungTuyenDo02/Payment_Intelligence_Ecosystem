"""Rule-based event generation (Stage C spec section 3). No anomalies yet (C03)."""

import math
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from synthetic_generator.config import RETRYABLE_ERRORS, SimulationConfig, simulation_id

HOUR_MS = 3_600_000
LOCAL_OFFSET_HOURS = 7  # Asia/Ho_Chi_Minh has no DST
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def provider_ids(config: SimulationConfig) -> list[str]:
    return [f"prov_{i + 1:03d}" for i in range(len(config.providers))]


def merchant_ids(config: SimulationConfig) -> list[str]:
    return [f"mer_{i + 1:04d}" for i in range(config.n_merchants)]


def format_time(ms: int) -> str:
    """UTC ISO 8601 with milliseconds and a trailing Z (contract `event_time`)."""
    return (EPOCH + timedelta(milliseconds=ms)).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _lognormal(rng: np.random.Generator, median: float, sigma: float) -> float:
    return float(rng.lognormal(math.log(median), sigma))


def _choice(rng: np.random.Generator, weights: dict[str, float]) -> str:
    keys = list(weights)
    p = np.array([weights[k] for k in keys], dtype=float)
    return keys[int(rng.choice(len(keys), p=p / p.sum()))]


def _hourly_intensity(config: SimulationConfig) -> list[float]:
    """Expected payments for each UTC hour, seasonality applied in local time."""
    hod, dow = config.time.hour_of_day_factors, config.time.day_of_week_factors
    hod_mean, dow_mean = sum(hod) / 24, sum(dow) / 7
    start = datetime.combine(config.time.start_date, datetime.min.time(), tzinfo=UTC)
    out = []
    for h in range(config.time.days * 24):
        local = start + timedelta(hours=h + LOCAL_OFFSET_HOURS)
        factor = (hod[local.hour] / hod_mean) * (dow[local.weekday()] / dow_mean)
        out.append(config.payments_per_hour * factor)
    return out


def generate_events(config: SimulationConfig) -> list[dict[str, Any]]:
    """All events of one simulation, sorted by event_time then event_id. Deterministic per seed."""
    rng = np.random.default_rng(config.seed)
    sid = simulation_id(config)
    tag = sid.removeprefix("sim-")  # keeps ids unique across simulations in one database
    providers, merchants = provider_ids(config), merchant_ids(config)
    m_weights = {m: 1 / (i + 1) ** config.merchant_zipf_s for i, m in enumerate(merchants)}
    start_ms = int(
        (datetime.combine(config.time.start_date, datetime.min.time(), tzinfo=UTC) - EPOCH)
        / timedelta(milliseconds=1)
    )
    retry = config.retry

    attempts: list[
        tuple[int, int, int, dict[str, Any]]
    ] = []  # (event_ms, payment, attempt, payload)
    n_payment = 0
    for hour, lam in enumerate(_hourly_intensity(config)):
        offsets = np.sort(rng.integers(0, HOUR_MS, size=int(rng.poisson(lam))))
        for offset in offsets:
            n_payment += 1
            payment_id = f"pay-{tag}-{n_payment:06d}"
            method = _choice(rng, dict(config.method_weights))
            amount_cfg = config.amounts[method]
            amount = max(1000, round(_lognormal(rng, amount_cfg.median_vnd, amount_cfg.sigma), -3))
            merchant = _choice(rng, m_weights)
            # shortcut: first-attempt provider is uniform; add provider weights to config if needed
            provider = int(rng.integers(len(providers)))
            t = start_ms + hour * HOUR_MS + int(offset)
            attempt = 0
            while True:
                attempt += 1
                p_cfg = config.providers[provider]
                failed = bool(rng.random() < p_cfg.failure_prob)
                error = _choice(rng, dict(config.error_code_weights)) if failed else None
                if error == "TIMEOUT":
                    latency = config.timeout_ms
                else:
                    raw = _lognormal(rng, p_cfg.latency_median_ms, p_cfg.latency_sigma)
                    latency = min(config.timeout_ms - 1, round(raw))
                t += latency
                attempts.append(
                    (
                        t,
                        n_payment,
                        attempt,
                        {
                            "payment_id": payment_id,
                            "attempt_id": f"att-{tag}-{n_payment:06d}-{attempt}",
                            "attempt_number": attempt,
                            "provider_id": providers[provider],
                            "merchant_id": merchant,
                            "payment_method": method,
                            "amount": int(amount),
                            "currency": "VND",
                            "status": "FAILED" if failed else "SUCCESS",
                            "error_code": error,
                            "latency_ms": int(latency),
                        },
                    )
                )
                if not (
                    error in RETRYABLE_ERRORS
                    and attempt <= retry.max_retries
                    and rng.random() < retry.retry_prob
                ):
                    break
                t += round(rng.uniform(retry.wait_seconds_min, retry.wait_seconds_max) * 1000)
                if rng.random() < retry.retry_switch_provider_prob:
                    others = [i for i in range(len(providers)) if i != provider]
                    provider = others[int(rng.integers(len(others)))]

    attempts.sort(key=lambda a: (a[0], a[1], a[2]))
    return [
        {
            "event_id": f"evt-{tag}-{i + 1:07d}",
            "event_type": "payment.attempt.completed",
            "schema_version": "1.0.0",
            "event_time": format_time(ms),
            "source_system": "synthetic_generator",
            "simulation_id": sid,
            "payload": payload,
        }
        for i, (ms, _, _, payload) in enumerate(attempts)
    ]
