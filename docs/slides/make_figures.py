"""Figures for the slides and the weekly report (vector PDF in docs/slides/figures/).

Reads only what the dashboard reads: results/published.json (test and report numbers, quoted),
the committed Stage G bundles in results/, and the local Product 01 TUNING run. Nothing under
artifacts/runs/*/test/ and no report-simulation run is opened (test-once rule).

Run: make slides-figures   (or: uv run python docs/slides/make_figures.py)
"""

import json
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from dashboard.build import MIN_ATTEMPTS, hourly, load  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
OUT = Path(__file__).with_name("figures")
S1, S2, S3, MUTED, INK, INK2, GRID = (
    "#2a78d6", "#eb6834", "#1baf7a", "#c3c2b7", "#0b0b0b", "#52514e", "#e1e0d9",
)  # fmt: skip
RED = "#d03b3b"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 8, "axes.edgecolor": MUTED,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
    "grid.color": GRID, "grid.linewidth": 0.8, "axes.axisbelow": True,
    "legend.frameon": False, "savefig.bbox": "tight", "pdf.fonttype": 42,
})  # fmt: skip


def vn(x: float, d: int = 3) -> str:
    return f"{x:,.{d}f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def bundle(prefix: str) -> dict:
    path = next((REPO / "results").glob(f"{prefix}-*/results.json"))
    return json.loads(path.read_text("utf-8"))


def save(fig: plt.Figure, name: str) -> None:
    fig.savefig(OUT / f"{name}.pdf")
    plt.close(fig)
    print(OUT / f"{name}.pdf")


def p01_failure(ctx) -> None:
    p = ctx.p01
    if p is None or p.kpi is None:
        print("skip p01_failure: no tuning run (make demo)")
        return
    index, per = hourly(p.kpi)
    local = index.tz_convert("Asia/Ho_Chi_Minh")
    providers = sorted(k for k in per if k != "ALL")
    fig, axes = plt.subplots(len(providers), 1, figsize=(6.2, 2.9), sharex=True, sharey=True)
    for ax, prov, color in zip(axes, providers, (S1, S2, S3), strict=False):
        f = per[prov]
        rate = (f["technical_failures"] / f["attempts"]).where(f["attempts"] >= MIN_ATTEMPTS)
        for inc in p.incidents:
            if inc["detector"] == "pooled" and inc["target"] == prov and \
                    "technical_failure_rate" in inc["metrics"]:  # fmt: skip
                ax.axvspan(pd.Timestamp(inc["start"]).tz_convert("Asia/Ho_Chi_Minh"),
                           pd.Timestamp(inc["end"]).tz_convert("Asia/Ho_Chi_Minh"),
                           color=RED, alpha=0.18, lw=0)  # fmt: skip
        for lab in p.labels:
            if lab["type"] in {"provider_outage", "error_burst"} and \
                    lab["provider_id"] in (None, prov):  # fmt: skip
                ax.axvspan(pd.Timestamp(lab["start"]).tz_convert("Asia/Ho_Chi_Minh"),
                           pd.Timestamp(lab["end"]).tz_convert("Asia/Ho_Chi_Minh"),
                           fill=False, ls="--", lw=1, ec=INK2)  # fmt: skip
        ax.plot(local, rate.values, color=color, lw=1.4)
        ax.set_ylabel(prov, rotation=0, ha="right", va="center", color=INK)
        ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
        ax.set_ylim(0, 1)
    axes[-1].xaxis.set_major_formatter(matplotlib.dates.DateFormatter("%d/%m", tz=local.tz))
    handles = [plt.Rectangle((0, 0), 1, 1, color=RED, alpha=0.18),
               plt.Rectangle((0, 0), 1, 1, fill=False, ls="--", ec=INK2)]  # fmt: skip
    fig.legend(
        handles,
        ["detector báo sự cố", "sự cố cài sẵn (đáp án)"],
        loc="upper center",
        ncol=2,
        bbox_to_anchor=(0.5, 1.04),
    )
    save(fig, "p01_failure")


