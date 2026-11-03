"""Typed baseline config (projects/fraud-risk/configs/*.yaml)."""

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class ConfigError(ValueError):
    """The config file is missing or invalid."""


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DataConfig(_Strict):
    use_identity: bool = False
    manifest: str


class SplitConfig(_Strict):
    train_frac: float = Field(gt=0, lt=1)
    valid_frac: float = Field(gt=0, lt=1)


class MetricsConfig(_Strict):
    precision_target: float = Field(default=0.5, gt=0, le=1)
    fpr_target: float = Field(default=0.05, gt=0, lt=1)
    bootstrap_resamples: int = Field(default=200, ge=1)
    threshold_method: Literal["max_f1", "precision_target"] = "max_f1"


class FeaturesConfig(_Strict):
    numeric: list[str] = []
    categorical: list[str] = []
    derived: list[str] = []


class RuleBasedConfig(_Strict):
    rules: list[dict[str, Any]]


class LogisticConfig(_Strict):
    C: float = Field(default=1.0, gt=0)
    max_iter: int = Field(default=1000, ge=1)


class BaselineConfig(_Strict):
    status: Literal["draft", "frozen"]
    seed: int
    data: DataConfig
    split: SplitConfig
    metrics: MetricsConfig
    features: FeaturesConfig
    rule_based: RuleBasedConfig
    logistic: LogisticConfig


def load_config(path: Path) -> tuple[BaselineConfig, dict[str, Any], str]:
    """Return (typed config, raw dict, original text)."""
    if not path.is_file():
        raise ConfigError(f"config not found: {path}")
    text = path.read_text("utf-8")
    raw = yaml.safe_load(text)
    try:
        return BaselineConfig.model_validate(raw), raw, text
    except ValidationError as err:
        raise ConfigError(f"invalid config {path}:\n{err}") from err
