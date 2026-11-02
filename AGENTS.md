# AGENTS.md — Payment Intelligence Ecosystem

Instructions for AI coding agents (Claude Code, Codex, or similar).
Read this whole file before changing anything. The human owner is the Technical Owner and approves architecture, contracts and merges.

## 1. Project in one paragraph

A modular data and AI platform with a shared foundation and two independent products:
- **Shared Foundation**: data contract, synthetic payment generator, dataset adapters, validation, common infrastructure.
- **Product 01 — Payment Reliability** (`projects/payment-reliability/`): KPIs, anomaly detection, incidents, API, dashboard.
- **Product 02 — Fraud & Risk** (`projects/fraud-risk/`): feature engineering, models, evaluation, scoring, investigation.

It is a 6-week demo for an internship report and a possible internal proposal. It runs locally with Docker. Quality of evaluation (no leakage, reproducibility, honest reporting) matters more than model score.

## 2. Current task scope

You are only doing **Stage A (skeleton)** and **Stage B (baselines)** below. Do not start anything listed under "Out of scope".

**In scope**
- Stage A: repository skeleton, tooling, Docker Compose with PostgreSQL, contract drafts, dataset manifest tooling.
- Stage B: IEEE-CIS adapter, time-based split, metrics, a rule-based baseline and a Logistic Regression baseline, with tests and a reproducible run log.

**Out of scope (do not build, do not stub beyond an empty README)**
- Synthetic generator logic, ingestion pipeline, dbt models, detectors, APIs, dashboards.
- Gradient Boosting, Isolation Forest, advanced feature engineering, MLflow, Kafka, Spark, Kubernetes, authentication.
- ULB and MoMTSim adapters.
- Any LLM or chatbot feature.

If a task seems to need something out of scope, stop and ask.

## 3. Hard rules (never break these)

1. **No real or company data.** Only public datasets supplied by the owner and synthetic data. Never add internal data, credentials, tokens or secrets to the repo.
2. **Do not download datasets yourself.** IEEE-CIS requires a Kaggle login and accepting competition terms. The owner places files under `datasets/raw/` (git-ignored). If files are missing, fail with a clear message that says where to put them.
3. **Never commit** dataset files, Parquet outputs, model artifacts or `.env`. Only `.env.example`.
4. **Contracts are frozen by the owner.** Files in `contracts/` may only be created as `*.draft.json` / drafts with a changelog entry. Do not edit an approved contract (no `draft` in its status) without explicit approval. Propose changes in `docs/decisions/` as an ADR instead.
5. **No card data or sensitive authentication data** in any schema, fixture or log.
6. **Ground-truth labels are separate from model input.** Features and labels live in different objects/tables; code that builds features must not be able to read the label column.
7. **No random split for evaluation.** Splits are by time. The test set is used **once** per frozen configuration (see section 7).
8. **Every transformer, scaler, encoder, imputer and threshold is fit on train (thresholds on validation) only.** Never fit on validation or test.
9. **No automatic blocking of transactions.** Risk scores are decision support only.
10. **Do not claim results you have not run.** Report real numbers from real runs. If a test or command fails, say so.
11. **Do not widen scope silently.** No extra modules, frameworks or dependencies beyond this file without noting the reason in your final report.

## 4. Tech stack

- Python 3.11+, managed with `uv` (fallback: `venv` + `pip`). Single `pyproject.toml` at repo root.
- Libraries for Stage A/B: `pandas`, `pyarrow`, `numpy`, `scikit-learn`, `pyyaml`, `pydantic`, `jsonschema`, `pytest`, `pytest-cov`, `ruff`.
- Docker Compose: PostgreSQL 16 only, with a health check. No other services yet.
- Code and comments in English. Documents under `docs/` may be in Vietnamese or English.
- Style: type hints on public functions, short docstrings, `ruff` clean, no dead code.

## 5. Repository layout (create exactly this, empty folders get a short `README.md`)

