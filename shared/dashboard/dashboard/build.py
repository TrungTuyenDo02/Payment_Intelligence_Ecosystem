"""`make dashboard`: one static HTML page for both products (ADR 0007).

One scrolling page with a sidebar: KPI tiles, the two pipelines, Product 01, Product 02, data &
quality. Charts are inline SVG (`charts.py`), so the file opens offline and can be attached to
the report.

What it reads, and what it never reads:

- Product 01: the TUNING detection run (`detections/det-*/evaluation.json`), its KPI Parquet and
  simulation. Never a report-simulation run (`*/report/`, evaluated once).
- Product 02: validation metrics of local runs (`runs/*/metrics.json`, top level only), the
  Stage G result bundles, the latest batch-scoring run.
- Test numbers and report-simulation numbers: only quoted from `results/published.json`.
  Nothing under `artifacts/runs/*/test/` is opened (test-once rule).

Sections whose inputs are missing say which command creates them instead of failing.
"""

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import yaml

from dashboard.charts import bar_chart, line_chart

REPO_ROOT = Path(__file__).resolve().parents[3]
LOCAL = ZoneInfo("Asia/Ho_Chi_Minh")
MIN_ATTEMPTS = 20  # hours with fewer attempts are hidden: their rates are mostly noise
MODEL_VN = {"rule_based": "Luật", "logistic": "Logistic Regression", "gbm": "Gradient Boosting"}
METRIC_VN = {
    "technical_failure_rate": "tỷ lệ lỗi kỹ thuật",
    "latency_p50": "độ trễ",
    "method_share": "tỷ trọng phương thức",
}
DETECTOR_VN = {"pooled": "D-B gộp cửa sổ (chính)", "robust_z": "D-A z-score (cơ sở)"}
POLICY_VN = {
    "none": "Không cảnh báo",
    "max_f1": "Ngưỡng max F1 (mốc)",
    "cost_v2": "Ngưỡng chi phí chọn trên V2",
    "rule_raw": "Luật chi phí, điểm gốc",
    "rule_calibrated": "Luật chi phí, đã hiệu chỉnh",
    "top_0.5%": "Top 0,5% mỗi ngày",
    "top_1%": "Top 1% mỗi ngày",
    "top_2%": "Top 2% mỗi ngày",
    "top_5%": "Top 5% mỗi ngày",
}
MID_COST = "L0.75/R5/F1"  # middle of the G04 grid, the one the Stage G report discusses


# --- formatting -------------------------------------------------------------------------------


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


def mtime(path: Path) -> str:
    return (
        datetime.fromtimestamp(path.stat().st_mtime, UTC)
        .astimezone(LOCAL)
        .strftime("%d/%m/%Y %H:%M")
    )


# --- building blocks --------------------------------------------------------------------------

FULL, WIDE, HALF = 960, 680, 500  # chart viewBox widths: full row, 2/3 column, 1/2 column

ICONS = {
    "grid": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" '
    'height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/><rect x="3" '
    'y="14" width="7" height="7" rx="1.5"/>',
    "flow": '<circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="6" '
    'r="3"/><path d="M18 9a9 9 0 0 1-9 9"/><path d="M6 9v6"/>',
    "activity": '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "check": '<path d="M22 11.1V12a10 10 0 1 1-5.9-9.1"/><path d="M22 4 12 14 9 11"/>',
    "alert": '<path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 '
    '0z"/><path d="M12 9v4M12 17h.01"/>',
    "chart": '<path d="M18 20V10M12 20V4M6 20v-6"/>',
    "layers": '<path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/>',
    "moon": '<path d="M21 12.8A9 9 0 1 1 11.2 3 7 7 0 0 0 21 12.8z"/>',
}


def icon(name: str) -> str:
    return f'<svg class="ico" viewBox="0 0 24 24" aria-hidden="true">{ICONS[name]}</svg>'


def table(head: list[str], rows: list[list[str]], numeric_from: int = 1) -> str:
    """HTML table; cells are already-escaped HTML."""
    th = "".join(f"<th>{escape(h)}</th>" for h in head)
    body = "".join(
        "<tr>"
        + "".join(
            f'<td class="{"num" if i >= numeric_from else ""}">{c}</td>' for i, c in enumerate(r)
        )
        + "</tr>"
        for r in rows
    )
    return (
        f'<div class="table-wrap"><table><thead><tr>{th}</tr></thead>'
        f"<tbody>{body}</tbody></table></div>"
    )


def tile(label: str, value: str, sub: str = "", *, ico: str = "chart", hue: str = "s1") -> str:
    """KPI tile: colored icon chip, label, big value, one line of context."""
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    return (
        f'<div class="tile"><div class="tile-head"><span class="chip chip-{hue}">{icon(ico)}'
        f'</span><span class="label">{escape(label)}</span></div>'
        f'<div class="value">{value}</div>{sub_html}</div>'
    )


def status(ok: bool | None, text: str) -> str:
    """Status pill with icon + word (never color alone)."""
    if ok is None:
        return f'<span class="pill info">ⓘ {text}</span>'
    return (f'<span class="pill good">✓ {text}</span>' if ok
            else f'<span class="pill bad">✗ {text}</span>')  # fmt: skip


def empty(text: str) -> str:
    return f'<p class="empty">{text}</p>'


def card(title: str, body: str, note: str = "", meta: str = "") -> str:
    """White card; `meta` is a small label at the top right (run id, scope)."""
    note_html = f'<p class="note">{note}</p>' if note else ""
    meta_html = f'<span class="meta">{meta}</span>' if meta else ""
    return (
        f'<section class="card"><div class="card-head"><h3>{escape(title)}</h3>{meta_html}</div>'
        f"{body}{note_html}</section>"
    )


def stats(rows: list[tuple[str, str, str]]) -> str:
    """Label / value / detail rows for the narrow side cards."""
    items = "".join(
        f'<div class="stat"><span class="stat-label">{label}</span><b>{value}</b>'
        + (f"<small>{sub}</small>" if sub else "")
        + "</div>"
        for label, value, sub in rows
    )
    return f'<div class="stats">{items}</div>'


def grid(kind: str, *cells: str) -> str:
    """`g21`: two-thirds + one-third; `g11`: two halves. Stacks on narrow screens."""
    return f'<div class="grid {kind}">' + "".join(cells) + "</div>"


def section(sid: str, title: str, sub: str, body: str) -> str:
    return (
        f'<section class="section" id="{sid}"><div class="section-head"><h2>{escape(title)}</h2>'
        f"<p>{sub}</p></div>{body}</section>"
    )


def meter(p: float) -> str:
    """Small inline bar for a probability in a table cell."""
    return f'<span class="meter" aria-hidden="true"><i style="width:{p * 100:.0f}%"></i></span>'


# --- loading ----------------------------------------------------------------------------------


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text("utf-8"))
    except (OSError, ValueError):
        return None


def find_detection_run(artifacts: Path) -> Path | None:
    """Latest TUNING detection run. Report runs (`*/report/`, one-time) are never read."""
    runs = []
    for path in (artifacts / "detections").glob("det-*/evaluation.json"):
        ev = read_json(path)
        if ev and ev.get("stage") == "tuning":
            runs.append(path)
    return max(runs, key=lambda p: p.stat().st_mtime).parent if runs else None


def latest_execution(folder: Path) -> dict[str, Any] | None:
    records = sorted((folder / "executions").glob("exec-*.json"), key=lambda p: p.stat().st_mtime)
    return read_json(records[-1]) if records else None


