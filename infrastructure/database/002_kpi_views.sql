-- Stage D reliability KPIs (stage-d-spec.md section 3, ADR 0005). Plain views over payment_events.
-- Idempotent: CREATE OR REPLACE, safe to run again (make db-init).
-- Buckets: 15 minutes in UTC, by event_time (the time an attempt finished; spec Q1).
-- Empty buckets are kept with zero counts and NULL rates, so a traffic loss stays visible.

-- One row per attempt, with its bucket and failure class.
-- Technical failures: TIMEOUT, PROVIDER_ERROR, NETWORK_ERROR. Business failures: DECLINED,
-- INVALID_REQUEST (Stage C spec decision 2).
CREATE OR REPLACE VIEW kpi_attempts AS
SELECT
    simulation_id,
    date_bin('15 minutes', event_time, TIMESTAMPTZ '2000-01-01 00:00:00+00') AS bucket_start,
    provider_id,
    payment_method,
    attempt_number,
    status,
    error_code,
    latency_ms,
    COALESCE(error_code IN ('TIMEOUT', 'PROVIDER_ERROR', 'NETWORK_ERROR'), false)
        AS is_technical_failure,
    COALESCE(error_code IN ('DECLINED', 'INVALID_REQUEST'), false) AS is_business_failure
FROM payment_events;

-- Every 15-minute bucket from the first to the last attempt of each simulation.
CREATE OR REPLACE VIEW kpi_buckets AS
SELECT s.simulation_id, b.bucket_start
FROM (
    SELECT simulation_id, min(bucket_start) AS first_bucket, max(bucket_start) AS last_bucket
    FROM kpi_attempts
    GROUP BY simulation_id
) AS s
CROSS JOIN LATERAL generate_series(s.first_bucket, s.last_bucket, INTERVAL '15 minutes')
    AS b (bucket_start);

-- Grain: one row per (simulation_id, bucket_start, provider_id); provider_id 'ALL' = all providers.
-- Counts are kept next to rates so a detector knows how many attempts a rate is based on.
-- Latency percentiles exclude TIMEOUT, whose latency is always the timeout limit.
CREATE OR REPLACE VIEW kpi_provider_15m AS
WITH attempts AS (
    SELECT * FROM kpi_attempts
    UNION ALL
    SELECT simulation_id, bucket_start, 'ALL', payment_method, attempt_number, status, error_code,
           latency_ms, is_technical_failure, is_business_failure
    FROM kpi_attempts
),
targets AS (
    SELECT DISTINCT simulation_id, provider_id FROM attempts
),
counts AS (
    SELECT
        b.simulation_id,
        b.bucket_start,
        t.provider_id,
        count(a.status) AS attempts,
        count(*) FILTER (WHERE a.status = 'SUCCESS') AS successes,
        count(*) FILTER (WHERE a.attempt_number = 1) AS first_attempts,
        count(*) FILTER (WHERE a.attempt_number = 1 AND a.status = 'SUCCESS')
            AS first_attempt_successes,
        count(*) FILTER (WHERE a.attempt_number > 1) AS retries,
        count(*) FILTER (WHERE a.is_technical_failure) AS technical_failures,
        count(*) FILTER (WHERE a.is_business_failure) AS business_failures,
        count(*) FILTER (WHERE a.error_code = 'TIMEOUT') AS timeouts,
        count(*) FILTER (WHERE a.status IS NOT NULL AND a.error_code IS DISTINCT FROM 'TIMEOUT')
            AS latency_attempts,
        percentile_cont(0.5) WITHIN GROUP (ORDER BY a.latency_ms)
            FILTER (WHERE a.error_code IS DISTINCT FROM 'TIMEOUT') AS latency_p50_ms,
        percentile_cont(0.95) WITHIN GROUP (ORDER BY a.latency_ms)
            FILTER (WHERE a.error_code IS DISTINCT FROM 'TIMEOUT') AS latency_p95_ms
    FROM kpi_buckets AS b
    JOIN targets AS t USING (simulation_id)
    LEFT JOIN attempts AS a
        ON a.simulation_id = b.simulation_id
        AND a.bucket_start = b.bucket_start
        AND a.provider_id = t.provider_id
    GROUP BY b.simulation_id, b.bucket_start, t.provider_id
)
SELECT
    *,
    successes::double precision / NULLIF(attempts, 0) AS success_rate,
    first_attempt_successes::double precision / NULLIF(first_attempts, 0)
        AS first_attempt_success_rate,
    technical_failures::double precision / NULLIF(attempts, 0) AS technical_failure_rate,
    business_failures::double precision / NULLIF(attempts, 0) AS business_failure_rate,
    retries::double precision / NULLIF(attempts, 0) AS retry_share,
    timeouts::double precision / NULLIF(attempts, 0) AS timeout_rate
FROM counts;

-- Grain: one row per (simulation_id, bucket_start, provider_id, error_code) that has at least one
-- failure; provider_id 'ALL' = all providers. Missing rows mean zero.
CREATE OR REPLACE VIEW kpi_errors_15m AS
SELECT simulation_id, bucket_start, provider_id, error_code, count(*) AS failures
FROM kpi_attempts
WHERE error_code IS NOT NULL
GROUP BY simulation_id, bucket_start, provider_id, error_code
UNION ALL
SELECT simulation_id, bucket_start, 'ALL', error_code, count(*)
FROM kpi_attempts
WHERE error_code IS NOT NULL
GROUP BY simulation_id, bucket_start, error_code;

-- Grain: one row per (simulation_id, bucket_start, payment_method), zero-filled.
-- first_attempts counts new payments (attempt_number = 1); method_share is the method's part of
-- all new payments in the bucket, which does not depend on the time of day.
CREATE OR REPLACE VIEW kpi_method_15m AS
WITH methods AS (
    SELECT DISTINCT simulation_id, payment_method FROM kpi_attempts
),
counts AS (
    SELECT
        b.simulation_id,
        b.bucket_start,
        m.payment_method,
        count(a.status) AS first_attempts
    FROM kpi_buckets AS b
    JOIN methods AS m USING (simulation_id)
    LEFT JOIN kpi_attempts AS a
        ON a.simulation_id = b.simulation_id
        AND a.bucket_start = b.bucket_start
        AND a.payment_method = m.payment_method
        AND a.attempt_number = 1
    GROUP BY b.simulation_id, b.bucket_start, m.payment_method
)
SELECT
    *,
    sum(first_attempts) OVER (PARTITION BY simulation_id, bucket_start) AS all_first_attempts,
    first_attempts::double precision
        / NULLIF(sum(first_attempts) OVER (PARTITION BY simulation_id, bucket_start), 0)
        AS method_share
FROM counts;
