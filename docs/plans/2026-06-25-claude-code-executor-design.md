# Claude Code 作为 harness 可切换执行后端 — 设计 + 验证计划

- **日期**: 2026-06-25
- **类型**: 设计文档（pre-implementation）+ 验证计划
- **触发**: 用户希望「把 agent MD 直接交给 claude 命令执行」，解决框架与 Claude Code 生态割裂；要求 per-agent 可在 pydantic-ai 与 claude-code 之间切换
- **状态**: 设计阶段，**未实现**；待 Phase 1 验证通过后展开详细设计与实施计划
- **关联**: [`docs/plans/2026-06-23-harness-vs-claudecode-gap-audit.md`](2026-06-23-harness-vs-claudecode-gap-audit.md)（之前的差距审查）

---

## 1. 背景与动机

### 1.1 当前架构（基线，事实）

- `workflow.json` 声明 DAG（nodes = agents，edges = `after` / `on_pass` / `on_fail`）；每个 agent 有 `tools` / `result_type_schema` / `model` / `retries`
- `workflows/<wf>/agents/*.md` 是 agent system prompt（frontmatter + body）
- harness 把 DAG 编译成 LangGraph；每个 node = 一个 pydantic-ai Agent
- agent 间数据传递**已是文件契约**：`<session_dir>/<file>.json`（baseline.json / metrics.json / ...）+ `state.outputs[agent_name]` 双轨
- ask_user 当前链路：tool → event_bus.emit → WS → 前端 AgentQuestionCard → POST answer → tool 拿到答案继续（`harness/tools/ask_user.py`）
- 前端订阅 WS 事件（AgentTextDelta / AgentToolCall / NodeStarted / ...）渲染对话流/DAG/chart/todo/budget

### 1.2 用户诉求

1. Claude Code 作为**可切换的执行后端**（per-agent 选 pydantic-ai 或 claude-code）
2. 复用 agent MD prompt（直接喂给 claude）
3. 复用工具——**只做增量，不做替换**：bash/grep/glob 用 Claude 原生，仅 ask_user/TodoTool/render_chart 这类前端联动工具走桥接
4. ask_user 仍能桥接到前端
5. 前端展示统一

### 1.3 已排除的方案

经差距审查（2026-06-23），单纯把 harness 抄成「Claude Code 风格」成本高且永远落后。改为：直接用 Claude Code 作为执行后端，harness 专注 DAG/前端/契约层。

---

## 2. 方案选择

### 2.1 候选方案对比

| 方案 | 描述 | 结论 |
|---|---|---|
| **A. 节点级可插拔执行器** | DAG 不变；每 agent 可声明 `executor: "claude-code"`；spawn `claude -p` 子进程执行 | ✅ **选中** |
| B. 生成 Claude Code 原生工程 | workflow.json → `.claude/commands/*` + `.claude/agents/*`；抛弃 harness DAG/前端 | ❌ 抛弃已建好的 DAG/前端/replay/budget |
| C. Claude Code 作为 pydantic-ai 工具 | pydantic-ai 主导，多一个 `delegate_to_claude` 工具 | ❌ 没真正统一，Claude tool-loop 优势用不上 |

**选 A 的理由**：
1. 已建好的 DAG 引擎 / 前端可视化 / 断点续传 / budget envelope / schema 强校验是护城河，Claude Code 没有，不该扔
2. per-agent 切换是用户明确需求，方案 A 天然支持
3. 文件契约（`<session_dir>/*.json`）已存在，Claude Code 兼容无成本

### 2.2 关键决策

