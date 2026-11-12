"""`make demo`: Product 01 end to end, one step at a time, on the TUNING simulation only.

Checks PostgreSQL first (KPIs are SQL views, ADR 0005) and stops with a short how-to if it is
missing, instead of a long traceback. Each step says what it does and where its output goes.
The run must reproduce the published tuning numbers (scripts/check_demo.py); the report
simulation (evaluated once) is never generated, loaded or scored here.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEMO_CONFIG = "shared/synthetic-generator/configs/demo.yaml"
SIM = "sim-485cacc9c858"
DET = "det-3ddc26cff253"
PY = sys.executable

STEPS = [
    (
        "Sinh dữ liệu giả lập: 7 ngày, 3 provider, 20 merchant, 4 sự cố cài sẵn (demo.yaml)",
        ["-m", "synthetic_generator.cli", "--config", DEMO_CONFIG],
        f"artifacts/simulations/{SIM}/ (events.jsonl, anomaly_labels.json)",
    ),
    (
        "Tạo bảng và view KPI trong PostgreSQL (chạy lại nhiều lần vẫn an toàn)",
        ["-m", "synthetic_generator.ingest", "--init-db"],
        "PostgreSQL: bảng payment_events, view kpi_provider_15m, kpi_errors_15m, kpi_method_15m",
    ),
    (
        "Nạp sự kiện vào PostgreSQL, kiểm tra từng dòng theo contract payment-event",
        ["-m", "synthetic_generator.ingest", "--sim", SIM],
        "PostgreSQL: bảng payment_events (nạp lại không tạo dòng trùng)",
    ),
    (
        "Tính KPI 15 phút bằng view SQL và xuất ra Parquet",
        ["-m", "payment_reliability.cli", "kpi", "--sim", SIM],
        f"artifacts/kpi/{SIM}/ (provider_15m, errors_15m, method_15m .parquet)",
    ),
    (
        "Chạy hai detector (D-A z-score, D-B gộp cửa sổ), gộp cảnh báo thành sự cố, chấm với nhãn",
        ["-m", "payment_reliability.cli", "detect"],
        f"artifacts/detections/{DET}/ (evaluation.json, incidents.json, scores.parquet)",
    ),
    (
        "So với số đã công bố cho bộ tuning",
        [str(ROOT / "scripts" / "check_demo.py")],
        "chỉ in ra màn hình",
    ),
    (
        "Dựng dashboard HTML tĩnh cho cả hai sản phẩm",
        ["-m", "dashboard.build"],
        "artifacts/dashboard/index.html",
    ),
]

NO_DB = """
Không kết nối được PostgreSQL tại {host}:{port} (user {user}, database {db}).
Lỗi: {err}

Demo Product 01 cần PostgreSQL 16, vì KPI được tính bằng SQL view (ADR 0005).
Cách có PostgreSQL:
  1. Cài Docker Desktop, mở nó lên, rồi chạy:
       copy .env.example .env      (PowerShell; Git Bash: cp .env.example .env)
       make up                     (bật PostgreSQL 16 trong Docker)
       make demo
  2. Hoặc dùng một PostgreSQL 16 có sẵn: khai POSTGRES_HOST, POSTGRES_PORT, POSTGRES_USER,
     POSTGRES_PASSWORD, POSTGRES_DB trong file .env, rồi chạy lại make demo.

Không có PostgreSQL vẫn chạy được:
  make simulate                     (chỉ bước 1: sinh dữ liệu)
  make score-model && make score    (Product 02, cần dataset IEEE-CIS)
"""


def database_problem() -> str | None:
    """None if PostgreSQL answers, else a how-to message."""
    import psycopg

    try:
        from synthetic_generator.ingest import connect

        with connect() as conn:
            conn.execute("SELECT 1")
    except psycopg.Error as err:
        return NO_DB.format(
            host=os.environ.get("POSTGRES_HOST") or "127.0.0.1",
            port=os.environ.get("POSTGRES_PORT") or "5432",
            user=os.environ.get("POSTGRES_USER") or "pie",
            db=os.environ.get("POSTGRES_DB") or "pie",
            err=str(err).strip().splitlines()[0] if str(err).strip() else type(err).__name__,
        )
    return None


def explain(args: list[str], out: str) -> list[str]:
    """Short human reading of a step's output (falls back to the raw lines)."""
    lines = [line for line in out.strip().splitlines() if line.strip()]
    if "--sim" in args and "synthetic_generator.ingest" in args and lines:
        try:
            c = json.loads(lines[-1])
            return [
                f"đọc {c['rows_read']} dòng: {c['rows_accepted']} dòng mới, "
                f"{c['rows_duplicate']} dòng đã có từ lần trước (bỏ qua), "
                f"{c['rows_rejected']} dòng bị từ chối"
            ]
        except (ValueError, KeyError):
            pass
    return lines[-8:]


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    print("== Demo Product 01: độ ổn định thanh toán (dữ liệu giả lập, bộ tuning) ==")
    print("Kiểm tra PostgreSQL ...", flush=True)
    problem = database_problem()
    if problem:
        print(problem, file=sys.stderr)
        return 2
    print("PostgreSQL sẵn sàng.\n")

    total = len(STEPS)
    for i, (what, args, where) in enumerate(STEPS, start=1):
        print(f"[{i}/{total}] {what}", flush=True)
        started = time.monotonic()
        proc = subprocess.run(
            [PY, *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
            env={**os.environ, "PYTHONIOENCODING": "utf-8"}, cwd=ROOT,
        )  # fmt: skip
        seconds = time.monotonic() - started
        if proc.returncode != 0:
            failed = f"THẤT BẠI sau {seconds:.0f} giây (mã lỗi {proc.returncode})."
            print(f"      {failed}", file=sys.stderr)
            for line in (proc.stdout + proc.stderr).strip().splitlines()[-15:]:
                print(f"      | {line}", file=sys.stderr)
            return 1
        for line in explain(args, proc.stdout):
            print(f"      {line}")
        print(f"      → kết quả: {where}  ({seconds:.0f} giây)\n", flush=True)

    dashboard = ROOT / "artifacts" / "dashboard" / "index.html"
    print("== Xong ==")
    print(f"Mở dashboard bằng trình duyệt: {dashboard}")
    print("Phần Product 02 của dashboard chỉ có số khi máy đã có artifacts/runs/ (xem README).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
