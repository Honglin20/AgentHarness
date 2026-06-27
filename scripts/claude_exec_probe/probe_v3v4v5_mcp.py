"""V3 + V4 + V5: MCP stdio 连接 + handler 长阻塞 + tool_result 回流。

V3: claude 通过 --mcp-config 连上 echo server，调 echo 成功（block=0）
V4 ⭐: echo handler block 30s；claude 子进程等待不超时
V5: handler 返回固定字符串；claude 后续 message 引用该字符串

策略：
- 分两次跑 claude（先 V3 烟雾测，再 V4+V5 死活命题），便于诊断
- mcp-config 用临时文件
- echo server 行为通过 mcp_echo_server.log 验证（server 侧证据）
- claude 行为通过 stream-json 事件验证（client 侧证据）
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

CLI = "claude"
PROBE_DIR = Path(__file__).parent
ECHO_SERVER = PROBE_DIR / "mcp_echo_server.py"
ECHO_LOG = PROBE_DIR / "mcp_echo_server.log"
SERVER_NAME = "echo-server"
TOOL_NAME = "mcp__echo-server__echo"

BLOCK_SECONDS = 30  # V4 死活命题的等待时长


def write_mcp_config() -> Path:
    """写一个 mcp-config JSON，指向我们的 echo server。"""
    cfg = {
        "mcpServers": {
            SERVER_NAME: {
                "command": sys.executable,
                "args": [str(ECHO_SERVER)],
            }
        }
    }
    f = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", prefix="mcp-config-", delete=False, dir=str(PROBE_DIR)
    )
    json.dump(cfg, f, indent=2)
    f.close()
    return Path(f.name)


def run_claude(prompt: str, mcp_config: Path, timeout: int) -> tuple[subprocess.CompletedProcess, list[dict], float]:
    """跑一次 claude -p，启用 stream-json + MCP。prompt 走 stdin 避免 variadic flag 吞掉。"""
    cmd = [
        CLI, "-p",
        "--dangerously-skip-permissions",
        "--output-format", "stream-json",
        "--include-partial-messages",
        "--verbose",
        "--strict-mcp-config",
        "--mcp-config", str(mcp_config),
        "--allowed-tools", TOOL_NAME,
    ]
    print(f"\n  $ claude -p --output-format stream-json ... --allowed-tools {TOOL_NAME}  (prompt via stdin)")
    t0 = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, input=prompt)
    elapsed = time.time() - t0
    print(f"  exit={proc.returncode}  elapsed={elapsed:.1f}s  stdout_bytes={len(proc.stdout)}")
    if proc.stderr:
        # stderr 只打印尾巴，避免太长
        print(f"  stderr_tail={proc.stderr[-400:]!r}")

    events: list[dict] = []
    for ln in proc.stdout.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        try:
            events.append(json.loads(ln))
        except json.JSONDecodeError:
            pass
    return proc, events, round(elapsed, 1)


def find_events(events: list[dict], **kvargs) -> list[dict]:
    """简单的事件过滤器。"""
    out = []
    for ev in events:
        if all(ev.get(k) == v for k, v in kvargs.items()):
            out.append(ev)
    return out


def event_summary(ev: dict) -> str:
    """人类可读事件摘要，用于报告。"""
    t = ev.get("type", "?")
    sub = ev.get("subtype") or ev.get("name") or ""
    if t == "assistant" and "message" in ev:
        # message.content 是数组
        msg = ev["message"]
        content = msg.get("content", [])
        parts = []
        for c in content:
            if c.get("type") == "text":
                parts.append(f"text:{c.get('text', '')[:80]!r}")
            elif c.get("type") == "tool_use":
                parts.append(f"tool_use({c.get('name')}:{c.get('input')})")
        return f"assistant[{', '.join(parts)}]"
    if t == "user" and "message" in ev:
        msg = ev["message"]
        content = msg.get("content", [])
        parts = []
        for c in content:
            if c.get("type") == "tool_result":
                tc = c.get("content", "")
                if isinstance(tc, list):
                    tc = " ".join(str(x.get("text", "")) for x in tc if isinstance(x, dict))
                parts.append(f"tool_result:{str(tc)[:80]!r}")
            else:
                parts.append(str(c)[:80])
        return f"user[{', '.join(parts)}]"
    if t == "result":
        return f"result(is_error={ev.get('is_error')}, num_turns={ev.get('num_turns')}, cost=${ev.get('total_cost_usd', 0):.4f}, result={str(ev.get('result'))[:80]!r})"
    if t == "system":
        return f"system/{sub}"
    if t == "stream_event":
        return f"stream_event/{sub}"
    return f"{t}/{sub}"


# ---------------------------------------------------------------------------
# V3: MCP 连接 + 基本 tools/call roundtrip
# ---------------------------------------------------------------------------

def run_v3(mcp_config: Path) -> dict:
    print("\n=== V3: MCP stdio connect + basic echo roundtrip ===")
    marker = "hello-v3"
    prompt = (
        f'Call the echo tool with text="{marker}". '
        f'After receiving the tool result, output exactly the word DONE on its own line.'
    )
    proc, events, elapsed = run_claude(prompt, mcp_config, timeout=120)

    # 期望：能看到 assistant 含 tool_use(mcp__echo-server__echo, {text:hello-v3})
    # 后续 user 含 tool_result "echoed: hello-v3"
    # 最终 assistant 输出 DONE
    tool_uses = []
    tool_results = []
    final_texts = []
    for ev in events:
        if ev.get("type") == "assistant":
            for c in ev.get("message", {}).get("content", []):
                if c.get("type") == "tool_use":
                    tool_uses.append(c)
        elif ev.get("type") == "user":
            for c in ev.get("message", {}).get("content", []):
                if c.get("type") == "tool_result":
                    tc = c.get("content", "")
                    if isinstance(tc, list):
                        tc = " ".join(str(x.get("text", "")) for x in tc if isinstance(x, dict))
                    tool_results.append(str(tc))
        elif ev.get("type") == "result":
            r = ev.get("result", "")
            final_texts.append(str(r))

    print(f"  tool_uses={len(tool_uses)} tool_results={len(tool_results)}")
    for tu in tool_uses:
        print(f"    tool_use: name={tu.get('name')} input={tu.get('input')}")
    for tr in tool_results:
        print(f"    tool_result: {tr[:120]!r}")
    print(f"    final result: {final_texts[-1][:120]!r}" if final_texts else "    final result: <none>")

    saw_echo_call = any(tu.get("name") == TOOL_NAME for tu in tool_uses)
    saw_echo_response = any("echoed:" in tr for tr in tool_results)
    saw_done = any("DONE" in t for t in final_texts)
    passed = proc.returncode == 0 and saw_echo_call and saw_echo_response

    print(f"  -> {'PASS' if passed else 'FAIL'}  (saw_echo_call={saw_echo_call}, saw_echo_response={saw_echo_response}, saw_done={saw_done})")

    return {
        "name": "V3",
        "passed": passed,
        "exit_code": proc.returncode,
        "elapsed_s": elapsed,
        "saw_echo_call": saw_echo_call,
        "saw_echo_response": saw_echo_response,
        "saw_done_in_final": saw_done,
        "tool_use_count": len(tool_uses),
        "tool_result_count": len(tool_results),
        "tool_results_sample": tool_results[:2],
        "final_result_sample": final_texts[-1][:200] if final_texts else None,
        "event_timeline": [event_summary(ev) for ev in events],
    }


# ---------------------------------------------------------------------------
# V4 + V5: 长阻塞 + tool_result 回流到下一轮
# ---------------------------------------------------------------------------

def run_v4v5(mcp_config: Path) -> dict:
    print(f"\n=== V4 ⭐ + V5: handler blocks {BLOCK_SECONDS}s + result flows to next turn ===")
    marker = "marker-XYZ789"
    prompt = (
        f'Call the echo tool with text="{marker}" and block_seconds={BLOCK_SECONDS}. '
        f'After you receive the result, repeat the exact text returned by the tool. '
        f'Do not say anything else.'
    )

    # 清理 server 端日志，便于本次判断
    ECHO_LOG.unlink(missing_ok=True)

    # V4 timeout 留充足：30s block + ~10s cold start + ~10s 两轮 LLM call = ~50s 起步
    proc, events, elapsed = run_claude(prompt, mcp_config, timeout=BLOCK_SECONDS + 90)

    # === V4：claude 在 tools/call 到 tool_result 之间至少等了 BLOCK_SECONDS 秒 ===
    # 策略：从 stream-json 事件里找 tool_use 时间戳和 tool_result 时间戳
    # stream-json 事件本身没有 timestamp，但 partial 事件流可以近似
    # 更可靠：server 端 mcp_echo_server.log 有 CALL 时间和 returning 时间
    server_log = ECHO_LOG.read_text() if ECHO_LOG.exists() else ""
    print(f"  server_log_exists={ECHO_LOG.exists()} bytes={len(server_log)}")
    if server_log:
        for ln in server_log.splitlines()[-6:]:
            print(f"    server | {ln}")

    # 验证 server 行为：有 CALL + blocking + returning
    server_saw_call = "CALL echo" in server_log
    server_slept = f"blocking {BLOCK_SECONDS}s" in server_log
    server_returned = "echoed:" in server_log
    # 额外硬证据：从 server 日志时间戳算出真实 block 时长
    # 形如 "HH:MM:SS,mmm CALL echo ..." 与 "HH:MM:SS,mmm -> returning after X.XXs"
    import re as _re
    call_match = _re.search(r"(\d{2}:\d{2}:\d{2},\d{3}) CALL echo", server_log)
    ret_match = _re.search(r"(\d{2}:\d{2}:\d{2},\d{3})\s+-> returning after ([\d.]+)s", server_log)
    server_block_seconds = None
    if call_match and ret_match:
        def _parse_ts(s: str) -> float:
            h, m, rest = s.split(":")
            sec, ms = rest.split(",")
            return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000.0
        server_block_seconds = round(_parse_ts(ret_match.group(1)) - _parse_ts(call_match.group(1)), 3)
    server_returned_after_field = float(ret_match.group(2)) if ret_match else None

    # 验证 client 行为：claude 真的等了 ≥ BLOCK_SECONDS 秒
    # 用 wall-clock elapsed 时间近似：claude 子进程从启动到结束应 ≥ BLOCK_SECONDS
    elapsed_meets_threshold = elapsed >= BLOCK_SECONDS  # 至少等够 30s

    # 没有出现 timeout / aborted 错误
    result_events = [ev for ev in events if ev.get("type") == "result"]
    is_error = any(ev.get("is_error") for ev in result_events)
    api_error = any(ev.get("api_error_status") for ev in result_events)
    has_timeout_signal = (
        is_error
        or api_error
        or "timeout" in server_log.lower()
        or any("timeout" in json.dumps(ev).lower() for ev in events)
    )

    print(f"  server_saw_call={server_saw_call} server_slept={server_slept} server_returned={server_returned}")
    print(f"  client_elapsed={elapsed}s (>= {BLOCK_SECONDS}? {elapsed_meets_threshold})")
    print(f"  is_error={is_error} api_error={api_error} has_timeout_signal={has_timeout_signal}")

    v4_passed = (
        proc.returncode == 0
        and server_saw_call
        and server_slept
        and server_returned
        and elapsed_meets_threshold
        and not has_timeout_signal
        and server_block_seconds is not None
        and server_block_seconds >= BLOCK_SECONDS - 1  # 允许 1s 调度抖动
    )

    # === V5：claude 后续 message 引用了 echo 返回的字符串 ===
    expected_substr = f"echoed: {marker}"
    tool_results = []
    final_texts = []
    for ev in events:
        if ev.get("type") == "user":
            for c in ev.get("message", {}).get("content", []):
                if c.get("type") == "tool_result":
                    tc = c.get("content", "")
                    if isinstance(tc, list):
                        tc = " ".join(str(x.get("text", "")) for x in tc if isinstance(x, dict))
                    tool_results.append(str(tc))
        elif ev.get("type") == "result":
            final_texts.append(str(ev.get("result", "")))

    saw_expected_in_result = any(expected_substr in t for t in final_texts)
    saw_marker_anywhere = any(expected_substr in t for t in tool_results + final_texts)

    print(f"  expected_substr={expected_substr!r}")
    print(f"  saw_in_tool_result={any(expected_substr in t for t in tool_results)}")
    print(f"  saw_in_final_result={saw_expected_in_result}")

    v5_passed = saw_expected_in_result

    print(f"  -> V4 {'PASS' if v4_passed else 'FAIL'}  |  V5 {'PASS' if v5_passed else 'FAIL'}")

    return {
        "name": "V4+V5",
        "v4_passed": v4_passed,
        "v5_passed": v5_passed,
        "exit_code": proc.returncode,
        "elapsed_s": elapsed,
        "block_seconds_requested": BLOCK_SECONDS,
        "server": {
            "saw_call": server_saw_call,
            "slept": server_slept,
            "returned": server_returned,
            "block_seconds_observed": server_block_seconds,
            "returning_after_reported": server_returned_after_field,
        },
        "client": {
            "elapsed_meets_threshold": elapsed_meets_threshold,
            "is_error": is_error,
            "api_error": api_error,
            "has_timeout_signal": has_timeout_signal,
        },
        "v5": {
            "expected_substr": expected_substr,
            "saw_in_tool_result": any(expected_substr in t for t in tool_results),
            "saw_in_final_result": saw_expected_in_result,
            "saw_marker_anywhere": saw_marker_anywhere,
        },
        "event_timeline": [event_summary(ev) for ev in events],
        "server_log_tail": server_log.splitlines()[-8:],
    }


def main() -> int:
    print(f"Probe V3+V4+V5 starting; CLI={CLI}  ECHO_SERVER={ECHO_SERVER}")
    if not ECHO_SERVER.exists():
        print(f"ERROR: echo server not found at {ECHO_SERVER}", file=sys.stderr)
        return 2

    mcp_config = write_mcp_config()
    print(f"mcp-config written: {mcp_config}")
    print(f"config content:\n{mcp_config.read_text()}")

    v3 = run_v3(mcp_config)
    if not v3["passed"]:
        print("\n*** V3 FAIL — aborting before V4 (would waste 30+s) ***")
        report = {"v3": v3, "v4v5": None, "overall_passed": False}
        (PROBE_DIR / "report_v3v4v5.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
        return 1

    v4v5 = run_v4v5(mcp_config)
    overall = v3["passed"] and v4v5["v4_passed"] and v4v5["v5_passed"]

    report = {"v3": v3, "v4v5": v4v5, "overall_passed": overall}
    out_path = PROBE_DIR / "report_v3v4v5.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"\nReport written to {out_path}")
    print(f"\nOverall V3+V4+V5: {'PASS' if overall else 'FAIL'}")

    # 清理临时 mcp-config（保留以便 debug 时已写盘到 PROBE_DIR 内）
    try:
        mcp_config.unlink()
    except FileNotFoundError:
        pass
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
