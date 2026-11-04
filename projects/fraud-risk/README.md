# Product 02: Fraud & Risk

Code lives in the inner package `fraud_risk/` (ADR 0001):

- `fraud_risk/adapters/`: dataset adapters (`ieee_cis.py`)
- `fraud_risk/features/`: feature builders (`baseline_features.py`), label guard, `target_encoding.py` (Stage E experiment only)
- `fraud_risk/eda/`: data profiling on the train partition (`profile.py`)
- `fraud_risk/evaluation/`: `split.py` (with `gap_days`), `metrics.py`, `run_log.py`, `entity_overlap.py`
- `fraud_risk/baselines/`: `rule_based.py`, `logistic.py`
- `fraud_risk/models/`: `gbm.py` (Stage E, HistGradientBoosting, ADR 0006)
- `fraud_risk/experiments/`: `leakage.py` (Stage E, validation only; the only user of `random_split`)
- `fraud_risk/scripts/`: CLI entry points (`run_baseline`, `run_gbm`, `plot_results`)
- `configs/`: `baseline.yaml` (frozen), `gbm.yaml` (the only Stage E config pre-registered for test), `leakage.yaml`
- `tests/`: tests for this project
