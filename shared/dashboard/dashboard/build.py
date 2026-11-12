"""`make dashboard`: one static HTML page for both products (ADR 0007), four tabs.

Tabs: overview with the two pipelines, Product 01, Product 02, data & quality. Charts are inline
SVG (`charts.py`), so the file opens offline and can be attached to the report.

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
    return f'<div class="table-wrap"><table><thead><tr>{th}</tr></thead><tbody>{body}</tbody></table></div>'  # noqa: E501


def tile(label: str, value: str, sub: str = "", tone: str = "") -> str:
    sub_html = f'<div class="sub">{sub}</div>' if sub else ""
    return (f'<div class="tile {tone}"><div class="label">{escape(label)}</div>'
            f'<div class="value">{value}</div>{sub_html}</div>')  # fmt: skip


def status(ok: bool | None, text: str) -> str:
    """Status with icon + word (never color alone)."""
    if ok is None:
        return f'<span class="status info">ⓘ {text}</span>'
    return (f'<span class="status good">✓ {text}</span>' if ok
            else f'<span class="status bad">✗ {text}</span>')  # fmt: skip


def empty(text: str) -> str:
    return f'<p class="empty">{text}</p>'


def card(title: str, body: str, note: str = "") -> str:
    note_html = f'<p class="note">{note}</p>' if note else ""
    return f'<section class="card"><h3>{escape(title)}</h3>{body}{note_html}</section>'


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


# --- tab 1: overview and pipelines ------------------------------------------------------------


def node(state: str, title: str, lines: list[str], where: str = "") -> dict[str, Any]:
    return {"state": state, "title": title, "lines": lines, "where": where}


ICON = {"ok": "✓", "missing": "○", "locked": "🔒", "info": "ⓘ"}
STATE_VN = {"ok": "đã chạy", "missing": "chưa có", "locked": "khoá (một lần)", "info": "thông tin"}


def flow(nodes: list[dict[str, Any]]) -> str:
    items = "".join(
        f'<li class="node {n["state"]}"><div class="node-head"><span class="node-icon" '
        f'aria-hidden="true">{ICON[n["state"]]}</span><span class="node-state">'
        f"{STATE_VN[n['state']]}</span></div><h4>{escape(n['title'])}</h4>"
        + "".join(f"<p>{line}</p>" for line in n["lines"])
        + (f"<code>{escape(n['where'])}</code>" if n["where"] else "")
        + "</li>"
        for n in nodes
    )
    return f'<ol class="flow">{items}</ol>'


def pipeline_01(ctx: Context) -> str:
    p = ctx.p01
    sim = p.sim_manifest if p else None
    kpi = p.kpi_manifest if p else None
    matches = p01_matches_published(ctx)
    nodes = [
        node("ok", "Cấu hình", ["<b>demo.yaml</b> (frozen)", "7 ngày, 3 provider, 4 sự cố"],
             "shared/synthetic-generator/configs/"),
        node("ok" if sim else "missing", "Sinh dữ liệu giả lập",
             [f"<b>{vn(sim['events'], 0)}</b> sự kiện", f"{vn(sim['payments'], 0)} payment"]
             if sim else ["chạy <code>make simulate</code>"],
             f"simulations/{sim['simulation_id']}/" if sim else ""),
        node("ok" if kpi else "missing", "PostgreSQL",
             ["kiểm tra contract payment-event", "bảng <b>payment_events</b>"]
             if kpi else ["chạy <code>make up</code>, <code>make ingest</code>"]),
        node("ok" if kpi else "missing", "KPI 15 phút (SQL view)",
             [f"<b>{vn(kpi['rows']['provider_15m'], 0)}</b> dòng provider × khung",
              "tỷ lệ lỗi, độ trễ, lưu lượng"] if kpi else ["chạy <code>make kpi</code>"],
             f"kpi/{kpi['simulation_id']}/" if kpi else ""),
        node("ok" if p else "missing", "Detector D-A, D-B",
             [f"D-B: <b>{p.alerts.get('pooled', 0)}</b> khung cảnh báo",
              f"D-A: {p.alerts.get('robust_z', 0)} khung cảnh báo"]
             if p else ["chạy <code>make detect</code>"],
             f"detections/{p.run.name}/" if p else ""),
        node("ok" if matches else ("missing" if matches is None else "info"), "Sự cố và đánh giá",
             [f"D-B bắt <b>{p.evaluation['detectors']['pooled']['detected']}/"
              f"{len(p.evaluation['detectors']['pooled']['anomalies'])}</b> sự cố",
              status(matches, "khớp số công bố")]
             if p else ["chưa có lần chạy"]),
        node("ok", "Dashboard", ["trang này"], "artifacts/dashboard/index.html"),
    ]  # fmt: skip
    return flow(nodes)


def pipeline_02(ctx: Context) -> str:
    p = ctx.p02
    card_ = p.card or {}
    raw = (ctx.repo / "datasets" / "raw" / "ieee-cis" / "train_transaction.csv").exists()
    pub = {m["model"]: m for m in ctx.published.get("product_02", {}).get("models", [])}
    gbm = pub.get("gbm", {})
    skew = (p.scores or {}).get("skew_check", {})
    nodes = [
        node("ok" if raw else "info", "Dataset IEEE-CIS",
             ["590.540 giao dịch, 3,5% gian lận", "checksum trong manifest"
              + ("" if raw else "; <b>file thô không có trên máy này</b>")],
             "datasets/manifests/ieee-cis.yaml"),
        node("ok", "Chia theo thời gian", ["train 60% · validation 20% · test 20%",
                                           "validation chia V1 / V2 / V3"]),
        node("ok" if p.card else "missing", "Mô hình Gradient Boosting",
             [f"học trên <b>{vn(card_.get('train_rows'), 0)}</b> dòng train",
              f"{len(card_.get('features', {}).get('numeric', [])) + len(card_.get('features', {}).get('categorical', []))} đặc trưng"]  # noqa: E501
             if p.card else ["chạy <code>make score-model</code>"],
             f"models/{p.model_dir.name}/" if p.model_dir else ""),
        node("ok" if p.card else "missing", "Hiệu chỉnh xác suất",
             [f"<b>{escape(card_['calibration']['method'])}</b> fit trên V1"]
             if p.card else ["cùng lệnh <code>make score-model</code>"]),
        node("ok" if p.scores else "missing", "Chấm điểm theo lô",
             [f"<b>{vn(p.scores['rows'], 0)}</b> giao dịch không nhãn",
              status(skew.get("max_abs_diff") == 0.0, "trùng điểm lúc huấn luyện")]
             if p.scores else ["chạy <code>make score</code>"],
             f"scores/{p.scores_path.name}" if p.scores_path else ""),
        node("locked", "Tập test (một lần)",
             [f"PR-AUC test <b>{vn(gbm.get('test_pr_auc'))}</b> (trích lại)",
              "không chạy lại, không đọc lại"], escape(gbm.get("run_id", ""))),
    ]  # fmt: skip
    return flow(nodes)


def tab_overview(ctx: Context) -> str:
    pub01 = ctx.published.get("product_01", {})
    pub02 = {m["model"]: m for m in ctx.published.get("product_02", {}).get("models", [])}
    gbm = pub02.get("gbm", {})
    rep = pub01.get("report", {}).get("pooled", {})
    tun = ctx.p01.evaluation["detectors"]["pooled"] if ctx.p01 else None
    tiles = "".join([
        tile("Product 01 · D-B trên bộ tuning",
             f"{tun['detected']}/{len(tun['anomalies'])}" if tun else "—",
             f"sự cố, {vn(tun['false_per_day'], 1)} báo nhầm/ngày" if tun else "chưa chạy"),
        tile("Product 01 · D-B trên bộ report", f"{rep.get('detected', '—')}/{rep.get('total', 4)}",
             "đánh giá một lần, trích lại"),
        tile("Product 02 · PR-AUC test", vn(gbm.get("test_pr_auc")),
             "Gradient Boosting, đánh giá một lần, trích lại"),
        tile("Product 02 · lần chấm gần nhất",
             vn(ctx.p02.scores["rows"], 0) if ctx.p02.scores else "—",
             "giao dịch đã chấm" if ctx.p02.scores else "chưa chạy make score"),
    ])  # fmt: skip
    run01 = (
        "Chạy lại: <code>make up</code> rồi <code>make demo</code>. "
        "Bộ report (đánh giá một lần) không bao giờ được chạy lại."
    )
    run02 = (
        "Chạy lại: <code>make score-model</code>, <code>make score</code> (cần dataset). "
        "Mọi thứ trừ ô 🔒 chỉ dùng train và validation."
    )
    flow01 = card("Product 01 · Độ ổn định thanh toán (dữ liệu giả lập)", pipeline_01(ctx), run01)
    flow02 = card("Product 02 · Rủi ro gian lận (IEEE-CIS)", pipeline_02(ctx), run02)
    lead = (
        '<p class="lead">Một nền tảng dùng chung (contract dữ liệu, quản lý dataset, quy tắc đánh '
        "giá, PostgreSQL), <b>hai pipeline độc lập</b> không dùng chung dữ liệu (ADR 0002). Mỗi ô "
        "dưới đây là một bước; ✓ là đã có kết quả trên máy này.</p>"
    )
    return f'{lead}<div class="tiles">{tiles}</div>{flow01}{flow02}'


# --- tab 2: Product 01 ------------------------------------------------------------------------


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
                   f"{local(inc['first_alert_at'])}, điểm cao nhất {vn(inc['max_score'], 1)}")  # fmt: skip  # noqa: E501
            bands.append((i0, i1, "band-alert", tip))
    return bands


def kpi_charts(p: P01) -> str:
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
    legend = "".join(
        f'<span class="key"><i style="background:var(--s{s})"></i>{escape(n)}</span>'
        for n, s, _ in fail
    ) + ('<span class="key"><i class="key-alert"></i>D-B báo sự cố</span>'
         '<span class="key"><i class="key-truth"></i>sự cố cài sẵn (đáp án)</span>')  # fmt: skip
    return (
        f'<div class="legend">{legend}</div>'
        + card("Tỷ lệ lỗi kỹ thuật theo giờ, mỗi provider một hàng (cùng thang)",
               "".join(
                   line_chart(labels, [(name, slot, vals)], y_fmt=lambda v: pct(v, 0),
                              title=f"Tỷ lệ lỗi kỹ thuật {name}", x_ticks=ticks, height=150,
                              y_max=top_fail,
                              bands=_bands(index, p, "technical_failure_rate",
                                           {"provider_outage", "error_burst"}, target=name))
                   for name, slot, vals in fail
               ),
               f"Giờ Việt Nam. Ẩn giờ có dưới {MIN_ATTEMPTS} attempt (tỷ lệ trên vài attempt chủ "
               "yếu là nhiễu). Rê chuột để xem số và sự cố.")
        + card("Độ trễ trung vị theo giờ (ms, không tính TIMEOUT)",
               line_chart(labels, lat, y_fmt=lambda v: vn(v, 0), title="Độ trễ trung vị",
                          x_ticks=ticks, bands=_bands(index, p, "latency_p50",
                                                      {"latency_degradation"})))
        + card("Lưu lượng: số attempt mỗi giờ",
               line_chart(labels, traffic, y_fmt=lambda v: vn(v, 0), title="Lưu lượng",
                          x_ticks=ticks, height=180),
               "Mùa vụ theo giờ trong ngày là giả định của bộ sinh dữ liệu: thấp ban đêm, đỉnh trưa và tối.")  # noqa: E501
    )  # fmt: skip  # noqa: E501


def report_card(ctx: Context) -> str:
    """Report-simulation numbers, quoted from results/published.json (evaluated once)."""
    rep = ctx.published.get("product_01", {}).get("report", {})
    rep_rows = [
        [escape(DETECTOR_VN[d]), f"{rep[d]['detected']}/{rep[d]['total']}",
         vn(rep[d]["false_per_day"], 1)]
        for d in ("pooled", "robust_z") if d in rep
    ]  # fmt: skip
    return card("Bộ report: đánh giá một lần (trích lại)",
                table(["Detector", "Bắt được", "Báo nhầm/ngày"], rep_rows),
                f"Lần chạy <code>{escape(rep.get('run_id', ''))}</code> trên "
                f"<code>{escape(rep.get('simulation_id', ''))}</code>, seed khác và có một loại "
                "sự cố chưa gặp khi chỉnh ngưỡng. Không chạy lại; số lấy từ "
                "results/published.json.")  # fmt: skip


def tab_p01(ctx: Context) -> str:
    p = ctx.p01
    if p is None:
        return empty("Chưa có lần chạy detector trên bộ tuning. Chạy <code>make up</code> rồi "
                     "<code>make demo</code>.") + report_card(ctx)  # fmt: skip
    ev = p.evaluation
    head = (f'<p class="lead">Mô phỏng <code>{escape(ev["simulation_id"])}</code> (bộ tuning), lần '
            f'chạy detector <code>{escape(ev["run_id"])}</code>. Dữ liệu giả lập; 4 sự cố được cài '
            "sẵn để kiểm chứng detector.</p>")  # fmt: skip
    if p.kpi is None:
        return head + empty(f"Thiếu KPI: chạy <code>make kpi SIM={escape(ev['simulation_id'])}"
                            "</code>.")  # fmt: skip
    summary = provider_summary(p.kpi)
    all_row = summary.loc["ALL"] if "ALL" in summary.index else summary.iloc[0]
    folded = fold_echoes([i for i in p.incidents if i["detector"] == "pooled"])
    pooled = ev["detectors"]["pooled"]
    tiles = "".join([
        tile("Attempt (7 ngày)", vn(float(all_row["attempts"]), 0)),
        tile("Thành công", pct(all_row["success_rate"])),
        tile("Thành công ngay lần đầu", pct(all_row["first_attempt_success_rate"])),
        tile("Lỗi kỹ thuật", pct(all_row["technical_failure_rate"])),
        tile("Sự cố D-B báo", str(len(folded)),
             f"bắt {pooled['detected']}/{len(pooled['anomalies'])} sự cố cài sẵn"),
    ])  # fmt: skip
    prov_rows = [
        [escape(str(name)), vn(float(r["attempts"]), 0), pct(r["success_rate"]),
         pct(r["first_attempt_success_rate"]), pct(r["technical_failure_rate"]),
         pct(r["business_failure_rate"]), pct(r["retry_share"]), vn(r["median_bucket_p50_ms"], 0)]
        for name, r in summary.iterrows()
    ]  # fmt: skip
    inc_rows = [
        [escape(i["incident_id"]), escape(i["target"]),
         escape(", ".join(METRIC_VN.get(m, m) for m in i["metrics"])), local(i["start"]),
         f"{i['buckets'] * 15} phút", local(i["first_alert_at"]), vn(i["max_score"], 1),
         escape(", ".join(i["echoes"])) or "—"]
        for i in folded
    ]  # fmt: skip
    per = {d: {a["anomaly_id"]: a for a in r["anomalies"]} for d, r in ev["detectors"].items()}

    def cell(a: dict[str, Any] | None) -> str:
        if a and a["detected"]:
            return status(True, f"bắt, sau {a['delay_minutes']:.0f} phút")
        return status(False, "trượt")

    truth_rows = [
        [escape(lab["anomaly_id"]), escape(lab["type"]), f"x{vn(lab['magnitude'], 1)}",
         escape(lab["provider_id"] or lab["payment_method"] or lab["error_code"] or "ALL"),
         f"{local(lab['start'])}–{local(lab['end'])[-5:]}",
         cell(per.get("pooled", {}).get(lab["anomaly_id"])),
         cell(per.get("robust_z", {}).get(lab["anomaly_id"]))]
        for lab in p.labels
    ]  # fmt: skip
    summary_rows = [
        [escape(DETECTOR_VN[d]), f"{r['detected']}/{len(r['anomalies'])}",
         vn(r["false_per_day"], 1)]
        for d, r in ev["detectors"].items() if d in DETECTOR_VN
    ]  # fmt: skip
    return (
        head + f'<div class="tiles">{tiles}</div>' + kpi_charts(p)
        + card("Detector so với sự cố cài sẵn (bộ tuning)",
               table(["Sự cố", "Loại", "Mức", "Đối tượng", "Thời gian", "D-B (chính)",
                      "D-A (cơ sở)"], truth_rows, numeric_from=7)
               + table(["Detector", "Bắt được", "Báo nhầm/ngày"], summary_rows),
               "Đáp án chỉ dùng để đánh giá; người vận hành thật không có nó. Sự cố x1,5 nằm "
               "dưới giới hạn phát hiện.")
        + report_card(ctx)
        + card("Sự cố D-B báo", table(["Sự cố", "Đối tượng", "Chỉ số", "Bắt đầu", "Kéo dài",
                                       "Cảnh báo lúc", "Điểm cao nhất", "Gộp ALL"], inc_rows,
                                      numeric_from=4)
               if inc_rows else empty("Detector không báo sự cố nào."),
               "Cảnh báo ALL trùng thời gian với một provider được gộp vào sự cố của provider đó.")
        + card("Theo provider (cả kỳ)", table(["Provider", "Attempt", "Thành công",
                                               "Thành công lần đầu", "Lỗi kỹ thuật",
                                               "Lỗi nghiệp vụ", "Tỷ lệ retry",
                                               "Độ trễ trung vị (ms)"], prov_rows))
    )  # fmt: skip


# --- tab 3: Product 02 ------------------------------------------------------------------------


def published_models(ctx: Context) -> str:
    models = ctx.published.get("product_02", {}).get("models", [])
    if not models:
        return empty("Thiếu results/published.json.")
    bars = []
    for m in models:
        name = MODEL_VN.get(m["model"], m["model"])
        ci = m.get("test_pr_auc_ci")
        ci_text = f" [{vn(ci[0])}; {vn(ci[1])}]" if ci else ""
        bars.append(
            (
                f"{name} · validation",
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
    th = ctx.published.get("product_02", {}).get("threshold", {})
    legend = ('<div class="legend"><span class="key"><i style="background:var(--s2)"></i>'
              'validation</span><span class="key"><i style="background:var(--s1)"></i>test (một '
              "lần)</span></div>")  # fmt: skip
    return (
        card("Chất lượng xếp hạng (trích lại số đã công bố)",
             legend + bar_chart(bars, x_fmt=lambda v: vn(v, 2), title="PR-AUC theo mô hình")
             + table(["Mô hình", "PR-AUC validation", "PR-AUC test [95% CI]",
                      "Recall @ FPR 5% (test)", "Lần chạy"], rows),
             "Recall tại FPR 5% chọn ngưỡng bằng nhãn của chính tập test, nên chỉ đo thứ tự điểm, "
             "không phải hiệu quả của một ngưỡng triển khai.")
        + card("Ngưỡng đã chốt trước khi mở test",
               table(["Mô hình", "Ngưỡng", "Precision (test)", "Recall (test)", "FPR (test)"],
                     [[escape(MODEL_VN.get(th.get("model", ""), "")), vn(th.get("threshold")),
                       vn(th.get("precision")), vn(th.get("recall")), pct(th.get("fpr"), 2)]]),
               "Bảng này và bảng trên ở hai điểm vận hành khác nhau (FPR 1,24% và 5%), nên không "
               "đọc là recall “tụt từ 51% xuống 37%”.")
    )  # fmt: skip


def calibration_card(ctx: Context) -> str:
    res, src = ctx.p02.cal
    if not res:
        return card(
            "Hiệu chỉnh xác suất", empty("Chưa có kết quả G03 (<code>make calibration</code>).")
        )  # noqa: E501
    gbm = res["models"]["gbm"]
    names = {"raw": "Điểm gốc", "prior_shift": "Dịch tiên nghiệm", "platt": "Platt (chọn)"}
    v3 = {m: gbm[m]["blocks"]["V3"] for m in ("raw", "prior_shift", "platt") if m in gbm}
    truth = next(iter(v3.values()))["prevalence"]
    bars = [(names[m], b["mean_pred"], "fill-s1" if m != "raw" else "fill-muted",
             f"<b>{names[m]}</b><br>xác suất trung bình {pct(b['mean_pred'], 1)}<br>log loss "
             f"{vn(b['log_loss'])} · Brier {vn(b['brier'], 4)}") for m, b in v3.items()]  # fmt: skip  # noqa: E501
    rows = [[names[m], pct(b["mean_pred"], 1), vn(b["log_loss"]), vn(b["brier"], 4),
             vn(b["pr_auc"])] for m, b in v3.items()]  # fmt: skip
    return card("Hiệu chỉnh: điểm có đọc được như xác suất không? (khối V3)",
                bar_chart(bars, x_fmt=lambda v: pct(v, 0), title="Xác suất trung bình trên V3",
                          ref=(truth, f"tỷ lệ gian lận thật {pct(truth, 1)}"),
                          value_fmt=lambda v: pct(v, 1))
                + table(["Phương pháp", "Xác suất TB", "Log loss", "Brier", "PR-AUC"], rows),
                f"Thăm dò, chỉ train + validation · <code>{escape(src.name)}</code>. PR-AUC không "
                "đổi giữa các phương pháp (hiệu chỉnh đơn điệu).")  # fmt: skip


def policy_card(ctx: Context) -> str:
    res, src = ctx.p02.pol
    if not res:
        return card("So sánh chính sách", empty("Chưa có kết quả G04 (<code>make policy</code>)."))
    rows = [r for r in res["v3"] if r["cost_key"] == MID_COST]
    rows.sort(key=lambda r: r["cost"])
    bars = [(POLICY_VN.get(r["policy"], r["policy"]), r["cost"],
             "fill-s1" if r["policy"] == "rule_calibrated" else "fill-muted",
             f"<b>{escape(POLICY_VN.get(r['policy'], r['policy']))}</b><br>tổng chi phí "
             f"{vn(r['cost'], 0)} [{vn(r['cost_ci_day'][0], 0)}; {vn(r['cost_ci_day'][1], 0)}]"
             f"<br>{r['alerts']} cảnh báo, bắt {r['tp']} gian lận") for r in rows]  # fmt: skip
    table_rows = [[escape(POLICY_VN.get(r["policy"], r["policy"])), vn(r["alerts"], 0),
                   vn(r["tp"], 0), pct(r["recall"], 1), vn(r["caught_amount"], 0),
                   vn(r["cost"], 0)] for r in rows]  # fmt: skip
    wins = sum(1 for w in res.get("v3_winners", {}).values() if w == "rule_calibrated")
    return card(f"Chính sách quyết định: tổng chi phí giả định trên V3 ({MID_COST})",
                bar_chart(bars, x_fmt=lambda v: vn(v, 0), title="Tổng chi phí theo chính sách")
                + table(["Chính sách", "Cảnh báo", "Gian lận bắt", "Recall", "Tiền gian lận bắt",
                         "Tổng chi phí"], table_rows),
                f"<b>Phân tích độ nhạy, không phải ROI</b>: chi phí là giả định (mất 0,75 × số "
                f"tiền khi bỏ sót, 5 mỗi lần duyệt, 1 mỗi cảnh báo nhầm). Luật chi phí đã hiệu chỉnh "  # noqa: E501
                f"rẻ nhất ở {wins}/{len(res.get('v3_winners', {}))} tổ hợp, một phần do được chấm "
                f"bằng chính hàm chi phí nó tối ưu. <code>{escape(src.name)}</code>.")  # fmt: skip


def stability_card(ctx: Context) -> str:
    res, src = ctx.p02.stab
    if not res:
        return card(
            "Độ ổn định theo tuần", empty("Chưa có kết quả G05 (<code>make stability</code>).")
        )  # noqa: E501
    weeks = res["weekly"]
    labels = [f"{'Train' if w['part'] == 'train' else 'Validation'} tuần {w['week']}"
              for w in weeks]  # fmt: skip
    ticks = [(i, ("T" if w["part"] == "train" else "V") + str(w["week"]))
             for i, w in enumerate(weeks) if i % 2 == 0 or w["part"] == "valid"]  # fmt: skip
    train = [w["pr_auc"] if w["part"] == "train" else None for w in weeks]
    valid = [w["pr_auc"] if w["part"] == "valid" else None for w in weeks]
    rate = [("Tỷ lệ gian lận", 1, [w["prevalence"] for w in weeks])]
    groups = [[escape(g["column"]), escape(str(g["value"])), vn(g["rows"], 0), vn(g["frauds"], 0),
               pct(g["prevalence"], 1), vn(g["recall_at_fpr"], 2),
               status(False, "cỡ mẫu nhỏ") if g["small_sample"] else ""]
              for g in res["groups"]]  # fmt: skip
    return (
        card("PR-AUC theo tuần (cùng một mô hình)",
             line_chart(labels, [("train (trong mẫu)", 2, train), ("validation", 1, valid)],
                        y_fmt=lambda v: vn(v, 2), title="PR-AUC theo tuần", x_ticks=ticks,
                        markers=True, y_min=None),
             "Tuần train là trong mẫu nên cao hơn; hai tuần validation cuối thấp nhất. PSI của 4 "
             f"đầu vào đều dưới 0,05 nên không giải thích được sự sụt. <code>{escape(src.name)}</code>.")  # noqa: E501
        + card("Tỷ lệ gian lận theo tuần",
               line_chart(labels, rate, y_fmt=lambda v: pct(v, 1), title="Tỷ lệ gian lận theo tuần",
                          x_ticks=ticks, markers=True, height=180))
        + card("Theo nhóm (validation)", table(["Cột", "Giá trị", "Dòng", "Gian lận",
                                                 "Tỷ lệ gian lận", "Recall @ FPR 5%", ""], groups,
                                                numeric_from=2),
               "Không so PR-AUC giữa nhóm vì nó phụ thuộc tỷ lệ gian lận; recall tại FPR cố định "
               "so được hơn.")
    )  # fmt: skip  # noqa: E501


BUCKETS = [(0.0, 0.01, "< 1%"), (0.01, 0.02, "1–2%"), (0.02, 0.05, "2–5%"), (0.05, 0.1, "5–10%"),
           (0.1, 0.2, "10–20%"), (0.2, 0.5, "20–50%"), (0.5, 1.01, "≥ 50%")]  # fmt: skip


def scoring_card(ctx: Context) -> str:
    p = ctx.p02
    if not p.scores or p.scores_csv is None:
        return card(
            "Chấm điểm theo lô gần nhất",
            empty("Chưa chấm: chạy <code>make score-model</code> rồi <code>make score</code>."),
        )  # noqa: E501
    probs = p.scores_csv["score_calibrated"]
    counts = [int(((probs >= lo) & (probs < hi)).sum()) for lo, hi, _ in BUCKETS]
    bars = [(name, c, "fill-s1", f"xác suất {name}: <b>{c}</b> giao dịch")
            for (_, _, name), c in zip(BUCKETS, counts, strict=True)]  # fmt: skip
    top = p.scores_csv.sort_values("score_calibrated", ascending=False).head(10)
    rows = [[str(r.TransactionID), vn(r.score), pct(r.score_calibrated, 1)]
            for r in top.itertuples()]  # fmt: skip
    skew = p.scores.get("skew_check", {})
    tiles = "".join([
        tile("Giao dịch đã chấm", vn(p.scores["rows"], 0), escape(p.scores["execution_id"])),
        tile("Xác suất trung bình", pct(p.scores.get("score_calibrated_mean"), 1), "đã hiệu chỉnh"),
        tile("Xác suất ≥ 50%", str(counts[-1]), "giao dịch"),
        tile("Lệch huấn luyện–chấm điểm", vn(skew.get("max_abs_diff"), 1),
             f"trên {skew.get('rows_compared', 0)} dòng",
             "good" if skew.get("max_abs_diff") == 0.0 else "bad"),
    ])  # fmt: skip
    return card("Chấm điểm theo lô gần nhất",
                f'<div class="tiles">{tiles}</div><h4>Phân bố xác suất gian lận (đã hiệu chỉnh)</h4>'  # noqa: E501
                + bar_chart(bars, x_fmt=lambda v: vn(v, 0), title="Phân bố xác suất")
                + "<h4>10 giao dịch rủi ro nhất</h4>"
                + table(["TransactionID", "Điểm gốc", "Xác suất"], rows),
                f"Mô hình <code>{escape(p.scores['model_version'])}</code>, đặc trưng "
                f"<code>{escape(p.scores['feature_version'])}</code>. Đầu vào là giao dịch validation "  # noqa: E501
                "không nhãn; 10 giao dịch rủi ro nhất chỉ để minh hoạ, không phải quyết định chặn.")  # fmt: skip  # noqa: E501


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
    pub = ctx.published.get("product_02", {}).get("leakage", {})
    leak = (
        f"Thí nghiệm rò rỉ <code>{escape(pub.get('run_id', ''))}</code> (trích lại): mã hoá "
        f"<code>card1</code> bằng nhãn làm PR-AUC validation tăng {vn(pub.get('target_encoding_card1'))}; "  # noqa: E501
        f"chia ngẫu nhiên thay vì theo thời gian làm PR-AUC giảm "
        f"{vn(abs(pub.get('random_split', 0)))}."
    )
    body = (table(["Lần chạy", "Mô hình", "Số đặc trưng", "PR-AUC validation [95% CI]",
                   "Recall @ FPR 5%"], rows, numeric_from=3)
            if rows else empty("Chưa có lần chạy validation trên máy này (cần dataset: "
                               "<code>make baseline</code>, <code>make gbm</code>)."))  # fmt: skip
    return card("Các biến thể trên validation (thăm dò)", body, leak)


def tab_p02(ctx: Context) -> str:
    return (
        '<p class="lead">Dataset công khai IEEE-CIS, chia theo thời gian 60/20/20. Số test chỉ '
        "được <b>trích lại</b> (đánh giá một lần); mọi phân tích khác dùng train và validation "
        "(thăm dò). Điểm rủi ro chỉ hỗ trợ quyết định, không tự động chặn giao dịch.</p>"
        + published_models(ctx)
        + scoring_card(ctx)
        + '<h2 class="section">Từ xếp hạng đến quyết định (Stage G, thăm dò)</h2>'
        + calibration_card(ctx)
        + policy_card(ctx)
        + stability_card(ctx)
        + runs_card(ctx)
    )


# --- tab 4: data & quality --------------------------------------------------------------------


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
    out.append(
        (
            None if skew is None else skew.get("max_abs_diff") == 0.0,
            "Điểm chấm theo lô trùng điểm lúc huấn luyện",
            f"{skew['rows_compared']} dòng" if skew else "chưa chấm",
        )
    )
    for path, name in (
        (ctx.artifacts / "test_runs.json", "test Product 02"),
        (ctx.artifacts / "detect_report_runs.json", "bộ report Product 01"),
    ):
        entries = read_json(path)
        if entries is None:
            out.append((None, f"Sổ test-một-lần ({name})", "không tìm thấy"))
        else:
            forced = sum(bool(e.get("forced")) for e in entries)
            out.append(
                (
                    forced == 0,
                    f"Sổ test-một-lần ({name}) không có lần chạy --force",
                    f"{len(entries)} lần đánh giá đã ghi",
                )
            )
    for prefix, name in (
        ("cal", "G03 hiệu chỉnh"),
        ("pol", "G04 chính sách"),
        ("stab", "G05 độ ổn định"),
    ):
        res, src = getattr(ctx.p02, prefix)
        out.append((res is not None, f"Kết quả {name} có sẵn", escape(src.name) if src else "—"))
    out.append(
        (None, "Dashboard không đọc tập test", "số test chỉ trích từ results/published.json")
    )
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
    for prefix, kind in (
        ("cal", "G03 hiệu chỉnh"),
        ("pol", "G04 chính sách"),
        ("stab", "G05 độ ổn định"),
    ):
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
    return table(
        [
            "Loại",
            "experiment_id (khoá cấu hình)",
            "execution_id (lần chạy gần nhất)",
            "Commit",
            "Lúc",
        ],
        rows,
        numeric_from=5,
    )


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


def tab_quality(ctx: Context) -> str:
    check_rows = [[status(ok, "đạt" if ok else ("không đạt" if ok is False else "ghi chú")),
                   escape(name), detail] for ok, name, detail in checks(ctx)]  # fmt: skip
    sim = ctx.p01.sim_manifest if ctx.p01 else None
    manifest = yaml.safe_load((ctx.repo / "datasets" / "manifests" / "ieee-cis.yaml")
                              .read_text("utf-8")) if (ctx.repo / "datasets" / "manifests" /
                                                       "ieee-cis.yaml").exists() else None  # fmt: skip  # noqa: E501
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
    return (
        card("Kiểm tra tự động", table(["Kết quả", "Kiểm tra", "Chi tiết"], check_rows,
                                       numeric_from=3))
        + card("Các lần chạy và mã nhận diện", runs_table(ctx),
               "experiment_id nhận diện cấu hình (cũng là khoá chặn test-một-lần); execution_id "
               "nhận diện từng lần chạy, kèm commit và môi trường (ADR 0010).")
        + card("Nguồn dữ liệu", table(["Nguồn", "Mã", "Mô tả", "Checksum"], data_rows,
                                      numeric_from=4) if data_rows else empty("Không có."))
        + card("Hạn chế: những gì dashboard này không chứng minh",
               "<ul class='limits'>" + "".join(f"<li>{x}</li>" for x in LIMITS) + "</ul>")
    )  # fmt: skip


# --- page -------------------------------------------------------------------------------------

TABS = [("overview", "Tổng quan"), ("p01", "Product 01 · Độ ổn định"),
        ("p02", "Product 02 · Gian lận"), ("quality", "Dữ liệu & chất lượng")]  # fmt: skip

CSS_PATH = Path(__file__).with_name("page.css")
JS_PATH = Path(__file__).with_name("page.js")


def build(artifacts: Path, git_sha: str = "", repo: Path = REPO_ROOT) -> str:
    """The whole page as HTML text."""
    ctx = load(artifacts, repo)
    built = datetime.now(UTC).astimezone(LOCAL).strftime("%d/%m/%Y %H:%M")
    sha = f" · commit <code>{escape(git_sha[:7])}</code>" if git_sha else ""
    tabs = "".join(
        f'<button role="tab" id="tab-{k}" aria-controls="panel-{k}" data-tab="{k}">{escape(v)}</button>'  # noqa: E501
        for k, v in TABS
    )
    bodies = {"overview": tab_overview(ctx), "p01": tab_p01(ctx), "p02": tab_p02(ctx),
              "quality": tab_quality(ctx)}  # fmt: skip
    panels = "".join(
        f'<section class="panel" role="tabpanel" id="panel-{k}" data-tab="{k}" '
        f'aria-labelledby="tab-{k}">'
        f'<h2 class="print-only">{escape(v)}</h2>{bodies[k]}</section>'
        for k, v in TABS
    )
    css, js = CSS_PATH.read_text("utf-8"), JS_PATH.read_text("utf-8")
    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Payment Intelligence Dashboard</title><style>{css}</style></head>
<body>
<header class="top"><div class="wrap">
<div class="brand"><h1>Payment Intelligence Ecosystem</h1>
<p>Dashboard tĩnh từ kết quả các lần chạy · dựng lúc {built}{sha} · không dùng dữ liệu thật</p></div>
<button class="theme" type="button" aria-label="Đổi giao diện sáng/tối">◐</button>
</div><nav class="wrap tabs" role="tablist">{tabs}</nav></header>
<main class="wrap">{panels}</main>
<div class="tooltip" role="status" hidden></div>
<script>{js}</script>
</body></html>
"""  # noqa: E501


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
