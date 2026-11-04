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
export PYTHONPATH := shared/dataset-management:shared/synthetic-generator:projects/fraud-risk:projects/payment-reliability

.PHONY: help setup lint test up down eda baseline baseline-final report simulate db-init ingest kpi detect tune detect-plot detect-report

help:
	@echo "Targets: setup lint test up down eda baseline baseline-final report simulate db-init ingest kpi detect tune detect-plot detect-report"

setup:
ifeq ($(UV),)
	python3 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install pandas pyarrow numpy scikit-learn pyyaml pydantic jsonschema 'psycopg[binary]' pytest pytest-cov ruff matplotlib
else
	uv sync
endif

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

detect-plot:
	$(RUN) python -m payment_reliability.cli plot $(if $(RUN_DIR),--run-dir $(RUN_DIR),)

# One-time evaluation on the report simulation; config must be frozen by the OWNER.
detect-report:
	$(RUN) python -m payment_reliability.cli detect-report $(if $(DETECTOR_CONFIG),--config $(DETECTOR_CONFIG),) $(if $(FORCE),--force,)
