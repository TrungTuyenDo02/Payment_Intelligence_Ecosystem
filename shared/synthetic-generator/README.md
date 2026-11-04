# synthetic-generator

Rule-based generator of synthetic `payment-event` data, plus ingestion into PostgreSQL (Stage C, [spec](../../docs/architecture/stage-c-spec.md), [report](../../docs/architecture/stage-c-report.md)).

Product 01 (Payment Reliability) runs only on this data (ADR 0002). **Every value below is an assumption written in a config file, not learned from real data.** Results computed on it show that the pipeline and detectors behave as designed, not how a real payment system behaves.

## Files

| Path | Content |
| --- | --- |
| `synthetic_generator/config.py` | Typed config (unknown fields rejected) and `simulation_id` |
| `synthetic_generator/generator.py` | Event generation and anomaly injection |
| `synthetic_generator/cli.py` | `make simulate [CONFIG=...]` |
| `synthetic_generator/ingest.py` | `make db-init`, `make ingest SIM=<simulation_id>` |
| `configs/demo.yaml` | `purpose: tuning`, seed 42: for tuning the Stage D detector |
| `configs/report.yaml` | `purpose: report`, seed 2026: for reporting the detector only |

## Commands

```bash
make simulate
```

```bash
make simulate CONFIG=shared/synthetic-generator/configs/report.yaml
```

```bash
make up
```

```bash
make db-init
```

```bash
make ingest SIM=<simulation_id>
```

`make simulate` writes `artifacts/simulations/<simulation_id>/` (git-ignored):

- `events.jsonl`: one event per line, sorted by `event_time` then `event_id`;
- `anomaly_labels.json`: ground truth, the only place anomalies are named;
- `simulation_manifest.yaml`: `simulation_id`, generator and numpy versions, seed, counts, SHA-256 of `events.jsonl`, full config.

## Assumptions

### World

| Assumption | Value in `demo.yaml` | Why |
| --- | --- | --- |
| Period | 7 days from Monday 2026-01-05, 00:00 UTC | Spec decision 4 |
| Providers | 3 (`prov_001`..`prov_003`) | Spec decision 4 |
| Merchants | 20 (`mer_0001`..), weight of merchant *i* ∝ 1 / *i*^1.1 (Zipf) | A few large merchants carry most traffic |
| Currency | VND only, amounts rounded to 1,000 VND, at least 1,000 | Contract allows only VND, which has no sub-unit |
| Timezone | Seasonality in local time Asia/Ho_Chi_Minh (UTC+7, no DST); event times in UTC | Contract requires UTC |

### Traffic

| Assumption | Value | Why |
| --- | --- | --- |
| Arrivals | Poisson count per UTC hour, uniform time inside the hour | Standard simple arrival model |
| Mean rate | 150 payments per hour, scaled by hour-of-day x day-of-week factors (each normalised to mean 1) | About 25 thousand payments in 7 days, so each provider has about 12 attempts per 15-minute bucket on average (raised from 30 by the owner, 2026-11-04; spec amendment A1) |
| Hour-of-day | Low at night (0.1 at 01:00–04:00), peaks at 12:00 (1.8) and 20:00 (2.0) local | Lunch and evening shopping peaks |
| Day-of-week | Friday 1.1, Saturday 1.2, Sunday 0.9, other days 1.0 | Mild weekend effect |
| Payment method | QR 45%, E_WALLET 25%, CARD 20%, BANK_TRANSFER 10% | QR is the most common method in Vietnam (NAPAS context, overview 7.4) |
| Amount | Log-normal per method, median QR 120k, E_WALLET 90k, CARD 350k, BANK_TRANSFER 1.5M VND | Small everyday payments, larger card and transfer payments |
| First-attempt provider | Uniform over providers | Shortcut: no provider weights in the config yet |

### Outcomes, latency and retries

