"""Tests for ingestion (Stage C, task C04). Database tests skip when PostgreSQL is not running."""

import copy
import json
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
import yaml
from synthetic_generator.cli import write_simulation
from synthetic_generator.config import SimulationConfig
from synthetic_generator.generator import generate_events
from synthetic_generator.ingest import (
    IngestError,
    check_batch,
    connect,
    cross_attempt_errors,
    ingest,
    init_db,
)

DEMO = Path(__file__).resolve().parents[1] / "configs" / "demo.yaml"


def _small_config() -> SimulationConfig:
    raw = yaml.safe_load(DEMO.read_text("utf-8"))
    raw["time"]["days"] = 1
    raw["anomalies"] = []
    return SimulationConfig.model_validate(raw)


@pytest.fixture(scope="module")
def events() -> list[dict[str, Any]]:
    return generate_events(_small_config())


def _lines(events: list[dict[str, Any]]) -> list[str]:
    return [json.dumps(e) for e in events]


def _retried_payment(events: list[dict[str, Any]]) -> str:
    return next(e["payload"]["payment_id"] for e in events if e["payload"]["attempt_number"] == 2)


def _attempt(**kw: Any) -> dict[str, Any]:
    base = {
        "attempt_number": 1,
        "merchant_id": "mer_0001",
        "amount": 1000,
        "payment_method": "QR",
        "currency": "VND",
        "status": "FAILED",
    }
    return {**base, **kw}


def test_cross_attempt_rules_accept_valid_chain() -> None:
    chain = [_attempt(), _attempt(attempt_number=2, status="SUCCESS")]
    assert cross_attempt_errors(chain) == []


@pytest.mark.parametrize(
    ("chain", "message"),
    [
        ([_attempt(), _attempt()], "duplicate (payment_id, attempt_number)"),
        ([_attempt(), _attempt(attempt_number=3)], "not consecutive"),
        ([_attempt(attempt_number=2)], "not consecutive"),
        ([_attempt(), _attempt(attempt_number=2, amount=2000)], "amount differs"),
        ([_attempt(), _attempt(attempt_number=2, merchant_id="mer_0002")], "merchant_id differs"),
        ([_attempt(), _attempt(attempt_number=2, payment_method="CARD")], "payment_method"),
        (
            [_attempt(status="SUCCESS"), _attempt(attempt_number=2, status="SUCCESS")],
            "more than one SUCCESS",
        ),
        ([_attempt(status="SUCCESS"), _attempt(attempt_number=2)], "attempt after SUCCESS"),
    ],
)
def test_cross_attempt_rules_reject(chain: list[dict[str, Any]], message: str) -> None:
    assert any(message in e for e in cross_attempt_errors(chain))


def test_generated_batch_is_fully_accepted(events: list[dict[str, Any]]) -> None:
    sid = events[0]["simulation_id"]
    batch = check_batch(_lines(events), sid)
    assert batch.rejects == []
    assert len(batch.accepted) == len(events)


def test_broken_attempt_rejects_the_whole_payment(events: list[dict[str, Any]]) -> None:
    sid = events[0]["simulation_id"]
    pid = _retried_payment(events)
    bad = copy.deepcopy(events)
    target = next(e for e in bad if e["payload"]["payment_id"] == pid)
    target["payload"]["amount"] += 1000  # still a valid event, breaks the shared-field rule
    batch = check_batch(_lines(bad), sid)
    rejected = {r.payment_id for r in batch.rejects}
    assert rejected == {pid}
    n_attempts = sum(e["payload"]["payment_id"] == pid for e in events)
    assert len(batch.rejects) == n_attempts
    assert all("amount differs" in r.reasons[0] for r in batch.rejects)
    assert len(batch.accepted) == len(events) - n_attempts


def test_contract_error_rejects_the_other_attempts_too(events: list[dict[str, Any]]) -> None:
    sid = events[0]["simulation_id"]
    pid = _retried_payment(events)
    lines = _lines(events)
    idx = next(i for i, e in enumerate(events) if e["payload"]["payment_id"] == pid)
    broken = copy.deepcopy(events[idx])
    broken["payload"]["card_number"] = "4111"
    lines[idx] = json.dumps(broken)
    batch = check_batch(lines, sid)
    assert {r.payment_id for r in batch.rejects} == {pid}
    first = next(r for r in batch.rejects if r.line_number == idx + 1)
    assert any("card_number" in reason for reason in first.reasons)
    others = [r for r in batch.rejects if r.line_number != idx + 1]
    assert others and all("another attempt" in r.reasons[0] for r in others)