def p01_detectors(pub: dict) -> None:
    p01 = pub["product_01"]
    fig, ax = plt.subplots(figsize=(3.5, 2.5))
    names = ["Detector z-score\n(đường cơ sở)", "Detector nhị thức\n(chính)"]
    keys = ["robust_z", "pooled"]
    w = 0.36
    for k, (stage, color, label) in enumerate(
        [("tuning", MUTED, "bộ chỉnh ngưỡng"), ("report", S1, "bộ kiểm tra (một lần)")]
    ):
        vals = [p01[stage][d]["detected"] for d in keys]
        xs = [i + (k - 0.5) * w for i in range(2)]
        ax.bar(xs, vals, w * 0.92, color=color, label=label)
        for x, v in zip(xs, vals, strict=True):
            ax.text(x, v + 0.08, f"{v}/4", ha="center", va="bottom", fontsize=8, color=INK)
    ax.set_xticks(range(2), names)
    ax.set_ylim(0, 4.9)
    ax.set_yticks(range(5))
    ax.set_ylabel("sự cố bắt được / 4")
    ax.legend(loc="upper left")
    save(fig, "p01_detectors")


def p02_prauc(pub: dict) -> None:
    models = pub["product_02"]["models"]
    names = {"rule_based": "Luật", "logistic": "Logistic\nRegression", "gbm": "Gradient\nBoosting"}
    fig, ax = plt.subplots(figsize=(3.7, 2.6))
    w = 0.36
    for i, m in enumerate(models):
        first = i == 0
        ax.bar(
            i - w / 2, m["valid_pr_auc"], w * 0.92, color=S2, label="validation" if first else None
        )
        ci = m.get("test_pr_auc_ci")
        err = [[m["test_pr_auc"] - ci[0]], [ci[1] - m["test_pr_auc"]]] if ci else None
        ax.bar(i + w / 2, m["test_pr_auc"], w * 0.92, color=S1, yerr=err, ecolor=INK, capsize=3,
               label="test (một lần)" if i == 0 else None)  # fmt: skip
        ax.text(i - w / 2, m["valid_pr_auc"] + 0.01, vn(m["valid_pr_auc"]), ha="center",
                va="bottom", fontsize=8)  # fmt: skip
        ax.text(i + w / 2, (ci[1] if ci else m["test_pr_auc"]) + 0.01, vn(m["test_pr_auc"]),
                ha="center", va="bottom", fontsize=8)  # fmt: skip
    ax.axhline(0.035, color=INK2, ls=":", lw=1, label="đoán ngẫu nhiên ≈ 0,035")
    ax.set_xticks(range(len(models)), [names[m["model"]] for m in models])
    ax.set_ylabel("PR-AUC")
    ax.set_ylim(0, 0.6)
    ax.legend(loc="upper left")
    save(fig, "p02_prauc")


def p02_calibration() -> None:
    gbm = bundle("cal")["models"]["gbm"]
    rows = [("Điểm gốc", "raw", MUTED), ("Dịch tiên nghiệm", "prior_shift", S1),
            ("Platt (chọn)", "platt", S1)]  # fmt: skip
    v3 = {k: gbm[k]["blocks"]["V3"] for _, k, _ in rows}
    truth = v3["raw"]["prevalence"]
    fig, axes = plt.subplots(1, 2, figsize=(6.0, 1.9))
    ax = axes[0]
    for i, (_, k, color) in enumerate(rows):
        ax.barh(i, v3[k]["mean_pred"], color=color, height=0.6)
        ax.text(v3[k]["mean_pred"] + 0.004, i, f"{v3[k]['mean_pred']:.1%}".replace(".", ","),
                va="center", fontsize=9)  # fmt: skip
    ax.axvline(truth, color=INK, ls="--", lw=1.2)
    ax.text(truth + 0.004, -0.5, f"tỷ lệ thật {truth:.1%}".replace(".", ","), fontsize=9)
    ax.set_yticks(range(3), [r[0] for r in rows])
    ax.invert_yaxis()
    ax.set_ylim(2.5, -0.9)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_title("Xác suất dự đoán trung bình", fontsize=9, loc="left")
    ax = axes[1]
    for i, (_, k, color) in enumerate(rows):
        ax.barh(i, v3[k]["log_loss"], color=color, height=0.6)
        ax.text(v3[k]["log_loss"] + 0.005, i, vn(v3[k]["log_loss"]), va="center", fontsize=9)
    ax.set_yticks(range(3), ["", "", ""])
    ax.set_ylim(2.5, -0.9)
    ax.set_title("Log loss (thấp hơn là tốt)", fontsize=9, loc="left")
    save(fig, "p02_calibration")


