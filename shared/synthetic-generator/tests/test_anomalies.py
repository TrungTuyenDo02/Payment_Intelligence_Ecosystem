"""Acceptance tests for anomaly injection and ground truth (Stage C, task C03)."""

import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Any

import pytest
import yaml
from synthetic_generator.cli import check_events, write_simulation
from synthetic_generator.config import SimulationConfig
from synthetic_generator.generator import anomaly_labels, generate_events

CONFIGS = Path(__file__).resolve().parents[1] / "configs"
CONTRACT_KEYS = {
    "event_id",
    "event_type",
    "schema_version",
    "event_time",
    "source_system",
    "simulation_id",
    "payload",
}
PAYLOAD_KEYS = {
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
}


def _raw(name: str) -> dict[str, Any]:
    return yaml.safe_load((CONFIGS / name).read_text("utf-8"))


def _cfg(name: str, **overrides: Any) -> SimulationConfig:
    return SimulationConfig.model_validate({**_raw(name), **overrides})


@pytest.fixture(scope="module")
def tuning() -> tuple[SimulationConfig, list[dict[str, Any]], list[dict[str, Any]]]:
    """(config, events with anomalies, events of the same world without anomalies)."""
    cfg = _cfg("demo.yaml")
    return cfg, generate_events(cfg), generate_events(_cfg("demo.yaml", anomalies=[]))


@pytest.fixture(scope="module")
def report() -> tuple[SimulationConfig, list[dict[str, Any]], list[dict[str, Any]]]:
    cfg = _cfg("report.yaml")
    return cfg, generate_events(cfg), generate_events(_cfg("report.yaml", anomalies=[]))