def test_garbage_lines_and_wrong_simulation(events: list[dict[str, Any]]) -> None:
    sid = events[0]["simulation_id"]
    lines = ["{not json", "[1, 2]", json.dumps({**events[0], "simulation_id": "sim-other"})]
    batch = check_batch(lines, sid)
    assert [r.line_number for r in batch.rejects][:2] == [1, 2]
    assert "not JSON" in batch.rejects[0].reasons[0]
    assert any("simulation_id is not" in r for r in batch.rejects[2].reasons)


def test_duplicate_event_id_in_file(events: list[dict[str, Any]]) -> None:
    sid = events[0]["simulation_id"]
    single = next(
        e
        for e in events
        if e["payload"]["status"] == "SUCCESS" and e["payload"]["attempt_number"] == 1
    )
    batch = check_batch([json.dumps(single), json.dumps(single)], sid)
    assert any("duplicate event_id" in r for rej in batch.rejects for r in rej.reasons)


# --- PostgreSQL integration (each test gets its own schema, dropped afterwards) ---


@pytest.fixture
def db() -> Iterator[psycopg.Connection]:
    try:
        conn = connect()
    except psycopg.OperationalError as err:
        pytest.skip(f"PostgreSQL not reachable (start it with `make up`): {err}")
    conn.autocommit = True
    schema = f"test_{uuid.uuid4().hex[:8]}"
    conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(f"SET search_path TO {schema}")
    init_db(conn)
    try:
        yield conn
    finally:
        conn.execute(f"DROP SCHEMA {schema} CASCADE")
        conn.close()


def _count(conn: psycopg.Connection, table: str) -> int:
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_ingest_and_reingest_is_idempotent(db: psycopg.Connection, tmp_path: Path) -> None:
    sim = write_simulation(_small_config(), tmp_path)
    n = len((sim / "events.jsonl").read_text("utf-8").splitlines())
    first = ingest(db, sim)
    assert first["rows_accepted"] == n and first["rows_rejected"] == 0
    second = ingest(db, sim)
    assert second["rows_accepted"] == 0 and second["rows_duplicate"] == n
    assert _count(db, "payment_events") == n
    assert _count(db, "ingestion_runs") == 2
    init_db(db)  # running the schema again is harmless


def test_rejects_are_stored_with_reasons(db: psycopg.Connection, tmp_path: Path) -> None:
    sim = write_simulation(_small_config(), tmp_path)
    path = sim / "events.jsonl"
    lines = path.read_text("utf-8").splitlines()
    lines[0] = "{not json"
    data = ("\n".join(lines) + "\n").encode("utf-8")
    path.write_bytes(data)
    manifest = yaml.safe_load((sim / "simulation_manifest.yaml").read_text("utf-8"))
    manifest["events_sha256"] = __import__("hashlib").sha256(data).hexdigest()
    (sim / "simulation_manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    counts = ingest(db, sim)
    assert counts["rows_rejected"] == 1
    reasons = db.execute("SELECT reasons FROM ingestion_rejects").fetchone()[0]
    assert "not JSON" in reasons[0]
    ingest(db, sim)
    assert _count(db, "ingestion_rejects") == 1  # rejects are not duplicated either


def test_changed_file_for_same_simulation_is_refused(
    db: psycopg.Connection, tmp_path: Path
) -> None:
    sim = write_simulation(_small_config(), tmp_path)
    ingest(db, sim)
    path = sim / "events.jsonl"
    data = path.read_bytes() + b"{}\n"
    path.write_bytes(data)
    manifest = yaml.safe_load((sim / "simulation_manifest.yaml").read_text("utf-8"))
    manifest["events_sha256"] = __import__("hashlib").sha256(data).hexdigest()
    (sim / "simulation_manifest.yaml").write_text(yaml.safe_dump(manifest), encoding="utf-8")
    with pytest.raises(IngestError, match="checksum changed"):
        ingest(db, sim)
    assert _count(db, "ingestion_runs") == 1  # the refused run left nothing behind


def test_file_not_matching_manifest_is_refused(tmp_path: Path) -> None:
    sim = write_simulation(_small_config(), tmp_path)
    (sim / "events.jsonl").write_bytes(b"{}\n")
    with pytest.raises(IngestError, match="does not match"):
        ingest(None, sim)  # type: ignore[arg-type]  # fails before touching the database
