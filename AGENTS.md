# AGENTS.md — Payment Intelligence Ecosystem

Instructions for AI coding agents (Claude Code, Codex, or similar). Version 2, includes the owner's binding decisions in section 2.
Read this whole file before changing anything. The human owner is the Technical Owner and approves architecture, contracts and merges.

## 1. Project in one paragraph

A modular data and AI platform with a shared foundation and two independent products:
- **Shared Foundation**: data contract, synthetic payment generator, dataset adapters, validation, common infrastructure.
- **Product 01 — Payment Reliability** (`projects/payment-reliability/`): KPIs, anomaly detection, incidents, API, dashboard.
- **Product 02 — Fraud & Risk** (`projects/fraud-risk/`): feature engineering, models, evaluation, scoring, investigation.

It is a 6-week demo for an internship report and a possible internal proposal. It runs locally with Docker. Quality of evaluation (no leakage, reproducibility, honest reporting) matters more than model score. The owner is a student who must be able to explain every step to mentors, so clarity beats cleverness.

## 2. Owner decisions (binding, supersede anything else in this file)

| ID | Decision |
| --- | --- |
| D1 | **Package layout.** Folders keep the hyphenated names from section 6. Importable Python code lives in snake_case packages inside them: `projects/fraud-risk/fraud_risk/` and `shared/dataset-management/dataset_management/`. Imports look like `from fraud_risk.evaluation.split import ...`. `pyproject.toml` sets pytest `pythonpath` to `["shared/dataset-management", "projects/fraud-risk"]`, and the Makefile exports the same `PYTHONPATH` for scripts. Create packages only where code exists in Stage A/B; other folders get a README. Record this as `docs/decisions/0001-package-layout.md` (pre-approved, write it in T01). |
| D2 | **EDA tooling.** Use only `pandas`, `numpy` and `matplotlib` (add `matplotlib` as a dev dependency). No profiling libraries. EDA output tables live in `artifacts/eda/` (git-ignored) and are never committed. Only `docs/data-analysis/eda-summary.md` is committed, with the minimum aggregate numbers needed as evidence (Kaggle licence terms are not yet checked). |
| D3 | **T02 scope.** Only `contracts/payment-event/` is drafted, using the inputs in section 9. `contracts/risk-context/` contains a README only. |
| D4 | **Empty test suite.** `make test` must pass in T01. Add a smoke test (`tests/test_layout.py`) that checks the layout and that `git check-ignore datasets/raw/x.csv` reports the path as ignored. If the folder is not a git repository the test must skip with a clear reason, not fail. |
| D5 | **Frozen config.** A config YAML has a field `status: draft` or `status: frozen`. `make baseline-final` refuses any config that is not `frozen`. Only the owner sets `frozen`; agents never do. |
| D6 | **Run identity.** `run_id` and the test-once hash are computed from: the canonical config (excluding the `status` field), the seed, the dataset manifest SHA-256 checksum, and the split boundaries. The git SHA is **not** part of the hash. |
| D7 | **Postgres.** Keep the T01 health check even though Stage A/B does not use the database yet; later stages do. |

## 3. Current task scope

You are only doing **Stage A (skeleton)** and **Stage B (baselines)**. Do not start anything listed under "Out of scope".

**In scope**
- Stage A: repository skeleton, tooling, Docker Compose with PostgreSQL, contract draft, dataset manifest tooling.
- Stage B: IEEE-CIS adapter, time-based split, a data profiling script (EDA) that produces evidence for preprocessing decisions, metrics, a rule-based baseline and a Logistic Regression baseline, with tests and a reproducible run log.

**Out of scope (do not build, do not stub beyond an empty README)**
- Synthetic generator logic, ingestion pipeline, dbt models, detectors, APIs, dashboards.
- Gradient Boosting, Isolation Forest, advanced feature engineering, MLflow, Kafka, Spark, Kubernetes, authentication.
- ULB and MoMTSim adapters, `contracts/risk-context/` schema.
- Any LLM or chatbot feature.

If a task seems to need something out of scope, stop and ask.

## 4. Hard rules (never break these)

