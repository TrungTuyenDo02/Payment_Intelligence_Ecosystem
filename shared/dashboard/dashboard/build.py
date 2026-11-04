"""`make dashboard`: one static HTML page from the run folders of both products (ADR 0007).

Reads only finished outputs under `artifacts/` (KPI Parquet, detection runs, fraud run folders,
leakage experiment). It trains nothing and reads no dataset. Sections whose runs do not exist yet
say so instead of failing. Charts are PNG images embedded in the page, so the file works offline
and can be attached to the report.
"""

import argparse
import base64
import io
import json
import subprocess
import sys
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCAL = ZoneInfo("Asia/Ho_Chi_Minh")
# Categorical slots 1-3 of the dataviz palette (validated all-pairs); ALL in neutral ink.
PROVIDER_COLORS = ["#2a78d6", "#eb6834", "#1baf7a"]
INK, INK_2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
MIN_ATTEMPTS = 20  # hours with fewer attempts are hidden: their rates are mostly noise
MODEL_VN = {"rule_based": "Luật", "logistic": "Logistic Regression", "gbm": "Gradient Boosting"}
METRIC_VN = {
    "technical_failure_rate": "tỷ lệ lỗi kỹ thuật",
    "latency_p50": "độ trễ",
    "method_share": "tỷ trọng phương thức",
}


