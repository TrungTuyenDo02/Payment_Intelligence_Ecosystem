# Payment Intelligence Ecosystem

Modular data and AI platform demo (6-week internship project):

- **Shared Foundation** (`shared/`, `contracts/`, `datasets/`): data contracts, dataset tooling, validation.
- **Product 01: Payment Reliability** (`projects/payment-reliability/`): not started.
- **Product 02: Fraud & Risk** (`projects/fraud-risk/`): baselines on IEEE-CIS (Stage B).

Rules for contributors and AI agents: see [`AGENTS.md`](AGENTS.md). Session protocol: [`CLAUDE.md`](CLAUDE.md).

## Quick start

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/) (or `venv` + `pip`), Docker with Compose.

```bash
cp .env.example .env      # edit the password
make setup
make lint
make test
make up                   # PostgreSQL 16, waits until healthy
make down
```

## Stage B workflow (IEEE-CIS)

```bash
# 1. Put train_transaction.csv (and train_identity.csv) in datasets/raw/ieee-cis/
# 2. Write the dataset manifest (see shared/dataset-management/README.md)
# 3. Profile the train partition, then read artifacts/eda/ and review docs/data-analysis/eda-summary.md
make eda
# 4. Train + validation only
make baseline                       # -> artifacts/runs/<run_id>/
# 5. Only after the owner sets status: frozen in the config, once:
make baseline-final                 # -> artifacts/runs/<run_id>/test/
```

Raw data is never committed. Put the IEEE-CIS files under `datasets/raw/ieee-cis/` (see [`datasets/README.md`](datasets/README.md)).

## Code layout

Folders with hyphens keep the names from `AGENTS.md`; Python code lives in a snake_case package inside them
(`projects/fraud-risk/fraud_risk/`, `shared/dataset-management/dataset_management/`). See
[ADR 0001](docs/decisions/0001-package-layout.md).
