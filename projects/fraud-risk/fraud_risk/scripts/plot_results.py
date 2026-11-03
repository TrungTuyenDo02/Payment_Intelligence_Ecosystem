"""Draw result charts from one baseline run folder (`make report`).

Reads only `metrics.json` and `split.json` of an existing run, so it never touches
data or models. Charts and a Markdown summary table go to `docs/assets/results/`.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ARTIFACTS = REPO_ROOT / "artifacts"
DEFAULT_OUT = REPO_ROOT / "docs" / "assets" / "results"

MODEL_LABELS = {"rule_based": "Luật (rule-based)", "logistic": "Logistic Regression"}
PART_LABELS = {"train": "Train", "valid": "Validation", "test": "Test"}
PART_COLORS = {"train": "#9aa5b1", "valid": "#2f6fdb", "test": "#1a9e5c"}


class ReportError(RuntimeError):
    """No usable run folder."""


def latest_run_dir(artifacts_dir: Path) -> Path:
    """Most recently written run folder (validation or test) under `artifacts/runs/`."""
    candidates = sorted(
        (artifacts_dir / "runs").glob("**/metrics.json"), key=lambda p: p.stat().st_mtime
    )
    if not candidates:
        raise ReportError(f"no run found under {artifacts_dir / 'runs'}; run `make baseline` first")
    return candidates[-1].parent


def _load(run_dir: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        split = json.loads((run_dir / "split.json").read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ReportError(f"{run_dir} is not a complete run folder: {exc.filename}") from exc
    return metrics, split


def _eval_parts(metrics: dict[str, Any]) -> list[str]:
    first = next(iter(metrics["models"].values()))
    return [p for p in ("valid", "test") if p in first]


def _style(ax: plt.Axes, title: str, ylabel: str) -> None:
    ax.set_title(title, loc="left", fontsize=12, fontweight="bold")
    ax.set_ylabel(ylabel)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.3)
    ax.set_axisbelow(True)


def plot_pr_auc(metrics: dict[str, Any], out: Path) -> Path:
    """PR-AUC per model and partition, with the 95% bootstrap CI and the random baseline."""
    parts, models = _eval_parts(metrics), list(metrics["models"])
    width = 0.8 / len(parts)
    fig, ax = plt.subplots(figsize=(7, 4))
    for j, part in enumerate(parts):
        xs = [i + (j - (len(parts) - 1) / 2) * width for i in range(len(models))]
        vals = [metrics["models"][m][part]["pr_auc"] for m in models]
        cis = [metrics["models"][m][part]["pr_auc_ci"] for m in models]
        err = [
            [v - c["low"] for v, c in zip(vals, cis, strict=True)],
            [c["high"] - v for v, c in zip(vals, cis, strict=True)],
        ]
        bars = ax.bar(
            xs,
            vals,
            width * 0.9,
            yerr=err,
            capsize=4,
            color=PART_COLORS[part],
            label=PART_LABELS[part],
        )
        ax.bar_label(bars, fmt="%.3f", padding=3, fontsize=9)
        prevalence = metrics["models"][models[0]][part]["prevalence"]
        ax.axhline(prevalence, color=PART_COLORS[part], ls="--", lw=1)
    ax.plot([], [], color="#555", ls="--", lw=1, label="Mô hình ngẫu nhiên (= tỷ lệ gian lận)")
    ax.set_xticks(range(len(models)), [MODEL_LABELS.get(m, m) for m in models])
    _style(ax, "PR-AUC (thanh lỗi: khoảng tin cậy 95%)", "PR-AUC")
    ax.legend(frameon=False)
    return _save(fig, out / "pr_auc.png")


def plot_recall_targets(metrics: dict[str, Any], out: Path) -> Path:
    """Recall at the precision target and at the FPR target, per model and partition."""
    parts, models = _eval_parts(metrics), list(metrics["models"])
    sample = metrics["models"][models[0]][parts[0]]
    p_target = sample["recall_at_precision"]["precision_target"]
    f_target = sample["recall_at_fpr"]["fpr_target"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    for ax, key, title in (
        (axes[0], "recall_at_precision", f"Recall khi precision ≥ {p_target:g}"),
        (axes[1], "recall_at_fpr", f"Recall khi FPR ≤ {f_target:.0%}"),
    ):
        width = 0.8 / len(parts)
        for j, part in enumerate(parts):
            xs = [i + (j - (len(parts) - 1) / 2) * width for i in range(len(models))]
            vals = [metrics["models"][m][part][key]["recall"] for m in models]
            bars = ax.bar(xs, vals, width * 0.9, color=PART_COLORS[part], label=PART_LABELS[part])
            ax.bar_label(bars, fmt="%.2f", padding=3, fontsize=9)
        ax.set_xticks(range(len(models)), [MODEL_LABELS.get(m, m) for m in models])
        ax.set_ylim(0, 1.05)
        _style(ax, title, "Recall")
    axes[0].legend(frameon=False)
    return _save(fig, out / "recall_targets.png")


def plot_split(metrics: dict[str, Any], split: dict[str, Any], out: Path) -> Path:
    """Rows and fraud rate of each chronological partition."""
    rates = dict(split.get("fraud_rate", {}))
    first = next(iter(metrics["models"].values()))
    for part in _eval_parts(metrics):
        rates.setdefault(part, first[part]["prevalence"])
    parts = [p for p in PART_LABELS if p in split["rows"]]
    fig, ax = plt.subplots(figsize=(7, 3.6))
    bars = ax.bar(
        [PART_LABELS[p] for p in parts],
        [split["rows"][p] for p in parts],
        color=[PART_COLORS[p] for p in parts],
    )
    labels = [
        f"{split['rows'][p]:,} dòng\n" + (f"gian lận {rates[p]:.2%}" if p in rates else "chưa mở")
        for p in parts
    ]
    ax.bar_label(bars, labels=labels, padding=3, fontsize=9)
    ax.set_ylim(0, max(split["rows"].values()) * 1.3)
    _style(ax, "Chia dữ liệu theo thời gian", "Số giao dịch")
    return _save(fig, out / "split.png")


def summary_table(metrics: dict[str, Any]) -> str:
    """Markdown table of the headline numbers, ready to paste into the README."""
    parts = _eval_parts(metrics)
    sample = metrics["models"][next(iter(metrics["models"]))][parts[0]]
    p_target = sample["recall_at_precision"]["precision_target"]
    f_target = sample["recall_at_fpr"]["fpr_target"]
    lines = [
        f"Run `{metrics['run_id']}` (stage: {metrics['stage']})",
        "",
        f"| Mô hình | Tập | PR-AUC [95% CI] | Tỷ lệ gian lận | Recall @ precision {p_target:g} "
        f"| Recall @ FPR {f_target:.0%} |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for model, by_part in metrics["models"].items():
        for part in parts:
            m = by_part[part]
            ci = m["pr_auc_ci"]
            lines.append(
                f"| {MODEL_LABELS.get(model, model)} | {PART_LABELS[part]} "
                f"| {m['pr_auc']:.3f} [{ci['low']:.3f}, {ci['high']:.3f}] "
                f"| {m['prevalence']:.2%} | {m['recall_at_precision']['recall']:.2f} "
                f"| {m['recall_at_fpr']['recall']:.2f} |"
            )
    return "\n".join(lines) + "\n"


def _save(fig: plt.Figure, path: Path) -> Path:
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def build_report(run_dir: Path, out: Path) -> list[Path]:
    """Write all charts and `summary.md` for one run; return the written paths."""
    metrics, split = _load(run_dir)
    out.mkdir(parents=True, exist_ok=True)
    summary = out / "summary.md"
    summary.write_text(summary_table(metrics), encoding="utf-8")
    return [
        plot_split(metrics, split, out),
        plot_pr_auc(metrics, out),
        plot_recall_targets(metrics, out),
        summary,
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, help="run folder; default: the latest run")
    parser.add_argument("--artifacts-dir", type=Path, default=DEFAULT_ARTIFACTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    try:
        run_dir = args.run_dir or latest_run_dir(args.artifacts_dir)
        paths = build_report(run_dir, args.out)
    except ReportError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"report for {run_dir}:")
    for path in paths:
        print(f"  {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