def vn(x: float | None, d: int = 3) -> str:
    """Vietnamese number format: `.` groups thousands, `,` marks decimals."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return f"{x:,.{d}f}".replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def pct(x: float | None, d: int = 1) -> str:
    return "—" if x is None or pd.isna(x) else vn(x * 100, d) + "%"


def local(text: str) -> str:
    """UTC ISO time -> `dd/mm HH:MM` in Vietnam time."""
    t = datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(LOCAL)
    return t.strftime("%d/%m %H:%M")


def _png(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, facecolor="#ffffff", bbox_inches="tight")
    plt.close(fig)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def _style(ax: plt.Axes) -> None:
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color("#c3c2b7")
    ax.tick_params(colors=INK_2, labelsize=8, length=0)
    ax.grid(axis="y", color=GRID, lw=0.8)
    ax.set_axisbelow(True)


def _table(head: list[str], rows: list[list[str]], numeric_from: int = 1) -> str:
    th = "".join(f"<th>{escape(h)}</th>" for h in head)
    body = ""
    for r in rows:
        cells = "".join(
            f'<td class="{"num" if i >= numeric_from else ""}">{c}</td>' for i, c in enumerate(r)
        )
        body += f"<tr>{cells}</tr>"
    return f"<table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table>"


# ---------- Product 01 ----------


def find_detection_run(artifacts: Path) -> Path | None:
    """The report-simulation run if it exists (the one to show), else the latest tuning run."""
    det = artifacts / "detections"
    for pattern in ("*/report/evaluation.json", "*/evaluation.json"):
        runs = sorted(det.glob(pattern), key=lambda p: p.stat().st_mtime)
        if runs:
            return runs[-1].parent
    return None


def provider_summary(prov: pd.DataFrame) -> pd.DataFrame:
    """Whole-period KPIs per provider from the 15-minute KPI table."""
    g = prov.groupby("provider_id")
    out = pd.DataFrame(
        {
            "attempts": g["attempts"].sum(),
            "success_rate": g["successes"].sum() / g["attempts"].sum(),
            "first_attempt_success_rate": g["first_attempt_successes"].sum()
            / g["first_attempts"].sum(),
            "technical_failure_rate": g["technical_failures"].sum() / g["attempts"].sum(),
            "business_failure_rate": g["business_failures"].sum() / g["attempts"].sum(),
            "retry_share": g["retries"].sum() / g["attempts"].sum(),
            "median_bucket_p50_ms": g["latency_p50_ms"].median(),
        }
    )
    return out.loc[sorted(out.index, key=lambda p: (p == "ALL", p))]


def failure_chart(prov: pd.DataFrame, incidents: list[dict[str, Any]]) -> str:
    """Hourly technical failure rate per provider, D-B incidents shaded on their provider."""
    providers = sorted(p for p in prov["provider_id"].unique() if p != "ALL")
    fig, axes = plt.subplots(len(providers), 1, figsize=(11, 1.7 * len(providers)), sharex=True,
                             squeeze=False)  # fmt: skip
    for ax, provider, color in zip(axes[:, 0], providers, PROVIDER_COLORS, strict=False):
        g = prov[prov["provider_id"] == provider].set_index("bucket_start")
        hourly = g[["technical_failures", "attempts"]].astype(float).resample("1h").sum()
        rate = hourly["technical_failures"] / hourly["attempts"].where(
            hourly["attempts"] >= MIN_ATTEMPTS
        )
        ax.plot(rate.index.tz_convert(LOCAL), rate.to_numpy(), color=color, lw=1.6)
        for inc in incidents:
            if inc["target"] == provider and "technical_failure_rate" in inc["metrics"]:
                s = pd.Timestamp(inc["start"]).tz_convert(LOCAL)
                e = pd.Timestamp(inc["end"]).tz_convert(LOCAL)
                ax.axvspan(s, max(e, s + pd.Timedelta(hours=2)), color="#e34948", alpha=0.3, lw=0)
        ax.set_ylabel(provider, fontsize=9, color=INK, rotation=0, ha="right", va="center")
        ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
        _style(ax)
    axes[-1, 0].xaxis.set_major_formatter(mdates.DateFormatter("%d/%m", tz=LOCAL))
    fig.suptitle("Tỷ lệ lỗi kỹ thuật theo giờ (giờ Việt Nam); vùng đỏ: sự cố detector báo; "
                 f"ẩn giờ có dưới {MIN_ATTEMPTS} attempt",
                 x=0.01, ha="left", fontsize=10, fontweight="bold", color=INK)  # fmt: skip
    fig.tight_layout()
    return _png(fig)


def latency_chart(prov: pd.DataFrame, incidents: list[dict[str, Any]]) -> str:
    """Hourly median of the 15-minute median latency, per provider, direct-labelled;
    latency incidents shaded."""
    providers = sorted(p for p in prov["provider_id"].unique() if p != "ALL")
    fig, ax = plt.subplots(figsize=(11, 2.6))
    ends = []
    for provider, color in zip(providers, PROVIDER_COLORS, strict=False):
        g = prov[prov["provider_id"] == provider].set_index("bucket_start")
        hourly = g["latency_p50_ms"].astype(float).resample("1h").median()
        attempts = g["latency_attempts"].astype(float).resample("1h").sum()
        hourly = hourly.where(attempts >= MIN_ATTEMPTS)
        ax.plot(hourly.index.tz_convert(LOCAL), hourly.to_numpy(), color=color, lw=1.6)
        last = hourly.dropna()
        if len(last):
            ends.append([float(last.iloc[-1]), last.index[-1].tz_convert(LOCAL), provider])
    for inc in incidents:
        if inc["target_type"] == "provider" and "latency_p50" in inc["metrics"]:
            s = pd.Timestamp(inc["start"]).tz_convert(LOCAL)
            e = pd.Timestamp(inc["end"]).tz_convert(LOCAL)
            ax.axvspan(s, max(e, s + pd.Timedelta(hours=2)), color="#e34948", alpha=0.3, lw=0)
    ends.sort()
    low, high = ax.get_ylim()
    gap = (high - low) * 0.09  # keep direct labels apart
    for i in range(1, len(ends)):
        ends[i][0] = max(ends[i][0], ends[i - 1][0] + gap)
    x_end = max((e[1] for e in ends), default=None)
    for y, _, provider in ends:
        ax.annotate(provider, (x_end, y), xytext=(6, 0), textcoords="offset points",
                    fontsize=8, color=INK_2, va="center")  # fmt: skip
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d/%m", tz=LOCAL))
    ax.set_ylabel("ms", fontsize=9, color=INK_2)
    ax.set_title("Trung vị độ trễ theo giờ, không tính TIMEOUT; vùng đỏ: sự cố độ trễ; "
                 f"ẩn giờ có dưới {MIN_ATTEMPTS} attempt",
                 loc="left", fontsize=10,
                 fontweight="bold", color=INK)  # fmt: skip
    _style(ax)
    fig.tight_layout()
    return _png(fig)


def reliability_section(artifacts: Path) -> str:
    run = find_detection_run(artifacts)
    if run is None:
        return ('<p class="empty">Chưa có lần chạy detector. Chạy <code>make kpi</code> và '
                "<code>make detect</code> (Stage D).</p>")  # fmt: skip
    evaluation = json.loads((run / "evaluation.json").read_text("utf-8"))
    sid, stage = evaluation["simulation_id"], evaluation["stage"]
    kpi_file = artifacts / "kpi" / sid / "provider_15m.parquet"
    if not kpi_file.exists():
        cmd = f"make kpi SIM={escape(sid)}"
        return f'<p class="empty">Thiếu KPI của {escape(sid)}: chạy <code>{cmd}</code>.</p>'
    prov = pd.read_parquet(kpi_file)
    incidents = [i for i in json.loads((run / "incidents.json").read_text("utf-8"))
                 if i["detector"] == "pooled"]  # fmt: skip
    summary = provider_summary(prov)
    all_row = summary.loc["ALL"]
    days = (prov["bucket_start"].max() - prov["bucket_start"].min()) / pd.Timedelta("1D")
    tiles = "".join(
        f'<div class="tile"><div class="label">{label}</div><div class="value">{value}</div></div>'
        for label, value in (
            ("Attempt", vn(float(all_row["attempts"]), 0)),
            ("Thành công", pct(all_row["success_rate"])),
            ("Thành công ngay lần đầu", pct(all_row["first_attempt_success_rate"])),
            ("Lỗi kỹ thuật", pct(all_row["technical_failure_rate"])),
            ("Sự cố detector báo", str(len(incidents))),
        )
    )
    rows = [
        [escape(p), vn(float(r["attempts"]), 0), pct(r["success_rate"]),
         pct(r["first_attempt_success_rate"]), pct(r["technical_failure_rate"]),
         pct(r["business_failure_rate"]), pct(r["retry_share"]),
         vn(r["median_bucket_p50_ms"], 0)]
        for p, r in summary.iterrows()
    ]  # fmt: skip
    provider_table = _table(
        ["Provider", "Attempt", "Thành công", "Thành công lần đầu", "Lỗi kỹ thuật",
         "Lỗi nghiệp vụ", "Tỷ lệ retry", "Trung vị độ trễ (ms)"], rows,
    )  # fmt: skip
    inc_rows = [
        [escape(i["incident_id"]), escape(i["target"]),
         escape(", ".join(METRIC_VN.get(m, m) for m in i["metrics"])), local(i["start"]),
         f"{i['buckets'] * 15} phút", local(i["first_alert_at"]), vn(i["max_score"], 1)]
        for i in incidents
    ]  # fmt: skip
    incident_table = (
        _table(
            ["Sự cố", "Đối tượng", "Chỉ số", "Bắt đầu", "Kéo dài", "Cảnh báo lúc", "Điểm cao nhất"],
            inc_rows,
            numeric_from=4,
        )  # fmt: skip
        if inc_rows
        else '<p class="empty">Detector không báo sự cố nào.</p>'
    )
    ev = evaluation["detectors"]["pooled"]
    check_rows = [
        [escape(a["anomaly_id"]), escape(a["type"]), f"x{vn(a['magnitude'], 1)}",
         escape(a["target"]), "Có" if a["detected"] else "<b>Không</b>",
         "—" if a["delay_minutes"] is None else f"{a['delay_minutes']:.0f} phút"]
        for a in ev["anomalies"]
    ]  # fmt: skip
    return f"""
