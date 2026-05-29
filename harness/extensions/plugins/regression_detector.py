"""Regression detection — compare benchmark metrics against a baseline."""
from __future__ import annotations

# Default thresholds: how much change constitutes a regression
_THRESHOLDS = {
    "score": 0.10,      # 10% score drop
    "cost": 0.50,        # 50% cost increase
    "latency": 0.50,     # 50% latency increase
    "tokens": 0.50,      # 50% token increase
}


def detect_regressions(
    baseline: dict,
    current: dict,
    thresholds: dict[str, float] | None = None,
) -> list[dict]:
    """Compare current benchmark metrics against a baseline.

    Returns a list of regression descriptors. Empty list means no regressions.
    Each descriptor has: metric, baseline, current, delta, direction, threshold.
    """
    t = {**_THRESHOLDS, **(thresholds or {})}
    regressions = []

    # Score regression (lower is worse)
    if "avg_score" in baseline and "avg_score" in current:
        b, c = baseline["avg_score"], current["avg_score"]
        if b > 0:
            drop = b - c
            if drop / b > t["score"]:
                regressions.append({
                    "metric": "avg_score",
                    "baseline": round(b, 4),
                    "current": round(c, 4),
                    "delta_pct": round(drop / b, 4),
                    "direction": "down",
                    "threshold": t["score"],
                })

    # Cost regression (higher is worse)
    if "avg_cost" in baseline and "avg_cost" in current:
        b, c = baseline["avg_cost"], current["avg_cost"]
        if b > 0:
            increase = (c - b) / b
            if increase > t["cost"]:
                regressions.append({
                    "metric": "avg_cost",
                    "baseline": round(b, 6),
                    "current": round(c, 6),
                    "delta_pct": round(increase, 4),
                    "direction": "up",
                    "threshold": t["cost"],
                })

    # Latency regression (higher is worse)
    if "avg_duration_ms" in baseline and "avg_duration_ms" in current:
        b, c = baseline["avg_duration_ms"], current["avg_duration_ms"]
        if b > 0:
            increase = (c - b) / b
            if increase > t["latency"]:
                regressions.append({
                    "metric": "avg_duration_ms",
                    "baseline": b,
                    "current": c,
                    "delta_pct": round(increase, 4),
                    "direction": "up",
                    "threshold": t["latency"],
                })

    # Token regression (higher is worse)
    if "avg_tokens" in baseline and "avg_tokens" in current:
        b, c = baseline["avg_tokens"], current["avg_tokens"]
        if b > 0:
            increase = (c - b) / b
            if increase > t["tokens"]:
                regressions.append({
                    "metric": "avg_tokens",
                    "baseline": b,
                    "current": c,
                    "delta_pct": round(increase, 4),
                    "direction": "up",
                    "threshold": t["tokens"],
                })

    return regressions
