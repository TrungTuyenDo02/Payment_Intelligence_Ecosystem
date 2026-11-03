# Changelog: payment-event contract

Versions follow semantic versioning. Events always carry the plain version (for example `1.0.0`); the draft or approved status is recorded only in this changelog and in the schema's `x-status`.

## 1.0.0, status: APPROVED (2026-11-03)

Approved by the owner on 2026-11-03. The schema content is revision 2 below; `x-status` is now `approved` and the file is renamed to `payment_event.schema.json`.

Rules across attempts of one payment, decided by the owner at approval. JSON Schema checks one event at a time, so these are enforced at ingestion (Stage C), and the synthetic generator must produce data that follows them:

- A retry may use a different `provider_id`. Reliability KPIs per provider are computed per attempt, not per payment.
- All attempts of a payment have the same `merchant_id`, `amount`, `payment_method` and `currency`.
- At most one attempt per payment has `status = SUCCESS`, and no attempt follows a `SUCCESS` (by `attempt_number`).
- `(payment_id, attempt_number)` is unique.
- `attempt_number` values of a payment are consecutive, starting at 1.

## 1.0.0, status: DRAFT, revision 2 (2026-11-03), awaiting owner approval

Changes agreed by the owner on 2026-11-03 during the contract review:

- Added required payload field `attempt_number` (integer, minimum 1). Without it, first-attempt success rate and retry rate could only be inferred from `event_time` order.
- `event_time` is documented as the time the attempt **finished** (UTC).
- `error_code` documents the split between business or client-side failures (`DECLINED`, `INVALID_REQUEST`) and technical failures (`TIMEOUT`, `PROVIDER_ERROR`, `NETWORK_ERROR`). The schema keeps one `FAILED` status; the KPI layer (Stage D) applies the split.
- Accepted the agent's choices from revision 1: ID fields are strings of length 1 to 64; `event_time` allows up to 6 fractional-second digits.
- Changelog heading no longer uses `1.0.0-draft`, which the schema's own semver pattern would reject.

## 1.0.0, status: DRAFT, revision 1 (2026-11-02)

- Added `payment_event.schema.draft.json` (JSON Schema 2020-12) from the blueprint inputs in `AGENTS.md` section 9.
- Envelope: `event_id`, `event_type`, `schema_version`, `event_time`, `source_system`, `simulation_id`, `payload`. `additionalProperties: false` at envelope and payload level.
- Payload: `payment_id`, `attempt_id`, `provider_id`, `merchant_id`, `payment_method`, `amount`, `currency`, `status`, `error_code`, `latency_ms`.
- Draft proposals (not in the blueprint; for owner review): enums for `event_type`, `source_system`, `payment_method`, `currency`, `status`, `error_code`; semver pattern for `schema_version`; integer `amount > 0` in the smallest VND unit; integer `latency_ms >= 0`; `error_code` must be `null` when `SUCCESS` and non-null when `FAILED`.
- Draft choices made by the agent and not listed in the blueprint (also for review): ID fields are strings of length 1–64; `event_time` allows up to 6 fractional-second digits.
- `payment_id != attempt_id` is enforced by `payment_event_rules.validate_event`, because JSON Schema cannot compare two fields.
- `event_id` uniqueness is **not** checked by the schema; it will be checked at ingestion in a later stage.
- No card data or authentication data fields. Any extra field (for example `card_number`) is rejected.
