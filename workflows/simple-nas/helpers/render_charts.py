#!/usr/bin/env python
"""render_charts.py — visualize NAS results via harness.tools.chart.render_chart().

读取:
  - $session_dir/baseline.json        — baseline 指标 (metrics.acc / latency_ms / params / one_epoch_sec)
  - $session_dir/candidates.json      — search-tier elite pool
    (每 entry: strategy_id / fitness / metrics{acc,latency_ms,params} / tier_applied{data_ratio,epochs} / direction_tag)
  - $session_dir/refinement/_merged.json — refine-tier strategy results
    (每 entry: status / strategy_id / tier_applied{tier_index,data_ratio,epochs} / metrics / loss_curve / search_mode_fitness)
  - $session_dir/metrics.json         — primary_metric + 方向 (higher/lower)
  - $session_dir/HISTORY.md           — 每 iter best_fitness 索引 (parse "- iter N | ... | best_fitness=X")

推送:
  - 通过 render_chart() stdout capture 通道（bash reader 检测 __HARNESS_CHART__ 前缀转发）
  - 前端 result 标签显示

图清单（每 tier 一组 + baseline 参考点）:
  - tier-scatter        — acc vs latency_ms 散点，baseline 星标，按 tier 分组多张
  - tier-optimal-line   — optimal_line（acc vs latency, optimal_line="max"），论文风格 Pareto 前沿
  - fitness-progression — iter-N best fitness 收敛曲线（cross-tier 全局）
  - top-strategies      — table，top-K strategy 明细
  - baseline-comparison — bar，baseline vs top-1 各指标对比

指标:
  - acc (higher better)         — 分类准确率
  - latency_ms (lower better)   — 推理延迟，单 sample
  - params (lower better)       — 参数量
  - fitness (higher better)     — 综合分（公式见 fitness.py）

调用方: analyzer.md (iter 跑完) / reporter.md (最终报告)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

# Locate harness root so this helper works regardless of caller's cwd.
# Layout: <repo>/workflows/nas/helpers/render_charts.py → repo root = parents[3]
_HARNESS_ROOT = Path(__file__).resolve().parents[3]
if str(_HARNESS_ROOT) not in sys.path:
    sys.path.insert(0, str(_HARNESS_ROOT))

from harness.tools.chart import render_chart  # noqa: E402


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def _load(path: Path) -> Any | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return None


def _load_history_best_fitness(history_md: Path) -> list[dict]:
    """Parse HISTORY.md lines: '- iter N | parent=X | best_fitness=Y | ...'"""
    if not history_md.exists():
        return []
    rows = []
    pat = re.compile(r"iter\s+(\d+).*?best_fitness=([\d.]+)")
    for line in history_md.read_text().splitlines():
        m = pat.search(line)
        if m:
            rows.append({"iter": int(m.group(1)), "best_fitness": float(m.group(2))})
    rows.sort(key=lambda r: r["iter"])
    return rows


# ---------------------------------------------------------------------------
# Tier grouping
# ---------------------------------------------------------------------------

def _group_by_tier(session: Path) -> dict[int, list[dict]]:
    """Return {tier_index: [strategy_dict, ...]}.

    Search-tier (candidates.json) gets tier_index=0.
    Refine-tier (refinement/_merged.json) uses its tier_applied.tier_index.
    Each strategy dict is normalized to a common shape for charting.
    """
    tiers: dict[int, list[dict]] = {}

    candidates = _load(session / "candidates.json") or []
    for c in candidates:
        ta = c.get("tier_applied", {}) or {}
        tier_idx = ta.get("tier_index", 0)
        tiers.setdefault(tier_idx, []).append({
            "strategy_id": c.get("strategy_id", "?"),
            "tier": tier_idx,
            "stage": "search",
            "acc": (c.get("metrics") or {}).get("acc", 0.0),
            "latency_ms": c.get("latency_ms", 0.0) or 0.0,
            "onnx_latency_ms": c.get("onnx_latency_ms"),  # may be None
            "params": c.get("params", 0) or 0,
            "fitness": c.get("fitness", 0.0) or 0.0,
            "direction_tag": c.get("direction_tag", ""),
        })

    merged = _load(session / "refinement" / "_merged.json") or []
    for r in merged:
        if r.get("status") != "ok":
            continue
        ta = r.get("tier_applied", {}) or {}
        tier_idx = ta.get("tier_index", 1)
        tiers.setdefault(tier_idx, []).append({
            "strategy_id": r.get("strategy_id", "?"),
            "tier": tier_idx,
            "stage": "refine",
            "acc": (r.get("metrics") or {}).get("acc", 0.0),
            "latency_ms": r.get("latency_ms", 0.0) or 0.0,
            "onnx_latency_ms": r.get("onnx_latency_ms"),  # may be None
            "params": r.get("params", 0) or 0,
            "fitness": r.get("search_mode_fitness", 0.0) or 0.0,
            "direction_tag": "refined",
        })

    return tiers


def _baseline_row(baseline: dict | None) -> dict:
    if not baseline:
        return {"strategy_id": "baseline", "tier": -1, "stage": "baseline",
                "acc": 0.0, "latency_ms": 0.0, "onnx_latency_ms": None,
                "params": 0, "fitness": 0.0, "direction_tag": "baseline"}
    return {
        "strategy_id": "baseline",
        "tier": -1,
        "stage": "baseline",
        "acc": (baseline.get("metrics") or {}).get("acc", 0.0),
        "latency_ms": baseline.get("latency_ms", 0.0) or 0.0,
        "onnx_latency_ms": baseline.get("onnx_latency_ms"),  # may be None
        "params": baseline.get("params", 0) or 0,
        "fitness": 0.0,  # baseline fitness undefined (it IS the reference)
        "direction_tag": "baseline",
    }


# ---------------------------------------------------------------------------
# Chart renderers
# ---------------------------------------------------------------------------

def _render_tier_scatter(tier_idx: int, rows: list[dict], baseline: dict,
                         node_id: str, latency_col: str = "latency_ms") -> None:
    """Scatter: acc vs <latency_col>, baseline marker, one chart per tier.

    latency_col: "latency_ms" (pytorch) or "onnx_latency_ms".
    Strategies missing the requested latency value are skipped (e.g. onnx export failed).
    """
    data = []
    for r in rows:
        lat = r.get(latency_col)
        if lat is None or lat == 0:
            continue
        data.append({
            "strategy_id": r["strategy_id"],
            "acc": r["acc"],
            latency_col: lat,
            "stage": r["stage"],
        })
    base_lat = baseline.get(latency_col)
    if base_lat is not None and base_lat != 0:
        data.append({
            "strategy_id": "baseline",
            "acc": baseline["acc"],
            latency_col: base_lat,
            "stage": "baseline",
        })
    if not data:
        return

    src_label = "ONNX" if latency_col == "onnx_latency_ms" else "PyTorch"
    render_chart(
        data=data,
        chart_type="scatter",
        x=latency_col,
        y="acc",
        hue="stage",
        label=f"tier_{tier_idx}_scatter_{latency_col}",
        title=f"Tier {tier_idx} — Acc vs {src_label} Latency (baseline ◆)",
        node_id=node_id,
    )


def _render_tier_optimal_line(tier_idx: int, rows: list[dict], baseline: dict,
                              node_id: str, latency_col: str = "latency_ms") -> None:
    """Optimal-line: acc vs <latency_col>, theoretical Pareto frontier (acc → max).

    AlphaGo-Moment / ASI-Arch style: highlights the pareto-optimal strategies
    that form the accuracy-latency frontier. Baseline shown as reference.
    """
    data = []
    for r in rows:
        lat = r.get(latency_col)
        if lat is None or lat == 0:
            continue
        data.append({
            "strategy_id": r["strategy_id"],
            "acc": r["acc"],
            latency_col: lat,
        })
    base_lat = baseline.get(latency_col)
    if base_lat is not None and base_lat != 0:
        data.append({
            "strategy_id": "baseline",
            "acc": baseline["acc"],
            latency_col: base_lat,
        })
    if not data:
        return

    src_label = "ONNX" if latency_col == "onnx_latency_ms" else "PyTorch"
    render_chart(
        data=data,
        chart_type="optimal_line",
        x=latency_col,
        y="acc",
        optimal_line="max",  # higher acc is better
        label=f"tier_{tier_idx}_optimal_{latency_col}",
        title=f"Tier {tier_idx} — Pareto Frontier ({src_label} latency, acc → max)",
        node_id=node_id,
    )


def _render_fitness_progression(history_rows: list[dict], node_id: str) -> None:
    """Line: best_fitness over iter-N (cross-tier global convergence)."""
    if not history_rows:
        return
    data = [{"iter": r["iter"], "best_fitness": r["best_fitness"]} for r in history_rows]
    render_chart(
        data=data,
        chart_type="line",
        x="iter",
        y="best_fitness",
        label="fitness_progression",
        title="Search Convergence — Best Fitness per Iter",
        node_id=node_id,
    )


def _render_top_strategies(all_rows: list[dict], baseline: dict, node_id: str, top_k: int = 10) -> None:
    """Table: top-K strategy 明细 across all tiers. Shows both latency columns."""
    sorted_rows = sorted(all_rows, key=lambda r: r["fitness"], reverse=True)[:top_k]
    data = []
    for r in sorted_rows:
        row = {
            "strategy_id": r["strategy_id"],
            "tier": r["tier"],
            "stage": r["stage"],
            "acc": round(r["acc"], 4),
            "latency_ms": round(r["latency_ms"], 6) if r.get("latency_ms") else None,
            "onnx_latency_ms": round(r["onnx_latency_ms"], 6) if r.get("onnx_latency_ms") else None,
            "params": r["params"],
            "fitness": round(r["fitness"], 4),
            "direction": r["direction_tag"],
        }
        data.append(row)
    # Baseline row at bottom for comparison
    data.append({
        "strategy_id": "baseline",
        "tier": "-",
        "stage": "baseline",
        "acc": round(baseline["acc"], 4),
        "latency_ms": round(baseline["latency_ms"], 6) if baseline.get("latency_ms") else None,
        "onnx_latency_ms": round(baseline["onnx_latency_ms"], 6) if baseline.get("onnx_latency_ms") else None,
        "params": baseline["params"],
        "fitness": "-",
        "direction": "baseline",
    })
    render_chart(
        data=data,
        chart_type="table",
        label="top_strategies",
        title=f"Top {top_k} Strategies (sorted by fitness)",
        node_id=node_id,
    )


def _render_baseline_comparison(best: dict, baseline: dict, node_id: str,
                                 latency_col: str = "latency_ms") -> None:
    """Bar: baseline vs top-1 strategy on acc/latency/params (normalized).

    latency_col: which latency to compare. "latency_ms" (pytorch) or "onnx_latency_ms".
    """
    if not best or best["strategy_id"] == "baseline":
        return
    best_lat = best.get(latency_col)
    base_lat = baseline.get(latency_col)
    # Skip latency bar if either side missing the requested source
    metrics = [("acc", "higher")]
    if best_lat and base_lat:
        metrics.append((latency_col, "lower"))
    metrics.append(("params", "lower"))

    data = []
    for metric, _ in metrics:
        b_v = baseline.get(metric, 0) or 0
        s_v = best.get(metric, 0) or 0
        if b_v == 0:
            continue
        data.append({"metric": metric, "entity": "baseline", "value": 1.0})
        data.append({"metric": metric, "entity": best["strategy_id"],
                     "value": round(s_v / b_v, 4)})

    if not data:
        return
    src_label = "ONNX" if latency_col == "onnx_latency_ms" else "PyTorch"
    render_chart(
        data=data,
        chart_type="bar",
        x="metric",
        y="value",
        hue="entity",
        label=f"baseline_comparison_{latency_col}",
        title=f"Baseline (1.0) vs Best — {src_label} latency",
        node_id=node_id,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    p = argparse.ArgumentParser(description="Render NAS result charts")
    p.add_argument("--session", required=True, help="NAS session_dir absolute path")
    p.add_argument("--node-id", default="analyzer",
                   help="node_id for chart routing (analyzer / reporter)")
    p.add_argument("--tier", type=int, default=None,
                   help="Only render charts for this tier index. Default: all tiers")
    p.add_argument("--top-k", type=int, default=10)
    p.add_argument("--latency-source", choices=["pytorch", "onnx", "both"], default="both",
                   help="Which latency to plot. 'both' draws two chart sets "
                        "(requires strategies to have onnx_latency_ms; falls back silently).")
    args = p.parse_args()

    session = Path(args.session).resolve()
    if not session.is_dir():
        print(json.dumps({"error": f"session_dir not found: {session}"}))
        sys.exit(1)

    baseline_raw = _load(session / "baseline.json")
    baseline = _baseline_row(baseline_raw)
    tiers = _group_by_tier(session)
    history_rows = _load_history_best_fitness(session / "HISTORY.md")

    if not tiers:
        print(json.dumps({"warning": "No candidates/refinement found — nothing to chart"}))
        return

    # Determine which latency sources to plot
    if args.latency_source == "both":
        latency_sources = ["latency_ms", "onnx_latency_ms"]
    else:
        latency_sources = ["onnx_latency_ms"] if args.latency_source == "onnx" else ["latency_ms"]

    rendered = []

    # Per-tier charts (one set per latency source)
    target_tiers = [args.tier] if args.tier is not None else sorted(tiers.keys())
    for tier_idx in target_tiers:
        rows = tiers.get(tier_idx, [])
        if not rows:
            continue
        for lat_col in latency_sources:
            # Skip onnx source entirely if no strategy in this tier has it
            has_data = any(r.get(lat_col) for r in rows) or baseline.get(lat_col)
            if not has_data:
                continue
            _render_tier_scatter(tier_idx, rows, baseline, args.node_id, latency_col=lat_col)
            rendered.append(f"tier_{tier_idx}_scatter_{lat_col}")
            _render_tier_optimal_line(tier_idx, rows, baseline, args.node_id, latency_col=lat_col)
            rendered.append(f"tier_{tier_idx}_optimal_{lat_col}")

    # Cross-tier charts
    _render_fitness_progression(history_rows, args.node_id)
    if history_rows:
        rendered.append("fitness_progression")

    all_rows = [r for rows in tiers.values() for r in rows]
    _render_top_strategies(all_rows, baseline, args.node_id, top_k=args.top_k)
    rendered.append("top_strategies")

    if all_rows:
        best = max(all_rows, key=lambda r: r["fitness"])
        for lat_col in latency_sources:
            if not (best.get(lat_col) and baseline.get(lat_col)):
                continue
            _render_baseline_comparison(best, baseline, args.node_id, latency_col=lat_col)
            rendered.append(f"baseline_comparison_{lat_col}")

    print(json.dumps({
        "rendered": rendered,
        "tiers_charted": target_tiers,
        "latency_sources": latency_sources,
        "total_strategies": len(all_rows),
        "baseline_strategy_id": "baseline",
    }, indent=2))


if __name__ == "__main__":
    main()
