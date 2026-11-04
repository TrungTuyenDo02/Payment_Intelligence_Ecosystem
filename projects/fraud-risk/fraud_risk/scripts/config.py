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
    gap_days: float = Field(default=0, ge=0)  # ADR 0003; 0 keeps the Stage B split


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


class GbmSection(_Strict):
    # Each list is a grid axis; the combination with the best validation PR-AUC is kept.
    grid: dict[Literal["learning_rate", "max_iter", "max_leaf_nodes", "l2_regularization",
                       "min_samples_leaf"], list[float | int]]  # fmt: skip


class GbmConfig(_Strict):
    """Stage E Gradient Boosting run (configs/gbm.yaml)."""

    status: Literal["draft", "frozen"]
    seed: int
    data: DataConfig
    split: SplitConfig
    metrics: MetricsConfig
    features: FeaturesConfig
    gbm: GbmSection


class EntityOverlapSection(_Strict):
    keys: list[list[str]]


class TargetEncodingSection(_Strict):
    column: str
    smoothing: float = Field(default=100.0, ge=0)


class LeakageConfig(_Strict):
    """Stage E leakage experiment (configs/leakage.yaml). Validation only, never test."""

    status: Literal["draft", "frozen"]
    seed: int
    data: DataConfig
    split: SplitConfig
    metrics: MetricsConfig
    features: FeaturesConfig
    logistic: LogisticConfig
    gap_days: list[float]
    target_encoding: TargetEncodingSection
    entity_overlap: EntityOverlapSection


def _load(path: Path, model: type[BaseModel]) -> tuple[Any, dict[str, Any], str]:
    if not path.is_file():
        raise ConfigError(f"config not found: {path}")
    text = path.read_text("utf-8")
    raw = yaml.safe_load(text)
    try:
        return model.model_validate(raw), raw, text
    except ValidationError as err:
        raise ConfigError(f"invalid config {path}:\n{err}") from err


def load_config(path: Path) -> tuple[BaselineConfig, dict[str, Any], str]:
    """Return (typed config, raw dict, original text)."""
    return _load(path, BaselineConfig)


def load_gbm_config(path: Path) -> tuple[GbmConfig, dict[str, Any], str]:
    return _load(path, GbmConfig)


def load_leakage_config(path: Path) -> tuple[LeakageConfig, dict[str, Any], str]:
    return _load(path, LeakageConfig)
