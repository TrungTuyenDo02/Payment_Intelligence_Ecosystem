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


# --- Stage G (stage-g-spec.md, ADR 0009): decisions on development data only -----------------


class FixedModelsSection(_Strict):
    """Stage G models are fixed (no grid search); GBM = the point chosen in run-f8807cb6f780."""

    gbm: dict[Literal["learning_rate", "max_iter", "max_leaf_nodes"], float | int]
    logistic: LogisticConfig | None = None  # only G03 compares calibration of both models


class ReproductionCheck(_Strict):
    """Validation PR-AUC the fixed models must reproduce, else the run stops (spec section 2)."""

    gbm_valid_pr_auc: float | None = None
    logistic_valid_pr_auc: float | None = None
    valid_max_time: int | None = None  # last validation TransactionDT; test starts after it
    tolerance: float = Field(default=0.002, gt=0)


class BlocksConfig(_Strict):
    """Validation blocks as inclusive day ranges (TransactionDT // 86400)."""

    V1: tuple[int, int]  # calibrate
    V2: tuple[int, int]  # select
    V3: tuple[int, int]  # evaluate


class DecisionBase(_Strict):
    status: Literal["draft", "frozen"]
    stage: Literal["exploratory"]  # every Stage G result is exploratory (validation reused)
    seed: int
    data: DataConfig
    split: SplitConfig
    features: FeaturesConfig
    models: FixedModelsSection
    blocks: BlocksConfig
    check: ReproductionCheck = ReproductionCheck()


class CalibrationSection(_Strict):
    methods: list[Literal["raw", "prior_shift", "platt"]]
    bins: int = Field(default=10, ge=2)
    select_by: Literal["log_loss", "brier"] = "log_loss"


class CalibrationConfig(DecisionBase):
    """G03 (configs/calibration.yaml)."""

    calibration: CalibrationSection


class CostGrid(_Strict):
    """Assumed costs in units of TransactionAmt (sensitivity analysis, not ROI)."""

    loss_rate: list[float]  # share of a missed fraud's amount that is lost
    c_review: list[float]  # cost of reviewing one alert
    c_friction: list[float]  # extra cost of one false alert (customer friction)


class BootstrapSection(_Strict):
    resamples: int = Field(default=1000, ge=10)
    seed: int = 42


class PolicySection(_Strict):
    calibration: CalibrationSection
    cost: CostGrid
    budgets_pct: list[float]  # top-N per day, N as % of the day's transactions
    fpr_target: float = Field(default=0.05, gt=0, lt=1)  # threshold transfer test
    bootstrap: BootstrapSection = BootstrapSection()


class PolicyConfig(DecisionBase):
    """G04 (configs/policy.yaml)."""

    policy: PolicySection


class StabilitySection(_Strict):
    psi_columns: list[str]  # feature columns (after build_features) compared with train
    psi_bins: int = Field(default=10, ge=2)  # quantile bins of the TRAIN values
    groups: list[str]  # raw columns to slice validation by
    min_frauds: int = Field(default=30, ge=1)  # below this a group is "small sample"
    fpr_target: float = Field(default=0.05, gt=0, lt=1)


class StabilityConfig(DecisionBase):
    """G05 (configs/stability.yaml)."""

    stability: StabilitySection


class ScoringSection(_Strict):
    calibration: Literal["raw", "prior_shift", "platt"]  # fixed from G03, fitted on V1 only
    sample_rows: int = Field(default=2000, ge=1)  # label-free demo input taken from V3


class ScoringConfig(DecisionBase):
    """G08 batch scorer (configs/scoring.yaml)."""

    scoring: ScoringSection
