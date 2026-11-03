"""Tests for the simulation config and simulation_id (Stage C, task C01)."""

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml
from synthetic_generator import GENERATOR_VERSION, config
from synthetic_generator.config import ConfigError, SimulationConfig, load_config, simulation_id

DEMO = Path(__file__).resolve().parents[1] / "configs" / "demo.yaml"


@pytest.fixture
def raw() -> dict[str, Any]:
    return yaml.safe_load(DEMO.read_text("utf-8"))


def _sim_id(raw: dict[str, Any]) -> str:
    return simulation_id(SimulationConfig.model_validate(raw))


def test_demo_config_loads() -> None:
    cfg, _ = load_config(DEMO)
    assert cfg.time.days == 7
    assert len(cfg.providers) == 3
    assert cfg.n_merchants == 20


def test_simulation_id_is_deterministic(raw: dict[str, Any]) -> None:
    sid = _sim_id(raw)
    assert sid == _sim_id(copy.deepcopy(raw))
    assert sid.startswith("sim-") and len(sid) == 16


def test_status_does_not_change_simulation_id(raw: dict[str, Any]) -> None:
    frozen = {**raw, "status": "frozen"}
    assert _sim_id(raw) == _sim_id(frozen)


def test_key_order_does_not_change_simulation_id(raw: dict[str, Any]) -> None:
    assert _sim_id(raw) == _sim_id(dict(reversed(list(raw.items()))))


def test_explicit_default_does_not_change_simulation_id(raw: dict[str, Any]) -> None:
    assert "anomalies" in raw
    without = {k: v for k, v in raw.items() if k != "anomalies"}
    assert _sim_id(raw) == _sim_id(without)


@pytest.mark.parametrize(
    ("key", "value"),
    [("seed", 43), ("purpose", "report"), ("payments_per_hour", 31), ("timeout_ms", 9000)],
)
def test_content_changes_simulation_id(raw: dict[str, Any], key: str, value: Any) -> None:
    assert _sim_id(raw) != _sim_id({**raw, key: value})


def test_generator_version_changes_simulation_id(
    raw: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _sim_id(raw)
    monkeypatch.setattr(config, "GENERATOR_VERSION", GENERATOR_VERSION + "-next")
    assert _sim_id(raw) != before


def _anomaly(**kw: Any) -> dict[str, Any]:
    base = {
        "type": "provider_outage",
        "start": "2026-01-07T10:00:00Z",
        "duration_minutes": 60,
        "magnitude": 5,
        "provider": 1,
    }
    return {**base, **kw}


def test_valid_anomaly_accepted(raw: dict[str, Any]) -> None:
    cfg = SimulationConfig.model_validate({**raw, "anomalies": [_anomaly()]})
    assert cfg.anomalies[0].provider == 1


def _mutations() -> list[tuple[str, Any]]:
    def set_path(path: str, value: Any) -> Any:
        def apply(r: dict[str, Any]) -> None:
            *parents, last = path.split(".")
            node = r
            for p in parents:
                node = node[p]
            node[last] = value

        return apply

    return [
        ("unknown top-level field", set_path("card_number", "4111")),
        ("unknown nested field", set_path("retry.foo", 1)),
        ("bad status", set_path("status", "approved")),
        ("bad purpose", set_path("purpose", "final")),
        ("23 hour factors", set_path("time.hour_of_day_factors", [1.0] * 23)),
        ("negative factor", set_path("time.day_of_week_factors", [1, 1, 1, 1, 1, 1, -1])),
        ("unknown method", set_path("method_weights", {"CASH": 1.0})),
        ("all-zero weights", set_path("error_code_weights", {"TIMEOUT": 0})),
        ("unknown error code", set_path("error_code_weights", {"FRAUD": 1.0})),
        ("missing amount", set_path("amounts", {"QR": {"median_vnd": 1, "sigma": 0}})),
        (
            "failure_prob > 1",
            set_path(
                "providers", [{"failure_prob": 1.5, "latency_median_ms": 1, "latency_sigma": 0}]
            ),
        ),
        ("no providers", set_path("providers", [])),
        ("wait max < min", set_path("retry.wait_seconds_max", 1)),
        (
            "switch with one provider",
            set_path(
                "providers", [{"failure_prob": 0.1, "latency_median_ms": 1, "latency_sigma": 0}]
            ),
        ),
        ("outage without provider", set_path("anomalies", [_anomaly(provider=None)])),
        ("burst without error_code", set_path("anomalies", [_anomaly(type="error_burst")])),
        ("drop without method", set_path("anomalies", [_anomaly(type="traffic_drop")])),
        ("provider out of range", set_path("anomalies", [_anomaly(provider=3)])),
        ("anomaly before start", set_path("anomalies", [_anomaly(start="2026-01-04T23:00:00Z")])),
        ("anomaly past end", set_path("anomalies", [_anomaly(start="2026-01-11T23:30:00Z")])),
        ("anomaly not UTC", set_path("anomalies", [_anomaly(start="2026-01-07T10:00:00+07:00")])),
    ]


@pytest.mark.parametrize(("name", "mutate"), _mutations(), ids=[n for n, _ in _mutations()])
def test_invalid_config_rejected(raw: dict[str, Any], name: str, mutate: Any) -> None:
    bad = copy.deepcopy(raw)
    mutate(bad)
    with pytest.raises(ValueError):
        SimulationConfig.model_validate(bad)


def test_load_config_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "missing.yaml")
    bad = tmp_path / "bad.yaml"
    bad.write_text("status: draft\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="invalid config"):
        load_config(bad)
