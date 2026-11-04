# Product 01: Payment Reliability

Reliability KPIs and anomaly detection on the synthetic payment events of Stage C.
Spec: [`docs/architecture/stage-d-spec.md`](../../docs/architecture/stage-d-spec.md).
Results: [`docs/architecture/stage-d-report.md`](../../docs/architecture/stage-d-report.md).

## Flow

1. `make db-init`, `make ingest SIM=<id>`: events into PostgreSQL (Stage C).
2. `make kpi SIM=<id>`: KPI views (`infrastructure/database/002_kpi_views.sql`) to `artifacts/kpi/<id>/*.parquet`.
3. `make tune`: threshold grid on the **tuning** simulation only, to `artifacts/tuning/<id>/grid.csv`.
4. `make detect`: both detectors on the tuning simulation, to `artifacts/detections/<run_id>/`
   (`config.yaml`, `scores.parquet`, `incidents.json`, `evaluation.json`, `git_sha.txt`, `environment.txt`).
5. `make detect-plot [RUN_DIR=...] [OUT=...]`: chart, by default of the latest tuning run to `docs/assets/results/stage-d-tuning.png`.
6. `make detect-report`: **once**, on the report simulation, only after the owner sets
   `status: frozen` in `configs/detector.yaml`. Refuses a hash already in `artifacts/detect_report_runs.json`.

## Package `payment_reliability`

| Module | Role | Reads labels? |
| --- | --- | --- |
| `kpi.py` | Fetch KPI views, write and load Parquet | No |
| `detectors.py` | D-A robust z-score, D-B pooled binomial score | No (tested) |
| `incidents.py` | Merge alerted buckets into incidents | No (tested) |
| `evaluation.py` | Detection, delay, false incidents per day | Yes, the only one |
| `plots.py` | Chart of a run | Yes, through `evaluation.load_labels` |
| `cli.py` | Commands above, run identity, one-time report rule | Via `evaluation.py` |