1. **No real or company data.** Only public datasets supplied by the owner and synthetic data. Never add internal data, credentials, tokens or secrets to the repo.
2. **Do not download datasets yourself.** IEEE-CIS requires a Kaggle login and accepting competition terms. The owner places files under `datasets/raw/ieee-cis/` (git-ignored). If files are missing, fail with a clear message that says where to put them. Do not search the rest of the disk.
3. **Never commit** dataset files, Parquet outputs, model artifacts, EDA tables or `.env`. Only `.env.example`.
4. **Contracts are frozen by the owner.** Files in `contracts/` may only be created as drafts (`*.draft.json`, status marked draft) with a changelog entry. Do not edit an approved contract without explicit approval. Propose changes as an ADR instead.
5. **No card data or sensitive authentication data** in any schema, fixture or log.
6. **Ground-truth labels are separate from model input.** Features and labels live in different objects/tables; code that builds features must not be able to read the label column.
7. **No random split for evaluation.** Splits are by time. The test set is used **once** per frozen configuration (see section 8).
8. **Every transformer, scaler, encoder, imputer and threshold is fit on train (thresholds on validation) only.** Never fit on validation or test.
9. **No automatic blocking of transactions.** Risk scores are decision support only.
10. **Do not claim results you have not run.** Report real numbers from real runs. If a test or command fails, say so.
11. **Do not widen scope silently.** No extra modules, frameworks or dependencies beyond this file without noting the reason in your report.
12. **Preprocessing decisions are evidence-based and use the train partition only.** Any statistic that drives a decision (missing-value strategy, clipping, grouping rare categories, dropping columns) is computed on the train partition. Purely descriptive statistics over all data (for example fraud rate over time) must be labelled "descriptive only" and must not feed a decision. Every decision is recorded in `docs/data-analysis/eda-summary.md` with its evidence; you may propose, only the owner approves.
13. **No pretrained or external models.** Do not download, load or run any pretrained fraud model, `joblib` or `pickle` file from the internet. Public IEEE-CIS models were trained on this same dataset with unknown splits, so scoring our validation or test rows with them is contaminated, and loading such files can execute arbitrary code. Do not copy code or features from public notebooks without telling the owner the source and licence. Published numbers may appear in a report only as clearly labelled external reference points.
14. **Owner-only actions.** Agents never mark EDA decisions `approved`, never set a config to `frozen`, never run `make baseline-final` unless the owner asks, and never approve a contract.

## 5. Tech stack

- Python 3.11+, managed with `uv` (fallback: `venv` + `pip`). Single `pyproject.toml` at repo root.
- Libraries for Stage A/B: `pandas`, `pyarrow`, `numpy`, `scikit-learn`, `pyyaml`, `pydantic`, `jsonschema`, `pytest`, `pytest-cov`, `ruff`, and `matplotlib` (EDA only).
- Docker Compose: PostgreSQL 16 only, with a health check. No other services yet.
- Code and comments in English. Reports to the owner and documents under `docs/`: Vietnamese.
- Style: type hints on public functions, short docstrings, `ruff` clean, no dead code.

## 6. Repository layout (create exactly this; folders without code get a short `README.md`)

```
payment-intelligence-ecosystem/
├── contracts/
│   ├── payment-event/            # payment_event.schema.draft.json, CHANGELOG.md, examples/
│   └── risk-context/             # README only
├── shared/
│   ├── synthetic-generator/      # README only
│   ├── data-validation/          # README only
│   ├── dataset-management/
│   │   └── dataset_management/   # package: manifest.py, cli.py
│   └── common/                   # README only
├── datasets/
│   ├── README.md
│   ├── manifests/                # one YAML per dataset
│   └── raw/                      # git-ignored; owner places ieee-cis/ here
├── projects/
│   ├── payment-reliability/      # README only
│   └── fraud-risk/
│       ├── fraud_risk/           # package
│       │   ├── adapters/         # ieee_cis.py
│       │   ├── features/         # baseline_features.py
│       │   ├── eda/              # profile.py (train partition only)
│       │   ├── evaluation/       # split.py, metrics.py, run_log.py
│       │   ├── baselines/        # rule_based.py, logistic.py
│       │   └── scripts/          # CLI entry points
│       ├── configs/              # baseline configs (YAML)
│       └── tests/                # includes tests/fixtures/ (small synthetic files only)
├── infrastructure/
│   ├── docker/
│   └── database/
├── docs/
│   ├── architecture/
│   ├── product/
│   ├── data-governance/
│   ├── data-analysis/            # eda-summary.md: preprocessing decisions, owner-approved
│   └── decisions/                # ADRs: 0001-package-layout.md
├── tests/                        # cross-project tests (test_layout.py)
├── artifacts/                    # git-ignored: runs, EDA tables, Parquet
├── AGENTS.md
├── CLAUDE.md
├── compose.yaml
├── .env.example
├── .gitignore
├── Makefile
├── pyproject.toml
└── README.md
```

`.gitignore` must cover: `datasets/raw/`, `artifacts/`, `*.parquet`, `*.csv` (except files under a `fixtures/` folder), `.env`, `__pycache__/`, `.venv/`, model files.

