"""`make ingest SIM=<simulation_id>`: load events.jsonl into PostgreSQL (Stage C spec section 6)."""

import argparse
import hashlib
import json
import os
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
import yaml
from psycopg.types.json import Jsonb

from synthetic_generator.cli import REPO_ROOT, load_contract_rules

SCHEMA_DIR = REPO_ROOT / "infrastructure" / "database"
SHARED_FIELDS = ("merchant_id", "amount", "payment_method", "currency")
PAYLOAD_COLUMNS = (
    "payment_id",
    "attempt_id",
    "attempt_number",
    "provider_id",
    "merchant_id",
    "payment_method",
    "amount",
    "currency",
    "status",
    "error_code",
    "latency_ms",
)
ENVELOPE_COLUMNS = (
    "event_id",
    "event_type",
    "schema_version",
    "event_time",
    "source_system",
    "simulation_id",
)


class IngestError(RuntimeError):
    """The whole batch is refused (nothing is written)."""


@dataclass
class Reject:
    line_number: int
    raw_line: str
    reasons: list[str]
    event_id: str | None = None
    payment_id: str | None = None


@dataclass
class Batch:
    accepted: list[dict[str, Any]] = field(default_factory=list)
    rejects: list[Reject] = field(default_factory=list)


def cross_attempt_errors(attempts: list[dict[str, Any]]) -> list[str]:
    """Contract 1.0.0 rules across the attempts (payloads) of one payment."""
    errors = []
    numbers = sorted(a["attempt_number"] for a in attempts)
    if len(set(numbers)) != len(numbers):
        errors.append("duplicate (payment_id, attempt_number)")
    if numbers != list(range(1, len(numbers) + 1)):
        errors.append(f"attempt_number not consecutive from 1: {numbers}")
    for name in SHARED_FIELDS:
        if len({a[name] for a in attempts}) > 1:
            errors.append(f"{name} differs between attempts")
    ordered = sorted(attempts, key=lambda a: a["attempt_number"])
    statuses = [a["status"] for a in ordered]
    if statuses.count("SUCCESS") > 1:
        errors.append("more than one SUCCESS")
    elif "SUCCESS" in statuses[:-1]:
        errors.append("attempt after SUCCESS")
    return errors


def check_batch(lines: list[str], simulation_id: str) -> Batch:
    """Split lines into accepted events and rejects; a payment is accepted or rejected whole."""
    rules = load_contract_rules()
    validator = rules.load_validator()
    batch = Batch()
    valid: list[tuple[int, str, dict[str, Any]]] = []
    seen_ids: set[str] = set()
    bad_payments: dict[str, str] = {}  # payment_id -> reason for its other attempts
    for no, line in enumerate(lines, start=1):
        try:
            event = json.loads(line)
        except json.JSONDecodeError as err:
            batch.rejects.append(Reject(no, line, [f"not JSON: {err.msg}"]))
            continue
        if not isinstance(event, dict):
            batch.rejects.append(Reject(no, line, ["not a JSON object"]))
            continue
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        event_id, payment_id = event.get("event_id"), payload.get("payment_id")
        event_id = event_id if isinstance(event_id, str) else None
        payment_id = payment_id if isinstance(payment_id, str) else None
        reasons = rules.validate_event(event, validator)
        if event.get("simulation_id") != simulation_id:
            reasons.append(f"simulation_id is not {simulation_id}")
        if event_id in seen_ids:
            reasons.append("duplicate event_id in file")
        if event_id:
            seen_ids.add(event_id)
        if reasons:
            batch.rejects.append(Reject(no, line, reasons, event_id, payment_id))
            if payment_id:
                bad_payments[payment_id] = (
                    f"another attempt of this payment was rejected (line {no})"
                )
            continue
        valid.append((no, line, event))

    by_payment: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for _, _, event in valid:
        by_payment[event["payload"]["payment_id"]].append(event["payload"])
    for pid, attempts in by_payment.items():
        errors = [] if pid in bad_payments else cross_attempt_errors(attempts)
        if errors:
            bad_payments[pid] = "; ".join(errors)

    for no, line, event in valid:
        pid = event["payload"]["payment_id"]
        if pid in bad_payments:
            reason = f"payment rejected: {bad_payments[pid]}"
            batch.rejects.append(Reject(no, line, [reason], event["event_id"], pid))
        else:
            batch.accepted.append(event)
    batch.rejects.sort(key=lambda r: r.line_number)
    return batch


