"""Merge alerted buckets into incidents (stage-d-spec.md section 5). Reads no labels."""

from typing import Any

import pandas as pd

BUCKET = pd.Timedelta(minutes=15)


def merge_incidents(alerts: pd.DataFrame, max_gap_buckets: int = 1) -> list[dict[str, Any]]:
    """One incident per run of alerted buckets of the same detector and target.

    Buckets of different metrics of one target join the same incident. Two alerted buckets
    belong together when at most `max_gap_buckets` quiet buckets lie between them.
    """
    hits = alerts[alerts["alert"]].sort_values("bucket_start")
    incidents: list[dict[str, Any]] = []
    for (detector, ttype, target), g in hits.groupby(
        ["detector", "target_type", "target"], sort=True
    ):
        current: dict[str, Any] | None = None
        for row in g.itertuples(index=False):
            start = row.bucket_start
            if current and start - current["_last"] <= (max_gap_buckets + 1) * BUCKET:
                current["_last"] = max(current["_last"], start)
                current["metrics"].add(row.metric)
                current["max_score"] = max(current["max_score"], float(row.score))
                continue
            if current:
                incidents.append(current)
            current = {
                "detector": detector,
                "target_type": ttype,
                "target": target,
                "_first": start,
                "_last": start,
                "metrics": {row.metric},
                "max_score": float(row.score),
            }
        if current:
            incidents.append(current)
    out = []
    for inc in sorted(incidents, key=lambda i: (i["detector"], i["_first"], i["target"])):
        out.append(
            {
                "detector": inc["detector"],
                "target_type": inc["target_type"],
                "target": inc["target"],
                "metrics": sorted(inc["metrics"]),
                "start": inc["_first"].strftime("%Y-%m-%dT%H:%M:%SZ"),
                "end": (inc["_last"] + BUCKET).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "first_alert_at": (inc["_first"] + BUCKET).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "buckets": int((inc["_last"] - inc["_first"]) / BUCKET) + 1,
                "max_score": round(inc["max_score"], 3),
            }
        )
    for detector in {i["detector"] for i in out}:
        mine = [i for i in out if i["detector"] == detector]
        for no, inc in enumerate(mine, start=1):
            inc["incident_id"] = f"{detector}-{no:03d}"
    return out