```
payment-intelligence-ecosystem/
├── contracts/
│   ├── payment-event/            # payment_event.schema.draft.json, CHANGELOG.md
│   └── risk-context/
├── shared/
│   ├── synthetic-generator/      # README only for now
│   ├── data-validation/
│   ├── dataset-management/       # manifest tooling (Stage A)
│   └── common/
├── datasets/
│   ├── README.md
│   ├── manifests/                # one YAML per dataset
│   └── raw/                      # git-ignored, owner puts files here
├── projects/
│   ├── payment-reliability/      # README only for now
│   └── fraud-risk/
│       ├── adapters/             # ieee_cis.py
│       ├── features/             # baseline_features.py
│       ├── evaluation/           # split.py, metrics.py, run_log.py
│       ├── baselines/            # rule_based.py, logistic.py
│       ├── configs/              # baseline configs (YAML)
│       ├── scripts/              # CLI entry points
│       └── tests/
├── infrastructure/
│   ├── docker/
│   └── database/
├── docs/
│   ├── architecture/
│   ├── product/
│   ├── data-governance/
│   └── decisions/                # ADRs: 0001-title.md
├── tests/                        # cross-project tests
├── artifacts/                    # git-ignored, run outputs
├── AGENTS.md
├── compose.yaml
├── .env.example
├── .gitignore
├── Makefile
├── pyproject.toml
└── README.md
```

`.gitignore` must cover: `datasets/raw/`, `artifacts/`, `*.parquet`, `*.csv` (except small test fixtures under a `fixtures/` folder), `.env`, `__pycache__/`, `.venv/`, model files.

## 6. Commands (provide these in the Makefile)

| Command | Purpose |
| --- | --- |
| `make setup` | Create the environment and install dependencies |
| `make lint` | `ruff check .` and `ruff format --check .` |
| `make test` | `pytest` with coverage for `shared/` and `projects/fraud-risk/` |
| `make up` / `make down` | Start and stop Docker Compose |
| `make baseline` | Run Stage B end to end on validation only (never touches test) |
| `make baseline-final` | Run the test evaluation once for a frozen config (see section 7) |

A task is only done when `make lint` and `make test` pass.

## 7. Stage B specification (fraud baselines on IEEE-CIS)

**Input.** `train_transaction.csv` (and optionally `train_identity.csv`) supplied by the owner in `datasets/raw/ieee-cis/`. Label column: `isFraud`. Time column: `TransactionDT` (seconds from an unknown reference point, so use it only for ordering and for cyclical features such as hour of day).

**Adapter** (`adapters/ieee_cis.py`)
- Read with explicit dtypes, convert to Parquet under `artifacts/`, record row counts.
- Return two objects: `X` (features, no label) and `y` (label) plus `time` (ordering key). Keep the join with identity optional and off by default.
- Do not invent fields (no fake merchant or provider IDs).
- Write a dataset manifest YAML (source, version if known, SHA-256 checksum, license note "Kaggle competition terms, research use only, verify before any other use", download date supplied by owner).

**Split** (`evaluation/split.py`)
- Sort by `TransactionDT`. Default: first 60% train, next 20% validation, last 20% test (configurable, boundaries by time, no shuffling).
- Assert no time overlap between parts. Save split boundaries to the run log.
- Provide a leaky variant (`random_split`) **only** for the later leakage experiment, clearly named and not used by baselines.

**Metrics** (`evaluation/metrics.py`)
- PR-AUC (average precision), precision, recall, F1 at a threshold, false positive rate, recall at a fixed precision target (default 0.50, configurable).
- Do not report accuracy as a headline metric. It may appear only with a note about class imbalance.
- Bootstrap 95% confidence intervals (default 200 resamples, seeded) for PR-AUC.

**Baseline 1 — rule-based** (`baselines/rule_based.py`)
- Transparent rules whose thresholds are computed from **train only** (for example: amount above the train 99th percentile; selected `ProductCD` values with a train fraud rate above a train-derived cutoff). Return a score in [0, 1] (the fraction of rules triggered, or a documented weighted sum) so it can be evaluated with the same metrics.
- Document each rule in the config and in the run log.

**Baseline 2 — Logistic Regression** (`baselines/logistic.py`)
- scikit-learn `Pipeline`: numeric imputation (median) + scaling for numeric columns, one-hot (`handle_unknown='ignore'`) for low-cardinality categoricals, `LogisticRegression(class_weight='balanced', max_iter=1000)`.
- Feature list is explicit in a YAML config (start small: `TransactionAmt`, log of amount, hour of day derived from `TransactionDT`, `ProductCD`, `card4`, `card6`, and the `C1`–`C14` counting columns). No high-cardinality IDs as raw numeric features.
- Fit the whole pipeline on train only. Choose the decision threshold on validation (maximise F1, or meet the precision target). Save the threshold in the run log.

**Run log** (`evaluation/run_log.py`)
Each run writes `artifacts/runs/<run_id>/`:
- `config.yaml` (copy of the config), `metrics.json`, `split.json`, `threshold.json`, `environment.txt` (Python and package versions), `git_sha.txt`, dataset manifest checksum.
- `run_id` is deterministic from config hash plus seed.