| Assumption | Value | Why |
| --- | --- | --- |
| Failure probability per attempt | `prov_001` 15%, `prov_002` 22%, `prov_003` 30% | **Deliberately high** so Stage D has enough retries (owner, 2026-11-04) |
| Error code of a failure | DECLINED 25%, TIMEOUT 25%, PROVIDER_ERROR 25%, NETWORK_ERROR 20%, INVALID_REQUEST 5% | 70% technical failures (owner, 2026-11-04) |
| Latency | Log-normal per provider, median 450 / 600 / 800 ms, sigma 0.35 / 0.45 / 0.55 | Faster providers are also more stable |
| Timeout | `TIMEOUT` attempts have latency exactly `timeout_ms` = 10,000 ms; all others stay below it | A timeout is the wait limit being hit |
| Which failures retry | Only `TIMEOUT`, `PROVIDER_ERROR`, `NETWORK_ERROR` | Spec decision 7: a decline will not succeed on retry |
| Retry probability, limit | 90%, at most 2 retries (3 attempts) | Owner, 2026-11-04 |
| Wait before retry | Uniform 5–60 s after the failed attempt finished | Client-side retry |
| Provider on retry | Switch to another provider (uniform) with probability 30% | Spec decision 8 |
| Fields kept on retry | `merchant_id`, `amount`, `payment_method`, `currency` | Contract 1.0.0 rule |
| `event_time` | Attempt start + latency (the time the attempt finished) | Contract revision 2 |

### Anomalies

Each anomaly has a half-open UTC window `[start, start + duration)` and a `magnitude > 1`. It applies to attempts that **start** inside the window (payment arrival time for `traffic_drop`).

| Type | Effect | Target |
| --- | --- | --- |
| `provider_outage` | Failure probability x magnitude (capped at 1); added failures are `TIMEOUT` or `PROVIDER_ERROR` (50/50) | One provider |
| `latency_degradation` | Latency x magnitude, still below `timeout_ms` | One provider |
| `error_burst` | Failure probability x magnitude; added failures carry the given `error_code` | All providers, or one |
| `traffic_drop` | Payments of the method are kept with probability 1 / magnitude | One payment method |

| Config | Anomalies |
| --- | --- |
| `demo.yaml` (tuning) | `provider_outage` prov_002 x4, 90 min · `latency_degradation` prov_001 x3, 3 h · `error_burst` NETWORK_ERROR x3, 45 min · **weak** `provider_outage` prov_001 x1.5, 2 h |
| `report.yaml` (report) | `provider_outage` prov_003 x3, 60 min · `latency_degradation` prov_002 x2.5, 2 h · **`traffic_drop`** QR x5, 2 h (a type tuning never sees) · **weak** `provider_outage` prov_002 x1.5, 2 h |

The weak x1.5 scenarios (owner, 2026-11-04; spec amendment A2) are smaller than the random spread of one 15-minute bucket, so a detector must pool several buckets to see them. They show where detection stops working, not only that obvious incidents are caught.

## Guarantees (all tested)

- Every event passes the contract's `validate_event` before anything is written; events carry contract fields only.
- `simulation_id` = `sim-` + first 12 hex of SHA-256 over the validated config without `status`, the seed and `GENERATOR_VERSION`. Changing `status` or writing a default explicitly does not change it.
- Same config, seed and numpy version give byte-identical files. Each payment draws from its own RNG stream, so payments that touch no anomaly window are identical to a run without anomalies.
- Payment ids are numbered after `traffic_drop`, so gaps reveal nothing. Ids carry the simulation tag, so several simulations can share one database.

## Ingestion

- One transaction per `make ingest`. Every line goes through `validate_event`; bad lines go to `ingestion_rejects` with reasons and do not stop the batch.
- The five rules across attempts (contract 1.0.0 changelog) are checked per payment. If any attempt of a payment is rejected, **all** its attempts are rejected (spec decision 6).
- Loading the same simulation again inserts nothing new (`ON CONFLICT DO NOTHING`). A changed `events.jsonl` for a `simulation_id` already loaded is refused (spec decision 9), as is a file that does not match its manifest checksum.
- Connection settings come from `POSTGRES_*` in `.env`; defaults match `compose.yaml`. Database tests use a throwaway schema and skip with a reason when PostgreSQL is not running.