POLICY = {
    "none": "Không cảnh báo", "max_f1": "Ngưỡng F1 tốt nhất (mốc)",
    "cost_v2": "Ngưỡng chi phí cố định",
    "rule_raw": "Luật chi phí, điểm gốc", "rule_calibrated": "Luật chi phí, đã hiệu chỉnh",
    "top_0.5%": "Top 0,5%/ngày", "top_1%": "Top 1%/ngày", "top_2%": "Top 2%/ngày",
    "top_5%": "Top 5%/ngày",
}  # fmt: skip


def p02_policy() -> None:
    rows = sorted((r for r in bundle("pol")["v3"] if r["cost_key"] == "L0.75/R5/F1"),
                  key=lambda r: r["cost"])  # fmt: skip
    fig, ax = plt.subplots(figsize=(4.1, 2.7))
    for i, r in enumerate(rows):
        color = S1 if r["policy"] == "rule_calibrated" else MUTED
        lo, hi = r["cost_ci_day"]
        ax.barh(i, r["cost"], color=color, height=0.65,
                xerr=[[r["cost"] - lo], [hi - r["cost"]]], ecolor=INK2, capsize=2)  # fmt: skip
        ax.text(hi + 2500, i, vn(r["cost"], 0), va="center", fontsize=8)
    ax.set_yticks(range(len(rows)), [POLICY[r["policy"]] for r in rows])
    ax.invert_yaxis()
    ax.set_xticks([0, 50000, 100000, 150000, 200000])
    ax.xaxis.set_major_formatter(lambda v, _: f"{v / 1000:.0f}k")
    ax.set_xlabel("tổng chi phí giả định (đơn vị tương đối)")
    save(fig, "p02_policy")


def p02_transfer() -> None:
    res = bundle("pol")
    pts = [("khối chọn → khối đánh giá", res["transfer_v3"])] + [
        (f"tuần {r['select'][1:]} → tuần {r['evaluate'][1:]}", r["transfer"])
        for r in res["rolling"]
    ]
    fig, ax = plt.subplots(figsize=(3.2, 2.2))
    ax.axvline(0.05, color=INK, ls="--", lw=1.2)
    ax.text(0.0505, -0.55, "mục tiêu 5%", fontsize=8)
    for i, (_, t) in enumerate(pts):
        ax.plot([t["fpr"]], [i], "o", color=S1, ms=8, mec="white", mew=1.5)
        ax.text(t["fpr"] + 0.0012, i, f"{t['fpr']:.2%}".replace(".", ","), va="center", fontsize=8)
    ax.set_yticks(range(len(pts)), [p[0] for p in pts])
    ax.set_ylim(len(pts) - 0.5, -0.9)
    ax.set_xlim(0.03, 0.065)
    ax.set_xticks([0.03, 0.04, 0.05, 0.06])
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_xlabel("tỷ lệ báo nhầm thực tế ở giai đoạn sau")
    save(fig, "p02_transfer")