## 7. Commands (provide these in the Makefile)

| Command | Purpose |
| --- | --- |
| `make setup` | Create the environment and install dependencies |
| `make lint` | `ruff check .` and `ruff format --check .` |
| `make test` | `pytest` with coverage for `shared/` and `projects/fraud-risk/` |
| `make up` / `make down` | Start and stop Docker Compose |
| `make eda` | Run the data profiling script on the train partition and write tables to `artifacts/eda/` |
| `make baseline` | Run Stage B end to end on train and validation only (never touches test) |
| `make baseline-final` | Run the test evaluation once for a frozen config (see section 8) |

The Makefile exports `PYTHONPATH` as in D1. A task is only done when `make lint` and `make test` pass.

## 8. Stage B specification (fraud baselines on IEEE-CIS)

**Input.** `train_transaction.csv` (and optionally `train_identity.csv`) in `datasets/raw/ieee-cis/` (override with env var `IEEE_CIS_DIR`). Label column: `isFraud`. Time column: `TransactionDT` (seconds from an unknown reference point, so use it only for ordering and for cyclical features such as hour of day). The Kaggle `test_transaction.csv` and `test_identity.csv` have no labels; **never use them for evaluation**. Our own chronological split of the `train_*` files provides train, validation and test.

**Adapter** (`fraud_risk/adapters/ieee_cis.py`)
- Read with explicit dtypes, convert to Parquet under `artifacts/`, record row counts.
- Return `X` (features, no label), `y` (label) and `time` (ordering key). Keep the identity join optional and off by default.
- Do not invent fields (no fake merchant or provider IDs).
- Dataset manifest YAML: source, version if known, SHA-256 checksum, licence note "Kaggle competition terms, research use only, verify before any other use", download date supplied by the owner.

**Split** (`fraud_risk/evaluation/split.py`)
- Sort by `TransactionDT`. Default: first 60% train, next 20% validation, last 20% test (configurable, boundaries by time, no shuffling).
- Assert no time overlap between parts. Save split boundaries to the run log.
- Provide a leaky variant (`random_split`) **only** for the later leakage experiment, clearly named and never used by baselines.

**Metrics** (`fraud_risk/evaluation/metrics.py`)
- PR-AUC (average precision), precision, recall, F1 at a threshold, false positive rate, recall at a fixed precision target (default 0.50, configurable).
- Do not report accuracy as a headline metric. It may appear only with a note about class imbalance.
- Bootstrap 95% confidence intervals (default 200 resamples, seeded) for PR-AUC.

**EDA and preprocessing evidence** (`fraud_risk/eda/profile.py`; tables to `artifacts/eda/`; skeleton `docs/data-analysis/eda-summary.md`)
Run on the **train partition** produced by the split. The script produces tables (CSV or Markdown) and figures, not conclusions. It must cover six steps:
1. **Data profile:** row and column counts, dtypes, memory use, fraud rate (train), and the same by time bucket (labelled "descriptive only" when computed on all data).
2. **Missing values:** missing rate per column, groups of columns missing together, missingness difference between fraud and non-fraud rows, and the effect of joining the identity table (optional, off by default).
3. **Class imbalance:** fraud rate per time bucket and whether it is stable; inputs for justifying `class_weight`.
4. **Distributions and outliers:** quantiles, skewness and extreme values of `TransactionAmt` and the counting columns; candidate transformations (for example log) with before/after summary statistics.
5. **Categoricals:** number of distinct values, share of rare values, fraud rate per value (train), candidates for grouping.
6. **Leakage candidates:** columns that are unique per row, near-perfectly associated with the label in train, or that encode time or order in a way that would not exist at scoring time. List them; do not drop them yourself.

`eda-summary.md` is a table with the columns: Decision | Evidence (table or figure reference) | Alternative considered | Status. Every row you add has Status `proposed`. Preprocessing and the feature list used by the baselines follow `approved` rows only.

**Baseline 1 — rule-based** (`baselines/rule_based.py`)
- Transparent rules whose thresholds are computed from **train only** (for example: amount above the train 99th percentile; selected `ProductCD` values with a train fraud rate above a train-derived cutoff). Return a score in [0, 1] (fraction of rules triggered, or a documented weighted sum) so it can be evaluated with the same metrics.
- Document each rule in the config and in the run log.

