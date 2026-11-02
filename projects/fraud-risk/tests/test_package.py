"""Smoke test: the fraud_risk package and its subpackages import (ADR 0001)."""

import importlib

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "fraud_risk.adapters",
        "fraud_risk.features",
        "fraud_risk.eda",
        "fraud_risk.evaluation",
        "fraud_risk.baselines",
        "fraud_risk.scripts",
    ],
)
def test_subpackage_importable(module: str) -> None:
    importlib.import_module(module)