| 决策点 | 选项 | 选择 | 理由 |
|---|---|---|---|
| 进程模型 | 每节点子进程 / 每 workflow 长会话 / 阶段级长会话 | **每节点子进程** | 最干净、零跨 agent 状态污染、per-agent 切换天然；冷启动 1-3s 可接受 |
| sub_agent 工具 | harness MCP 桥接 / Claude 原生 Task | **Claude 原生 Task** | 用户指定；Claude 内部并行调度更高效；牺牲一些 DAG 可见性（用 stream-json 翻译补） |
| 工具桥接策略 | 全桥接 / 仅增量 | **仅增量** | bash/Read/Grep/Glob/Edit/Write/WebSearch 用原生；ask_user/TodoTool/render_chart 桥接（前端联动必需） |
| 工具桥接机制 | MCP server / hooks / 混合 | **MCP server (stdio)** | MCP tool handler 是 async 可无限期 block——天然适合 ask_user |
| 结果提取 | 末消息 JSON / 侧文件 / 双轨 | **末消息 JSON + 校验**（待 V7 验证） | 镜像 pydantic-ai result_type 语义；失败用 `--resume` 注入 feedback 重试 |

---

## 3. 终态架构

### 3.1 工具映射（增量桥接原则）

| 工具 | Claude 原生 | harness 桥接（MCP） | 说明 |
|---|---|---|---|
| Bash / Read / Grep / Glob / Edit / Write / WebSearch | ✅ | ❌ | stream-json 已报告调用+结果，翻译即可 |
| **ask_user** | 无 | ✅ MCP | 前端 AgentQuestionCard |
| **TodoTool** | 有 TodoWrite（事件不可见） | ✅ MCP | 前端 StepRow / iteration 分组依赖 todo.updated；用原生等于丢这层 UI |
| **render_chart** | 无 | ✅ MCP | 前端图表面板 |
| **sub_agent** | 有 Task | ❌ 用原生 | 用户指定；Claude 内部调度 |

桥接工具由 harness 启的 stdio MCP server 暴露，每个 claude 子进程通过 `--mcp-config` 连一次。

### 3.2 stream-json → event_bus 翻译

**核心结论：前端零改动。**

`claude -p --output-format stream-json --include-partial-messages --verbose` stdout（每行一个 JSON）→ 翻译器逐行消费 → emit 到现有 event_bus：

| Claude Code stream-json | harness event | 前端组件 |
|---|---|---|
| `system/init` | `node.started` (含 tools, model, iteration) | 节点 running + 工具列表 |
| `assistant/text` 增量 | `agent.text_delta` | 对话流式气泡 |
| `assistant/thinking` 增量 | `agent.thinking_delta` | thinking 折叠区 |
| `assistant/tool_use` | `agent.tool_call` (含 tool_call_id) | 工具调用卡片 |
| `user/tool_result` | `agent.tool_result` (含 tool_call_id) | 卡片结果填充 |
| bash `tool_result` partial | `agent.tool_output_delta` | `toolStreamingOutput` 字段（已有） |
| `result/success` | `node.completed` (含 token, cost) | 节点 success |
| `result/error` | `node.failed` (含 retry 决策) | 节点 failed + 重试 |

DAG 图 / retry / token budget / 断点续传 **全部不动**。

### 3.3 ask_user 桥接（8 步链路）

```
1. Claude 子进程决定调 ask_user
   ↓ MCP RPC: tools/call ask_user {question, options, ...}

2. harness MCP handler (async):
   ├─ 生成 question_id
   ├─ event_bus.emit("agent.question", payload)
   ├─ pending_questions[question_id] = asyncio.Future()
   └─ await future   ← block，Claude 子进程同步 block

3. event_bus → WS push → 前端 ConversationStore.addQuestion()
   前端 AgentQuestionCard 渲染选项

4. 用户点选项 / 自定义 → POST /api/runs/<id>/question/<qid>/answer

5. backend route: pending_questions[qid].set_result(answer)

6. MCP handler 的 await future 解出 → return string 给 Claude

7. Claude 收 tool_result，继续 turn

8. event_bus emit agent.question_answered → 前端问题卡片转 "answered"
```

