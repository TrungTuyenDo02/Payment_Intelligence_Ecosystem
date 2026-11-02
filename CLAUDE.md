@AGENTS.md

# CLAUDE.md — session protocol for Claude Code

`AGENTS.md` (imported above) is the source of truth for scope, hard rules, stack and task acceptance criteria. This file only adds how to run the work in order. If the two files ever conflict, `AGENTS.md` wins; report the conflict.

## Language

- Code, identifiers, comments, commit messages: English.
- Reports to the owner and anything under `docs/`: Vietnamese (the owner is a Vietnamese student who must be able to explain every step).
- Explain *why* in reports, not only *what*. The owner has to defend this work in front of mentors.

## Data location

The owner has already downloaded the IEEE-CIS files on their personal computer. Expected layout (git-ignored):

```
datasets/raw/ieee-cis/
  train_transaction.csv
  train_identity.csv
  test_transaction.csv      # NO labels (isFraud is absent). Never use for evaluation.
  test_identity.csv         # NO labels.
  sample_submission.csv     # ignore
```

- Allow the path to be overridden with the environment variable `IEEE_CIS_DIR`.
- Evaluation uses **only** `train_*` files and our own time-based split. The Kaggle `test_*` files carry no labels and must not be used for metrics.
- If a file is missing, stop with a clear message that names the missing file and where it must be placed. Do not look elsewhere on the disk and do not try to download anything.

## Pretrained models: policy

Public models trained on IEEE-CIS exist (for example on Hugging Face). They were trained on this same dataset with unknown splits, so scoring our validation or test rows with them is contaminated.

- Do **not** download, load or run any pretrained fraud model or `joblib`/`pickle` file from the internet. Loading such files can execute arbitrary code.
- Do not copy code or features from public notebooks without telling the owner the source and licence.
- Published numbers from model cards may be mentioned in a report only as clearly labelled external reference points, never as our results.

## Execution order

Run tasks strictly in this order. One task per session when possible; start a fresh session (`/clear`) between tasks to keep context small.

| Step | Task | Gate before moving on |
| --- | --- | --- |
| 1 | T01 repo skeleton | `make setup lint test` pass; Postgres container healthy |
| 2 | T02 contract drafts | **Owner reviews** the draft schema; do not proceed until told "approved" |
| 3 | T03 dataset manifest tooling | Tests pass |
| 4 | T04 IEEE-CIS adapter | Tests pass on the mini-fixture; run on the real files once they are present and report row counts |
| 5 | T05 time-based split | No-overlap test passes; split boundaries printed in the report |
| 6 | T05b EDA profiling | **STOP.** Owner reads the tables, fills `eda-summary.md` decisions, marks rows `approved` |
| 7 | T06 metrics | Tests pass |
| 8 | T07 rule-based baseline | Thresholds derived from train only (tested) |
| 9 | T08 logistic baseline | Uses only approved decisions; fit on train only (tested) |
| 10 | T09 run log and CLI | `make baseline` creates a full run folder; test-once rule tested |
| 11 | T10 leakage guard tests | Guards fail when they should |

After T10, stop and wait. Do not start Stage C or anything under "Out of scope" in `AGENTS.md`.

## How to work on each task

1. **Plan first.** Read the task row in `AGENTS.md`, list the files you will touch and the tests you will write. Show the plan and wait for a go-ahead if the task has any ambiguity.
2. **Branch** `task/<ID>-<slug>`. Small commits.
3. **Tests with code.** Write the test before or together with the implementation. Run `make lint` and `make test` before reporting.
4. **Stay inside the allowed files** for the task. If you need another file, ask.
5. **Report in Vietnamese** using the format in section 10 of `AGENTS.md`, plus one extra block: "Điều chủ dự án cần hiểu để giải thích phần này" — 3 to 5 sentences covering the idea, the input and output, and what would go wrong if the step were skipped.
6. **Stop** at the end of the task. Do not roll into the next task without the owner's go-ahead.

## Stop conditions (ask instead of guessing)

- The real data files are not where expected, or a column name differs from what the code assumes.
- A decision would change a frozen contract, the split rule, or the test-once rule.
- A test fails and the fix would require changing the specification.
- You are about to add a dependency or tool not listed in `AGENTS.md`.
- Anything in the repo appears to contain company data or credentials.

## Things to avoid

- Do not "improve" the model to get a nicer metric. Baselines are meant to be simple and honest.
- Do not tune on the test split, and do not run `make baseline-final` unless the owner explicitly asks.
- Do not generate large amounts of boilerplate or documentation nobody asked for.
- Do not write conclusions in `eda-summary.md`; write proposals with evidence and leave the status as `proposed`.