def connect() -> psycopg.Connection:
    """Connection from POSTGRES_* variables; defaults match compose.yaml."""
    return psycopg.connect(
        host=(os.environ.get("POSTGRES_HOST") or "127.0.0.1"),
        port=int(os.environ.get("POSTGRES_PORT") or "5432"),
        user=(os.environ.get("POSTGRES_USER") or "pie"),
        password=(os.environ.get("POSTGRES_PASSWORD") or "change-me-local-only"),
        dbname=(os.environ.get("POSTGRES_DB") or "pie"),
        connect_timeout=5,
    )


def schema_files() -> list[Path]:
    """SQL files in number order: 001 tables (Stage C), 002 KPI views (Stage D), ..."""
    return sorted(SCHEMA_DIR.glob("[0-9][0-9][0-9]_*.sql"))


def init_db(conn: psycopg.Connection) -> list[str]:
    """Run every schema file (each is idempotent); return the file names."""
    files = schema_files()
    for path in files:
        conn.execute(path.read_text("utf-8"))
    conn.commit()
    return [p.name for p in files]


def ingest(conn: psycopg.Connection, sim_dir: Path) -> dict[str, Any]:
    """Load one simulation folder in a single transaction; return the run counts."""
    events_path = sim_dir / "events.jsonl"
    data = events_path.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    manifest = yaml.safe_load((sim_dir / "simulation_manifest.yaml").read_text("utf-8"))
    sid = manifest["simulation_id"]
    if manifest["events_sha256"] != sha:
        raise IngestError(f"{events_path}: checksum does not match simulation_manifest.yaml")

    with conn.transaction():
        previous = conn.execute(
            "SELECT DISTINCT events_sha256 FROM ingestion_runs WHERE simulation_id = %s", (sid,)
        ).fetchall()
        if any(row[0] != sha for row in previous):
            raise IngestError(
                f"{sid} was loaded before from a different events.jsonl (checksum changed); "
                "refusing to mix two versions (spec decision 9)"
            )
        batch = check_batch(data.decode("utf-8").splitlines(), sid)
        run_id = conn.execute(
            "INSERT INTO ingestion_runs (simulation_id, source_file, events_sha256, rows_read,"
            " rows_accepted, rows_duplicate, rows_rejected) VALUES (%s, %s, %s, %s, 0, 0, 0)"
            " RETURNING run_id",
            (sid, str(events_path), sha, len(batch.accepted) + len(batch.rejects)),
        ).fetchone()[0]
        columns = (*ENVELOPE_COLUMNS, *PAYLOAD_COLUMNS, "ingestion_run_id")
        rows = [
            (*(e[c] for c in ENVELOPE_COLUMNS), *(e["payload"][c] for c in PAYLOAD_COLUMNS), run_id)
            for e in batch.accepted
        ]
        with conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO payment_events ({', '.join(columns)})"
                f" VALUES ({', '.join(['%s'] * len(columns))}) ON CONFLICT (event_id) DO NOTHING",
                rows,
            )
            inserted = cur.execute(
                "SELECT count(*) FROM payment_events WHERE ingestion_run_id = %s", (run_id,)
            ).fetchone()[0]
            cur.executemany(
                "INSERT INTO ingestion_rejects (ingestion_run_id, simulation_id, line_number,"
                " event_id, payment_id, reasons, raw_line) VALUES (%s, %s, %s, %s, %s, %s, %s)"
                " ON CONFLICT (simulation_id, line_number) DO NOTHING",
                [
                    (
                        run_id,
                        sid,
                        r.line_number,
                        r.event_id,
                        r.payment_id,
                        Jsonb(r.reasons),
                        r.raw_line,
                    )
                    for r in batch.rejects
                ],
            )
        counts = {
            "run_id": run_id,
            "simulation_id": sid,
            "rows_read": len(batch.accepted) + len(batch.rejects),
            "rows_accepted": inserted,
            "rows_duplicate": len(batch.accepted) - inserted,
            "rows_rejected": len(batch.rejects),
        }
        conn.execute(
            "UPDATE ingestion_runs SET rows_accepted = %s, rows_duplicate = %s, rows_rejected = %s"
            " WHERE run_id = %s",
            (counts["rows_accepted"], counts["rows_duplicate"], counts["rows_rejected"], run_id),
        )
    return counts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--init-db", action="store_true", help="create tables (idempotent)")
    group.add_argument("--sim", help="simulation_id under --sim-root")
    parser.add_argument("--sim-root", type=Path, default=REPO_ROOT / "artifacts" / "simulations")
    args = parser.parse_args(argv)
    with connect() as conn:
        if args.init_db:
            print(f"schema ready ({', '.join(init_db(conn))})")
        else:
            print(json.dumps(ingest(conn, args.sim_root / args.sim)))


if __name__ == "__main__":
    main()
