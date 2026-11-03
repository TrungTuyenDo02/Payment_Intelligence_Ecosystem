"""Typed simulation config (shared/synthetic-generator/configs/*.yaml) and simulation_id."""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from synthetic_generator import GENERATOR_VERSION

# Enum values from contracts/payment-event/payment_event.schema.json.
PaymentMethod = Literal["QR", "CARD", "BANK_TRANSFER", "E_WALLET"]
ErrorCode = Literal["TIMEOUT", "PROVIDER_ERROR", "DECLINED", "NETWORK_ERROR", "INVALID_REQUEST"]
# Only technical failures are retried (Stage C spec, decision 7).
RETRYABLE_ERRORS: frozenset[str] = frozenset({"TIMEOUT", "PROVIDER_ERROR", "NETWORK_ERROR"})


class ConfigError(ValueError):
    """The config file is missing or invalid."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _check_weights(weights: dict[str, float], name: str) -> None:
    if not weights or any(w < 0 for w in weights.values()) or sum(weights.values()) <= 0:
        raise ValueError(f"{name}: weights must be >= 0 with a positive sum")


class TimeConfig(_Strict):
    start_date: date  # simulation starts at 00:00 UTC of this day
    days: int = Field(ge=1)
    # Seasonality is applied in local time Asia/Ho_Chi_Minh (UTC+7).
    hour_of_day_factors: list[float] = Field(min_length=24, max_length=24)
    day_of_week_factors: list[float] = Field(min_length=7, max_length=7)  # Monday first

    @model_validator(mode="after")
    def _factors(self) -> Self:
        for name in ("hour_of_day_factors", "day_of_week_factors"):
            if any(f < 0 for f in getattr(self, name)) or sum(getattr(self, name)) <= 0:
                raise ValueError(f"{name}: factors must be >= 0 with a positive sum")
        return self


class ProviderConfig(_Strict):
    failure_prob: float = Field(ge=0, le=1)
    latency_median_ms: float = Field(gt=0)
    latency_sigma: float = Field(ge=0)  # log-normal sigma


class AmountConfig(_Strict):
    median_vnd: float = Field(gt=0)
    sigma: float = Field(ge=0)  # log-normal sigma; amounts are rounded to 1,000 VND


class RetryConfig(_Strict):
    retry_prob: float = Field(ge=0, le=1)
    max_retries: int = Field(ge=0)
    wait_seconds_min: float = Field(ge=0)
    wait_seconds_max: float = Field(ge=0)
    retry_switch_provider_prob: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _wait(self) -> Self:
        if self.wait_seconds_max < self.wait_seconds_min:
            raise ValueError("wait_seconds_max must be >= wait_seconds_min")
        return self


class AnomalyConfig(_Strict):
    type: Literal["provider_outage", "latency_degradation", "error_burst", "traffic_drop"]
    start: datetime  # UTC
    duration_minutes: int = Field(ge=1)
    # Strength multiplier > 1: failure prob x m (outage, burst), latency x m, traffic / m.
    magnitude: float = Field(gt=1)
    provider: int | None = Field(default=None, ge=0)  # index into `providers`
    payment_method: PaymentMethod | None = None
    error_code: ErrorCode | None = None

    @model_validator(mode="after")
    def _targets(self) -> Self:
        needed = {
            "provider_outage": "provider",
            "latency_degradation": "provider",
            "error_burst": "error_code",
            "traffic_drop": "payment_method",
        }[self.type]
        if getattr(self, needed) is None:
            raise ValueError(f"{self.type} needs `{needed}`")
        if self.start.tzinfo is None or self.start.utcoffset() != timedelta(0):
            raise ValueError("anomaly start must be UTC, for example 2026-01-03T10:00:00Z")
        return self


class SimulationConfig(_Strict):
    status: Literal["draft", "frozen"]
    purpose: Literal["tuning", "report"]  # separate seeds for detector tuning and reporting
    seed: int
    time: TimeConfig
    payments_per_hour: float = Field(gt=0)
    n_merchants: int = Field(ge=1)
    merchant_zipf_s: float = Field(ge=0)  # 0 = uniform merchant weights
    providers: list[ProviderConfig] = Field(min_length=1)
    method_weights: dict[PaymentMethod, float]
    amounts: dict[PaymentMethod, AmountConfig]
    error_code_weights: dict[ErrorCode, float]
    timeout_ms: int = Field(gt=0)
    retry: RetryConfig
    anomalies: list[AnomalyConfig] = []

    @model_validator(mode="after")
    def _cross_fields(self) -> Self:
        _check_weights(self.method_weights, "method_weights")
        _check_weights(self.error_code_weights, "error_code_weights")
        missing = {m for m, w in self.method_weights.items() if w > 0} - set(self.amounts)
        if missing:
            raise ValueError(f"amounts missing for methods: {sorted(missing)}")
        if self.retry.retry_switch_provider_prob > 0 and len(self.providers) < 2:
            raise ValueError("retry_switch_provider_prob > 0 needs at least 2 providers")
        begin = datetime.combine(self.time.start_date, datetime.min.time(), tzinfo=UTC)
        end = begin + timedelta(days=self.time.days)
        for i, a in enumerate(self.anomalies):
            if a.provider is not None and a.provider >= len(self.providers):
                raise ValueError(f"anomalies[{i}]: provider index out of range")
            if a.start < begin or a.start + timedelta(minutes=a.duration_minutes) > end:
                raise ValueError(f"anomalies[{i}]: window outside the simulation period")
        return self


def simulation_id(config: SimulationConfig) -> str:
    """Deterministic id: SHA-256 of the canonical config (minus status), seed, generator version."""
    body = config.model_dump(mode="json", exclude={"status"})
    payload = json.dumps(
        {"config": body, "seed": config.seed, "generator_version": GENERATOR_VERSION},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return f"sim-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:12]}"


def load_config(path: Path) -> tuple[SimulationConfig, dict[str, Any]]:
    """Return (typed config, raw dict)."""
    if not path.is_file():
        raise ConfigError(f"config not found: {path}")
    raw = yaml.safe_load(path.read_text("utf-8"))
    try:
        return SimulationConfig.model_validate(raw), raw
    except ValidationError as err:
        raise ConfigError(f"invalid config {path}:\n{err}") from err