**为什么干净**：
- MCP handler 是 async，可无限期 block——天然「子进程内等用户」语义
- event_bus → WS → 前端 → POST → resolve future 这条链路与现有 pydantic-ai ask_user **完全一致**，Python 实现零改动，只换 wrapper
- 前端不知道后端是 pydantic-ai 还是 Claude Code

**边界**：
- 用户关浏览器：WS disconnect → `future.set_result("User disconnected")` → Claude 自判（复用现有 `TIMEOUT_MESSAGE` 机制）
- 用户取消 run：SIGTERM 子进程，future cancelled
- 同节点多次 ask_user：每次新 question_id，串行 await

### 3.4 结果提取 + schema 校验

- Claude 系统提示里要求「最终消息必须是合法 JSON 且匹配 schema」
- harness 解析 `result.result` 字段为 JSON → 校验 `result_type_schema`
- 失败 → `--resume <session_id>` 注入 schema 错误 feedback → Claude 重试（镜像现有 schema-retry）

### 3.5 per-agent 切换机制

`workflow.json` 每个 agent 加字段：

```json
{
  "name": "project_analyzer",
  "executor": "claude-code",   // 默认 "pydantic-ai"
  "after": [],
  "tools": ["bash", "grep", "ask_user"],
  ...
}
```

切换 = 改一个字段。DAG 引擎看 `executor` 字段分派到 pydantic-ai executor 或 claude-code executor。

---

## 4. 验证计划

### 4.1 验证策略

**核心假设（必须先验证）**：`claude -p` 在调用 MCP 工具时会**无限期等待** tool response（没有内部超时）。

如果这个假设不成立，ask_user 这种长阻塞场景死，整个方案 A 死，回退到方案 C 或重新设计。

### 4.2 Phase 1 — 存在性验证（任一失败 → 方案 A 死）

| # | 验证点 | 怎么验 | 通过标准 |
|---|---|---|---|
| **V1** | `claude -p` 基本可被 Python subprocess 拉起并捕获 stdout | `subprocess.Popen(["claude","-p","say hi"], stdout=PIPE)` | 非空 stdout，exit code 0 |
| **V2** | stream-json 输出格式符合预期 | 加 `--output-format stream-json --verbose --include-partial-messages` | 逐行 JSON 解析成功；能看到 `system/init` / `assistant/text` / `result` 三类基础事件 |
| **V3** | claude 能通过 `--mcp-config` 连上 stdio MCP server | 最小 MCP server（echo 工具），prompt 要求 claude 调 echo | claude 发出 `tools/call`，server 收到 |
| **V4** ⭐ | **MCP handler 可 block ≥30s 且 claude 会等** | echo handler `time.sleep(30)` 再返回 | claude 子进程 30s 内不退出/不报 timeout；30s 后拿 result 继续 |
| **V5** | tool response 正确回流到 claude 下一轮 | V4 handler 返回 `"user said: YES"`，看 claude 后续文本是否引用 | claude 下一条 assistant message 含 "YES" |

**V4 是死活命题。**

### 4.3 Phase 2 — 功能验证（Phase 1 过了才做）

| # | 验证点 | 怎么验 | 通过标准 |
|---|---|---|---|
| **V6** | ask_user 端到端模拟 | ask_user MCP tool；handler emit event + 挂 future；测试代码 5s 后 `future.set_result("user picked B")` | Claude 收 "user picked B" 并继续；事件 payload 符合 `AgentQuestionPayload` schema |
| **V7** | 结果提取 + schema 校验 + `--resume` 重试 | 要求 Claude 输出严格 JSON `{"summary": "...", "count": int}`；故意首次失败；解析失败后 `--resume` 注入 feedback | 第一次 parse 失败 → 注入 → 第二次合法 → 校验过 |
| **V8** | 原生 Task 工具在 `-p` 下可用 | `.claude/agents/child.md`；prompt 要求 Claude 调 Task 委托 | stream-json 能看到 child agent 的 tool_use/tool_result；child 结果回流 parent |
| **V9** | `--permission-mode bypassPermissions` 真的跳过所有 prompt | 触发权限的命令（如 `rm`） | 不卡权限提示，直接执行 |
| **V10** | stream-json 翻译层完整覆盖事件类型 | 复合 prompt 触发 bash + Read + ask_user + Task | 翻译出的 event 序列与 pydantic-ai 节点的类型一致 |

