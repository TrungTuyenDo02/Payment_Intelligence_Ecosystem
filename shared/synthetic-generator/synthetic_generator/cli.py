"""`make simulate CONFIG=...`: write one simulation to artifacts/simulations/<simulation_id>/."""

import argparse
import hashlib
import importlib.util
import json
from importlib import metadata
from pathlib import Path
from types import ModuleType
from typing import Any

import yaml

from synthetic_generator import GENERATOR_VERSION
from synthetic_generator.config import SimulationConfig, load_config, simulation_id
from synthetic_generator.generator import anomaly_labels, generate_events

REPO_ROOT = Path(__file__).resolve().parents[3]
RULES_PATH = REPO_ROOT / "contracts" / "payment-event" / "payment_event_rules.py"


def load_contract_rules() -> ModuleType:
    """The contract's validate_event (the folder name has a dash, so import by path)."""
    spec = importlib.util.spec_from_file_location("payment_event_rules", RULES_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_events(events: list[dict[str, Any]]) -> None:
    """Raise if any event breaks the contract; the generator must never emit invalid events."""
    rules = load_contract_rules()
    validator = rules.load_validator()
    for event in events:
        errors = rules.validate_event(event, validator)
        if errors:
            raise ValueError(
                f"generated event {event.get('event_id')} breaks the contract: {errors}"
            )


def events_jsonl(events: list[dict[str, Any]]) -> bytes:
    lines = (json.dumps(e, separators=(",", ":"), ensure_ascii=True) for e in events)
    return ("\n".join(lines) + "\n").encode("utf-8")


def write_simulation(config: SimulationConfig, out_root: Path) -> Path:
    """Generate, validate and write events, labels and manifest; return the simulation folder."""
    events = generate_events(config)
    check_events(events)
    data = events_jsonl(events)
    sid = simulation_id(config)
    out = out_root / sid
    out.mkdir(parents=True, exist_ok=True)
    (out / "events.jsonl").write_bytes(data)
    labels = json.dumps(anomaly_labels(config), indent=2, sort_keys=True, ensure_ascii=True)
    (out / "anomaly_labels.json").write_text(labels + "\n", encoding="utf-8")
    manifest = {
        "simulation_id": sid,
        "generator_version": GENERATOR_VERSION,
        "seed": config.seed,
        "numpy_version": metadata.version("numpy"),  # byte-identical output assumes the same numpy
        "events": len(events),
        "anomalies": len(config.anomalies),
        "payments": len({e["payload"]["payment_id"] for e in events}),
        "events_sha256": hashlib.sha256(data).hexdigest(),
        "config": config.model_dump(mode="json"),
    }
    (out / "simulation_manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return out


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out-root", type=Path, default=REPO_ROOT / "artifacts" / "simulations")
    args = parser.parse_args(argv)
    config, _ = load_config(args.config)
    out = write_simulation(config, args.out_root)
    print(f"{simulation_id(config)} -> {out}")


if __name__ == "__main__":
    main()
