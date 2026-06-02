"""Efficiency-based scoring for benchmark tasks."""
from __future__ import annotations

_DEFAULT_WEIGHTS = {"success": 0.4, "duration": 0.3, "tokens": 0.3}


def _normalize(value: float, baseline: float | None, higher_is_worse: bool = True) -> float:
    if not baseline or not value:
        return 1.0
    ratio = baseline / value if higher_is_worse else value / baseline
    return min(max(ratio, 0.0), 1.0)


class EfficiencyScorer:
    def __init__(
        self,
        weights: dict[str, float] | None = None,
        thresholds: dict[str, dict[str, int]] | None = None,
    ):
        self.weights = weights or dict(_DEFAULT_WEIGHTS)
        self.thresholds = thresholds or {}

    def score_task(
        self,
        task_result: dict,
        baseline: dict | None = None,
    ) -> dict:
        status = task_result.get("status", "pending")
        success_score = 1.0 if status == "completed" else 0.0

        duration_ms = task_result.get("duration_ms") or 0
        token_total = 0
        tu = task_result.get("token_usage")
        if tu and isinstance(tu, dict):
            token_total = tu.get("total", 0)

        task_id = task_result.get("task_id", "")

        # Baseline: config threshold > historical > None
        dur_baseline = self._get_threshold(task_id, "max_duration_ms")
        tok_baseline = self._get_threshold(task_id, "max_tokens")
        if not dur_baseline and baseline:
            dur_baseline = baseline.get("duration_ms")
        if not tok_baseline and baseline:
            tok_baseline = baseline.get("tokens")

        duration_score = _normalize(duration_ms, dur_baseline, higher_is_worse=True)
        token_score = _normalize(token_total, tok_baseline, higher_is_worse=True)

        w = self.weights
        score = (
            w.get("success", 0.4) * success_score
            + w.get("duration", 0.3) * duration_score
            + w.get("tokens", 0.3) * token_score
        )

        return {
            "score": round(score, 4),
            "breakdown": {
                "success": round(success_score, 4),
                "duration": round(duration_score, 4),
                "tokens": round(token_score, 4),
            },
            "score_source": "efficiency",
        }

    def _get_threshold(self, task_id: str, key: str) -> float | None:
        t = self.thresholds.get(task_id)
        if t:
            v = t.get(key)
            if v is not None:
                return float(v)
        return None

    @staticmethod
    def compute_baseline(historical_results: list[dict]) -> dict[str, dict]:
        """Compute per-task best (lowest) duration_ms and tokens from historical results."""
        best: dict[str, dict] = {}
        for result in historical_results:
            for tr in result.get("task_results", []):
                tid = tr.get("task_id", "")
                if not tid:
                    continue
                dur = tr.get("duration_ms")
                tu = tr.get("token_usage")
                tokens = tu.get("total", 0) if tu and isinstance(tu, dict) else 0

                if tid not in best:
                    best[tid] = {}
                b = best[tid]
                if dur and (not b.get("duration_ms") or dur < b["duration_ms"]):
                    b["duration_ms"] = dur
                if tokens and (not b.get("tokens") or tokens < b["tokens"]):
                    b["tokens"] = tokens
        return best
