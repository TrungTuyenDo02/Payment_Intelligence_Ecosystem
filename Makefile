# Payment Intelligence Ecosystem: developer commands (AGENTS.md section 6).
SHELL := /bin/bash
.DEFAULT_GOAL := help

UV := $(shell command -v uv 2>/dev/null)
ifeq ($(UV),)
  # Fallback: venv + pip
  RUN := PATH="$(CURDIR)/.venv/bin:$$PATH"
else
  RUN := uv run --frozen
endif
CONFIG ?= projects/fraud-risk/configs/baseline.yaml
# POSTGRES_* from .env (never committed); defaults in code match compose.yaml.
-include .env
export POSTGRES_USER POSTGRES_PASSWORD POSTGRES_DB POSTGRES_PORT
# PYTHONPATH separator: ";" on Windows (OS=Windows_NT), ":" elsewhere.
SEP := $(if $(filter Windows_NT,$(OS)),;,:)
# Windows and WSL share this folder: keep the Windows uv environment apart from WSL's .venv.
ifeq ($(OS),Windows_NT)
  export UV_PROJECT_ENVIRONMENT ?= .venv-win
endif
export PYTHONPATH := shared/dataset-management$(SEP)shared/synthetic-generator$(SEP)shared/dashboard$(SEP)projects/fraud-risk$(SEP)projects/payment-reliability


.PHONY: help setup hooks lint test up down eda baseline baseline-final report leakage gbm gbm-final simulate db-init ingest kpi detect tune detect-plot detect-report dashboard

help:
	@echo "Targets: setup hooks lint test up down eda baseline baseline-final report leakage gbm gbm-final simulate db-init ingest kpi detect tune detect-plot detect-report dashboard"

setup:
ifeq ($(UV),)
	python3 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install pandas pyarrow numpy scikit-learn pyyaml pydantic jsonschema 'psycopg[binary]' pytest pytest-cov ruff matplotlib
else
	uv sync
endif
	@$(MAKE) --no-print-directory hooks

# Git hooks in .githooks/ (commit-msg drops AI-tool attribution lines). Safe to run again.
hooks:
	@if git rev-parse --git-dir >/dev/null 2>&1; then git config core.hooksPath .githooks && echo "git hooks: .githooks"; fi

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .

test:
	$(RUN) pytest --cov --cov-report=term-missing

up:
	docker compose up -d --wait postgres

down:
	docker compose down

eda:
	$(RUN) python -m fraud_risk.eda.profile $(if $(wildcard $(CONFIG)),--config $(CONFIG),)

# Train + validation only; never touches test.
baseline:
	$(RUN) python -m fraud_risk.scripts.run_baseline --config $(CONFIG) --stage validation

# One-time test evaluation of a config the OWNER has frozen. FORCE=1 re-runs (logged warning).
baseline-final:
	$(RUN) python -m fraud_risk.scripts.run_baseline --config $(CONFIG) --stage final $(if $(FORCE),--force,)

# Charts + summary table from the latest run (or RUN_DIR=artifacts/runs/<run_id>[/test]).
report:
	$(RUN) python -m fraud_risk.scripts.plot_results $(if $(RUN_DIR),--run-dir $(RUN_DIR),)

# Stage E (stage-e-spec.md). leakage: validation only. gbm: validation; gbm-final: test once,
# config frozen by the OWNER.
GBM_CONFIG ?= projects/fraud-risk/configs/gbm.yaml
leakage:
	$(RUN) python -m fraud_risk.experiments.leakage

gbm:
	$(RUN) python -m fraud_risk.scripts.run_gbm --config $(GBM_CONFIG) --stage validation

gbm-final:
	$(RUN) python -m fraud_risk.scripts.run_gbm --config $(GBM_CONFIG) --stage final $(if $(FORCE),--force,)

# Synthetic payment events (Stage C). CONFIG defaults to the demo scenario.
SIM_CONFIG := $(if $(filter command line,$(origin CONFIG)),$(CONFIG),shared/synthetic-generator/configs/demo.yaml)
simulate:
	$(RUN) python -m synthetic_generator.cli --config $(SIM_CONFIG)

# Stage C ingestion into PostgreSQL (start it with `make up`).
db-init:
	$(RUN) python -m synthetic_generator.ingest --init-db

ingest:
	$(if $(SIM),,$(error SIM=<simulation_id> is required))
	$(RUN) python -m synthetic_generator.ingest --sim $(SIM)

# Stage D (stage-d-spec.md). KPIs need PostgreSQL with the simulation loaded (make ingest).
kpi:
	$(if $(SIM),,$(error SIM=<simulation_id> is required))
	$(RUN) python -m payment_reliability.cli kpi --sim $(SIM)

detect:
	$(RUN) python -m payment_reliability.cli detect $(if $(DETECTOR_CONFIG),--config $(DETECTOR_CONFIG),)

tune:
	$(RUN) python -m payment_reliability.cli tune $(if $(DETECTOR_CONFIG),--config $(DETECTOR_CONFIG),)

# RUN_DIR=artifacts/detections/<run_id>[/report] OUT=docs/assets/results/<name>.png
detect-plot:
	$(RUN) python -m payment_reliability.cli plot $(if $(RUN_DIR),--run-dir $(RUN_DIR),) $(if $(OUT),--out $(OUT),)

# One-time evaluation on the report simulation; config must be frozen by the OWNER.
detect-report:
	$(RUN) python -m payment_reliability.cli detect-report $(if $(DETECTOR_CONFIG),--config $(DETECTOR_CONFIG),) $(if $(FORCE),--force,)

# Stage F: static dashboard from artifacts/ (ADR 0007), written to artifacts/dashboard/index.html.
dashboard:
	$(RUN) python -m dashboard.build