def _ts(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _attempt_start(event: dict[str, Any]) -> datetime:
    return _ts(event["event_time"]) - timedelta(milliseconds=event["payload"]["latency_ms"])


def _inside(label: dict[str, Any], when: datetime) -> bool:
    return _ts(label["start"]) <= when < _ts(label["end"])


def _payment_no(event: dict[str, Any]) -> int:
    return int(event["payload"]["payment_id"].rsplit("-", 1)[1])


def _comparable(event: dict[str, Any]) -> tuple[Any, ...]:
    """Everything except the ids, which carry the simulation tag."""
    p = event["payload"]
    rest = {k: v for k, v in p.items() if k not in ("payment_id", "attempt_id")}
    return (event["event_time"], tuple(sorted(rest.items())))


def test_labels_match_config(tuning: Any) -> None:
    cfg, _, _ = tuning
    labels = anomaly_labels(cfg)
    assert [lab["type"] for lab in labels] == [a.type for a in cfg.anomalies]
    assert [lab["anomaly_id"] for lab in labels] == ["anom-01", "anom-02", "anom-03"]
    outage = labels[0]
    assert outage["provider_id"] == "prov_002"
    assert outage["start"] == "2026-01-06T05:00:00.000Z"
    assert outage["end"] == "2026-01-06T06:30:00.000Z"
    assert labels[2]["error_code"] == "NETWORK_ERROR" and labels[2]["provider_id"] is None


def test_labels_file_written(tmp_path: Path) -> None:
    cfg = _cfg("report.yaml")
    out = write_simulation(cfg, tmp_path)
    assert json.loads((out / "anomaly_labels.json").read_text("utf-8")) == anomaly_labels(cfg)


@pytest.mark.parametrize("name", ["demo.yaml", "report.yaml"])
def test_events_reveal_nothing(name: str) -> None:
    events = generate_events(_cfg(name))
    check_events(events)
    for e in events:
        assert set(e) == CONTRACT_KEYS
        assert set(e["payload"]) == PAYLOAD_KEYS


def test_payment_ids_have_no_gaps_after_traffic_drop(report: Any) -> None:
    _, events, _ = report
    numbers = sorted({_payment_no(e) for e in events})
    assert numbers == list(range(1, len(numbers) + 1))


def test_payments_outside_windows_are_unchanged(tuning: Any) -> None:
    """Per-payment RNG streams: an anomaly changes only payments that touch its window."""
    cfg, with_anom, without = tuning
    labels = anomaly_labels(cfg)

    def group(events: list[dict[str, Any]]) -> dict[int, list[dict[str, Any]]]:
        out: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for e in events:
            out[_payment_no(e)].append(e)
        return out

    a, b = group(with_anom), group(without)
    assert a.keys() == b.keys()  # no traffic_drop in tuning: same payments
    untouched = changed = 0
    for no, events in b.items():
        touches = any(_inside(lab, _attempt_start(e)) for e in events for lab in labels)
        if touches:
            changed += [_comparable(e) for e in a[no]] != [_comparable(e) for e in events]
        else:
            untouched += 1
            assert [_comparable(e) for e in a[no]] == [_comparable(e) for e in events], no
    assert untouched > 0.9 * len(b)
    assert changed > 0


def _in_window(
    events: list[dict[str, Any]], label: dict[str, Any], provider: str | None = None
) -> list[dict[str, Any]]:
    return [
        e["payload"]
        for e in events
        if _inside(label, _attempt_start(e))
        and (provider is None or e["payload"]["provider_id"] == provider)
    ]


def test_provider_outage_raises_failures_inside_window(tuning: Any) -> None:
    cfg, with_anom, without = tuning
    label = anomaly_labels(cfg)[0]
    hit = _in_window(with_anom, label, "prov_002")
    base = _in_window(without, label, "prov_002")
    fail_hit = sum(p["status"] == "FAILED" for p in hit) / len(hit)
    fail_base = sum(p["status"] == "FAILED" for p in base) / len(base)
    assert fail_hit > 0.6 > 0.4 > fail_base
    extra = [p["error_code"] for p in hit if p["error_code"]]
    assert sum(c in ("TIMEOUT", "PROVIDER_ERROR") for c in extra) / len(extra) > 0.7


def test_latency_degradation_inside_window(tuning: Any) -> None:
    cfg, with_anom, without = tuning
    label = anomaly_labels(cfg)[1]

    def med(events: list[dict[str, Any]]) -> float:
        rows = _in_window(events, label, "prov_001")
        return median(p["latency_ms"] for p in rows if p["error_code"] != "TIMEOUT")

    assert 2.3 < med(with_anom) / med(without) < 3.7  # magnitude 3


def test_error_burst_inside_window(tuning: Any) -> None:
    cfg, with_anom, without = tuning
    label = anomaly_labels(cfg)[2]

    def count(events: list[dict[str, Any]]) -> int:
        return sum(p["error_code"] == "NETWORK_ERROR" for p in _in_window(events, label))

    assert count(with_anom) >= 3 * max(1, count(without))


def test_traffic_drop_inside_window(report: Any) -> None:
    cfg, with_anom, without = report
    label = next(lab for lab in anomaly_labels(cfg) if lab["type"] == "traffic_drop")

    def first_qr(events: list[dict[str, Any]]) -> int:
        return sum(
            p["payment_method"] == "QR" and p["attempt_number"] == 1
            for p in _in_window(events, label)
        )

    def first_other(events: list[dict[str, Any]]) -> int:
        return sum(
            p["payment_method"] != "QR" and p["attempt_number"] == 1
            for p in _in_window(events, label)
        )

    assert first_qr(with_anom) < 0.4 * first_qr(without)  # magnitude 5: keep about 1 in 5
    assert first_other(with_anom) == first_other(without)


def test_report_config_differs_from_tuning() -> None:
    tune, rep = _cfg("demo.yaml"), _cfg("report.yaml")
    assert (tune.purpose, rep.purpose) == ("tuning", "report")
    assert tune.seed != rep.seed
    assert {a.type for a in rep.anomalies} - {a.type for a in tune.anomalies}


def test_magnitude_must_exceed_one() -> None:
    raw = _raw("demo.yaml")
    raw["anomalies"][0]["magnitude"] = 1
    with pytest.raises(ValueError):
        SimulationConfig.model_validate(raw)
