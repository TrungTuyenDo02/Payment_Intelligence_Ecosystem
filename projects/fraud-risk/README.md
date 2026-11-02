# Product 02: Fraud & Risk

Code lives in the inner package `fraud_risk/` (ADR 0001):

- `fraud_risk/adapters/`: dataset adapters (`ieee_cis.py`)
- `fraud_risk/features/`: feature builders (`baseline_features.py`)
- `fraud_risk/evaluation/`: `split.py`, `metrics.py`, `run_log.py`
- `fraud_risk/baselines/`: `rule_based.py`, `logistic.py`
- `fraud_risk/scripts/`: CLI entry points (`python -m fraud_risk.scripts.<name>`)
- `configs/`: baseline YAML configs (not Python)
- `tests/`: tests for this project
