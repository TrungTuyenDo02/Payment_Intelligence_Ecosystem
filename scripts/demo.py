"""`make demo`: both products end to end, with progress, results and checks in the terminal.

- Product 01 (synthetic payments, TUNING simulation only): simulate -> load PostgreSQL -> KPI ->
  detectors -> dashboard. Needs PostgreSQL (KPIs are SQL views, ADR 0005); without it the
  product is skipped with a how-to. The report simulation (evaluated once) is never touched.
- Product 02 (IEEE-CIS, development data only): train the batch scorer, score the label-free
  validation sample. Skipped when the dataset is not on this machine.

Each step shows the product, a progress bar over all steps and where its output goes. The run
ends with a table of results per product and a checklist; exit code 1 if a check fails,
2 if a requested product could not run.

Usage: python scripts/demo.py [--product all|01|02]
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_demo  # noqa: E402  (scripts/check_demo.py: published tuning numbers)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
DEMO_CONFIG = "shared/synthetic-generator/configs/demo.yaml"
SIM = check_demo.SIMULATION
DET = check_demo.DETECTION
DATASET = ROOT / "datasets" / "raw" / "ieee-cis" / "train_transaction.csv"
PY = sys.executable
BAR = 24

P01 = "Product 01 — Payment Reliability (dữ liệu thanh toán giả lập)"
P02 = "Product 02 — Fraud & Risk (IEEE-CIS, chỉ dữ liệu phát triển)"

STEPS_01 = [
    ("Sinh dữ liệu giả lập: 7 ngày, 3 provider, 20 merchant, 4 sự cố cài sẵn",
     ["-m", "synthetic_generator.cli", "--config", DEMO_CONFIG],
     f"artifacts/simulations/{SIM}/"),
    ("Tạo bảng và view KPI trong PostgreSQL",
     ["-m", "synthetic_generator.ingest", "--init-db"],
     "PostgreSQL: payment_events, kpi_*"),
    ("Nạp sự kiện vào PostgreSQL, kiểm tra từng dòng theo contract payment-event",
     ["-m", "synthetic_generator.ingest", "--sim", SIM],
     "PostgreSQL: payment_events"),
    ("Tính KPI 15 phút bằng view SQL, xuất Parquet",
     ["-m", "payment_reliability.cli", "kpi", "--sim", SIM],
     f"artifacts/kpi/{SIM}/"),
    ("Chạy hai detector (D-A z-score, D-B gộp cửa sổ), gộp cảnh báo thành sự cố",
     ["-m", "payment_reliability.cli", "detect"],
     f"artifacts/detections/{DET}/"),
    ("Dựng dashboard HTML cho cả hai sản phẩm",
     ["-m", "dashboard.build"],
     "artifacts/dashboard/index.html"),
]  # fmt: skip
STEPS_02 = [
    ("Huấn luyện bộ chấm điểm: Gradient Boosting trên train, hiệu chỉnh Platt trên V1",
     ["-m", "fraud_risk.scoring.batch", "train"],
     "artifacts/models/score-…/"),
    ("Chấm điểm 2.000 giao dịch validation không nhãn (sample_v3.csv)",
     ["-m", "fraud_risk.scoring.batch", "score"],
     "artifacts/scores/exec-….csv"),
]  # fmt: skip

NO_DB = """Không kết nối được PostgreSQL tại {host}:{port} ({err}).
Product 01 cần PostgreSQL 16. Cách bật: mở Docker Desktop, rồi chạy `make up`
(lần đầu: copy .env.example .env). Xem docs/demo-guide.md."""


class Progress:
    """Progress bar over every step of the run."""

    def __init__(self, total: int) -> None:
        self.total, self.done = total, 0

    def line(self, product: str, i: int, n: int, what: str) -> str:
        pct = round(100 * self.done / self.total) if self.total else 100
        fill = round(BAR * self.done / self.total) if self.total else BAR
        return f"[{'█' * fill}{'░' * (BAR - fill)}] {pct:3d}% | {product} | bước {i}/{n}: {what}"


def database_problem() -> str | None:
    """None if PostgreSQL answers, else a how-to message."""
    import psycopg

    try:
        from synthetic_generator.ingest import connect

        with connect() as conn:
            conn.execute("SELECT 1")
    except psycopg.Error as err:
        first = str(err).strip().splitlines()[0] if str(err).strip() else type(err).__name__
        return NO_DB.format(
            host=os.environ.get("POSTGRES_HOST") or "127.0.0.1",
            port=os.environ.get("POSTGRES_PORT") or "5432",
            err=first,
        )
    return None


def run_step(args: list[str]) -> tuple[bool, str, float]:
    """Run one step as a child process; (ok, output, seconds)."""
    started = time.monotonic()
    proc = subprocess.run(
        [PY, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"}, cwd=ROOT,
    )  # fmt: skip
    return proc.returncode == 0, proc.stdout + proc.stderr, time.monotonic() - started


def run_product(
    name: str, steps: list[tuple[str, list[str], str]], bar: Progress
) -> dict[str, str] | None:
    """Run the steps of one product; their last output lines keyed by step index, or None."""
    print(f"\n=== {name} ===", flush=True)
    outputs: dict[str, str] = {}
    for i, (what, args, where) in enumerate(steps, start=1):
        print(bar.line(name.split(" —")[0], i, len(steps), what), flush=True)
        ok, out, seconds = run_step(args)
        bar.done += 1
        if not ok:
            print(f"      ✗ THẤT BẠI sau {seconds:.0f} giây. Cuối thông báo lỗi:", file=sys.stderr)
            for line in out.strip().splitlines()[-12:]:
                print(f"      | {line}", file=sys.stderr)
            return None
        outputs[str(i)] = out
        print(f"      ✓ xong trong {seconds:.0f} giây → {where}", flush=True)
    return outputs


def _last_json(text: str) -> dict:
    for line in reversed(text.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise ValueError("no JSON line in output")


def vn(x: float, d: int = 3) -> str:
    """Number with a decimal comma, as in the Vietnamese reports."""
    return f"{x:.{d}f}".replace(".", ",")


def _yes(found: bool, delay: float | None) -> str:
    return f"✓ bắt, sau {delay:.0f} phút" if found and delay is not None else "✗ trượt"


def report_01(outputs: dict[str, str]) -> list[tuple[bool, str]]:
    """Per-anomaly table and the Product 01 checks."""
    load = _last_json(outputs["3"])
    sim_dir, det_dir = ARTIFACTS / "simulations" / SIM, ARTIFACTS / "detections" / DET
    labels = json.loads((sim_dir / "anomaly_labels.json").read_text("utf-8"))
    ev = json.loads((det_dir / "evaluation.json").read_text("utf-8"))
    per = {d: {a["anomaly_id"]: a for a in r["anomalies"]} for d, r in ev["detectors"].items()}

    print("\n--- Kết quả Product 01 ---")
    print(f"Nạp: {load['rows_read']} sự kiện; {load['rows_accepted']} mới, "
          f"{load['rows_duplicate']} đã có từ lần trước, "
          f"{load['rows_rejected']} bị từ chối")  # fmt: skip
    print(f"{'Sự cố cài sẵn':<44} {'D-B (chính)':<22} {'D-A (đường cơ sở)'}")
    for lab in labels:
        target = lab["provider_id"] or lab["payment_method"] or lab["error_code"] or "ALL"
        mag = f"{lab['magnitude']:g}".replace(".", ",")
        name = f"{lab['anomaly_id']} {lab['type']} x{mag} ({target})"
        b, a = per["pooled"][lab["anomaly_id"]], per["robust_z"][lab["anomaly_id"]]
        print(f"{name:<44} {_yes(b['detected'], b['delay_minutes']):<22} "
              f"{_yes(a['detected'], a['delay_minutes'])}")  # fmt: skip
    for det, label in (("pooled", "D-B"), ("robust_z", "D-A")):
        r = ev["detectors"][det]
        print(f"{label}: bắt {r['detected']}/{len(r['anomalies'])} sự cố, "
              f"{vn(r['false_per_day'], 1)} báo nhầm/ngày")  # fmt: skip

    _, problems = check_demo.check(ARTIFACTS)
    checks = [(load["rows_rejected"] == 0, "Mọi sự kiện qua kiểm tra contract (0 dòng bị từ chối)")]
    for det, (found, per_day) in check_demo.EXPECTED.items():
        bad = [p for p in problems if p.startswith(det)]
        checks.append((not bad, f"{check_demo.NAMES[det]} khớp số công bố "
                                f"({found}/4, {per_day:g} báo nhầm/ngày)"))  # fmt: skip
    checks.append(((ARTIFACTS / "dashboard" / "index.html").is_file(), "Dashboard đã dựng"))
    return checks


def report_02(outputs: dict[str, str]) -> list[tuple[bool, str]]:
    """Score summary, top transactions and the Product 02 checks."""
    summary = _last_json(outputs["2"])
    scores_path = ROOT / summary["scores"] if not Path(summary["scores"]).is_absolute() \
        else Path(summary["scores"])  # fmt: skip
    model_dir = ARTIFACTS / "models" / summary["model_version"]
    with scores_path.open(encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    with (model_dir / "sample_v3.csv").open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        has_label = "isFraud" in (reader.fieldnames or [])
        info = {r["TransactionID"]: r for r in reader}
    cal = sorted(rows, key=lambda r: float(r["score_calibrated"]), reverse=True)
    mean = sum(float(r["score_calibrated"]) for r in rows) / max(len(rows), 1)

    print("\n--- Kết quả Product 02 ---")
    print(f"Mô hình {summary['model_version']}, lần chấm {summary['execution_id']}: "
          f"{summary['rows']} giao dịch → {scores_path.relative_to(ROOT)}")  # fmt: skip
    print(f"Xác suất gian lận trung bình (đã hiệu chỉnh): {vn(mean)}; "
          f"≥ 0,5: {sum(float(r['score_calibrated']) >= 0.5 for r in rows)} giao dịch")  # fmt: skip
    print("5 giao dịch rủi ro nhất (để minh hoạ, không phải quyết định chặn):")
    print(f"  {'TransactionID':<14} {'TransactionAmt':>14} {'ProductCD':<9} {'Điểm gốc':>9} "
          f"{'Xác suất':>9}")  # fmt: skip
    for r in cal[:5]:
        t = info.get(r["TransactionID"], {})
        amt = vn(float(t["TransactionAmt"]), 2) if t.get("TransactionAmt") else "?"
        print(f"  {r['TransactionID']:<14} {amt:>14} {t.get('ProductCD', '?'):<9} "
              f"{vn(float(r['score'])):>9} {vn(float(r['score_calibrated'])):>9}")  # fmt: skip

    skew = summary["skew_check"]
    return [
        (True, "Mô hình tái tạo PR-AUC validation của Stage E (kiểm tra lúc huấn luyện)"),
        (not has_label, "Đầu vào chấm điểm không có cột nhãn isFraud"),
        (skew["rows_compared"] == summary["rows"] and skew["max_abs_diff"] == 0.0,
         f"Điểm theo lô trùng điểm lúc huấn luyện ({skew['rows_compared']} dòng, "
         f"chênh lớn nhất {vn(skew['max_abs_diff'] or 0.0, 1)})"),
    ]  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Demo of both products")
    parser.add_argument("--product", choices=["all", "01", "02"], default="all")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    want01, want02 = args.product in ("all", "01"), args.product in ("all", "02")
    skipped: list[str] = []
    db = database_problem() if want01 else None
    if want01 and db:
        print(f"\n=== {P01} ===\n✗ BỎ QUA. {db}", file=sys.stderr)
        skipped.append("Product 01 (thiếu PostgreSQL)")
        want01 = False
    if want02 and not DATASET.is_file():
        print(f"\n=== {P02} ===\n– BỎ QUA: không có {DATASET.relative_to(ROOT)} trên máy này "
              "(dataset do chủ dự án tải từ Kaggle, không nằm trong git).")  # fmt: skip
        want02 = False
        if args.product == "02":
            skipped.append("Product 02 (thiếu dataset)")

    bar = Progress(len(STEPS_01) * want01 + len(STEPS_02) * want02)
    checks: list[tuple[bool, str]] = []
    failed = False
    if want01:
        out = run_product(P01, STEPS_01, bar)
        checks += report_01(out) if out is not None else [(False, "Product 01 chạy hết các bước")]
        failed |= out is None
    if want02:
        out = run_product(P02, STEPS_02, bar)
        checks += report_02(out) if out is not None else [(False, "Product 02 chạy hết các bước")]
        failed |= out is None

    print(f"\n[{'█' * BAR}] 100% | Kiểm tra")
    for ok, text in checks:
        print(f"  {'✓' if ok else '✗'} {text}")
    for text in skipped:
        print(f"  – Bỏ qua: {text}")
    passed = sum(ok for ok, _ in checks)
    print(f"\nTổng kết: {passed}/{len(checks)} kiểm tra đạt" + (f", {len(skipped)} phần bỏ qua"
                                                                if skipped else ""))  # fmt: skip
    if (ARTIFACTS / "dashboard" / "index.html").is_file():
        print(f"Dashboard: {ARTIFACTS / 'dashboard' / 'index.html'} (mở bằng trình duyệt)")
    if failed or passed < len(checks):
        return 1
    return 2 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
