"""Compare incidents with the injected anomalies (stage-d-spec.md section 6).

This is the only module that reads `anomaly_labels.json`. Detectors and incident merging never
import it (tested).
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


def load_labels(sim_dir: Path) -> list[dict[str, Any]]:
    """Ground truth written by the generator next to events.jsonl."""
    return json.loads((sim_dir / "anomaly_labels.json").read_text("utf-8"))


def _ts(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def right_target(incident: dict[str, Any], label: dict[str, Any]) -> bool:
    """Strict rule (spec Q3): the incident names what the anomaly affected."""
    if label["type"] == "traffic_drop":
        return incident["target_type"] == "method" and incident["target"] == label["payment_method"]
    if incident["target_type"] != "provider":
        return False
    if label["provider_id"] is None:  # error_burst on all providers: any provider or ALL
        return True
    return incident["target"] == label["provider_id"]


def overlaps(incident: dict[str, Any], label: dict[str, Any], grace_minutes: int) -> bool:
    """Incident [start, end) meets the anomaly window [start, end + grace)."""
    grace = timedelta(minutes=grace_minutes)
    return _ts(incident["start"]) < _ts(label["end"]) + grace and _ts(label["start"]) < _ts(
        incident["end"]
    )


def evaluate(
    incidents: list[dict[str, Any]],
    labels: list[dict[str, Any]],
    days: float,
    grace_minutes: int = 15,
) -> dict[str, Any]:
    """Per-anomaly detection, delay and false incidents for the incidents of one detector."""
    per_anomaly = []
    for lab in labels:
        near = [i for i in incidents if overlaps(i, lab, grace_minutes)]
        hits = [i for i in near if right_target(i, lab)]
        first = min((_ts(i["first_alert_at"]) for i in hits), default=None)
        delay = None if first is None else (first - _ts(lab["start"])).total_seconds() / 60
        per_anomaly.append(
            {
                "anomaly_id": lab["anomaly_id"],
                "type": lab["type"],
                "magnitude": lab["magnitude"],
                "target": lab["provider_id"] or lab["payment_method"] or "ALL",
                "detected": bool(hits),
                "detected_any_target": bool(near),
                "delay_minutes": delay,
                "incidents": sorted(i["incident_id"] for i in hits),
            }
        )
    in_time = [i for i in incidents if any(overlaps(i, lab, grace_minutes) for lab in labels)]
    false = [i for i in incidents if i not in in_time]
    right = [i for i in in_time if any(right_target(i, lab) and overlaps(i, lab, grace_minutes)
                                       for lab in labels)]  # fmt: skip
    delays = [a["delay_minutes"] for a in per_anomaly if a["delay_minutes"] is not None]
    return {
        "anomalies": per_anomaly,
        "detected": sum(a["detected"] for a in per_anomaly),
        "detected_any_target": sum(a["detected_any_target"] for a in per_anomaly),
        "total": len(per_anomaly),
        "incidents": len(incidents),
        "false_incidents": len(false),
        "false_per_day": round(len(false) / days, 3),
        "wrong_target_incidents": len(in_time) - len(right),
        "mean_delay_minutes": round(sum(delays) / len(delays), 1) if delays else None,
        "false_incident_ids": [i["incident_id"] for i in false],
    }