**Baseline 2 — Logistic Regression** (`baselines/logistic.py`)
- scikit-learn `Pipeline`: numeric imputation (median) + scaling for numeric columns, one-hot (`handle_unknown='ignore'`) for low-cardinality categoricals, `LogisticRegression(class_weight='balanced', max_iter=1000)`.
- Feature list is explicit in a YAML config. Until the owner approves rows in `eda-summary.md`, use only this starter list for tests and smoke runs: `TransactionAmt`, log of amount, hour of day derived from `TransactionDT`, `ProductCD`, `card4`, `card6`, and the `C1`–`C14` counting columns. After approval, follow the approved decisions only. No high-cardinality IDs as raw numeric features.
- Fit the whole pipeline on train only. Choose the decision threshold on validation (maximise F1, or meet the precision target). Save the threshold in the run log.

**Config files** (`projects/fraud-risk/configs/*.yaml`) contain at least: `status` (`draft` or `frozen`, see D5), `seed`, split fractions, feature list, model parameters, metric settings.

**Run log** (`fraud_risk/evaluation/run_log.py`)
Each run writes `artifacts/runs/<run_id>/`:
- `config.yaml` (copy), `metrics.json`, `split.json`, `threshold.json`, `environment.txt` (Python and package versions), `git_sha.txt`, dataset manifest checksum.
- `run_id` is deterministic and computed as in D6.

**Test-once rule**
- `make baseline` evaluates train and validation only.
- `make baseline-final` evaluates on test. It requires `status: frozen`, computes the hash as in D6, and refuses to run if `artifacts/test_runs.json` already contains that hash (override only with `--force`, which writes a warning into `metrics.json`). Choosing a different model or threshold after seeing test results is a new config and must be disclosed in the report.

**Reproducibility**
- All randomness takes an explicit seed from the config. Running twice with the same config, seed and data produces identical `metrics.json` (assert this in a test on a small fixture).

## 9. Inputs for T02 (payment event contract, draft)

The blueprint defines these; implement them as a **draft** JSON Schema (`payment_event.schema.draft.json`), additionalProperties false at both levels.

**Envelope fields:** `event_id`, `event_type`, `schema_version`, `event_time` (UTC, ISO 8601 with `Z`), `source_system`, `simulation_id`, `payload`.

**Payload fields:** `payment_id`, `attempt_id`, `provider_id`, `merchant_id`, `payment_method`, `amount`, `currency`, `status`, `error_code`, `latency_ms`.

**Blueprint example values:** `event_type` = `payment.attempt.completed`, `schema_version` = `1.0.0`, `payment_method` = `QR`, `currency` = `VND`, `status` = `FAILED`, `error_code` = `TIMEOUT`, `latency_ms` = 3500, `source_system` = `synthetic_generator`.

**Blueprint rules:** `event_id` unique; `payment_id` differs from `attempt_id`; time stored in UTC; `status` from a defined set; `schema_version` supports upgrades; no card or authentication data; `simulation_id` allows exact reproduction.

**Draft proposals (the blueprint does not specify these; the owner reviews them with the draft):**
- `event_type`: enum with the single value `payment.attempt.completed`.
- `schema_version`: string matching semantic versioning `x.y.z`.
- `source_system`: enum with the single value `synthetic_generator`.
- `payment_method`: enum `QR`, `CARD`, `BANK_TRANSFER`, `E_WALLET`.
- `currency`: enum with the single value `VND`.
- `amount`: integer greater than 0, smallest currency unit (VND has no sub-unit).
- `status`: enum `SUCCESS`, `FAILED`.
- `error_code`: enum `TIMEOUT`, `PROVIDER_ERROR`, `DECLINED`, `NETWORK_ERROR`, `INVALID_REQUEST`, or `null`. If `status` is `SUCCESS`, `error_code` must be `null`; if `FAILED`, it must not be `null` (use `if/then`).
- `latency_ms`: integer greater than or equal to 0.

JSON Schema cannot express "two fields differ" or "event_id is unique". Enforce `payment_id != attempt_id` in a small validation function with tests, and state in the changelog that uniqueness is checked at ingestion in a later stage.

Required tests: one valid example; invalid examples for each rule above, including an extra field such as `card_number` (must be rejected), a non-UTC timestamp, an unknown `status`, `SUCCESS` with a non-null `error_code`, and `payment_id == attempt_id`.

Do not invent a `risk-context` schema (D3).

## 10. Tasks, gates and acceptance criteria

Work one task at a time, one branch per task (`task/T01-skeleton`), small commits. After each task stop, report, and wait for the owner. Gates marked **STOP** require owner action before the next task.