<p class="meta">Mô phỏng <code>{escape(sid)}</code> ({escape(stage)}), {vn(days, 0)} ngày, khung 15 phút.
Lần chạy detector <code>{escape(evaluation["run_id"])}</code>, detector D-B (gộp cửa sổ). Dữ liệu giả lập.</p>
<div class="tiles">{tiles}</div>
<h3>Theo provider (cả kỳ)</h3>{provider_table}
<img alt="Tỷ lệ lỗi kỹ thuật theo giờ của từng provider, vùng sự cố tô đỏ" src="{failure_chart(prov, incidents)}">
<img alt="Trung vị độ trễ theo giờ của từng provider" src="{latency_chart(prov, incidents)}">
<h3>Danh sách sự cố</h3>{incident_table}
<details><summary>Đối chiếu với sự cố đã cài sẵn (chỉ để đánh giá, người vận hành không thấy phần này)</summary>
{_table(["Bất thường", "Loại", "Độ lớn", "Đối tượng", "Phát hiện", "Độ trễ"], check_rows, numeric_from=2)}
<p class="meta">Bắt được {ev["detected"]}/{ev["total"]}; báo nhầm {vn(ev["false_per_day"], 2)} sự cố mỗi ngày.</p>
</details>"""  # noqa: E501


# ---------- Product 02 ----------


def fraud_runs(artifacts: Path) -> list[tuple[str, dict[str, Any]]]:
    """(run label, metrics.json) of every Stage B/E fraud run, test runs first per run id."""
    out = []
    for path in sorted((artifacts / "runs").glob("**/metrics.json")):
        metrics = json.loads(path.read_text("utf-8"))
        out.append((f"{metrics['run_id']} ({metrics['stage']})", metrics))
    return out


def fraud_section(artifacts: Path) -> str:
    runs = fraud_runs(artifacts)
    rows = []
    for label, metrics in runs:
        for model, parts in metrics["models"].items():
            for part in ("valid", "test"):
                if part not in parts:
                    continue
                m = parts[part]
                ci = m["pr_auc_ci"]
                rows.append([
                    escape(MODEL_VN.get(model, model)),
                    "Validation" if part == "valid" else "<b>Test</b>",
                    f"{vn(m['pr_auc'])} [{vn(ci['low'])}; {vn(ci['high'])}]",
                    pct(m["prevalence"], 2),
                    vn(m["recall_at_fpr"]["recall"], 2), f"<code>{escape(label)}</code>",
                ])  # fmt: skip
    table = (
        _table(
            ["Mô hình", "Tập", "PR-AUC [95% CI]", "Tỷ lệ gian lận", "Recall @ FPR 5%", "Lần chạy"],
            rows,
            numeric_from=2,
        )  # fmt: skip
        if rows
        else '<p class="empty">Chưa có lần chạy trong <code>artifacts/runs/</code> '
        "trên máy này (dataset IEEE-CIS chỉ có trên máy chủ dự án). "
        "Chạy <code>make baseline</code>, "
        "<code>make gbm</code>.</p>"
    )
    leak = sorted((artifacts / "experiments").glob("leak-*/summary.md"))
    leak_html = (
        f"<pre>{escape(leak[-1].read_text('utf-8'))}</pre>"
        if leak
        else '<p class="empty">Chưa chạy <code>make leakage</code>.</p>'
    )
    return f"""