**Test-once rule**
- `make baseline` evaluates train and validation only.
- `make baseline-final` evaluates on test. It must read a frozen config, compute its hash, and refuse to run if `artifacts/test_runs.json` already contains that hash (override only with `--force`, which logs a warning in `metrics.json`). Selecting a different model or threshold after seeing test results counts as a new config and must be noted in the report.

**Reproducibility**
- All randomness takes an explicit seed from the config. Running twice with the same config, seed and data produces identical `metrics.json` (assert this in a test on a small fixture).

## 8. Tasks and acceptance criteria

Work one task at a time, one branch per task (`task/T01-skeleton`), small commits, and a short summary at the end of each task.

| ID | Task | Files you may touch | Acceptance criteria |
| --- | --- | --- | --- |
| T01 | Repo skeleton and tooling | Root files, folder READMEs, `infrastructure/`, `compose.yaml`, `.env.example`, `Makefile`, `pyproject.toml` | Layout matches section 5; `make setup lint test` pass on an empty test suite; `docker compose up -d postgres` becomes healthy; `.gitignore` verified by trying to `git add` a dummy `datasets/raw/x.csv` (must be ignored) |
| T02 | Contract drafts | `contracts/` | JSON Schema draft for Payment Event envelope (fields as in the owner's blueprint: `event_id`, `event_type`, `schema_version`, `event_time` UTC, `source_system`, `simulation_id`, `payload`); enum values for `status`; a valid and an invalid example; schema validation tests; changelog; status marked draft awaiting approval |
| T03 | Dataset manifest tooling | `shared/dataset-management/`, `datasets/manifests/` | CLI computes SHA-256 and writes a manifest YAML; test with a small fixture; fails clearly if the file is missing |
| T04 | IEEE-CIS adapter | `projects/fraud-risk/adapters/`, tests | Reads the CSV, outputs `X`, `y`, `time`; handles missing columns with a clear error; unit tests on a synthetic mini-fixture shaped like IEEE-CIS (no real data in the repo) |
| T05 | Time-based split | `projects/fraud-risk/evaluation/split.py`, tests | Chronological, non-overlapping, deterministic; test proves no train row is later than any validation row, and no validation row later than any test row |
| T06 | Metrics | `evaluation/metrics.py`, tests | Matches `sklearn` on a handcrafted example; recall-at-precision verified by hand-computed case; bootstrap seeded and reproducible |
| T07 | Rule-based baseline | `baselines/rule_based.py`, config, tests | Thresholds derived from train only (test proves changing validation data does not change thresholds); outputs scores in [0, 1] |
| T08 | Logistic baseline | `baselines/logistic.py`, `features/`, config, tests | Pipeline fit on train only (test with a spy or assertion on fit data); threshold chosen on validation; deterministic with a fixed seed |
| T09 | Run log and CLI | `evaluation/run_log.py`, `scripts/`, Makefile targets | `make baseline` creates the run folder with all listed files; `make baseline-final` enforces the test-once rule (test with a fixture) |
| T10 | Leakage guard tests | `projects/fraud-risk/tests/` | Tests that fail if: a label-derived column enters features, a random split is used by a baseline, a transformer is fitted outside train |

If the real IEEE-CIS files are not present, T04–T10 must still pass their tests on fixtures, and `make baseline` must exit with a clear "dataset not found" message instead of a stack trace.

## 9. Working agreement

- Read before writing. Prefer small, reviewable changes. Do not refactor unrelated code.
- Only edit files listed for the current task. If you need another file, say why and ask.
- Do not add dependencies without listing them and the reason in your report.
- Write tests with the code, not afterwards.
- When requirements are ambiguous or conflict with section 3, stop and ask rather than guessing.
- Do not create ADRs on your own; propose them in your report and let the owner decide.

## 10. Final report format (after each task)

1. What changed (files, one line each).
2. Commands run and their results (`make lint`, `make test`, anything else), including failures.
3. Numbers produced, if any, with the run id they came from.
4. Assumptions you made and open questions.
5. Anything you noticed that conflicts with this file or the contracts.

## 11. Later stages (for context only; do not start)

Stage C: synthetic generator and ingestion. Stage D: dbt marts, KPIs and detectors. Stage E: leakage experiments, Gradient Boosting, scoring API. Stage F: dashboards, integration, report. The contract and the evaluation rules in this file are the foundation for all of them, so keep them clean.