def p02_stability() -> None:
    weeks = bundle("stab")["weekly"]
    xs = list(range(len(weeks)))
    fig, axes = plt.subplots(2, 1, figsize=(3.6, 2.5), sharex=True,
                             gridspec_kw={"height_ratios": [3, 2]})  # fmt: skip
    ax = axes[0]
    for part, color, name in (("train", S2, "train (trong mẫu)"), ("valid", S1, "validation")):
        pts = [(i, w["pr_auc"]) for i, w in enumerate(weeks) if w["part"] == part]
        ax.plot(*zip(*pts, strict=True), "o-", color=color, ms=4, lw=1.6, label=name)
    ax.set_ylabel("PR-AUC")
    ax.legend(loc="lower center", bbox_to_anchor=(0.5, 1.0), ncol=2)
    first_valid = next(i for i, w in enumerate(weeks) if w["part"] == "valid")
    for a in axes:
        a.axvspan(first_valid - 0.5, len(weeks) - 0.5, color=S1, alpha=0.06, lw=0)
    ax = axes[1]
    ax.plot(xs, [w["prevalence"] for w in weeks], "o-", color=S3, ms=3.5, lw=1.4)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_ylabel("tỷ lệ gian lận")
    ax.set_xticks(xs[::3], [str(i + 1) for i in xs[::3]], fontsize=7)
    ax.set_xlabel("tuần (nền xanh: validation)")
    save(fig, "p02_stability")


def p02_scores(ctx) -> None:
    p = ctx.p02
    if p.scores_csv is None:
        print("skip p02_scores: no scoring run (make score)")
        return
    probs = p.scores_csv["score_calibrated"]
    edges = [0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.01]
    names = ["<1%", "1–2%", "2–5%", "5–10%", "10–20%", "20–50%", "≥50%"]
    counts = [
        int(((probs >= a) & (probs < b)).sum()) for a, b in zip(edges, edges[1:], strict=False)
    ]
    fig, ax = plt.subplots(figsize=(3.4, 2.4))
    ax.bar(range(len(counts)), counts, color=S1, width=0.7)
    for i, c in enumerate(counts):
        ax.text(i, c + 10, str(c), ha="center", fontsize=8)
    ax.set_xticks(range(len(counts)), names)
    ax.set_xlabel("xác suất gian lận đã hiệu chỉnh")
    ax.set_ylabel("số giao dịch")
    save(fig, "p02_scores")


def tests_progress() -> None:
    steps = [("đầu tuần", 381), ("độ ổn định", 414), ("đóng gói", 429), ("chấm điểm lô", 439),
             ("demo", 443), ("có PostgreSQL", 454), ("giao diện", 460),
             ("dashboard", 463)]  # fmt: skip
    fig, ax = plt.subplots(figsize=(3.5, 2.4))
    ax.plot(range(len(steps)), [s[1] for s in steps], "o-", color=S1, lw=1.8, ms=5)
    for i, (_, n) in enumerate(steps):
        ax.text(i, n + 3, str(n), ha="center", fontsize=8)
    ax.set_xticks(range(len(steps)), [s[0] for s in steps], rotation=25, ha="right", fontsize=8)
    ax.set_ylim(370, 480)
    ax.set_ylabel("test pass")
    save(fig, "tests_progress")


def dashboard_crop() -> None:
    """Top of the README dashboard screenshot (tiles + pipeline), readable on a slide."""
    from PIL import Image

    src = REPO / "docs" / "assets" / "results" / "dashboard.png"
    Image.open(src).crop((0, 0, 1440, 715)).save(OUT / "dashboard_top.png")
    print(OUT / "dashboard_top.png")


def main() -> int:
    OUT.mkdir(exist_ok=True)
    pub = json.loads((REPO / "results" / "published.json").read_text("utf-8"))
    ctx = load(REPO / "artifacts", REPO)
    p01_failure(ctx)
    p01_detectors(pub)
    p02_prauc(pub)
    p02_calibration()
    p02_policy()
    p02_transfer()
    p02_stability()
    p02_scores(ctx)
    tests_progress()
    dashboard_crop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
