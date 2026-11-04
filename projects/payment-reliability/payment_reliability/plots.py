"""Chart of one detection run: each anomaly window with its KPI and both detector scores.

Reads a run folder (scores.parquet, config.yaml) and the simulation's labels, so it belongs to
evaluation, not detection.
"""

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
import yaml  # noqa: E402

from payment_reliability.evaluation import load_labels  # noqa: E402
from payment_reliability.kpi import load_kpis  # noqa: E402

INK, INK_2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
COLORS = {"pooled": "#2a78d6", "robust_z": "#eb6834"}
NAMES = {"pooled": "D-B gộp cửa sổ", "robust_z": "D-A z-score bền vững"}
METRIC = {
    "provider_outage": ("technical_failure_rate", "Tỷ lệ lỗi kỹ thuật"),
    "error_burst": ("technical_failure_rate", "Tỷ lệ lỗi kỹ thuật"),
    "latency_degradation": ("latency_p50", "Trung vị độ trễ (ms)"),
    "traffic_drop": ("method_share", "Tỷ trọng trong payment mới"),
}
TYPE_VN = {
    "provider_outage": "Provider lỗi",
    "error_burst": "Bùng lỗi mạng",
    "latency_degradation": "Độ trễ tăng",
    "traffic_drop": "Mất lưu lượng",
}


def _kpi_values(kpis: dict[str, pd.DataFrame], metric: str, target: str) -> pd.Series:
    if metric == "method_share":
        m = kpis["method_15m"]
        g = m[m["payment_method"] == target]
        return g.set_index("bucket_start")["method_share"]
    p = kpis["provider_15m"]
    g = p[p["provider_id"] == target].set_index("bucket_start")
    col = "latency_p50_ms" if metric == "latency_p50" else "technical_failure_rate"
    return g[col]


def plot_run(run_dir: Path, kpi_root: Path, sim_root: Path, out: Path, hours: int = 8) -> Path:
    """One column per anomaly: KPI of its target (top), scores and thresholds (bottom)."""
    cfg = yaml.safe_load((run_dir / "config.yaml").read_text("utf-8"))
    sid = json.loads((run_dir / "evaluation.json").read_text("utf-8"))["simulation_id"]
    scores = pd.read_parquet(run_dir / "scores.parquet")
    kpis = load_kpis(kpi_root, sid)
    labels = load_labels(sim_root / sid)
    thresholds = {d: cfg["detectors"][d]["threshold"] for d in COLORS}
    fig, axes = plt.subplots(2, len(labels), figsize=(4.2 * len(labels), 5.2), sharex="col",
                             gridspec_kw={"height_ratios": [1.2, 1]}, squeeze=False)  # fmt: skip
    for col, lab in enumerate(labels):
        start, end = pd.Timestamp(lab["start"]), pd.Timestamp(lab["end"])
        lo, hi = start - pd.Timedelta(hours=hours), end + pd.Timedelta(hours=hours / 2)
        target = lab["provider_id"] or lab["payment_method"] or "ALL"
        metric, ylabel = METRIC[lab["type"]]
        top, bottom = axes[0][col], axes[1][col]
        values = _kpi_values(kpis, metric, target)
        values = values[(values.index >= lo) & (values.index <= hi)]
        for ax in (top, bottom):
            ax.axvspan(start, end, color=MUTED, alpha=0.18, lw=0)
            ax.spines[["top", "right"]].set_visible(False)
            ax.spines[["left", "bottom"]].set_color("#c3c2b7")
            ax.tick_params(colors=INK_2, labelsize=8, length=0)
            ax.grid(axis="y", color=GRID, lw=0.8)
            ax.set_axisbelow(True)
        top.plot(values.index, values.to_numpy(), color=INK_2, lw=1.5, drawstyle="steps-post")
        if metric != "latency_p50":
            top.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
        top.set_title(f"{TYPE_VN[lab['type']]} x{lab['magnitude']:g} · {target}", loc="left",
                      fontsize=10, fontweight="bold", color=INK)  # fmt: skip
        top.set_ylabel(ylabel, fontsize=8.5, color=INK_2)
        for det, color in COLORS.items():
            s = scores[(scores["detector"] == det) & (scores["target"] == target)
                       & (scores["metric"] == metric)]  # fmt: skip
            s = s[(s["bucket_start"] >= lo) & (s["bucket_start"] <= hi)]
            bottom.plot(s["bucket_start"], s["score"].to_numpy(), color=color, lw=2,
                        label=NAMES[det] if col == 0 else None)  # fmt: skip
            bottom.axhline(thresholds[det], color=color, ls="--", lw=1)
        bottom.set_ylabel("Điểm (z)", fontsize=8.5, color=INK_2)
        low, high = bottom.get_ylim()
        bottom.set_ylim(min(low, -2), max(high, max(thresholds.values()) * 1.15))
        bottom.xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d/%m\n%H:%M"))
        bottom.set_xlim(lo, hi)
    handles, names = axes[1][0].get_legend_handles_labels()
    handles.append(matplotlib.patches.Patch(color=MUTED, alpha=0.3))
    names.append("Cửa sổ bất thường đã cài")
    fig.legend(handles, names, loc="lower center", ncol=3, frameon=False, fontsize=9)
    fig.suptitle(
        f"Phát hiện bất thường trên mô phỏng {sid} (đường đứt: ngưỡng; giờ UTC)",
        x=0.01, ha="left", fontsize=11, fontweight="bold", color=INK,
    )  # fmt: skip
    fig.tight_layout(rect=(0, 0.06, 1, 0.96))
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=170, facecolor="#ffffff")
    plt.close(fig)
    return out
