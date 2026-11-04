"""Acceptance tests for the base generator (Stage C, task C02)."""

from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pytest
import yaml
from synthetic_generator.cli import check_events, load_contract_rules, main, write_simulation
from synthetic_generator.config import RETRYABLE_ERRORS, SimulationConfig, simulation_id
from synthetic_generator.generator import format_time, generate_events

DEMO = Path(__file__).resolve().parents[1] / "configs" / "demo.yaml"


def _config(**overrides: Any) -> SimulationConfig:
    raw = yaml.safe_load(DEMO.read_text("utf-8"))
    raw.update(overrides)
    return SimulationConfig.model_validate(raw)


@pytest.fixture(scope="module")
def demo_events() -> list[dict[str, Any]]:
    return generate_events(_config())


@pytest.fixture(scope="module")
def big() -> tuple[SimulationConfig, list[dict[str, Any]]]:
    """Large sample for rate checks: about 60 thousand payments in 2 days."""
    raw_time = yaml.safe_load(DEMO.read_text("utf-8"))["time"]
    cfg = _config(payments_per_hour=1250, time={**raw_time, "days": 2}, anomalies=[])
    return cfg, generate_events(cfg)


def _by_payment(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in events:
        out[e["payload"]["payment_id"]].append(e["payload"])
    return {k: sorted(v, key=lambda p: p["attempt_number"]) for k, v in out.items()}


def test_demo_size_matches_spec(demo_events: list[dict[str, Any]]) -> None:
    payments = len(_by_payment(demo_events))
    assert 23_000 < payments < 27_500  # 7 days x 24 h x 150 per hour = 25,200 expected
    assert 27_500 < len(demo_events) < 32_500  # about 30 thousand events with retries


def test_every_event_passes_the_contract(demo_events: list[dict[str, Any]]) -> None:
    rules = load_contract_rules()
    validator = rules.load_validator()
    assert all(rules.validate_event(e, validator) == [] for e in demo_events)
    check_events(demo_events)  # the CLI's own gate


def test_ids_unique_and_payment_differs_from_attempt(demo_events: list[dict[str, Any]]) -> None:
    assert len({e["event_id"] for e in demo_events}) == len(demo_events)
    assert len({e["payload"]["attempt_id"] for e in demo_events}) == len(demo_events)
    assert all(e["payload"]["payment_id"] != e["payload"]["attempt_id"] for e in demo_events)
    sid = simulation_id(_config())
    assert all(e["simulation_id"] == sid for e in demo_events)


def test_sorted_by_event_time_then_event_id(demo_events: list[dict[str, Any]]) -> None:
    keys = [(e["event_time"], e["event_id"]) for e in demo_events]
    assert keys == sorted(keys)


def test_cross_attempt_rules(demo_events: list[dict[str, Any]]) -> None:
    """Contract 1.0.0 changelog: the rules ingestion will enforce."""
    for attempts in _by_payment(demo_events).values():
        assert [a["attempt_number"] for a in attempts] == list(range(1, len(attempts) + 1))
        for field in ("merchant_id", "amount", "payment_method", "currency"):
            assert len({a[field] for a in attempts}) == 1
        statuses = [a["status"] for a in attempts]
        assert statuses.count("SUCCESS") <= 1
        assert "SUCCESS" not in statuses[:-1]


def test_retry_only_technical_errors_and_bounded(demo_events: list[dict[str, Any]]) -> None:
    cfg = _config()
    for attempts in _by_payment(demo_events).values():
        assert len(attempts) <= cfg.retry.max_retries + 1
        for a in attempts[:-1]:
            assert a["error_code"] in RETRYABLE_ERRORS


def test_latency_and_amount_rules(demo_events: list[dict[str, Any]]) -> None:
    timeout = _config().timeout_ms
    for e in demo_events:
        p = e["payload"]
        assert p["amount"] >= 1000 and p["amount"] % 1000 == 0
        if p["error_code"] == "TIMEOUT":
            assert p["latency_ms"] == timeout
        else:
            assert 0 <= p["latency_ms"] < timeout


def test_retry_waits_and_time_order(demo_events: list[dict[str, Any]]) -> None:
    times = {e["payload"]["attempt_id"]: e["event_time"] for e in demo_events}
    for attempts in _by_payment(demo_events).values():
        ts = [times[a["attempt_id"]] for a in attempts]
        assert ts == sorted(ts)


def test_rates_match_config_on_large_sample(
    big: tuple[SimulationConfig, list[dict[str, Any]]],
) -> None:
    cfg, events = big
    first = [e["payload"] for e in events if e["payload"]["attempt_number"] == 1]
    n = len(first)
    assert n > 50_000

    total_w = sum(cfg.method_weights.values())
    methods = Counter(p["payment_method"] for p in first)
    for m, w in cfg.method_weights.items():
        assert abs(methods[m] / n - w / total_w) < 0.01, m

    providers = Counter(p["provider_id"] for p in first)
    failed = Counter(p["provider_id"] for p in first if p["status"] == "FAILED")
    for i, p_cfg in enumerate(cfg.providers):
        pid = f"prov_{i + 1:03d}"
        assert abs(providers[pid] / n - 1 / len(cfg.providers)) < 0.01
        assert abs(failed[pid] / providers[pid] - p_cfg.failure_prob) < 0.01, pid

    errors = Counter(p["error_code"] for p in first if p["error_code"])
    n_err, total_e = sum(errors.values()), sum(cfg.error_code_weights.values())
    for code, w in cfg.error_code_weights.items():
        assert abs(errors[code] / n_err - w / total_e) < 0.03, code


def test_retry_switch_rate(big: tuple[SimulationConfig, list[dict[str, Any]]]) -> None:
    cfg, events = big
    pairs = [
        (a[i - 1]["provider_id"], a[i]["provider_id"])
        for a in _by_payment(events).values()
        for i in range(1, len(a))
    ]
    assert len(pairs) > 1_000
    switched = sum(prev != cur for prev, cur in pairs) / len(pairs)
    assert abs(switched - cfg.retry.retry_switch_provider_prob) < 0.04


def test_seasonality_in_local_time(big: tuple[SimulationConfig, list[dict[str, Any]]]) -> None:
    """Busiest local hour (20:00, UTC 13:00) has clearly more payments than 03:00 (UTC 20:00)."""
    _, events = big
    first = [e for e in events if e["payload"]["attempt_number"] == 1]
    by_utc_hour = Counter(int(e["event_time"][11:13]) for e in first)
    assert by_utc_hour[13] > 10 * by_utc_hour[20]


def test_two_runs_are_byte_identical(tmp_path: Path) -> None:
    cfg = _config()
    a = write_simulation(cfg, tmp_path / "a")
    b = write_simulation(cfg, tmp_path / "b")
    for name in ("events.jsonl", "anomaly_labels.json", "simulation_manifest.yaml"):
        assert (a / name).read_bytes() == (b / name).read_bytes(), name


def test_seed_changes_output() -> None:
    assert generate_events(_config(seed=1))[0] != generate_events(_config(seed=2))[0]


def test_manifest_and_cli(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    main(["--config", str(DEMO), "--out-root", str(tmp_path)])
    sid = simulation_id(_config())
    assert sid in capsys.readouterr().out
    manifest = yaml.safe_load((tmp_path / sid / "simulation_manifest.yaml").read_text("utf-8"))
    lines = (tmp_path / sid / "events.jsonl").read_text("utf-8").splitlines()
    assert manifest["simulation_id"] == sid
    assert manifest["events"] == len(lines)
    assert manifest["config"]["seed"] == 42


def test_check_events_rejects_bad_event(demo_events: list[dict[str, Any]]) -> None:
    bad = {**demo_events[0], "payload": {**demo_events[0]["payload"], "currency": "USD"}}
    with pytest.raises(ValueError, match="breaks the contract"):
        check_events([bad])


def test_format_time() -> None:
    assert format_time(0) == "1970-01-01T00:00:00.000Z"
    assert format_time(1_767_571_200_123) == "2026-01-05T00:00:00.123Z"
