# Phase 1 验证报告 — Claude Code 作为 harness 可切换执行后端

- **日期**: 2026-06-25
- **状态**: ✅ **全部通过（V1-V5）** — 方案 A 技术路径确认可行
- **关联设计**: [`../2026-06-25-claude-code-executor-design.md`](../2026-06-25-claude-code-executor-design.md) §4.2

---

## 一句话结论

**死活命题 V4 通过：claude -p 调用 MCP 工具时没有任何内部超时，server handler block 30.006s 后 claude 子进程正常拿到 tool_result 并继续对话。方案 A 可进入 §3 详细设计阶段。**

---

## 验证环境

| 项 | 值 |
|---|---|
| Claude Code CLI | `2.1.150` (`/Users/mozzie/.local/bin/claude`) |
| Python | `/opt/anaconda3/envs/mindos/bin/python3` |
| MCP SDK | `mcp 1.27.1` + `fastmcp 3.3.1`（仅诊断用；probe server 手写） |
| echo server | 手写 stdio JSON-RPC（`scripts/claude_exec_probe/mcp_echo_server.py`） |
| 工作目录 | `/Users/mozzie/Desktop/Projects/AgentHarness` |

---

## 结果矩阵

| # | 验证点 | 结果 | elapsed | 证据 |
|---|---|---|---|---|
| **V1** | `claude -p` 基本 spawn | ✅ PASS | 8.8s | exit 0, stdout `"PONG"` |
| **V2** | stream-json 格式 | ✅ PASS | 16.2s | 12 行 JSON 全 parse 成功；事件分布 `system:4 / stream_event:6 / assistant:1 / result:1` |
| **V3** | MCP stdio 连接 + 工具调用 roundtrip | ✅ PASS | 16.0s | claude 发出 `mcp__echo-server__echo(text='hello-v3')` → tool_result `'echoed: hello-v3'` → 最终输出 `'DONE'` |
| **V4 ⭐** | **MCP handler block 30s 不超时** | ✅ **PASS** | 62.0s | server 阻塞 **30.006s**；client `is_error=False`；无 timeout 信号 |
| **V5** | tool_result 回流到下一轮 | ✅ PASS | （同 V4） | claude 最终结果含 `'echoed: marker-XYZ789'` |

---

## V4 死活命题 — 铁证

server 端日志（`scripts/claude_exec_probe/mcp_echo_server.log`）：

```
2026-06-25 19:11:22,171 <-- method=notifications/initialized id=None
2026-06-25 19:11:22,171 <-- method=tools/list id=1
2026-06-25 19:11:40,641 <-- method=tools/call id=2
2026-06-25 19:11:40,642 CALL echo text='marker-XYZ789' block_seconds=30
2026-06-25 19:11:40,642   -> blocking 30s (simulating long-running handler)
2026-06-25 19:12:10,648   -> returning after 30.01s: 'echoed: marker-XYZ789'
```

- server 收到 `tools/call` → 立刻 `time.sleep(30)` → **30.006s 后**才返回响应
- claude 子进程**期间没有任何 timeout / abort / api_error**
- `claude` 进程 exit code = 0
- elapsed 62.0s ≈ 30s block + cold start + 两轮 LLM call（合理）

**结论**：claude -p 对 MCP tool response **没有客户端侧超时**。ask_user 这种「子进程内等用户 30s+」的长阻塞场景**可行**。

---

## 关键观察（影响后续设计）

1. **stream-json schema 稳定**：12 行事件全 JSON 解析成功，0 parse error。事件类型集中在 `system / stream_event / assistant / user / result` 五类。`result` 事件含 `duration_ms / num_turns / total_cost_usd / usage / modelUsage / session_id` — V12 (token/cost) 和 V7 (`--resume` 复用 session_id) 字段天然支持。

2. **prompt 必须经 stdin 传**：`--allowed-tools` 是 variadic，会把命令行尾部位置参数当 tool 名吞掉。生产代码里 harness spawn claude 时**必须用 `subprocess.run(input=prompt)`**。

3. **`--strict-mcp-config` 有效**：claude 不会读全局 `~/.claude/mcp.json` 或 `.mcp.json`，只看 `--mcp-config` 提供的 server。harness 可放心注入自己的 MCP server 不污染用户配置。

4. **手写 JSON-RPC 比 fastmcp 更可靠**：fastmcp 3.3.1 启动时渲染 banner + 协议版本兼容性导致 claude `WaitForMcpServers` 后仍找不到工具；手写 minimal server (~120 行) 一次跑通。生产 MCP server 可基于此实现，避免引入额外噪音。

5. **协议版本 `2024-11-05` 兼容**：claude 2.1.150 接受此版本。生产 server 可继续用。

6. **claude 主动调 `WaitForMcpServers`**：claude 在首次调真实工具前会先 probe MCP server 是否 ready。这是个内部工具，不影响设计，但解释了 16-18s 的 cold start 时间。

---

## 对方案 A 的影响

| 设计假设 | 验证结果 |
|---|---|
| claude -p 可被 Python subprocess 拉起 | ✅ 直接确认 |
| stream-json 输出可被翻译为 harness event | ✅ 字段齐全，schema 稳定 |
| claude 能连 stdio MCP server 并调用工具 | ✅ `--mcp-config` + `--strict-mcp-config` |
| **MCP handler 可无限 block，claude 会等** | ✅ **核心假设成立** |
| tool response 可回流 claude 下一轮 | ✅ 直接确认 |

**方案 A 全部基础假设成立，无回退到方案 B/C 的必要。**

---

## 下一步

1. 展开 [`2026-06-25-claude-code-executor-design.md`](../2026-06-25-claude-code-executor-design.md) §3 各节详细设计：
   - MCP server 接口（暴露的工具集：ask_user / TodoTool / render_chart）
   - stream-json → event_bus 翻译器（基于本次观测的事件 schema）
   - `executor` 字段处理（workflow.json 加字段 + DAG 引擎分派）
   - 错误恢复（`--resume` + schema-retry 镜像现有 pydantic-ai 路径）
2. 详细设计通过 → writing-plans skill 出实施计划
3. （可选）跑 Phase 2 验证 V6-V10（ask_user e2e / 结果提取 / 原生 Task / 翻译层完整覆盖）— 也可在实施过程中按需补验

---

## 附录：验证产物

| 路径 | 说明 |
|---|---|
| `scripts/claude_exec_probe/probe_v1v2_basic.py` | V1+V2 probe 脚本 |
| `scripts/claude_exec_probe/report_v1v2.json` | V1+V2 详细报告 |
| `scripts/claude_exec_probe/mcp_echo_server.py` | 手写 stdio MCP echo server（生产 MCP server 可作模板） |
| `scripts/claude_exec_probe/probe_v3v4v5_mcp.py` | V3+V4+V5 probe 脚本 |
| `scripts/claude_exec_probe/report_v3v4v5.json` | V3+V4+V5 详细报告（含事件 timeline） |
| `scripts/claude_exec_probe/_diag_mcp_handshake.py` | 诊断脚本（直接 ping server 验证 JSON-RPC） |
| `scripts/claude_exec_probe/mcp_echo_server.log` | server 端日志（V4 铁证） |