def result_bundle(artifacts: Path, repo: Path, prefix: str) -> tuple[dict | None, Path | None]:
    """Stage G results: the local run if any, else the committed bundle in `results/`."""
    for root in (artifacts / "experiments", repo / "results"):
        found = sorted(root.glob(f"{prefix}-*/results.json"), key=lambda p: p.stat().st_mtime)
        if found:
            return read_json(found[-1]), found[-1].parent
    return None, None


def validation_runs(artifacts: Path) -> list[tuple[str, dict[str, Any], Path]]:
    """(run id, models' validation metrics, folder) from `runs/*/metrics.json` ONLY.

    The glob is one level deep on purpose: `runs/<id>/test/metrics.json` holds test numbers,
    which the dashboard quotes from results/published.json instead of reading them.
    """
    out = []
    for path in sorted((artifacts / "runs").glob("*/metrics.json")):
        m = read_json(path)
        if not m:
            continue
        valid = {k: v["valid"] for k, v in m.get("models", {}).items() if "valid" in v}
        if valid:
            out.append((m.get("run_id", path.parent.name), valid, path.parent))
    return out


def provider_summary(prov: pd.DataFrame) -> pd.DataFrame:
    """Whole-period KPIs per provider from the 15-minute KPI table (ALL last)."""
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


