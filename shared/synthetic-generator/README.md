# synthetic-generator

Rule-based generator of synthetic `payment-event` data (Stage C, [spec](../../docs/architecture/stage-c-spec.md)).

- `synthetic_generator/config.py`: typed config (unknown fields rejected) and `simulation_id`.
- `configs/demo.yaml`: demo scenario (7 days, 3 providers, 20 merchants, about 30 payments per hour). Every value is an assumption, not learned from real data.
- `simulation_id` = `sim-` + first 12 hex of SHA-256 over the validated config without `status`, the seed and `GENERATOR_VERSION`. Defaults are filled in before hashing, so writing a default value explicitly does not change the id.

- `synthetic_generator/generator.py`: events from the rules in spec section 3. Payments follow a Poisson process per UTC hour with seasonality in local time (UTC+7). The first-attempt provider is uniform. Only `TIMEOUT`, `PROVIDER_ERROR` and `NETWORK_ERROR` are retried; a retry keeps merchant, amount, method and currency and may switch provider. `TIMEOUT` latency equals `timeout_ms`; other latencies stay below it. Amounts are rounded to 1,000 VND.
- `synthetic_generator/cli.py`: `make simulate [CONFIG=...]` checks every event with the contract's `validate_event`, then writes `artifacts/simulations/<simulation_id>/` (`events.jsonl`, `anomaly_labels.json`, `simulation_manifest.yaml`). Same config, seed and numpy version give byte-identical files.

Anomalies (C03) and ingestion (C04) are not written yet; `anomaly_labels.json` is an empty list for now.