| ID | Task | Files you may touch | Acceptance criteria |
| --- | --- | --- | --- |
| T01 | Repo skeleton and tooling | Root files, folder READMEs, `infrastructure/`, `compose.yaml`, `.env.example`, `Makefile`, `pyproject.toml`, `tests/test_layout.py`, `docs/decisions/0001-package-layout.md` | Layout matches section 6; `make setup lint test` pass (D4); `docker compose up -d postgres` becomes healthy; imports work per D1 |
| T02 | Contract draft | `contracts/payment-event/` | Section 9 implemented; valid and invalid examples; schema validation tests; changelog; status draft. **STOP:** owner reviews before T03 |
| T03 | Dataset manifest tooling | `shared/dataset-management/`, `datasets/manifests/`, tests | CLI computes SHA-256 and writes a manifest YAML; tested on a small fixture; fails clearly if the file is missing |
| T04 | IEEE-CIS adapter | `projects/fraud-risk/fraud_risk/adapters/`, tests | Outputs `X`, `y`, `time`; clear error for missing columns or files; unit tests on a synthetic mini-fixture shaped like IEEE-CIS (no real data in the repo); run once on the real files when present and report row counts |
| T05 | Time-based split | `fraud_risk/evaluation/split.py`, tests | Chronological, non-overlapping, deterministic; test proves no train row is later than any validation row, and no validation row later than any test row |
| T05b | EDA profiling script | `fraud_risk/eda/`, `docs/data-analysis/`, Makefile, tests | `make eda` produces tables for the six steps using the train partition only (test proves changing validation or test rows does not change any output used for a decision); `eda-summary.md` skeleton exists with rows `proposed`; works on the fixture; clear "dataset not found" message otherwise. **STOP:** owner reads tables and approves decisions |
| T06 | Metrics | `fraud_risk/evaluation/metrics.py`, tests | Matches `sklearn` on a handcrafted example; recall-at-precision verified by a hand-computed case; bootstrap seeded and reproducible |
| T07 | Rule-based baseline | `fraud_risk/baselines/rule_based.py`, config, tests | Thresholds derived from train only (test proves changing validation data does not change them); scores in [0, 1] |
| T08 | Logistic baseline | `fraud_risk/baselines/logistic.py`, `fraud_risk/features/`, config, tests | Starter list until `eda-summary.md` is approved, then only approved decisions; pipeline fit on train only (test with a spy or assertion on fit data); threshold chosen on validation; deterministic with a fixed seed |
| T09 | Run log and CLI | `fraud_risk/evaluation/run_log.py`, `fraud_risk/scripts/`, Makefile | `make baseline` creates the run folder with all listed files; `make baseline-final` enforces D5, D6 and the test-once rule (tested with a fixture) |
| T10 | Leakage guard tests | `projects/fraud-risk/tests/` | Tests that fail if: a label-derived column enters features, a random split is used by a baseline, a transformer is fitted outside train |

If the real IEEE-CIS files are not present, T04–T10 must still pass their tests on fixtures, and `make baseline` must exit with a clear "dataset not found" message instead of a stack trace. After T10, stop and wait; do not start Stage C.

## 11. Working agreement

- Read before writing. Prefer small, reviewable changes. Do not refactor unrelated code.
- Plan first: list the files you will touch and the tests you will write; ask if anything is ambiguous.
- Only edit files listed for the current task. If you need another file, say why and ask.
- Do not add dependencies without listing them and the reason in your report.
- Write tests with the code, not afterwards.
- When requirements are ambiguous or conflict with section 4, stop and ask rather than guessing.
- Do not tune on the test split. Do not "improve" the model for a nicer metric; baselines are meant to be simple and honest.
- ADR 0001 is pre-approved (D1). For any other ADR, propose it in your report and let the owner decide.
- Stop and ask when: real data files are missing or columns differ from assumptions; a decision would change a frozen contract, the split rule or the test-once rule; a fix would require changing this specification; you are about to add an unlisted dependency or tool; anything in the repo appears to contain company data or credentials.

## 12. Final report format (after each task)

Write the report in Vietnamese (code stays in English):
1. What changed (files, one line each).
2. Commands run and their results (`make lint`, `make test`, anything else), including failures.
3. Numbers produced, if any, with the run id they came from.
4. Assumptions you made and open questions.
5. Anything that conflicts with this file or the contracts.
6. "Điều chủ dự án cần hiểu để giải thích phần này": 3 to 5 sentences on the idea, the input and output, and what would go wrong if the step were skipped.

## 13. Later stages (for context only; do not start)

Stage C: synthetic generator and ingestion. Stage D: dbt marts, KPIs and detectors. Stage E: leakage experiments, Gradient Boosting, scoring API. Stage F: dashboards, integration, report. The contract and the evaluation rules in this file are the foundation for all of them, so keep them clean.
