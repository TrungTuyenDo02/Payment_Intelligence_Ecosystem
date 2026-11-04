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
# One blue hue, light to dark in time order (validated as an ordinal ramp).
PART_COLORS = {"train": "#86b6ef", "valid": "#3987e5", "test": "#184f95"}
INK, INK_2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"


class ReportError(RuntimeError):
    """No usable run folder."""


def vn_number(value: float, decimals: int = 0) -> str:
    """Vietnamese number format: `.` groups thousands, `,` marks decimals."""
    text = f"{value:,.{decimals}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def vn_percent(value: float, decimals: int = 2) -> str:
    """Share in [0, 1] as a Vietnamese percentage, e.g. 0.0338 -> `3,38%`."""
    return vn_number(value * 100, decimals) + "%"


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


def _fraud_rates(metrics: dict[str, Any], split: dict[str, Any]) -> dict[str, float]:
    rates = dict(split.get("fraud_rate", {}))
    first = next(iter(metrics["models"].values()))
    for part in _eval_parts(metrics):
        rates.setdefault(part, first[part]["prevalence"])
    return rates


def plot_split(metrics: dict[str, Any], split: dict[str, Any], out: Path) -> Path:
    """One time axis cut into train, validation and test, with size and fraud rate."""
    rates = _fraud_rates(metrics, split)
    parts = [p for p in PART_LABELS if p in split["rows"]]
    total = sum(split["rows"][p] for p in parts)
    fig, ax = plt.subplots(figsize=(9, 2.1))
    left = 0.0
    for part in parts:
        n = split["rows"][part]
        width = n / total
        ax.barh(0, width - 0.003, left=left, height=0.5, color=PART_COLORS[part])
        ink = "#ffffff" if part != "train" else INK
        ax.text(
            left + width / 2,
            0,
            f"{PART_LABELS[part]} · {width:.0%}",
            ha="center",
            va="center",
            color=ink,
            fontsize=11,
            fontweight="bold",
        )
        rate = f"gian lận {vn_percent(rates[part])}" if part in rates else "chưa mở"
        ax.text(
            left + width / 2,
            -0.42,
            f"{vn_number(n)} giao dịch\n{rate}",
            ha="center",
            va="top",
            color=INK_2,
            fontsize=9.5,
        )
        left += width
    ax.annotate(
        "",
        xy=(1.0, 0.42),
        xytext=(0.0, 0.42),
        arrowprops={"arrowstyle": "->", "color": MUTED, "lw": 1.2},
    )
    ax.text(0.0, 0.5, "cũ hơn", color=MUTED, fontsize=9, va="bottom")
    ax.text(1.0, 0.5, "mới hơn (thời gian →)", color=MUTED, fontsize=9, va="bottom", ha="right")
    ax.set_xlim(0, 1)
    ax.set_ylim(-1.0, 0.75)
    ax.axis("off")
    ax.set_title(
        "Dữ liệu chia theo thời gian, không xáo trộn",
        loc="left",
        fontsize=12,
        fontweight="bold",
        color=INK,
    )
    return _save(fig, out / "split.png")


