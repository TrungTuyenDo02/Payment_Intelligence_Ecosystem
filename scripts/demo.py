"""`make demo`: both products end to end, with live progress, result tables and a checklist.

- Product 01 (synthetic payments, TUNING simulation only): simulate -> load PostgreSQL -> KPI ->
  detectors -> dashboard. Needs PostgreSQL (KPIs are SQL views, ADR 0005); without it the
  product is skipped with a how-to. The report simulation (evaluated once) is never touched.
- Product 02 (IEEE-CIS, development data only): train the batch scorer, score the label-free
  validation sample. Skipped when the dataset is not on this machine.

The logic (run steps, read results, checks) is plain Python; only the `render_*` functions and
`main` draw with `rich` (ADR 0011). Exit code 1 if a check fails, 2 if a requested product
could not run.

Usage: python scripts/demo.py [--product all|01|02]
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_demo  # noqa: E402  (scripts/check_demo.py: published tuning numbers)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
DEMO_CONFIG = "shared/synthetic-generator/configs/demo.yaml"
SIM = check_demo.SIMULATION
DET = check_demo.DETECTION
DATASET = ROOT / "datasets" / "raw" / "ieee-cis" / "train_transaction.csv"
PY = sys.executable

P01 = ("Product 01", "Payment Reliability", "dữ liệu thanh toán giả lập, bộ tuning")
P02 = ("Product 02", "Fraud & Risk", "IEEE-CIS, chỉ dữ liệu phát triển")


@dataclass(frozen=True)
class Step:
    title: str
    args: list[str]
    output: str


STEPS_01 = [
    Step("Sinh dữ liệu giả lập (7 ngày, 3 provider, 4 sự cố cài sẵn)",
         ["-m", "synthetic_generator.cli", "--config", DEMO_CONFIG],
         f"artifacts/simulations/{SIM}/"),
    Step("Tạo bảng và view KPI trong PostgreSQL",
         ["-m", "synthetic_generator.ingest", "--init-db"], "PostgreSQL"),
    Step("Nạp sự kiện, kiểm tra contract payment-event",
         ["-m", "synthetic_generator.ingest", "--sim", SIM], "PostgreSQL: payment_events"),
    Step("Tính KPI 15 phút (SQL view → Parquet)",
         ["-m", "payment_reliability.cli", "kpi", "--sim", SIM], f"artifacts/kpi/{SIM}/"),
    Step("Chạy detector D-A, D-B và gộp thành sự cố",
         ["-m", "payment_reliability.cli", "detect"], f"artifacts/detections/{DET}/"),
    Step("Dựng dashboard HTML",
         ["-m", "dashboard.build"], "artifacts/dashboard/index.html"),
]  # fmt: skip
STEPS_02 = [
    Step("Huấn luyện bộ chấm điểm (GBM trên train, Platt trên V1)",
         ["-m", "fraud_risk.scoring.batch", "train"], "artifacts/models/score-…/"),
    Step("Chấm 2.000 giao dịch validation không nhãn",
         ["-m", "fraud_risk.scoring.batch", "score"], "artifacts/scores/exec-….csv"),
]  # fmt: skip

NO_DB = (
    "Không kết nối được PostgreSQL tại {host}:{port} ({err}).\n"
    "Product 01 cần PostgreSQL 16. Mở Docker Desktop rồi chạy [bold]make up[/] "
    "(lần đầu: copy .env.example .env). Xem docs/demo-guide.md."
)


# --- logic (no drawing) -----------------------------------------------------------------------


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


def vn(x: float, d: int = 3) -> str:
    """Number with a decimal comma, as in the Vietnamese reports."""
    return f"{x:.{d}f}".replace(".", ",")


def _last_json(text: str) -> dict[str, Any]:
    for line in reversed(text.strip().splitlines()):
        if line.startswith("{"):
            return json.loads(line)
    raise ValueError("no JSON line in output")


@dataclass
class Result:
    """What one product produced: facts and rows to show, checks as (ok, text)."""

    facts: list[tuple[str, str]] = field(default_factory=list)
    rows: list[list[Any]] = field(default_factory=list)
    checks: list[tuple[bool, str]] = field(default_factory=list)


def results_01(outputs: dict[str, str]) -> Result:
    """Per-anomaly rows, load facts and the Product 01 checks."""
    load = _last_json(outputs["3"])
    sim_dir, det_dir = ARTIFACTS / "simulations" / SIM, ARTIFACTS / "detections" / DET
    labels = json.loads((sim_dir / "anomaly_labels.json").read_text("utf-8"))
    ev = json.loads((det_dir / "evaluation.json").read_text("utf-8"))
    per = {d: {a["anomaly_id"]: a for a in r["anomalies"]} for d, r in ev["detectors"].items()}
    res = Result()
    res.facts = [
        ("Sự kiện đã đọc", f"{load['rows_read']:,}".replace(",", ".")),
        ("Mới / đã có / bị từ chối",
         f"{load['rows_accepted']} / {load['rows_duplicate']} / {load['rows_rejected']}"),
    ]  # fmt: skip
    for det, name in (("pooled", "D-B (chính)"), ("robust_z", "D-A (cơ sở)")):
        r = ev["detectors"][det]
        res.facts.append((name, f"bắt {r['detected']}/{len(r['anomalies'])} sự cố, "
                                f"{vn(r['false_per_day'], 1)} báo nhầm/ngày"))  # fmt: skip
    for lab in labels:
        target = lab["provider_id"] or lab["payment_method"] or lab["error_code"] or "ALL"
        b, a = per["pooled"][lab["anomaly_id"]], per["robust_z"][lab["anomaly_id"]]
        res.rows.append([
            lab["anomaly_id"], lab["type"], f"x{lab['magnitude']:g}".replace(".", ","), target,
            (b["detected"], b["delay_minutes"]), (a["detected"], a["delay_minutes"]),
        ])  # fmt: skip

    _, problems = check_demo.check(ARTIFACTS)
    res.checks = [(load["rows_rejected"] == 0, "Mọi sự kiện qua kiểm tra contract")]
    for det, (found, per_day) in check_demo.EXPECTED.items():
        bad = [p for p in problems if p.startswith(det)]
        res.checks.append((not bad, f"{check_demo.NAMES[det]} khớp số công bố "
                                    f"({found}/4, {per_day:g} báo nhầm/ngày)"))  # fmt: skip
    res.checks.append(((ARTIFACTS / "dashboard" / "index.html").is_file(), "Dashboard đã dựng"))
    return res


def results_02(outputs: dict[str, str]) -> Result:
    """Score summary, top transactions and the Product 02 checks."""
    summary = _last_json(outputs["2"])
    scores_path = Path(summary["scores"])
    scores_path = scores_path if scores_path.is_absolute() else ROOT / scores_path
    model_dir = ARTIFACTS / "models" / summary["model_version"]
    with scores_path.open(encoding="utf-8") as fh:
        scored = list(csv.DictReader(fh))
    with (model_dir / "sample_v3.csv").open(encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        has_label = "isFraud" in (reader.fieldnames or [])
        info = {r["TransactionID"]: r for r in reader}
    probs = [float(r["score_calibrated"]) for r in scored]
    res = Result()
    res.facts = [
        ("Mô hình", summary["model_version"]),
        ("Lần chấm", summary["execution_id"]),
        ("Giao dịch đã chấm", str(summary["rows"])),
        ("Xác suất gian lận trung bình", vn(sum(probs) / max(len(probs), 1))),
        ("Xác suất ≥ 0,5", f"{sum(p >= 0.5 for p in probs)} giao dịch"),
        ("File kết quả", scores_path.relative_to(ROOT).as_posix()),
    ]
    for r in sorted(scored, key=lambda r: float(r["score_calibrated"]), reverse=True)[:5]:
        t = info.get(r["TransactionID"], {})
        amt = vn(float(t["TransactionAmt"]), 2) if t.get("TransactionAmt") else "?"
        res.rows.append([r["TransactionID"], amt, t.get("ProductCD", "?"),
                         vn(float(r["score"])), vn(float(r["score_calibrated"]))])  # fmt: skip
    skew = summary["skew_check"]
    res.checks = [
        (True, "Mô hình tái tạo PR-AUC validation của Stage E"),
        (not has_label, "Đầu vào chấm điểm không có cột nhãn isFraud"),
        (skew["rows_compared"] == summary["rows"] and skew["max_abs_diff"] == 0.0,
         f"Điểm theo lô trùng điểm lúc huấn luyện ({skew['rows_compared']} dòng)"),
    ]  # fmt: skip
    return res


# --- drawing (rich) ---------------------------------------------------------------------------


def _detected(cell: tuple[bool, float | None]) -> Text:
    found, delay = cell
    if found and delay is not None:
        return Text(f"✓ sau {delay:.0f} phút", style="green")
    return Text("✗ trượt", style="red")


def _facts(rows: list[tuple[str, str]]) -> Table:
    t = Table.grid(padding=(0, 2))
    t.add_column(style="dim")
    t.add_column(style="bold")
    for k, v in rows:
        t.add_row(k, v)
    return t


def render_01(console: Console, res: Result) -> None:
    t = Table(box=box.ROUNDED, header_style="bold", title="Sự cố cài sẵn và detector",
              title_style="bold", title_justify="left")  # fmt: skip
    for col in ("Mã", "Loại", "Mức", "Đối tượng", "D-B (chính)", "D-A (cơ sở)"):
        t.add_column(col)
    for aid, kind, mag, target, b, a in res.rows:
        t.add_row(aid, kind, mag, target, _detected(b), _detected(a))
    note = Text("Sự cố x1,5 nằm dưới giới hạn phát hiện; trượt là có chủ đích.", style="dim")
    console.print(Panel(Group(_facts(res.facts), Text(), t, note), box=box.ROUNDED,
                        title="[bold]Kết quả Product 01", title_align="left",
                        border_style="cyan"))  # fmt: skip


def render_02(console: Console, res: Result) -> None:
    t = Table(box=box.ROUNDED, header_style="bold", title="5 giao dịch rủi ro nhất",
              title_style="bold", title_justify="left")  # fmt: skip
    t.add_column("TransactionID")
    t.add_column("Số tiền", justify="right")
    t.add_column("ProductCD", justify="center")
    t.add_column("Điểm gốc", justify="right", style="dim")
    t.add_column("Xác suất", justify="right", style="bold magenta")
    for row in res.rows:
        t.add_row(*row)
    note = Text("Điểm gốc chỉ để xếp hạng; xác suất là điểm đã hiệu chỉnh trên V1. "
                "Danh sách chỉ để minh hoạ, không phải quyết định chặn.", style="dim")  # fmt: skip
    console.print(Panel(Group(_facts(res.facts), Text(), t, note), box=box.ROUNDED,
                        title="[bold]Kết quả Product 02", title_align="left",
                        border_style="magenta"))  # fmt: skip


def run_product(
    console: Console, product: tuple[str, str, str], steps: list[Step],
    progress: Progress, overall: Any,
) -> dict[str, str] | None:  # fmt: skip
    """Run the steps of one product with a live spinner; outputs keyed by step index, or None."""
    code, name, note = product
    console.print()
    console.print(Rule(f"[bold]{code} · {name}[/] [dim]{note}", align="left", style="dim"))
    outputs: dict[str, str] = {}
    for i, step in enumerate(steps, start=1):
        task = progress.add_task(f"  {code} · bước {i}/{len(steps)}: {step.title}", total=None)
        ok, out, seconds = run_step(step.args)
        progress.remove_task(task)
        progress.advance(overall)
        if not ok:
            console.print(f"  [red]✗[/] {i}/{len(steps)}  {step.title}  "
                          f"[red]THẤT BẠI[/] sau {seconds:.0f} giây")  # fmt: skip
            tail = "\n".join(out.strip().splitlines()[-12:])
            console.print(Panel(Text(tail or "(không có thông báo)"), title="Cuối thông báo lỗi",
                                border_style="red", box=box.ROUNDED))  # fmt: skip
            return None
        outputs[str(i)] = out
        console.print(f"  [green]✓[/] {i}/{len(steps)}  {step.title:<58}"
                      f"[dim]{vn(seconds, 1):>5} s  → {step.output}[/]")  # fmt: skip
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Demo of both products")
    parser.add_argument("--product", choices=["all", "01", "02"], default="all")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    console = Console(highlight=False)
    console.width = min(console.width, 110)  # readable on wide screens

    want01, want02 = args.product in ("all", "01"), args.product in ("all", "02")
    skipped: list[str] = []
    db = database_problem() if want01 else None
    plan = Table.grid(padding=(0, 2))
    for wanted, (code, name, note), ready, why in (
        (want01, P01, not db, "thiếu PostgreSQL"),
        (want02, P02, DATASET.is_file(), "thiếu dataset IEEE-CIS (không nằm trong git)"),
    ):
        if wanted:
            status = "[green]● sẵn sàng[/]" if ready else f"[yellow]○ bỏ qua: {why}[/]"
            plan.add_row(f"[bold]{code}[/]", name, f"[dim]{note}[/]", status)
    console.print(Panel(plan, title="[bold]Payment Intelligence Ecosystem · make demo",
                        title_align="left", subtitle="[dim]đánh giá trung thực · tái lập được",
                        subtitle_align="right", box=box.ROUNDED,
                        border_style="blue"))  # fmt: skip
    if want01 and db:
        console.print(Panel(db, title="Product 01 bị bỏ qua", border_style="yellow"))
        skipped.append("Product 01 (thiếu PostgreSQL)")
        want01 = False
    if want02 and not DATASET.is_file():
        want02 = False
        if args.product == "02":
            skipped.append("Product 02 (thiếu dataset)")

    checks: list[tuple[bool, str]] = []
    failed = False
    results: list[tuple[Any, Result]] = []
    progress = Progress(
        SpinnerColumn(), TextColumn("{task.description}"), BarColumn(bar_width=20),
        TaskProgressColumn(), MofNCompleteColumn(), TimeElapsedColumn(),
        console=console, transient=True,
    )  # fmt: skip
    with progress:
        overall = progress.add_task(
            "[bold]Tổng tiến độ", total=len(STEPS_01) * want01 + len(STEPS_02) * want02
        )
        for wanted, product, steps, compute, render in (
            (want01, P01, STEPS_01, results_01, render_01),
            (want02, P02, STEPS_02, results_02, render_02),
        ):
            if not wanted:
                continue
            out = run_product(console, product, steps, progress, overall)
            if out is None:
                failed = True
                checks.append((False, f"{product[0]} chạy hết các bước"))
                continue
            res = compute(out)
            results.append((render, res))
            checks += res.checks

    for render, res in results:
        console.print()
        render(console, res)

    table = Table.grid(padding=(0, 1))
    for ok, text in checks:
        table.add_row("[green]✓[/]" if ok else "[red]✗[/]", text)
    for text in skipped:
        table.add_row("[yellow]–[/]", f"Bỏ qua: {text}")
    passed = sum(ok for ok, _ in checks)
    good = not failed and passed == len(checks)
    verdict = f"{passed}/{len(checks)} kiểm tra đạt" + (
        f" · {len(skipped)} phần bỏ qua" if skipped else ""
    )
    dashboard = ARTIFACTS / "dashboard" / "index.html"
    lines = [table, Text()]
    lines.append(Text(verdict, style="bold green" if good else "bold red"))
    if dashboard.is_file():
        lines.append(Text.from_markup(f"Dashboard: [link={dashboard.as_uri()}]{dashboard}[/link]"
                                      " [dim](mở bằng trình duyệt)[/]"))  # fmt: skip
    border = "red" if not good else ("yellow" if skipped else "green")
    console.print()
    console.print(Panel(Group(*lines), title="[bold]Kiểm tra", title_align="left",
                        box=box.ROUNDED, border_style=border))  # fmt: skip
    if not good:
        return 1
    return 2 if skipped else 0


if __name__ == "__main__":
    sys.exit(main())
