-- Stage C ingestion tables (spec section 6). Idempotent: safe to run again (make db-init).
-- Also run automatically by the postgres container on first start (docker-entrypoint-initdb.d).

CREATE TABLE IF NOT EXISTS ingestion_runs (
    run_id          BIGSERIAL PRIMARY KEY,
    simulation_id   TEXT        NOT NULL,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    source_file     TEXT        NOT NULL,
    events_sha256   TEXT        NOT NULL,
    rows_read       INTEGER     NOT NULL,
    rows_accepted   INTEGER     NOT NULL,  -- newly inserted in this run
    rows_duplicate  INTEGER     NOT NULL,  -- valid but already loaded by an earlier run
    rows_rejected   INTEGER     NOT NULL
);
CREATE INDEX IF NOT EXISTS ingestion_runs_simulation_idx ON ingestion_runs (simulation_id);

CREATE TABLE IF NOT EXISTS payment_events (
    event_id          TEXT        PRIMARY KEY,
    event_type        TEXT        NOT NULL,
    schema_version    TEXT        NOT NULL,
    event_time        TIMESTAMPTZ NOT NULL,
    source_system     TEXT        NOT NULL,
    simulation_id     TEXT        NOT NULL,
    payment_id        TEXT        NOT NULL,
    attempt_id        TEXT        NOT NULL UNIQUE,
    attempt_number    INTEGER     NOT NULL CHECK (attempt_number >= 1),
    provider_id       TEXT        NOT NULL,
    merchant_id       TEXT        NOT NULL,
    payment_method    TEXT        NOT NULL,
    amount            BIGINT      NOT NULL CHECK (amount > 0),
    currency          TEXT        NOT NULL,
    status            TEXT        NOT NULL,
    error_code        TEXT,
    latency_ms        INTEGER     NOT NULL CHECK (latency_ms >= 0),
    ingestion_run_id  BIGINT      NOT NULL REFERENCES ingestion_runs (run_id),
    UNIQUE (payment_id, attempt_number)
);
CREATE INDEX IF NOT EXISTS payment_events_time_idx ON payment_events (event_time);
CREATE INDEX IF NOT EXISTS payment_events_simulation_idx ON payment_events (simulation_id);

CREATE TABLE IF NOT EXISTS ingestion_rejects (
    reject_id         BIGSERIAL PRIMARY KEY,
    ingestion_run_id  BIGINT  NOT NULL REFERENCES ingestion_runs (run_id),
    simulation_id     TEXT    NOT NULL,
    line_number       INTEGER NOT NULL,  -- 1-based line in events.jsonl
    event_id          TEXT,
    payment_id        TEXT,
    reasons           JSONB   NOT NULL,
    raw_line          TEXT    NOT NULL,
    UNIQUE (simulation_id, line_number)
);
