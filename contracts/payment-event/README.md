# payment-event contract

Status: **approved, version 1.0.0** (owner, 2026-11-03). Any change needs a new version and an entry in `CHANGELOG.md`.

- `payment_event.schema.json`: JSON Schema 2020-12 for the event envelope and payload.
- `payment_event_rules.py`: `validate_event(event)` = schema + rules JSON Schema cannot express (`payment_id != attempt_id`, real calendar date).
- `examples/valid.json`, `examples/invalid/*.json`: one file per broken rule.
- `CHANGELOG.md`: what changed, and the rules across attempts that ingestion checks.
- `tests/`: validation tests (run with `make test`).
