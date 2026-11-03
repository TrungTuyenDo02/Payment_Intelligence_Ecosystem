# synthetic-generator

Rule-based generator of synthetic `payment-event` data (Stage C, [spec](../../docs/architecture/stage-c-spec.md)).

- `synthetic_generator/config.py`: typed config (unknown fields rejected) and `simulation_id`.
- `configs/demo.yaml`: demo scenario (7 days, 3 providers, 20 merchants, about 30 payments per hour). Every value is an assumption, not learned from real data.
- `simulation_id` = `sim-` + first 12 hex of SHA-256 over the validated config without `status`, the seed and `GENERATOR_VERSION`. Defaults are filled in before hashing, so writing a default value explicitly does not change the id.

Event generation (C02), anomalies (C03) and ingestion (C04) are not written yet.
