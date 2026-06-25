"""V1 + V2: 基本 spawn + stream-json 格式验证。

V1: subprocess.Popen 拉起 `claude -p`，捕获 stdout，exit code 0 + 非空 stdout
V2: 加 stream-json flag，逐行 JSON 解析，能看到 system/init / assistant/text / result
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

PROMPT = "Reply with exactly the word: PONG"
CLI = "claude"


def run_v1() -> dict:
    """V1: 纯 text 输出，验证基本 spawn。"""
    print("\n=== V1: basic spawn (text output) ===")
    t0 = time.time()
    proc = subprocess.run(
        [CLI, "-p", "--dangerously-skip-permissions", PROMPT],
        capture_output=True,
        text=True,
        timeout=120,
    )
    elapsed = time.time() - t0
    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    print(f"  exit={proc.returncode}  elapsed={elapsed:.2f}s")
    print(f"  stdout={stdout!r}")
    if stderr:
        print(f"  stderr={stderr[:300]!r}")

    passed = proc.returncode == 0 and len(stdout) > 0
    print(f"  -> {'PASS' if passed else 'FAIL'}")
    return {
        "name": "V1",
        "passed": passed,
        "exit_code": proc.returncode,
        "elapsed_s": round(elapsed, 2),
        "stdout_len": len(stdout),
        "stdout_sample": stdout[:200],
        "stderr_sample": stderr[:300],
    }


def run_v2() -> dict:
    """V2: stream-json 输出，逐行解析，统计事件类型。"""
    print("\n=== V2: stream-json output ===")
    cmd = [
        CLI, "-p",
        "--dangerously-skip-permissions",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
        PROMPT,
    ]
    print(f"  cmd: {' '.join(cmd[:6])} ...")

    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    elapsed = time.time() - t0
    print(f"  exit={proc.returncode}  elapsed={elapsed:.2f}s  stdout_bytes={len(proc.stdout)}")

    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    print(f"  total_lines={len(lines)}")

    parsed_events: list[dict] = []
    parse_errors: list[str] = []
    for i, ln in enumerate(lines):
        try:
            obj = json.loads(ln)
            parsed_events.append(obj)
        except json.JSONDecodeError as e:
            parse_errors.append(f"line {i}: {e}: {ln[:120]!r}")

    print(f"  parsed_events={len(parsed_events)}  parse_errors={len(parse_errors)}")

    # 归类事件类型 —— stream-json 一般有 "type" 字段
    event_types: dict[str, int] = {}
    type_field_candidates = ("type",)
    for ev in parsed_events:
        for f in type_field_candidates:
            v = ev.get(f)
            if v is not None:
                key = f"{f}={v}"
                event_types[key] = event_types.get(key, 0) + 1
                break
        else:
            # 兜底：记录顶层 keys
            key = "unknown:" + ",".join(sorted(ev.keys())[:3])
            event_types[key] = event_types.get(key, 0) + 1

    print("  event_type_counts:")
    for k, v in sorted(event_types.items()):
        print(f"    {k}: {v}")

    # 通过标准：3 类基础事件可见 —— system/init, assistant text, result
    # 不同版本可能用不同字段名，先打印原始样本再判定
    has_init = any("init" in str(ev).lower() for ev in parsed_events[:5])
    has_text = any(
        ev.get("type") in ("assistant", "assistant_message")
        or ("message" in ev and ev.get("type") != "result")
        for ev in parsed_events
    )
    has_result = any(ev.get("type") == "result" for ev in parsed_events)

    print(f"  has_init_signal={has_init}  has_text_signal={has_text}  has_result={has_result}")

    # 真正的通过标准：JSON 解析全成功 + 至少看到 result 类事件 + 至少 3 个事件
    passed = (
        proc.returncode == 0
        and len(parse_errors) == 0
        and len(parsed_events) >= 3
        and has_result
    )
    print(f"  -> {'PASS' if passed else 'FAIL'}")

    # 保留前 3 个事件样本（截断）和最后 1 个（result）
    def _chop(o: dict) -> dict:
        s = json.dumps(o)
        return json.loads(s) if len(s) < 800 else {"_truncated_keys": list(o.keys()), "_len": len(s)}

    samples = {
        "first_event": _chop(parsed_events[0]) if parsed_events else None,
        "result_event": _chop(parsed_events[-1]) if parsed_events and has_result else None,
    }

    return {
        "name": "V2",
        "passed": passed,
        "exit_code": proc.returncode,
        "elapsed_s": round(elapsed, 2),
        "total_lines": len(lines),
        "parsed_events": len(parsed_events),
        "parse_errors": len(parse_errors),
        "event_type_counts": event_types,
        "has_init_signal": has_init,
        "has_text_signal": has_text,
        "has_result": has_result,
        "samples": samples,
        "stderr_sample": proc.stderr[-300:].strip(),
    }


def main() -> int:
    print(f"Probe V1+V2 starting; CLI={CLI}")
    v1 = run_v1()
    v2 = run_v2()
    report = {"v1": v1, "v2": v2}
    out_path = Path(__file__).parent / "report_v1v2.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nReport written to {out_path}")

    overall = v1["passed"] and v2["passed"]
    print(f"\nOverall V1+V2: {'PASS' if overall else 'FAIL'}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
