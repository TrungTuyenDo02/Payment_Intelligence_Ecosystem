# Changelog: payment-event contract

## 1.0.0-draft (2026-11-02), status: DRAFT, awaiting owner approval

- Added `payment_event.schema.draft.json` (JSON Schema 2020-12) from the blueprint inputs in `AGENTS.md` section 9.
- Envelope: `event_id`, `event_type`, `schema_version`, `event_time`, `source_system`, `simulation_id`, `payload`. `additionalProperties: false` at envelope and payload level.
- Payload: `payment_id`, `attempt_id`, `provider_id`, `merchant_id`, `payment_method`, `amount`, `currency`, `status`, `error_code`, `latency_ms`.
- Draft proposals (not in the blueprint; for owner review): enums for `event_type`, `source_system`, `payment_method`, `currency`, `status`, `error_code`; semver pattern for `schema_version`; integer `amount > 0` in the smallest VND unit; integer `latency_ms >= 0`; `error_code` must be `null` when `SUCCESS` and non-null when `FAILED`.
- Draft choices made by the agent and not listed in the blueprint (also for review): ID fields are strings of length 1–64; `event_time` allows up to 6 fractional-second digits.
- `payment_id != attempt_id` is enforced by `payment_event_rules.validate_event`, because JSON Schema cannot compare two fields.
- `event_id` uniqueness is **not** checked by the schema; it will be checked at ingestion in a later stage.
- No card data or authentication data fields. Any extra field (for example `card_number`) is rejected.
