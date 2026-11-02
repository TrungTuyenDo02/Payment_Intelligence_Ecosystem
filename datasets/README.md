# datasets

- `raw/` is git-ignored. The owner places files here; agents never download data.
- `manifests/` holds one YAML manifest per dataset.

## IEEE-CIS layout

```
datasets/raw/ieee-cis/
  train_transaction.csv
  train_identity.csv
  test_transaction.csv      # no labels, never used for evaluation
  test_identity.csv         # no labels
  sample_submission.csv     # ignored
```

Override the folder with the environment variable `IEEE_CIS_DIR`.
Licence: Kaggle competition terms, research use only. Verify before any other use.