def plot_results(metrics: dict[str, Any], out: Path) -> Path:
    """Validation vs test per model: PR-AUC (95% CI) and recall at the FPR target."""
    parts, models = _eval_parts(metrics), list(metrics["models"])
    sample = metrics["models"][models[0]][parts[0]]
    f_target = sample["recall_at_fpr"]["fpr_target"]
    prevalence = [
        sample_part["prevalence"]
        for sample_part in (metrics["models"][models[0]][p] for p in parts)
    ]
    panels = (
        (
            "pr_auc",
            "PR-AUC (vệt mờ: khoảng tin cậy 95%)",
            (min(prevalence), max(prevalence)),
            "ngẫu nhiên",
        ),
        (
            "recall_at_fpr",
            f"Tỷ lệ gian lận bắt được khi chỉ báo nhầm {f_target:.0%} giao dịch tốt",
            (f_target, f_target),
            "ngẫu nhiên",
        ),
    )
    fig, axes = plt.subplots(1, 2, figsize=(10, 2.9), sharey=True)
    ys = list(range(len(models)))[::-1]
    for ax, (key, title, rand, rand_label) in zip(axes, panels, strict=True):
        vmax = 0.0
        for y, model in zip(ys, models, strict=True):
            vals = []
            for part in parts:
                m = metrics["models"][model][part]
                v = m["pr_auc"] if key == "pr_auc" else m[key]["recall"]
                vals.append(v)
                if key == "pr_auc":
                    ci = m["pr_auc_ci"]
                    ax.plot(
                        [ci["low"], ci["high"]],
                        [y, y],
                        color=PART_COLORS[part],
                        lw=4,
                        alpha=0.35,
                        solid_capstyle="round",
                        zorder=2,
                    )
                vmax = max(vmax, v)
            if len(vals) == 2:
                ax.plot(vals, [y, y], color=GRID, lw=2, zorder=1)
            for part, v in zip(parts, vals, strict=True):
                ax.scatter(
                    v,
                    y,
                    s=90,
                    color=PART_COLORS[part],
                    edgecolor="#ffffff",
                    linewidth=2,
                    zorder=3,
                    label=PART_LABELS[part] if y == ys[0] else None,
                )
                # Lower value labelled on its left, higher on its right: never overlap.
                left_side = len(vals) == 2 and v == min(vals) and v != max(vals)
                ax.annotate(
                    vn_number(v, 3 if key == "pr_auc" else 2),
                    (v, y),
                    xytext=(-9 if left_side else 9, 0),
                    textcoords="offset points",
                    ha="right" if left_side else "left",
                    va="center",
                    fontsize=9,
                    color=INK_2,
                )
        ax.axvspan(rand[0], rand[1] + 1e-3, color=MUTED, alpha=0.25, lw=0)
        ax.axvline(rand[1], color=MUTED, ls="--", lw=1)
        ax.text(rand[1], len(models) - 0.45, f" {rand_label}", color=MUTED, fontsize=8.5, va="top")
        ax.set_xlim(-0.02, max(vmax * 1.25, 0.1))
        ax.xaxis.set_major_formatter(lambda x, _: vn_number(x, 2))
        ax.set_title(title, loc="left", fontsize=10.5, fontweight="bold", color=INK)
        ax.spines[["top", "right", "left"]].set_visible(False)
        ax.spines["bottom"].set_color("#c3c2b7")
        ax.tick_params(colors=INK_2, length=0)
        ax.grid(axis="x", color=GRID, lw=0.8)
        ax.set_axisbelow(True)
        ax.set_ylim(-0.6, len(models) - 0.4)
    axes[0].set_yticks(ys, [MODEL_LABELS.get(m, m) for m in models], fontsize=10, color=INK)
    fig.legend(
        *axes[0].get_legend_handles_labels(),
        loc="lower center",
        ncol=len(parts),
        frameon=False,
        fontsize=9.5,
        bbox_to_anchor=(0.5, -0.02),
    )
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    return _save(fig, out / "results.png", tight=False)


def summary_table(metrics: dict[str, Any]) -> str:
    """Markdown table of the headline numbers, ready to paste into the README."""
    parts = _eval_parts(metrics)
    sample = metrics["models"][next(iter(metrics["models"]))][parts[0]]
    p_target = sample["recall_at_precision"]["precision_target"]
    f_target = sample["recall_at_fpr"]["fpr_target"]
    lines = [
        f"Run `{metrics['run_id']}` (stage: {metrics['stage']})",
        "",
        "| Mô hình | Tập | PR-AUC [95% CI] | Tỷ lệ gian lận "
        f"| Recall @ precision {vn_number(p_target, 1)} "
        f"| Recall @ FPR {f_target:.0%} |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for model, by_part in metrics["models"].items():
        for part in parts:
            m = by_part[part]
            ci = m["pr_auc_ci"]
            lines.append(
                f"| {MODEL_LABELS.get(model, model)} | {PART_LABELS[part]} "
                f"| {vn_number(m['pr_auc'], 3)} "
                f"[{vn_number(ci['low'], 3)}; {vn_number(ci['high'], 3)}] "
                f"| {vn_percent(m['prevalence'])} "
                f"| {vn_number(m['recall_at_precision']['recall'], 2)} "
                f"| {vn_number(m['recall_at_fpr']['recall'], 2)} |"
            )
    return "\n".join(lines) + "\n"


def _save(fig: plt.Figure, path: Path, tight: bool = True) -> Path:
    if tight:
        fig.tight_layout()
    fig.savefig(path, dpi=200, facecolor="#ffffff")
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
        plot_results(metrics, out),
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
