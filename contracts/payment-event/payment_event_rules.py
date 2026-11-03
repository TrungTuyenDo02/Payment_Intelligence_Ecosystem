"""Validation for the Payment Event draft contract.

JSON Schema cannot express cross-field inequality, so `payment_id != attempt_id`
is checked here. `event_id` uniqueness is checked at ingestion (later stage).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).with_name("payment_event.schema.draft.json")


def load_validator() -> Draft202012Validator:
    """Load the draft schema and return a validator for it."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def validate_event(
    event: dict[str, Any], validator: Draft202012Validator | None = None
) -> list[str]:
    """Return a list of error messages; an empty list means the event is valid."""
    validator = validator or load_validator()
    errors = [
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in sorted(validator.iter_errors(event), key=lambda e: list(e.absolute_path))
    ]
    payload = event.get("payload")
    if (
        isinstance(payload, dict)
        and payload.get("payment_id") is not None
        and payload.get("payment_id") == payload.get("attempt_id")
    ):
        errors.append("payload: payment_id must differ from attempt_id")
    event_time = event.get("event_time")
    if isinstance(event_time, str) and event_time.endswith("Z"):
        try:
            datetime.fromisoformat(event_time.replace("Z", "+00:00"))
        except ValueError:
            errors.append(f"event_time: not a real calendar date/time: {event_time}")
    return errors
