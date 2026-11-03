# payment-event contract (DRAFT)

Status: **draft, awaiting owner approval**. Do not build on it as if it were frozen.

- `payment_event.schema.draft.json`: JSON Schema 2020-12 for the event envelope and payload.
- `payment_event_rules.py`: `validate_event(event)` = schema + rules JSON Schema cannot express (`payment_id != attempt_id`, real calendar date).
- `examples/valid.json`, `examples/invalid/*.json`: one file per broken rule.
- `CHANGELOG.md`: what changed and which values are draft proposals.
- `tests/`: validation tests (run with `make test`).