### 4.4 Phase 3 — 打磨验证（不阻塞落地）

| # | 验证点 | 通过标准 |
|---|---|---|
| **V11** | bash stdout 实时流式 | 前端 toolStreamingOutput 看到 1/2/3 逐行出现 |
| **V12** | token / cost 报告 | `result.usage` 字段填进 `AgentTokenUsage` schema |
| **V13** | 信号 / 超时 / 取消 | SIGTERM 后子进程干净退出，无 zombie；future cancelled |
| **V14** | 并发同名工具调用 | 两个 question_id 不串味儿；两个 future 独立 resolve |
| **V15** | thinking delta（推理模型） | `assistant/thinking` 翻译为 `agent.thinking_delta` |

### 4.5 测试脚手架（待实现）

```
docs/plans/2026-06-25-claude-code-executor/
├── verification-plan.md          ← 本文档 §4 复制 + 风险/回退
└── v1-basic-spawn.md ... v15-*.md ← 每个验证点一份小抄

scripts/claude_exec_probe/        ← 一次性验证脚本（验完归档/删除）
├── mcp_echo_server.py            ← V3-V5 用
├── mcp_ask_user_server.py        ← V6/V14 用
├── run_v1_basic.py
├── run_v4_blocking.py            ⭐
├── run_v6_ask_user_e2e.py
├── run_v7_resume_retry.py
└── README.md                     ← 每个脚本对应哪个 V
```

每个 V 一份可独立运行的 Python 脚本，输出 PASS/FAIL + 证据（原始 stdout 片段）。

---

## 5. 风险 + 回退

| 风险 | 概率 | 回退方案 |
|---|---|---|
| **V4 失败**：claude -p 对 MCP 工具有内部超时 | 中 | ask_user 改 async 模式：MCP 立即返回 `pending_id`，Claude 用 `check_answer` 轮询；或回退方案 C |
| **V8 失败**：Task 工具在 -p 下不可用 / 需要 TTY | 低 | sub_agent 改回 MCP 桥接 |
| **V11 失败**：stream-json 不流式 bash 输出 | 中 | 接受一次性 dump，前端 toolStreamingOutput 字段空着；不阻塞 |
| **V7 失败**：`--resume` 不带回 tool call 历史 | 低 | 改用「重新跑 + prompt 里写上次错」无状态重试 |
| stream-json schema 跨版本不稳 | 中 | 翻译器写防御性解析 + claude 版本变化时报警 |

---

## 6. 待办与下一步

### 当前状态
- ✅ 设计方案 A 选定
- ✅ 关键决策记录（per-node 子进程 / 原生 Task / 仅增量桥接 / MCP 桥接 / 末消息 JSON）
- ✅ 验证点拆解（V1-V15）
- ⏸ **等待用户批准后**实现 Phase 1 验证脚本

### 下一步
1. 实现 Phase 1 验证脚本（V1 / V3 / V4，可加 V2 / V5）
2. 跑通后下结论：方案 A 可行 / 不可行
3. 若可行 → 展开 §3 各节详细设计（MCP server 接口、stream-json 翻译器、executor 字段处理、错误恢复）
4. 详细设计后 → 进入实施计划（writing-plans skill）

### 不在本次范围
- 不实现生产代码（harness 改动 / 前端改动）
- 不动现有 pydantic-ai 执行路径（claude-code 是新增 executor，不是替换）
- 不抛弃任何现有 harness 能力（DAG / 前端 / replay / budget / schema 全保留）
