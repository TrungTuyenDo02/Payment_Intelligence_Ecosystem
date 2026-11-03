# dataset-management

Dataset manifest tooling (T03). Code lives in the inner package `dataset_management/` (ADR 0001).

A manifest records where a dataset came from, its licence note, the download date (supplied by the owner) and the SHA-256 of every file. Runs use the combined `checksum` so a changed file gives a different `run_id`.

Create the IEEE-CIS manifest after placing the files (run from the repo root):

```bash
PYTHONPATH=shared/dataset-management uv run python -m dataset_management.cli \
  --name ieee-cis \
  --source "Kaggle competition: IEEE-CIS Fraud Detection (https://www.kaggle.com/c/ieee-fraud-detection)" \
  --base-dir datasets/raw/ieee-cis \
  --file train_transaction.csv --file train_identity.csv \
  --download-date YYYY-MM-DD \
  --license-note "Kaggle competition terms, research use only, verify before any other use" \
  --out datasets/manifests/ieee-cis.yaml
```
