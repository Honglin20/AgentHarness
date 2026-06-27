#!/usr/bin/env python
"""profile_model.py — Profile an ONNX model (per-layer latency + params).

Used by scout baseline_runner to produce baseline_profile.json.
planner / reporter read it for hypothesis targeting + architecture suggestions.

Default implementation uses onnxruntime session profiling.

**Replacement policy**: replace profile_onnx() body with your own profiler
(vendor SDK, hardware simulator, analytical model). Signature + return schema
are locked for downstream compatibility.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def profile_onnx(onnx_path: str | Path, runs: int = 100) -> dict:
    """Profile an ONNX model.

    Args:
        onnx_path: path to .onnx file
        runs: inference runs for averaging latency

    Returns:
        On success:
            {
                "total_latency_ms": float,        # sum of per-layer latency
                "total_params": int,
                "total_flops": int | None,        # None in default impl
                "layers": [
                    {
                        "name": str,
                        "op_type": str,
                        "latency_ms": float,
                        "latency_pct": float,     # share of total_latency_ms
                        "params": int,             # 0 in default impl
                        "flops": int | None        # None in default impl
                    },
                    ...
                ],
                "top_latency_layers": [...],      # top 3 by latency_pct
                "top_flop_layers": [],             # empty (FLOPs not measured)
                "profile_source": "onnxruntime",
                "runs": int
            }
        On error: {"error": "<msg>"}
    """
    onnx_path = str(onnx_path)

    try:
        import onnx
        from onnx import numpy_helper
    except ImportError as e:
        return {"error": f"onnx package required: {e}"}

    try:
        import onnxruntime as ort
        import numpy as np
    except ImportError as e:
        return {"error": f"onnxruntime package required: {e}"}

    # 1. Load model + count total params
    try:
        model = onnx.load(onnx_path)
    except Exception as e:
        return {"error": f"onnx.load failed: {e}"}

    total_params = sum(
        numpy_helper.to_array(w).size for w in model.graph.initializer
    )
    op_type_map = {n.name: n.op_type for n in model.graph.node}

    # 2. Build ort session with profiling
    sess_options = ort.SessionOptions()
    sess_options.enable_profiling = True
    sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL

    try:
        session = ort.InferenceSession(
            onnx_path, sess_options=sess_options,
            providers=["CPUExecutionProvider"]
        )
    except Exception as e:
        return {"error": f"ort.InferenceSession failed: {e}"}

    # 3. Build feeds (dummy inputs matching model's input specs)
    feeds = {}
    for inp in session.get_inputs():
        shape = [d if isinstance(d, int) else 1 for d in inp.shape]
        dtype = np.int64 if "int" in str(inp.type).lower() else np.float32
        feeds[inp.name] = np.random.randn(*shape).astype(dtype)

    # 4. Warm-up (flushes any cold-start overhead)
    for _ in range(min(5, runs)):
        session.run(None, feeds)
    session.end_profiling()  # discard warm-up profile

    # Re-setup for measurement
    sess_options2 = ort.SessionOptions()
    sess_options2.enable_profiling = True
    sess_options2.graph_optimization_level = ort.GraphOptimizationLevel.ORT_DISABLE_ALL
    session2 = ort.InferenceSession(
        onnx_path, sess_options=sess_options2,
        providers=["CPUExecutionProvider"]
    )
    for _ in range(runs):
        session2.run(None, feeds)
    profile_file = session2.end_profiling()

    # 5. Parse profile JSON (Chrome trace event format)
    try:
        profile_data = json.loads(Path(profile_file).read_text())
    except Exception as e:
        return {"error": f"failed to parse ort profile: {e}"}

    # 6. Aggregate per-node latency (cat == "Node")
    node_dur_ns: dict[str, int] = {}
    for entry in profile_data:
        if entry.get("cat") == "Node":
            name = entry.get("name", "")
            node_dur_ns[name] = node_dur_ns.get(name, 0) + int(entry.get("dur", 0))

    total_dur_ns = sum(node_dur_ns.values())

    layers = []
    for name, dur_ns in node_dur_ns.items():
        op_type = op_type_map.get(name, "")
        clean_name = name
        # ort often names entries as "OpType:kernel_name"; split if so
        if ":" in name:
            prefix, _, rest = name.partition(":")
            if not op_type:
                op_type = prefix
            clean_name = rest or name

        latency_ms = (dur_ns / runs) / 1e6  # ns → ms (per-inference avg)
        layers.append({
            "name": clean_name,
            "op_type": op_type,
            "latency_ms": latency_ms,
            "latency_pct": (dur_ns / total_dur_ns * 100) if total_dur_ns > 0 else 0.0,
            "params": 0,
            "flops": None,
        })

    layers.sort(key=lambda x: x["latency_ms"], reverse=True)

    # Renormalize pct to sum to 100
    total_latency_ms = sum(l["latency_ms"] for l in layers)
    if total_latency_ms > 0:
        for l in layers:
            l["latency_pct"] = l["latency_ms"] / total_latency_ms * 100

    return {
        "total_latency_ms": total_latency_ms,
        "total_params": total_params,
        "total_flops": None,
        "layers": layers,
        "top_latency_layers": layers[:3],
        "top_flop_layers": [],
        "profile_source": "onnxruntime",
        "runs": runs,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--onnx", required=True)
    p.add_argument("--out", default=None,
                   help="write profile JSON to this path; if omitted, print to stdout")
    p.add_argument("--runs", type=int, default=100,
                   help="inference runs for averaging latency")
    args = p.parse_args()

    result = profile_onnx(args.onnx, runs=args.runs)

    if "error" in result:
        print(json.dumps(result), file=sys.stderr)
        sys.exit(1)

    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2))
        top = result.get("top_latency_layers", [])
        print(json.dumps({
            "total_latency_ms": result["total_latency_ms"],
            "total_params": result["total_params"],
            "top_layer": top[0] if top else None,
            "out_path": args.out,
        }))
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
