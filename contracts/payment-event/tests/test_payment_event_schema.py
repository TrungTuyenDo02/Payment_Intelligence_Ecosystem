"""Tests for the Payment Event draft contract (AGENTS.md section 9)."""

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator

CONTRACT_DIR = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "payment_event_rules", CONTRACT_DIR / "payment_event_rules.py"
)
assert _spec is not None and _spec.loader is not None
rules = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rules)


def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def validator() -> Draft202012Validator:
    return rules.load_validator()


@pytest.fixture
def valid_event() -> dict[str, Any]:
    return _load(CONTRACT_DIR / "examples" / "valid.json")


def test_schema_is_marked_draft() -> None:
    schema = _load(rules.SCHEMA_PATH)
    assert schema["x-status"] == "draft"
    assert rules.SCHEMA_PATH.name.endswith(".draft.json")


def test_valid_example_passes(valid_event: dict[str, Any], validator: Draft202012Validator) -> None:
    assert rules.validate_event(valid_event, validator) == []


def test_success_with_null_error_code_passes(
    valid_event: dict[str, Any], validator: Draft202012Validator
) -> None:
    valid_event["payload"]["status"] = "SUCCESS"
    valid_event["payload"]["error_code"] = None
    assert rules.validate_event(valid_event, validator) == []


@pytest.mark.parametrize(
    "path",
    sorted((CONTRACT_DIR / "examples" / "invalid").glob("*.json")),
    ids=lambda p: p.stem,
)
def test_invalid_example_files_fail(path: Path, validator: Draft202012Validator) -> None:
    assert rules.validate_event(_load(path), validator), f"{path.name} should be rejected"


def _mutate(event: dict[str, Any], dotted: str, value: Any) -> dict[str, Any]:
    event = copy.deepcopy(event)
    *parents, leaf = dotted.split(".")
    target = event
    for key in parents:
        target = target[key]
    if value is _DELETE:
        del target[leaf]
    else:
        target[leaf] = value
    return event


_DELETE = object()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("payload.card_number", "0000"),
        ("payload.cvv", "000"),
        ("password", "x"),
        ("event_time", "2026-01-15T10:21:07+07:00"),
        ("event_time", "2026-01-15T03:21:07"),
        ("event_time", "2026-13-45T03:21:07Z"),
        ("event_time", "15/01/2026 03:21:07"),
        ("payload.status", "PENDING"),
        ("payload.status", "success"),
        ("payload.error_code", "SOMETHING_ELSE"),
        ("payload.error_code", None),  # FAILED with null error_code
        ("event_type", "payment.created"),
        ("source_system", "core_banking"),
        ("schema_version", "1.0"),
        ("schema_version", "v1.0.0"),
        ("payload.payment_method", "CASH"),
        ("payload.currency", "USD"),
        ("payload.amount", 0),
        ("payload.amount", -1),
        ("payload.amount", 1500.5),
        ("payload.attempt_number", 0),
        ("payload.attempt_number", 1.5),
        ("payload.attempt_number", "1"),
        ("payload.attempt_number", _DELETE),
        ("payload.latency_ms", -1),
        ("payload.latency_ms", 1.5),
        ("event_id", ""),
        ("event_id", _DELETE),
        ("simulation_id", _DELETE),
        ("payload.merchant_id", _DELETE),
    ],
)
def test_rule_violations_are_rejected(
    valid_event: dict[str, Any], validator: Draft202012Validator, field: str, value: Any
) -> None:
    event = _mutate(valid_event, field, value)
    assert rules.validate_event(event, validator), f"{field}={value!r} should be rejected"


def test_success_with_error_code_rejected(
    valid_event: dict[str, Any], validator: Draft202012Validator
) -> None:
    event = _mutate(valid_event, "payload.status", "SUCCESS")
    assert any("error_code" in e for e in rules.validate_event(event, validator))


def test_payment_id_equal_to_attempt_id_rejected(
    valid_event: dict[str, Any], validator: Draft202012Validator
) -> None:
    event = _mutate(valid_event, "payload.attempt_id", valid_event["payload"]["payment_id"])
    errors = rules.validate_event(event, validator)
    assert errors == ["payload: payment_id must differ from attempt_id"]
