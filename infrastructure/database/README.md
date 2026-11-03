# database

SQL for PostgreSQL 16. Every `.sql` file here runs once when the `postgres` container starts with an empty volume (`docker-entrypoint-initdb.d`), and again on demand with `make db-init` (all statements are idempotent).

- `001_payment_events.sql`: Stage C ingestion tables `ingestion_runs`, `payment_events` (primary key `event_id`, unique `(payment_id, attempt_number)`) and `ingestion_rejects`.