def fold_echoes(incidents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Display only: an ALL incident overlapping a provider incident is listed on that incident
    as an echo (stage-d-report.md 3.3). incidents.json is unchanged."""
    providers = [i for i in incidents if i["target"] != "ALL"]
    out = [dict(i, echoes=[]) for i in providers]
    for inc in incidents:
        if inc["target"] != "ALL":
            continue
        host = next((o for o in out if o["start"] < inc["end"] and inc["start"] < o["end"]), None)
        if host is None:
            out.append(dict(inc, echoes=[]))
        else:
            host["echoes"].append(inc["incident_id"])
    return sorted(out, key=lambda i: i["start"])


@dataclass
class P01:
    run: Path
    evaluation: dict[str, Any]
    incidents: list[dict[str, Any]]
    labels: list[dict[str, Any]]
    kpi: pd.DataFrame | None
    sim_manifest: dict[str, Any] | None
    kpi_manifest: dict[str, Any] | None
    alerts: dict[str, int]


def load_p01(artifacts: Path) -> P01 | None:
    run = find_detection_run(artifacts)
    if run is None:
        return None
    ev = read_json(run / "evaluation.json")
    sid = ev["simulation_id"]
    sim_dir, kpi_dir = artifacts / "simulations" / sid, artifacts / "kpi" / sid
    kpi_file = kpi_dir / "provider_15m.parquet"
    alerts: dict[str, int] = {}
    if (run / "scores.parquet").exists():
        s = pd.read_parquet(run / "scores.parquet", columns=["detector", "alert"])
        alerts = {k: int(v) for k, v in s.groupby("detector")["alert"].sum().items()}
    sim_manifest = None
    if (sim_dir / "simulation_manifest.yaml").exists():
        sim_manifest = yaml.safe_load((sim_dir / "simulation_manifest.yaml").read_text("utf-8"))
    return P01(
        run=run,
        evaluation=ev,
        incidents=read_json(run / "incidents.json") or [],
        labels=read_json(sim_dir / "anomaly_labels.json") or [],
        kpi=pd.read_parquet(kpi_file) if kpi_file.exists() else None,
        sim_manifest=sim_manifest,
        kpi_manifest=read_json(kpi_dir / "kpi_manifest.json"),
        alerts=alerts,
    )


@dataclass
class P02:
    runs: list[tuple[str, dict[str, Any], Path]]
    model_dir: Path | None
    card: dict[str, Any] | None
    scores: dict[str, Any] | None
    scores_csv: pd.DataFrame | None
    scores_path: Path | None
    cal: tuple[dict | None, Path | None]
    pol: tuple[dict | None, Path | None]
    stab: tuple[dict | None, Path | None]


def load_p02(artifacts: Path, repo: Path) -> P02:
    model_dir = None
    pointer = artifacts / "models" / "LATEST"
    if pointer.exists():
        model_dir = artifacts / "models" / pointer.read_text("utf-8").strip()
    found = sorted((artifacts / "scores").glob("exec-*.json"), key=lambda p: p.stat().st_mtime)
    scores = read_json(found[-1]) if found else None
    csv_path = found[-1].with_suffix(".csv") if found else None
    scores_csv = pd.read_csv(csv_path) if csv_path and csv_path.exists() else None
    return P02(
        runs=validation_runs(artifacts),
        model_dir=model_dir if model_dir and model_dir.exists() else None,
        card=read_json(model_dir / "model_card.json") if model_dir else None,
        scores=scores,
        scores_csv=scores_csv,
        scores_path=found[-1] if found else None,
        cal=result_bundle(artifacts, repo, "cal"),
        pol=result_bundle(artifacts, repo, "pol"),
        stab=result_bundle(artifacts, repo, "stab"),
    )


@dataclass
class Context:
    artifacts: Path
    repo: Path
    published: dict[str, Any]
    p01: P01 | None
    p02: P02


def load(artifacts: Path, repo: Path = REPO_ROOT) -> Context:
    return Context(
        artifacts=artifacts,
        repo=repo,
        published=read_json(repo / "results" / "published.json") or {},
        p01=load_p01(artifacts),
        p02=load_p02(artifacts, repo),
    )


def p01_matches_published(ctx: Context) -> bool | None:
    """Does the local tuning run reproduce the published tuning numbers? None if no run."""
    pub = ctx.published.get("product_01", {}).get("tuning")
    if ctx.p01 is None or not pub:
        return None
    if ctx.p01.evaluation["simulation_id"] != pub["simulation_id"]:
        return False
    det = ctx.p01.evaluation["detectors"]
    return all(
        det[d]["detected"] == pub[d]["detected"]
        and abs(det[d]["false_per_day"] - pub[d]["false_per_day"]) < 1e-9
        for d in ("pooled", "robust_z")
    )


# --- overview: KPI tiles and the two pipelines ------------------------------------------------


def node(state: str, title: str, lines: list[str], where: str = "") -> dict[str, Any]:
    return {"state": state, "title": title, "lines": lines, "where": where}


ICON = {"ok": "✓", "missing": "○", "locked": "🔒", "info": "ⓘ"}
STATE_VN = {"ok": "đã chạy", "missing": "chưa có", "locked": "khoá (một lần)", "info": "thông tin"}


def flow(nodes: list[dict[str, Any]], label: str) -> str:
    """Horizontal stepper; the folder each step writes to is in the step's tooltip."""
    items = []
    for n in nodes:
        tip = f"<b>{escape(n['title'])}</b>: {STATE_VN[n['state']]}"
        if n["where"]:
            tip += f"<br>kết quả ở <code>{escape(n['where'])}</code>"
        items.append(
            f'<li class="step {n["state"]}" data-tip="{escape(tip)}">'
            f'<span class="step-dot" aria-hidden="true">{ICON[n["state"]]}</span>'
            f'<div class="step-body"><b>{escape(n["title"])}</b>'
            + "".join(f"<small>{line}</small>" for line in n["lines"])
            + f'<span class="sr">{STATE_VN[n["state"]]}</span></div></li>'
        )
    return f'<ol class="steps" aria-label="{escape(label)}">{"".join(items)}</ol>'


def lane(name: str, desc: str, steps: str, hint: str) -> str:
    return (
        f'<div class="lane"><div class="lane-head"><b>{name}</b><span>{desc}</span></div>'
        f'{steps}<p class="note">{hint}</p></div>'
    )


def pipeline_01(ctx: Context) -> str:
    p = ctx.p01
    sim = p.sim_manifest if p else None
    kpi = p.kpi_manifest if p else None
    matches = p01_matches_published(ctx)
    nodes = [
        node("ok", "Cấu hình", ["<b>demo.yaml</b> (frozen)", "7 ngày · 3 provider · 4 sự cố"],
             "shared/synthetic-generator/configs/"),
        node("ok" if sim else "missing", "Sinh dữ liệu giả lập",
             [f"<b>{vn(sim['events'], 0)}</b> sự kiện", f"{vn(sim['payments'], 0)} payment"]
             if sim else ["chạy <code>make simulate</code>"],
             f"artifacts/simulations/{sim['simulation_id']}/" if sim else ""),
        node("ok" if kpi else "missing", "PostgreSQL",
             ["kiểm tra contract", "bảng <b>payment_events</b>"]
             if kpi else ["<code>make up</code>, <code>make ingest</code>"]),
        node("ok" if kpi else "missing", "KPI 15 phút",
             [f"<b>{vn(kpi['rows']['provider_15m'], 0)}</b> dòng", "SQL view"]
             if kpi else ["chạy <code>make kpi</code>"],
             f"artifacts/kpi/{kpi['simulation_id']}/" if kpi else ""),
        node("ok" if p else "missing", "Detector D-A, D-B",
             [f"D-B <b>{p.alerts.get('pooled', 0)}</b> khung cảnh báo",
              f"D-A {p.alerts.get('robust_z', 0)} khung"]
             if p else ["chạy <code>make detect</code>"],
             f"artifacts/detections/{p.run.name}/" if p else ""),
        node("ok" if matches else ("missing" if matches is None else "info"), "Đánh giá sự cố",
             [f"D-B bắt <b>{p.evaluation['detectors']['pooled']['detected']}/"
              f"{len(p.evaluation['detectors']['pooled']['anomalies'])}</b>",
              "khớp số công bố" if matches else "chưa khớp số công bố"]
             if p else ["chưa có lần chạy"]),
        node("ok", "Dashboard", ["trang này"], "artifacts/dashboard/index.html"),
    ]  # fmt: skip
    return flow(nodes, "Pipeline Product 01")


def pipeline_02(ctx: Context) -> str:
    p = ctx.p02
    card_ = p.card or {}
    feats = card_.get("features", {})
    raw = (ctx.repo / "datasets" / "raw" / "ieee-cis" / "train_transaction.csv").exists()
    pub = {m["model"]: m for m in ctx.published.get("product_02", {}).get("models", [])}
    gbm = pub.get("gbm", {})
    skew = (p.scores or {}).get("skew_check", {})
    nodes = [
        node("ok" if raw else "info", "Dataset IEEE-CIS",
             ["590.540 giao dịch", "3,5% gian lận" if raw else "<b>không có trên máy này</b>"],
             "datasets/manifests/ieee-cis.yaml"),
        node("ok", "Chia theo thời gian", ["train 60 · valid 20 · test 20", "valid → V1/V2/V3"]),
        node("ok" if p.card else "missing", "Gradient Boosting",
             [f"<b>{vn(card_.get('train_rows'), 0)}</b> dòng train",
              f"{len(feats.get('numeric', [])) + len(feats.get('categorical', []))} đặc trưng"]
             if p.card else ["chạy <code>make score-model</code>"],
             f"artifacts/models/{p.model_dir.name}/" if p.model_dir else ""),
        node("ok" if p.card else "missing", "Hiệu chỉnh",
             [f"<b>{escape(card_['calibration']['method'])}</b>", "fit trên V1"]
             if p.card else ["<code>make score-model</code>"]),
        node("ok" if p.scores else "missing", "Chấm điểm theo lô",
             [f"<b>{vn(p.scores['rows'], 0)}</b> giao dịch",
              "lệch huấn luyện 0" if skew.get("max_abs_diff") == 0.0 else "có lệch"]
             if p.scores else ["chạy <code>make score</code>"],
             f"artifacts/scores/{p.scores_path.name}" if p.scores_path else ""),
        node("locked", "Tập test", [f"PR-AUC <b>{vn(gbm.get('test_pr_auc'))}</b>", "trích lại"],
             gbm.get("run_id", "")),
    ]  # fmt: skip
    return flow(nodes, "Pipeline Product 02")


def overview_tiles(ctx: Context) -> str:
    pub01 = ctx.published.get("product_01", {})
    pub02 = {m["model"]: m for m in ctx.published.get("product_02", {}).get("models", [])}
    gbm = pub02.get("gbm", {})
    ci = gbm.get("test_pr_auc_ci")
    rep = pub01.get("report", {}).get("pooled", {})
    p = ctx.p01
    tun = p.evaluation["detectors"]["pooled"] if p else None
    all_row = None
    if p is not None and p.kpi is not None:
        summary = provider_summary(p.kpi)
        all_row = summary.loc["ALL"] if "ALL" in summary.index else summary.iloc[0]
    skew = (ctx.p02.scores or {}).get("skew_check", {})
    return '<div class="tiles">' + "".join([
        tile("Attempt thanh toán (7 ngày)",
             vn(float(all_row["attempts"]), 0) if all_row is not None else "—",
             f"thành công {pct(all_row['success_rate'])}" if all_row is not None
             else "chưa chạy <code>make demo</code>", ico="activity", hue="s1"),
        tile("Tỷ lệ lỗi kỹ thuật",
             pct(all_row["technical_failure_rate"]) if all_row is not None else "—",
             "Product 01, toàn kỳ" if all_row is not None else "chưa có KPI",
             ico="alert", hue="s2"),
        tile("Sự cố D-B bắt được",
             f"{tun['detected']}/{len(tun['anomalies'])}" if tun else "—",
             (f"bộ tuning · bộ report {rep.get('detected', '—')}/{rep.get('total', 4)}"
              if tun else "chưa chạy detector"), ico="check", hue="s3"),
        tile("PR-AUC test · Gradient Boosting", vn(gbm.get("test_pr_auc")),
             (f"[{vn(ci[0])}; {vn(ci[1])}] · trích lại" if ci else "trích lại"),
             ico="chart", hue="s1"),
        tile("Giao dịch đã chấm điểm",
             vn(ctx.p02.scores["rows"], 0) if ctx.p02.scores else "—",
             (f"lệch huấn luyện–chấm điểm {vn(skew.get('max_abs_diff'), 1)}"
              if ctx.p02.scores else "chưa chạy <code>make score</code>"),
             ico="shield", hue="s2"),
    ]) + "</div>"  # fmt: skip


def pipeline_card(ctx: Context) -> str:
    return card(
        "Luồng pipeline",
        lane("Product 01 · Độ ổn định thanh toán", "dữ liệu giả lập", pipeline_01(ctx),
             "Chạy lại: <code>make up</code> rồi <code>make demo</code>. Bộ report (đánh giá "
             "một lần) không chạy lại.")
        + lane("Product 02 · Rủi ro gian lận", "IEEE-CIS", pipeline_02(ctx),
               "Chạy lại: <code>make score-model</code>, <code>make score</code> (cần dataset). "
               "Mọi bước trừ 🔒 chỉ dùng train và validation."),
        meta="✓ đã chạy · ○ chưa có · 🔒 một lần",
    )  # fmt: skip


# --- Product 01 -------------------------------------------------------------------------------


def hourly(prov: pd.DataFrame) -> tuple[pd.DatetimeIndex, dict[str, pd.DataFrame]]:
    """Common hourly UTC index and per-provider hourly sums / medians."""
    start = prov["bucket_start"].min().floor("h")
    end = prov["bucket_start"].max().floor("h")
    index = pd.date_range(start, end, freq="1h")
    out = {}
    for provider, g in prov.groupby("provider_id"):
        g = g.set_index("bucket_start")
        sums = g[["attempts", "technical_failures", "latency_attempts"]].astype(float)
        frame = sums.resample("1h").sum().reindex(index, fill_value=0.0)
        frame["latency"] = g["latency_p50_ms"].astype(float).resample("1h").median().reindex(index)
        out[str(provider)] = frame
    return index, out


def _hour_index(index: pd.DatetimeIndex, when: str) -> int:
    t = pd.Timestamp(when).floor("h")
    return int(max(0, min(len(index) - 1, index.searchsorted(t))))


def _bands(
    index: pd.DatetimeIndex, p: P01, metric: str, truth_types: set[str], target: str | None = None
) -> list:
    """Shaded hours: planted anomalies (dashed) and D-B incidents (red); optionally one target."""
    bands = []
    for lab in p.labels:
        if lab["type"] in truth_types and (target is None or lab["provider_id"] in (None, target)):
            i0 = _hour_index(index, lab["start"])
            i1 = _hour_index(index, (pd.Timestamp(lab["end"]) - pd.Timedelta("1min")).isoformat())
            what = lab["provider_id"] or lab["error_code"] or "ALL"
            tip = (f"<b>Sự cố cài sẵn {escape(lab['anomaly_id'])}</b><br>{escape(lab['type'])} "
                   f"x{vn(lab['magnitude'], 1)} · {escape(what)}<br>{local(lab['start'])}–"
                   f"{local(lab['end'])} (đáp án, người vận hành không thấy)")  # fmt: skip
            bands.append((i0, i1, "band-truth", tip))
    for inc in p.incidents:
        if (
            inc["detector"] == "pooled"
            and metric in inc["metrics"]
            and (target is None or inc["target"] == target)
        ):
            i0 = _hour_index(index, inc["start"])
            i1 = _hour_index(index, inc["end"])
            tip = (f"<b>D-B báo {escape(inc['incident_id'])}</b><br>{escape(inc['target'])}: "
                   f"{escape(METRIC_VN.get(metric, metric))}<br>cảnh báo lúc "
                   f"{local(inc['first_alert_at'])}, điểm cao nhất "
                   f"{vn(inc['max_score'], 1)}")  # fmt: skip
            bands.append((i0, i1, "band-alert", tip))
    return bands


def p01_charts(p: P01) -> tuple[str, str, str]:
    """(failure-rate small multiples, latency, traffic) cards."""
    assert p.kpi is not None
    index, per = hourly(p.kpi)
    labels = [t.tz_convert(LOCAL).strftime("%d/%m %H:00") for t in index]
    ticks = [(i, t.tz_convert(LOCAL).strftime("%d/%m")) for i, t in enumerate(index)
             if t.tz_convert(LOCAL).hour == 0]  # fmt: skip
    providers = sorted(k for k in per if k != "ALL")
    fail = [
        (prov, slot, [
            (r.technical_failures / r.attempts) if r.attempts >= MIN_ATTEMPTS else None
            for r in per[prov].itertuples()
        ])
        for slot, prov in enumerate(providers, start=1)
    ]  # fmt: skip
    lat = [
        (prov, slot, [
            r.latency if r.latency_attempts >= MIN_ATTEMPTS and pd.notna(r.latency) else None
            for r in per[prov].itertuples()
        ])
        for slot, prov in enumerate(providers, start=1)
    ]  # fmt: skip
    top_fail = max((v for _, _, vs in fail for v in vs if v is not None), default=0.0)
    traffic = [("Tất cả provider", 1, [float(v) for v in per["ALL"]["attempts"]])] \
        if "ALL" in per else []  # fmt: skip
    legend = (
        '<div class="legend"><span class="key"><i class="key-alert"></i>D-B báo sự cố</span>'
        '<span class="key"><i class="key-truth"></i>sự cố cài sẵn (đáp án)</span></div>'
    )
    failure = card(
        "Tỷ lệ lỗi kỹ thuật theo giờ",
        legend + "".join(
            line_chart(labels, [(name, slot, vals)], y_fmt=lambda v: pct(v, 0),
                       title=f"Tỷ lệ lỗi kỹ thuật {name}", x_ticks=ticks, height=150,
                       y_max=top_fail, width=WIDE,
                       bands=_bands(index, p, "technical_failure_rate",
                                    {"provider_outage", "error_burst"}, target=name))
            for name, slot, vals in fail
        ),
        f"Mỗi provider một hàng, cùng thang. Giờ Việt Nam; ẩn giờ có dưới {MIN_ATTEMPTS} attempt. "
        "Rê chuột để xem số và sự cố.",
        meta="theo provider",
    )  # fmt: skip
    latency = card(
        "Độ trễ trung vị theo giờ (ms)",
        line_chart(labels, lat, y_fmt=lambda v: vn(v, 0), title="Độ trễ trung vị", x_ticks=ticks,
                   width=HALF, height=220,
                   bands=_bands(index, p, "latency_p50", {"latency_degradation"})),
        "Không tính TIMEOUT.",
    )  # fmt: skip
    volume = card(
        "Lưu lượng: attempt mỗi giờ",
        line_chart(labels, traffic, y_fmt=lambda v: vn(v, 0), title="Lưu lượng", x_ticks=ticks,
                   width=HALF, height=220),
        "Thấp ban đêm, đỉnh trưa và tối (giả định của bộ sinh dữ liệu).",
    )  # fmt: skip
    return failure, latency, volume


def report_stats(ctx: Context) -> str:
    """Report-simulation numbers, quoted from results/published.json (evaluated once)."""
    rep = ctx.published.get("product_01", {}).get("report", {})
    rows = [(escape(DETECTOR_VN[d]), f"{rep[d]['detected']}/{rep[d]['total']}",
             f"{vn(rep[d]['false_per_day'], 1)} báo nhầm/ngày")
            for d in ("pooled", "robust_z") if d in rep]  # fmt: skip
    return (
        f"<h4>Bộ report · đánh giá một lần (trích lại)</h4>{stats(rows)}"
        f'<p class="note"><code>{escape(rep.get("run_id", ""))}</code> trên '
        f"<code>{escape(rep.get('simulation_id', ''))}</code>: seed khác, có một loại sự cố chưa "
        "gặp khi chỉnh ngưỡng. Không chạy lại.</p>"
    )


def detector_card(ctx: Context) -> str:
    p = ctx.p01
    assert p is not None
    ev = p.evaluation
    per = {d: {a["anomaly_id"]: a for a in r["anomalies"]} for d, r in ev["detectors"].items()}

    def cell(a: dict[str, Any] | None) -> str:
        if a and a["detected"]:
            return status(True, f"{a['delay_minutes']:.0f} phút")
        return status(False, "trượt")

    rows = [
        [f"<b>{escape(lab['anomaly_id'])}</b><small class='cell-sub'>{escape(lab['type'])} "
         f"x{vn(lab['magnitude'], 1)} · "
         f"{escape(lab['provider_id'] or lab['payment_method'] or lab['error_code'] or 'ALL')}"
         "</small>",
         cell(per.get("pooled", {}).get(lab["anomaly_id"])),
         cell(per.get("robust_z", {}).get(lab["anomaly_id"]))]
        for lab in p.labels
    ]  # fmt: skip
    rep = ctx.published.get("product_01", {}).get("report", {})

    def score(r: dict[str, Any] | None, total: int | None = None) -> str:
        if not r:
            return "—"
        n = total if total is not None else r.get("total", len(r.get("anomalies", [])))
        fp = vn(r["false_per_day"], 1)
        return f"<b>{r['detected']}/{n}</b><small class='cell-sub'>{fp} nhầm/ngày</small>"

    short = {"pooled": "D-B (chính)", "robust_z": "D-A (cơ sở)"}
    summary = [[short[d], score(r, len(r["anomalies"])), score(rep.get(d))]
               for d, r in ev["detectors"].items() if d in DETECTOR_VN]  # fmt: skip
    return card(
        "Detector so với đáp án",
        table(["Sự cố cài sẵn", "D-B", "D-A"], rows)
        + "<h4>Tổng hợp</h4>"
        + table(["Detector", "Tuning", "Report*"], summary)
        + f'<p class="note">* Trích lại: <code>{escape(rep.get("run_id", ""))}</code>, seed khác, '
        "đánh giá một lần, không chạy lại.</p>",
        "Đáp án chỉ dùng để đánh giá. Sự cố x1,5 nằm dưới giới hạn phát hiện.",
        meta="bộ tuning",
    )


def section_p01(ctx: Context) -> str:
    p = ctx.p01
    title = "Product 01 · Độ ổn định thanh toán"
    if p is None:
        body = grid("g11",
                    card("Chưa có dữ liệu",
                         empty("Chưa có lần chạy detector trên bộ tuning. Chạy <code>make up"
                               "</code> rồi <code>make demo</code>.")),
                    card("Số đã công bố", report_stats(ctx)))  # fmt: skip
        return section("p01", title, "Dữ liệu giả lập theo contract payment-event.", body)
    ev = p.evaluation
    sub = (f"Mô phỏng <code>{escape(ev['simulation_id'])}</code> (bộ tuning) · detector "
           f"<code>{escape(ev['run_id'])}</code> · dữ liệu giả lập, 4 sự cố cài sẵn")  # fmt: skip
    if p.kpi is None:
        msg = f"Thiếu KPI: chạy <code>make kpi SIM={escape(ev['simulation_id'])}</code>."
        return section("p01", title, sub, card("Thiếu KPI", empty(msg)))
    failure, latency, volume = p01_charts(p)
    folded = fold_echoes([i for i in p.incidents if i["detector"] == "pooled"])
    inc_rows = [
        [f"<b>{escape(i['incident_id'])}</b>", escape(i["target"]),
         escape(", ".join(METRIC_VN.get(m, m) for m in i["metrics"])), local(i["start"]),
         f"{i['buckets'] * 15} phút", local(i["first_alert_at"]), vn(i["max_score"], 1),
         escape(", ".join(i["echoes"])) or "—"]
        for i in folded
    ]  # fmt: skip
    summary = provider_summary(p.kpi)
    prov_rows = [
        [f"<b>{escape(str(name))}</b>", vn(float(r["attempts"]), 0), pct(r["success_rate"]),
         pct(r["first_attempt_success_rate"]), pct(r["technical_failure_rate"]),
         pct(r["business_failure_rate"]), pct(r["retry_share"]), vn(r["median_bucket_p50_ms"], 0)]
        for name, r in summary.iterrows()
    ]  # fmt: skip
    incidents = card(
        "Sự cố D-B báo",
        table(["Sự cố", "Đối tượng", "Chỉ số", "Bắt đầu", "Kéo dài", "Cảnh báo lúc",
               "Điểm cao nhất", "Gộp ALL"], inc_rows, numeric_from=4)
        if inc_rows else empty("Detector không báo sự cố nào."),
        "Cảnh báo ALL trùng thời gian với một provider được gộp vào sự cố của provider đó.",
        meta=f"{len(folded)} sự cố",
    )  # fmt: skip
    providers = card(
        "Theo provider (cả kỳ)",
        table(["Provider", "Attempt", "Thành công", "Thành công lần đầu", "Lỗi kỹ thuật",
               "Lỗi nghiệp vụ", "Tỷ lệ retry", "Độ trễ trung vị (ms)"], prov_rows),
    )  # fmt: skip
    body = (
        grid("g21", failure, detector_card(ctx))
        + grid("g11", latency, volume)
        + grid("g11", incidents, providers)
    )
    return section("p01", title, sub, body)


# --- Product 02 -------------------------------------------------------------------------------


def published_card(ctx: Context) -> str:
    models = ctx.published.get("product_02", {}).get("models", [])
    if not models:
        return card("Chất lượng xếp hạng", empty("Thiếu results/published.json."))
    bars = []
    for m in models:
        name = MODEL_VN.get(m["model"], m["model"])
        ci = m.get("test_pr_auc_ci")
        ci_text = f" [{vn(ci[0])}; {vn(ci[1])}]" if ci else ""
        bars.append(
            (
                f"{name} · valid",
                m["valid_pr_auc"],
                "fill-s2",
                f"<b>{escape(name)}</b><br>PR-AUC validation {vn(m['valid_pr_auc'])}",
            )
        )
        bars.append((f"{name} · test", m["test_pr_auc"], "fill-s1",
                     f"<b>{escape(name)}</b><br>PR-AUC test {vn(m['test_pr_auc'])}{ci_text}"
                     f"<br>{escape(m['run_id'])}"))  # fmt: skip
    rows = [
        [escape(MODEL_VN.get(m["model"], m["model"])), vn(m["valid_pr_auc"]),
         vn(m["test_pr_auc"]) + (f" [{vn(m['test_pr_auc_ci'][0])}; {vn(m['test_pr_auc_ci'][1])}]"
                                 if m.get("test_pr_auc_ci") else ""),
         vn(m["test_recall_at_fpr5"], 2), f"<code>{escape(m['run_id'])}</code>"]
        for m in models
    ]  # fmt: skip
    legend = ('<div class="legend"><span class="key"><i style="background:var(--s2)"></i>'
              'validation</span><span class="key"><i style="background:var(--s1)"></i>test (một '
              "lần)</span></div>")  # fmt: skip
    return card(
        "Chất lượng xếp hạng: PR-AUC",
        legend + bar_chart(bars, x_fmt=lambda v: vn(v, 2), title="PR-AUC theo mô hình",
                           width=WIDE, label_w=210)
        + table(["Mô hình", "Validation", "Test [95% CI]", "Recall @ FPR 5%", "Lần chạy"], rows),
        "Recall tại FPR 5% chọn ngưỡng bằng nhãn của chính tập test: chỉ đo thứ tự điểm, không "
        "phải hiệu quả của một ngưỡng triển khai.",
        meta="trích lại số công bố",
    )  # fmt: skip


def threshold_card(ctx: Context) -> str:
    p02 = ctx.published.get("product_02", {})
    th = p02.get("threshold", {})
    leak = p02.get("leakage", {})
    body = stats([
        ("Ngưỡng (chốt trước khi mở test)", vn(th.get("threshold")),
         escape(MODEL_VN.get(th.get("model", ""), ""))),
        ("Precision", vn(th.get("precision")), "trên tập test"),
        ("Recall", vn(th.get("recall")), "trên tập test"),
        ("FPR", pct(th.get("fpr"), 2), "cảnh báo nhầm / giao dịch thật"),
    ]) + "<h4>Thí nghiệm rò rỉ (validation)</h4>" + stats([
        ("Mã hoá card1 bằng nhãn", "+" + vn(leak.get("target_encoding_card1")), "PR-AUC tăng giả"),
        ("Chia ngẫu nhiên", "−" + vn(abs(leak.get("random_split", 0))), "so với chia thời gian"),
    ])  # fmt: skip
    return card(
        "Ngưỡng đã chốt",
        body,
        "Điểm vận hành FPR 1,24%, khác bảng bên trái (FPR 5%): không đọc là recall “tụt từ 51% "
        f"xuống 37%”. Rò rỉ: <code>{escape(leak.get('run_id', ''))}</code>.",
        meta="trích lại",
    )


BUCKETS = [(0.0, 0.01, "< 1%"), (0.01, 0.02, "1–2%"), (0.02, 0.05, "2–5%"), (0.05, 0.1, "5–10%"),
           (0.1, 0.2, "10–20%"), (0.2, 0.5, "20–50%"), (0.5, 1.01, "≥ 50%")]  # fmt: skip


def scoring_cards(ctx: Context) -> tuple[str, str]:
    """(distribution card, top-10 card) of the latest batch-scoring run."""
    p = ctx.p02
    if not p.scores or p.scores_csv is None:
        msg = empty("Chưa chấm: chạy <code>make score-model</code> rồi <code>make score</code>.")
        return card("Chấm điểm theo lô gần nhất", msg), card("Giao dịch rủi ro nhất", msg)
    probs = p.scores_csv["score_calibrated"]
    counts = [int(((probs >= lo) & (probs < hi)).sum()) for lo, hi, _ in BUCKETS]
    bars = [(name, c, "fill-s1", f"xác suất {name}: <b>{c}</b> giao dịch")
            for (_, _, name), c in zip(BUCKETS, counts, strict=True)]  # fmt: skip
    skew = p.scores.get("skew_check", {})
    mini = stats([
        ("Đã chấm", vn(p.scores["rows"], 0), "giao dịch không nhãn"),
        ("Xác suất trung bình", pct(p.scores.get("score_calibrated_mean"), 1), "đã hiệu chỉnh"),
        ("Lệch huấn luyện–chấm", vn(skew.get("max_abs_diff"), 1),
         status(skew.get("max_abs_diff") == 0.0, f"{skew.get('rows_compared', 0)} dòng")),
    ])  # fmt: skip
    dist = card(
        "Chấm điểm theo lô gần nhất",
        f'<div class="stats-row">{mini}</div><h4>Phân bố xác suất gian lận</h4>'
        + bar_chart(bars, x_fmt=lambda v: vn(v, 0), title="Phân bố xác suất", width=HALF,
                    label_w=90),
        f"Mô hình <code>{escape(p.scores['model_version'])}</code>, đặc trưng "
        f"<code>{escape(p.scores['feature_version'])}</code>.",
        meta=escape(p.scores["execution_id"]),
    )  # fmt: skip
    top = p.scores_csv.sort_values("score_calibrated", ascending=False).head(10)
    rows = [[f"<b>{r.TransactionID}</b>", vn(r.score),
             f"{meter(float(r.score_calibrated))} {pct(r.score_calibrated, 1)}"]
            for r in top.itertuples()]  # fmt: skip
    top_card = card(
        "10 giao dịch rủi ro nhất",
        table(["TransactionID", "Điểm gốc", "Xác suất (đã hiệu chỉnh)"], rows),
        "Giao dịch validation không nhãn; chỉ minh hoạ, không phải quyết định chặn.",
    )
    return dist, top_card


def calibration_card(ctx: Context) -> str:
    res, src = ctx.p02.cal
    if not res:
        msg = empty("Chưa có kết quả G03 (<code>make calibration</code>).")
        return card("Hiệu chỉnh xác suất", msg)
    gbm = res["models"]["gbm"]
    names = {"raw": "Điểm gốc", "prior_shift": "Dịch tiên nghiệm", "platt": "Platt (chọn)"}
    v3 = {m: gbm[m]["blocks"]["V3"] for m in ("raw", "prior_shift", "platt") if m in gbm}
    truth = next(iter(v3.values()))["prevalence"]
    bars = [(names[m], b["mean_pred"], "fill-s1" if m != "raw" else "fill-muted",
             f"<b>{names[m]}</b><br>xác suất trung bình {pct(b['mean_pred'], 1)}<br>log loss "
             f"{vn(b['log_loss'])} · Brier {vn(b['brier'], 4)}")
            for m, b in v3.items()]  # fmt: skip
    rows = [[names[m], pct(b["mean_pred"], 1), vn(b["log_loss"]), vn(b["brier"], 4)]
            for m, b in v3.items()]  # fmt: skip
    return card(
        "Hiệu chỉnh: điểm có đọc được như xác suất?",
        bar_chart(bars, x_fmt=lambda v: pct(v, 0), title="Xác suất trung bình trên V3",
                  ref=(truth, f"thật {pct(truth, 1)}"), value_fmt=lambda v: pct(v, 1),
                  width=HALF, label_w=150)
        + table(["Phương pháp", "Xác suất TB", "Log loss", "Brier"], rows),
        "Khối V3. PR-AUC không đổi giữa các phương pháp (hiệu chỉnh đơn điệu).",
        meta=escape(src.name),
    )  # fmt: skip


def policy_card(ctx: Context) -> str:
    res, src = ctx.p02.pol
    if not res:
        return card("So sánh chính sách", empty("Chưa có kết quả G04 (<code>make policy</code>)."))
    rows = sorted((r for r in res["v3"] if r["cost_key"] == MID_COST), key=lambda r: r["cost"])
    bars = [(POLICY_VN.get(r["policy"], r["policy"]), r["cost"],
             "fill-s1" if r["policy"] == "rule_calibrated" else "fill-muted",
             f"<b>{escape(POLICY_VN.get(r['policy'], r['policy']))}</b><br>tổng chi phí "
             f"{vn(r['cost'], 0)} [{vn(r['cost_ci_day'][0], 0)}; {vn(r['cost_ci_day'][1], 0)}]"
             f"<br>{r['alerts']} cảnh báo, bắt {r['tp']} gian lận") for r in rows]  # fmt: skip
    wins = sum(1 for w in res.get("v3_winners", {}).values() if w == "rule_calibrated")
    return card(
        "Chính sách quyết định: tổng chi phí giả định",
        bar_chart(bars, x_fmt=lambda v: vn(v, 0), title="Tổng chi phí theo chính sách",
                  width=HALF, label_w=190),
        "<b>Phân tích độ nhạy, không phải ROI.</b> Chi phí giả định: mất 0,75 × số tiền khi bỏ "
        f"sót, 5 mỗi lần duyệt, 1 mỗi cảnh báo nhầm. Luật chi phí đã hiệu chỉnh rẻ nhất ở {wins}/"
        f"{len(res.get('v3_winners', {}))} tổ hợp, một phần vì được chấm bằng chính hàm chi phí "
        "nó tối ưu.",
        meta=f"V3 · {MID_COST}",
    )  # fmt: skip


def stability_cards(ctx: Context) -> str:
    res, src = ctx.p02.stab
    if not res:
        msg = empty("Chưa có kết quả G05 (<code>make stability</code>).")
        return card("Độ ổn định theo tuần", msg)
    weeks = res["weekly"]
    labels = [f"{'Train' if w['part'] == 'train' else 'Validation'} tuần {w['week']}"
              for w in weeks]  # fmt: skip
    ticks = [(i, ("T" if w["part"] == "train" else "V") + str(w["week"]))
             for i, w in enumerate(weeks) if i % 3 == 0 or w["part"] == "valid"]  # fmt: skip
    train = [w["pr_auc"] if w["part"] == "train" else None for w in weeks]
    valid = [w["pr_auc"] if w["part"] == "valid" else None for w in weeks]
    rate = [("Tỷ lệ gian lận", 1, [w["prevalence"] for w in weeks])]
    groups = [[escape(g["column"]), f"<b>{escape(str(g['value']))}</b>", vn(g["rows"], 0),
               vn(g["frauds"], 0), pct(g["prevalence"], 1), vn(g["recall_at_fpr"], 2),
               status(False, "cỡ mẫu nhỏ") if g["small_sample"] else ""]
              for g in res["groups"]]  # fmt: skip
    return grid(
        "g11",
        card("PR-AUC theo tuần (cùng một mô hình)",
             line_chart(labels, [("train", 2, train), ("validation", 1, valid)],
                        y_fmt=lambda v: vn(v, 2), title="PR-AUC theo tuần", x_ticks=ticks,
                        markers=True, y_min=None, width=HALF, height=220),
             "Tuần train là trong mẫu nên cao hơn; hai tuần validation cuối thấp nhất. PSI của "
             "4 đầu vào đều dưới 0,05.", meta=escape(src.name)),
        card("Tỷ lệ gian lận theo tuần",
             line_chart(labels, rate, y_fmt=lambda v: pct(v, 1), title="Tỷ lệ gian lận theo tuần",
                        x_ticks=ticks, markers=True, width=HALF, height=220),
             "Dao động 1,85%–4,55% mỗi tuần: ngưỡng xác suất cố định sẽ trôi theo."),
    ) + card(
        "Theo nhóm (validation)",
        table(["Cột", "Giá trị", "Dòng", "Gian lận", "Tỷ lệ gian lận", "Recall @ FPR 5%", ""],
              groups, numeric_from=2),
        "Không so PR-AUC giữa nhóm vì nó phụ thuộc tỷ lệ gian lận; recall tại FPR cố định so được "
        "hơn.",
    )  # fmt: skip


def feature_label(folder: Path) -> str:
    """'20' or '23 (+3: card1_*)' from the run's config.yaml; flags runs without C1–C14."""
    try:
        feats = yaml.safe_load((folder / "config.yaml").read_text("utf-8"))["features"]
    except (OSError, KeyError, TypeError):
        return "—"
    derived = feats.get("derived", [])
    n = len(feats.get("numeric", [])) + len(feats.get("categorical", [])) + len(derived)
    extra = [d for d in derived if d not in {"log_amount", "hour_of_day"}]
    groups = sorted({e.split("_")[0] for e in extra})
    label = f"{n} (+{len(extra)}: {', '.join(g + '_*' for g in groups)})" if extra else str(n)
    return label if "C1" in feats.get("numeric", []) else f"{label} · bỏ C1–C14"


def runs_card(ctx: Context) -> str:
    rows = []
    for run_id, valid, folder in ctx.p02.runs:
        for model, m in valid.items():
            ci = m.get("pr_auc_ci", {})
            rows.append([f"<code>{escape(run_id)}</code>", escape(MODEL_VN.get(model, model)),
                         escape(feature_label(folder)),
                         f"{vn(m['pr_auc'])} [{vn(ci.get('low'))}; {vn(ci.get('high'))}]",
                         vn(m.get("recall_at_fpr", {}).get("recall"), 2)])  # fmt: skip
    body = (table(["Lần chạy", "Mô hình", "Số đặc trưng", "PR-AUC validation [95% CI]",
                   "Recall @ FPR 5%"], rows, numeric_from=3)
            if rows else empty("Chưa có lần chạy validation trên máy này (cần dataset: "
                               "<code>make baseline</code>, <code>make gbm</code>)."))  # fmt: skip
    return card("Các biến thể trên validation", body, meta="thăm dò")


def section_p02(ctx: Context) -> str:
    dist, top = scoring_cards(ctx)
    body = (
        grid("g21", published_card(ctx), threshold_card(ctx))
        + grid("g11", dist, top)
        + '<h3 class="subhead">Từ xếp hạng đến quyết định (Stage G, thăm dò)</h3>'
        + grid("g11", policy_card(ctx), calibration_card(ctx))
        + stability_cards(ctx)
        + runs_card(ctx)
    )
    sub = (
        "Dataset công khai IEEE-CIS, chia theo thời gian 60/20/20. Số test chỉ được <b>trích "
        "lại</b>; mọi phân tích khác dùng train và validation. Điểm rủi ro hỗ trợ quyết định, "
        "không tự động chặn giao dịch."
    )
    return section("p02", "Product 02 · Rủi ro gian lận", sub, body)


# --- data & quality ---------------------------------------------------------------------------


def checks(ctx: Context) -> list[tuple[bool | None, str, str]]:
    out: list[tuple[bool | None, str, str]] = []
    m = p01_matches_published(ctx)
    out.append(
        (
            m,
            "Product 01 tái lập đúng số tuning đã công bố",
            "D-B 3/4, 0 báo nhầm/ngày; D-A 2/4, 1,0" if m is not None else "chưa chạy",
        )
    )
    if ctx.p01 is not None:
        out.append(
            (
                ctx.p01.kpi is not None,
                "Có KPI cho mô phỏng của lần chạy detector",
                escape(ctx.p01.evaluation["simulation_id"]),
            )
        )
    skew = (ctx.p02.scores or {}).get("skew_check")
    out.append((None if skew is None else skew.get("max_abs_diff") == 0.0,
                "Điểm chấm theo lô trùng điểm lúc huấn luyện",
                f"{skew['rows_compared']} dòng" if skew else "chưa chấm"))  # fmt: skip
    for path, name in (
        (ctx.artifacts / "test_runs.json", "test Product 02"),
        (ctx.artifacts / "detect_report_runs.json", "bộ report Product 01"),
    ):
        entries = read_json(path)
        if entries is None:
            out.append((None, f"Sổ test-một-lần ({name})", "không tìm thấy"))
        else:
            forced = sum(bool(e.get("forced")) for e in entries)
            out.append((forced == 0, f"Sổ test-một-lần ({name}) không có --force",
                        f"{len(entries)} lần đánh giá đã ghi"))  # fmt: skip
    for prefix, name in (("cal", "G03 hiệu chỉnh"), ("pol", "G04 chính sách"),
                         ("stab", "G05 độ ổn định")):  # fmt: skip
        res, src = getattr(ctx.p02, prefix)
        where = escape(src.name) if src else "—"
        out.append((res is not None, f"Kết quả {name} có sẵn", where))
    note = "số test chỉ trích từ results/published.json"
    out.append((None, "Dashboard không đọc tập test", note))
    return out


def runs_table(ctx: Context) -> str:
    rows = []

    def add(kind: str, folder: Path | None, ident: str) -> None:
        if folder is None:
            return
        ex = latest_execution(folder) or {}
        rows.append([escape(kind), f"<code>{escape(ident)}</code>",
                     f"<code>{escape(ex.get('execution_id', '—'))}</code>",
                     escape(str(ex.get("commit", "—"))[:7]), mtime(folder)])  # fmt: skip

    if ctx.p01:
        add("Detector (tuning)", ctx.p01.run, ctx.p01.run.name)
    for prefix, kind in (("cal", "G03 hiệu chỉnh"), ("pol", "G04 chính sách"),
                         ("stab", "G05 độ ổn định")):  # fmt: skip
        _, src = getattr(ctx.p02, prefix)
        add(kind, src, src.name if src else "")
    if ctx.p02.model_dir:
        add("Bộ chấm điểm", ctx.p02.model_dir, ctx.p02.model_dir.name)
    if ctx.p02.scores:
        rows.append(["Lần chấm điểm", "—", f"<code>{escape(ctx.p02.scores['execution_id'])}</code>",
                     escape(str(ctx.p02.scores.get("commit", ""))[:7]),
                     mtime(ctx.p02.scores_path) if ctx.p02.scores_path else "—"])  # fmt: skip
    if not rows:
        return empty("Chưa có lần chạy nào trên máy này.")
    return table(["Loại", "experiment_id (khoá cấu hình)", "execution_id (lần chạy gần nhất)",
                  "Commit", "Lúc"], rows, numeric_from=5)  # fmt: skip


LIMITS = [
    "Product 01 dùng dữ liệu <b>giả lập</b>, mỗi bộ chỉ 4 sự cố: kết quả là kiểm chứng trên bất "
    "thường đã biết, không phải tỷ lệ phát hiện thực tế.",
    "Product 02: <code>C1–C14</code> mang gần hết tín hiệu (bỏ chúng thì PR-AUC validation 0,497 "
    "→ 0,158) và ý nghĩa của chúng chưa xác minh.",
    "Validation đã được dùng nhiều lần (lưới GBM, rò rỉ, đặc trưng lịch sử, Stage G): mọi số "
    "trên validation có thể lạc quan.",
    "Giả định nhãn gian lận có ngay; thực tế chargeback đến muộn nhiều tuần (ADR 0003).",
    "Hai sản phẩm không dùng chung dữ liệu (ADR 0002).",
    "Không phải hệ thống production: không API, không giám sát mô hình, không huấn luyện lại.",
]


def section_quality(ctx: Context) -> str:
    results = checks(ctx)
    check_rows = [[status(ok, "đạt" if ok else ("không đạt" if ok is False else "ghi chú")),
                   escape(name), detail] for ok, name, detail in results]  # fmt: skip
    passed = sum(ok is True for ok, _, _ in results)
    failed = sum(ok is False for ok, _, _ in results)
    sim = ctx.p01.sim_manifest if ctx.p01 else None
    manifest_path = ctx.repo / "datasets" / "manifests" / "ieee-cis.yaml"
    manifest = yaml.safe_load(manifest_path.read_text("utf-8")) if manifest_path.exists() else None
    data_rows = []
    if sim:
        data_rows.append(["Mô phỏng (Product 01)", f"<code>{escape(sim['simulation_id'])}</code>",
                          f"{vn(sim['events'], 0)} sự kiện, {vn(sim['payments'], 0)} payment, "
                          f"bộ sinh {escape(str(sim['generator_version']))}, seed {sim['seed']}",
                          f"<code>{escape(sim['events_sha256'][:12])}…</code>"])  # fmt: skip
    if manifest:
        size = sum(f["size_bytes"] for f in manifest["files"]) / 1e6
        data_rows.append(["IEEE-CIS (Product 02)", escape(manifest["name"]),
                          f"{len(manifest['files'])} file, {vn(size, 0)} MB, tải "
                          f"{escape(str(manifest['download_date']))}; không nằm trong git",
                          f"<code>{escape(manifest['checksum'][:12])}…</code>"])  # fmt: skip
    body = (
        grid("g21",
             card("Kiểm tra tự động", table(["Kết quả", "Kiểm tra", "Chi tiết"], check_rows,
                                            numeric_from=3),
                  meta=f"{passed} đạt · {failed} không đạt"),
             card("Hạn chế: những gì dashboard này không chứng minh",
                  "<ul class='limits'>" + "".join(f"<li>{x}</li>" for x in LIMITS) + "</ul>"))
        + card("Các lần chạy và mã nhận diện", runs_table(ctx),
               "experiment_id nhận diện cấu hình (cũng là khoá chặn test-một-lần); execution_id "
               "nhận diện từng lần chạy, kèm commit và môi trường (ADR 0010).")
        + card("Nguồn dữ liệu", table(["Nguồn", "Mã", "Mô tả", "Checksum"], data_rows,
                                      numeric_from=4) if data_rows else empty("Không có."))
    )  # fmt: skip
    return section(
        "quality",
        "Dữ liệu & chất lượng",
        "Kiểm tra tự động, mã lần chạy, nguồn dữ liệu và hạn chế.",
        body,
    )


# --- page -------------------------------------------------------------------------------------

NAV = [("overview", "grid", "Tổng quan"), ("pipeline", "flow", "Luồng pipeline"),
       ("p01", "activity", "Product 01 · Ổn định"), ("p02", "shield", "Product 02 · Gian lận"),
       ("quality", "check", "Dữ liệu & chất lượng")]  # fmt: skip

CSS_PATH = Path(__file__).with_name("page.css")
JS_PATH = Path(__file__).with_name("page.js")


def build(artifacts: Path, git_sha: str = "", repo: Path = REPO_ROOT) -> str:
    """The whole page as HTML text: one scrolling page, sidebar links to each section."""
    ctx = load(artifacts, repo)
    built = datetime.now(UTC).astimezone(LOCAL).strftime("%d/%m/%Y %H:%M")
    sha = f" · commit <code>{escape(git_sha[:7])}</code>" if git_sha else ""
    nav = "".join(f'<a href="#{k}">{icon(i)}<span>{escape(v)}</span></a>' for k, i, v in NAV)
    m01 = p01_matches_published(ctx)
    skew = (ctx.p02.scores or {}).get("skew_check")
    badges = (
        status(m01, "P01 khớp số công bố" if m01 is not False else "P01 chưa khớp")
        if m01 is not None else status(None, "P01 chưa chạy")
    ) + (
        status(skew.get("max_abs_diff") == 0.0, "P02 lệch chấm điểm 0")
        if skew else status(None, "P02 chưa chấm")
    )  # fmt: skip
    overview = (
        '<section class="section" id="overview">'
        + overview_tiles(ctx)
        + "</section>"
        + f'<div id="pipeline" class="anchor">{pipeline_card(ctx)}</div>'
    )
    body = overview + section_p01(ctx) + section_p02(ctx) + section_quality(ctx)
    css, js = CSS_PATH.read_text("utf-8"), JS_PATH.read_text("utf-8")
    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Payment Intelligence Dashboard</title><style>{css}</style></head>
<body><div class="app">
<aside class="side">
<div class="logo"><span class="logo-mark">PI</span>
<div><b>Payment Intelligence</b><small>Ecosystem · demo</small></div></div>
<nav class="side-nav" aria-label="Các phần của trang">{nav}</nav>
<div class="side-foot">
<button class="theme" type="button">{icon("moon")}<span>Sáng / tối</span></button>
<p>Dựng lúc {built}{sha}</p><p>Không dùng dữ liệu thật</p></div>
</aside>
<main class="main">
<header class="topbar"><div><h1>Dashboard</h1>
<p>Kết quả các lần chạy trên máy này · hai sản phẩm, một nền tảng, không chung dữ liệu</p></div>
<div class="badges">{badges}</div></header>
{body}
</main></div>
<div class="tooltip" role="status" hidden></div>
<script>{js}</script>
</body></html>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
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
