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
export PYTHONPATH := shared/dataset-management:projects/fraud-risk

.PHONY: help setup lint test up down eda baseline baseline-final

help:
	@echo "Targets: setup lint test up down eda baseline baseline-final"

setup:
ifeq ($(UV),)
	python3 -m venv .venv
	.venv/bin/pip install -U pip
	.venv/bin/pip install pandas pyarrow numpy scikit-learn pyyaml pydantic jsonschema pytest pytest-cov ruff matplotlib
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