<p class="meta">Dataset công khai IEEE-CIS, chia theo thời gian 60/20/20. Tập test chỉ mở một lần cho mỗi config đã chốt.
Điểm rủi ro chỉ hỗ trợ quyết định, không tự động chặn giao dịch.</p>
<h3>So sánh mô hình</h3>{table}
<h3>Thí nghiệm rò rỉ dữ liệu (chỉ validation)</h3>{leak_html}"""  # noqa: E501


# ---------- page ----------

CSS = """
:root{--bg:#f9f9f7;--surface:#ffffff;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--line:#e1e0d9}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);
font:15px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
main{max-width:1100px;margin:0 auto;padding:24px 16px 48px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:19px;margin:32px 0 8px;padding-top:8px;
border-top:1px solid var(--line)}h3{font-size:15px;margin:20px 0 8px}
.meta{color:var(--ink2);font-size:13px}.empty{color:var(--muted);font-style:italic}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin:12px 0}
.tile{background:var(--surface);border:1px solid var(--line);border-radius:8px;padding:12px}
.tile .label{color:var(--ink2);font-size:12px}.tile .value{font-size:22px;font-weight:600}
table{border-collapse:collapse;width:100%;background:var(--surface);font-size:13px;display:block;
overflow-x:auto}th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left;
white-space:nowrap}th{color:var(--ink2);font-weight:600}td.num{text-align:right;
font-variant-numeric:tabular-nums}img{max-width:100%;margin:12px 0;background:#fff}
pre{background:var(--surface);border:1px solid var(--line);padding:12px;overflow-x:auto;
font-size:12px}
details{margin:12px 0}summary{cursor:pointer;color:var(--ink2)}
"""


def build(artifacts: Path, git_sha: str = "") -> str:
    """The whole page as HTML text."""
    sha = f" · commit <code>{escape(git_sha[:7])}</code>" if git_sha else ""
    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Payment Intelligence Dashboard</title><style>{CSS}</style></head>
<body><main>
<h1>Payment Intelligence Ecosystem</h1>
<p class="meta">Dashboard tĩnh sinh bởi <code>make dashboard</code> từ kết quả các lần chạy{sha}. Không dùng dữ liệu thật của công ty.</p>
<h2>Product 01 · Độ ổn định thanh toán</h2>{reliability_section(artifacts)}
<h2>Product 02 · Rủi ro gian lận</h2>{fraud_section(artifacts)}
</main></body></html>
"""  # noqa: E501


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-dir", type=Path, default=REPO_ROOT / "artifacts")
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "artifacts" / "dashboard" / "index.html"
    )
    args = parser.parse_args(argv)
    try:
        sha = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
                             capture_output=True, text=True, check=True).stdout.strip()  # fmt: skip
    except (OSError, subprocess.CalledProcessError):
        sha = ""
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build(args.artifacts_dir, sha), encoding="utf-8")
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
