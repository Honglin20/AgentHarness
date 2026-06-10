# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

---

## 常用命令

### 安装
```bash
python install.py          # 交互式安装
python install.py --quick  # 非交互式（使用环境变量）
```

### 运行
```bash
# Web UI（后端同时提供 API 和静态前端）
bash examples/launch_ui.sh

# 或手动启动
python -m uvicorn server.app:app --host 0.0.0.0 --port 8000

# 前端开发模式（需要先启动后端）
cd frontend && npm run dev  # http://localhost:3000

# 构建前端
cd frontend && npm run build
```

### 部署注意
- `next.config.js` 配置 `output: "export", distDir: "out"`，构建产物在 `frontend/out/`
- 服务器从 `frontend/out/` 提供静态文件
- **前端源码改动后，必须 `cd frontend && npm run build`，然后将 `frontend/out/` 的变更一起提交并推送**
- 仅推送源码不推送构建产物 = 部署了旧代码

### 测试
```bash
pytest                         # 跳过慢速测试（不调用 LLM/MCP）
pytest -m slow                 # 包含慢速测试
pytest tests/harness/engine/   # 单模块测试
```

### Python 调试
```bash
python -c "from harness.api import Agent, Workflow; ..."
```

---

## 高层架构

### 双引擎设计
- **LangGraph (macro)**: DAG 拓扑编排、状态流转、并发依赖（fan-in/out）、checkpoint 持久化
- **Pydantic AI (micro)**: 单节点内 Agent 执行、prompt 构造、tool 调用循环、结构化输出、自动重试

### 三层上下文模型
- `inputs`: 用户输入，贯穿所有节点（自动注入为 `## Task`）
- `prompt`: Agent 人设（从 `workflows/<wf>/agents/<name>.md` 读取，作为 system_prompt）
- `upstream_outputs`: 上游 Agent 输出（自动注入为 `## Output from X`）

### EventBus 事件总线
- 进程级单例，pub/sub 模式
- WebSocket handler 订阅 → 推送到前端 zustand stores
- 关键事件：`workflow.started/completed`, `node.started/completed/failed`, `agent.text_delta`, `chart.render`, `chat.question/answer`

---

## 目录结构

```
workflows/                      # 工作流定义（每 workflow 一目录）
├── _shared/                    # 共享资源
│   ├── agents/                 # 框架级共享 agent（如 runner.md）
│   └── scripts/                # 跨 workflow 共享脚本
└── <name>/                     # 私有 workflow
    ├── workflow.json           # Agent 定义 + DAG 拓扑
    ├── agents/                 # 私有 agent MD
    └── scripts/                # 私有脚本

harness/                        # 核心框架
├── api.py                      # Agent, Workflow, WorkflowResult
├── config.py                   # configure(), .env 自动加载
├── engine/                     # LangGraph + Pydantic AI
│   ├── macro_graph.py          # DAG 编译为 StateGraph
│   └── llm_client.py           # LLM 客户端管理（httpx, provider, model）
├── compiler/                   # Markdown 解析 + DAG 构建
│   ├── md_parser.py            # YAML frontmatter + prompt 提取
│   └── dag_builder.py          # 依赖解析 + 拓扑排序 + 循环检测
├── tools/                      # 工具系统（**注意：包含两类来源，见下方"工具来源"**）
│   ├── ask_user.py             # ask_user: 结构化提问（单选/多选/自由输入）
│   ├── ask_human.py            # ask_human: 旧版薄壳，转调 ask_user
│   ├── _human_io.py            # 共享 Future 注册表（ask_user/ask_human 共用）
│   ├── bash.py                 # bash: 执行 shell 命令
│   ├── todo.py                 # todo: agent 驱动的步骤规划
│   ├── mcp_bridge.py           # MCP 桥接：把外部 MCP server 的工具适配进 Pydantic AI
│   ├── catalog.py              # ToolCatalogService：启动时连接 MCP server，构建完整工具目录
│   ├── defaults.py             # setup_default_mcp / setup_codegraph_mcp：默认 MCP server 配置
│   ├── chart.py                # 图表渲染（非 tool，纯函数）
│   └── tool_registry.py        # 工具注册表
└── extensions/                 # 扩展系统
    ├── eval/                   # EvalJudge: 自动评审 + 评分 + 重试（GraphMutator）
    ├── compact/                # AutoCompact: 对话压缩（Middleware）
    └── plugins/                # Hook plugins（EvalChartPlugin, AgentTracePlugin 等）

server/                         # FastAPI 服务
├── app.py                      # FastAPI 应用 + lifespan
├── routes.py                   # REST 路由
├── ws_handler.py               # WebSocket 事件处理
├── runner.py                   # WorkflowRunner（后台并发执行管理）
└── event_bus.py                # EventBus 单例

frontend/                       # Next.js 14 Web UI
└── src/
    ├── stores/                 # Zustand 状态管理
    │   ├── workflowStore.ts    # DAG 状态、节点高亮
    │   ├── conversationStore.ts # 消息流、chat.answer
    │   ├── outputStore.ts      # 文本渲染、chart
    │   └── runHistoryStore.ts  # 历史运行记录
    └── components/
        ├── dag/                # React Flow DAG 面板
        ├── chat/               # Chat UI
        └── sidebar/            # RunHistoryList

runs/                           # 运行记录持久化（{run_id}.json）
benchmarks/                     # Benchmark 评测定义 + 结果
```

---

## 工具来源（重要，避免重复造轮子 / 误判"工具不存在"）

项目的 agent 可用工具**来自两个来源**，不要只看 `harness/tools/*.py`：

### 1. 内置 Python 工具（`harness/tools/*.py`）
- `bash` — 执行 shell 命令
- `ask_user` / `ask_human` — 结构化提问
- `chart` — 图表渲染（非 tool，纯函数，由 agent 输出 `__HARNESS_CHART__:` 触发）
- `todo` / `todo_reminder` — agent 驱动的步骤规划
- `grep_glob` — 简化版 grep
- `sub_agent` — 子 agent 调用

### 2. MCP 远程工具（启动时由 `catalog.py` 连接，**不在 `harness/tools/` 里**）
**默认连接两个 MCP server**（见 `harness/tools/defaults.py` 的 `setup_default_mcp` / `setup_codegraph_mcp`）：

| MCP server | 包名 | 提供的工具 |
|------------|------|-----------|
| **filesystem** | `@modelcontextprotocol/server-filesystem` | `read_text_file`、`write_file`、`edit_file`、`create_directory`、`list_directory`、`directory_tree`、`move_file`、`search_files`、`get_file_info`、`list_allowed_directories` |
| **codegraph** | `codegraph serve --mcp`（或 `@colbymchenry/codegraph`） | `codegraph_search`、`codegraph_context`、`codegraph_callers`、`codegraph_callees`、`codegraph_impact`、`codegraph_node`、`codegraph_explore`、`codegraph_trace`、`codegraph_files`、`codegraph_status` |

> **判定工具是否存在的正确方式**：
> 1. 看 `harness/tools/*.py`（内置工具）
> 2. **还要**看 `harness/tools/defaults.py` 接入了哪些 MCP server，以及该 MCP server 的标准工具列表
> 3. 启动后端时观察 `[tool-catalog]` 日志或调 `GET /api/tools/catalog` 拿到完整列表
>
> **历史教训**：曾有判断"项目没有 read_text_file" → 错。read_text_file 由 filesystem MCP 提供，agent 默认可用，只是不在 `harness/tools/` 里。设计 bash 截断时直接利用它（bash 写文件 → agent 调 `read_text_file` 按需读），不要新建工具。

### 工具可用性约定（3 层分级模型）

工具按 `ToolTier`（`harness/tools/registry.py`）分 3 层：

| Tier | 行为 | 当前工具 |
|---|---|---|
| **FORCED** | 始终注入到每个 agent 的工具列表，写白名单也会强制加上；只有 `exclude=[...]` 才能去掉 | `todo` |
| **DEFAULT** | `tools=None`（默认）时自动加载；agent 写 `tools=[...]` 白名单时被替换 | `bash` `grep` `glob` `sub_agent` `ask_user` + filesystem MCP ×10 |
| **EXPLICIT** | 不会自动加载，agent 必须在 `tools=[...]` 显式列入（或用 glob 如 `codegraph_*`） | `render_chart` + codegraph MCP ×10 |

**典型场景**：
- `tools` 字段缺省 → 自动获得 FORCED + DEFAULT（共 15 个）
- `tools=["bash"]` → bash + todo（FORCED 强制注入）
- `tools=["bash"], exclude=["todo"]` → 只有 bash（强制层也能 exclude）
- `tools=["codegraph_search"]` → codegraph_search + todo（用户显式列 + 强制注入）

**判断工具分级的指引**：
- 是否框架级硬要求（有 reminder 强制注入 / description 强制行为）→ FORCED
- 是否绝大多数 agent 都需要（基础设施 / 文件操作 / 通用查询）→ DEFAULT
- 是否高成本或场景化（启动慢 / 占资源 / 仅特定 agent 类型用）→ EXPLICIT

> **历史教训**：曾有判断"项目没有 read_text_file" → 错。read_text_file 由 filesystem MCP 提供，DEFAULT tier 自动加载，agent 默认可用，只是不在 `harness/tools/` 里。

---

## 关键接口

### Agent 查找规则 (`resolve_agent_md`)
1. `workflows/<wf>/agents/<name>.md` 存在 → 返回
2. `workflows/_shared/agents/<name>.md` 存在 → 返回
3. 都不存在 → `AgentNotFoundError`

### Workflow 状态
```python
HarnessState = TypedDict {
    inputs: dict              # 初始输入
    outputs: dict             # {agent_name: result} — reducer 自动合并
    errors: dict              # {agent_name: error_info}
    metadata: dict            # 扩展插槽（token_usage, judgment, score_history 等）
}
```

### 事件协议格式
```json
{
  "type": "node.started",
  "ts": 1716000000000,
  "payload": { "node_id": "...", "agent_name": "..." }
}
```

### 事件 Priority 契约（PR-B 引入，避免关键事件被 Bus buffer FIFO 淘汰）

Bus 的 WS replay buffer 有大小上限（默认 `buffer_size=2000`），normal 事件按 FIFO 淘汰；**critical 事件永不淘汰**（独立的 `_critical_buffer`）。

判定规则：**"如果下游消费者错过了这个事件，UI 会永久错误吗？"** → critical；**"能被后续事件或刷新重建吗？"** → normal。

白名单定义在 `harness/extensions/bus.py` 的 `CRITICAL_EVENT_TYPES`（frozenset，约 24 个）：
- Workflow 生命周期：`workflow.started/completed/error/cancelled/resumed/interrupted/waiting_for_guidance/audit`
- Node 生命周期：`node.started/completed/failed`
- 工具状态变更：`agent.tool_call/tool_result/tool_output_truncated`、`bash.background_completed`
- 交互式提问：`chat.question/answer/timeout`
- TODO 状态：`todo.created/updated`
- Followup 生命周期：`followup.started/completed/failed`
- 图表最终渲染：`chart.render`

非关键（流式增量）：`agent.text_delta`、`agent.thinking_delta`、`agent.tool_output_delta`、`span.start/end`、`trace.step`、`step.summary` 等。

**调用约定**：
- `bus.emit(...)` 和 `safe_emit(...)` 的 `priority` 参数**默认 `None`**，None 时按 event_type 自动查表
- 显式传 `priority="critical"` 或 `"normal"` 会**覆盖**白名单（保留逃生通道）
- 添加新事件类型时，如果属于 critical 语义，**必须**同时加入 `CRITICAL_EVENT_TYPES`

历史教训：曾因 `node.completed` 走 normal priority，5641 个事件被 FIFO 淘汰了 3641 个 → 前端实时 token 显示只有单节点值（334.8k）而非真实总和（1.71M）。修复后所有 `node.completed` 自动 critical。

---

## 扩展系统职责分界

| 类型 | 能做什么 | 不能做什么 | 用途 |
|------|---------|-----------|------|
| **Hook** | 读取数据流，产生副产物（chart.render, trace.step） | 修改任何数据 | 观测、追踪、图表 |
| **Middleware** | 修改数据流，可抛 RejectAction/RetryAction | 改写 DAG 结构 | 内容过滤、注入记忆、预算控制 |
| **GraphMutator** | 改写 DAG（插入节点、修改依赖） | 修改运行时数据 | EvalJudge 自动插入评审节点 |

---

## 开发规范

### SDD (Spec-Driven Development)
1. **先敲定接口，再写代码。** 每个 Phase 开始前，必须与用户讨论并确认 SPEC.md 中对应章节的接口规范。
2. **SPEC.md 是唯一真相源。** 接口变更必须先更新 SPEC.md，获得用户确认后再修改实现代码。
3. **禁止实现未规范的接口。**

### 不重复造轮子原则
- 优先使用成熟库：langgraph, langchain, fastapi, reactflow, shadcn/ui
- 自建仅在成熟库无法满足需求时

### 12-Rule 模板
1. Think Before Coding — 明确假设，不确定则问
2. Simplicity First — 最少代码解决，不投机
3. Surgical Changes — 只改必须的，不碰无关的
4. Goal-Driven Execution — 定义成功标准，迭代验证
5. Use the model only for judgment calls — 路由、重试等 deterministic 逻辑用代码
6. Token budgets are not advisory — 接近 budget 及时总结
7. Surface conflicts, don't average them — 选一个，说明 why
8. Read before you write — 理解上下文再修改
9. Tests verify intent, not just behavior
10. Checkpoint after every significant step
11. Match the codebase's conventions
12. Fail loud

---

## 问题分类与质量标准（必须遵守）

当遇到用户反馈或缺陷报告时，**先判定是 bug 还是架构问题**，再决定动手方式：

- **Bug**：局部逻辑错误、状态丢失、渲染错位、边界条件未处理。修复方式 = 最小化 surgical fix，不动结构。
- **架构问题**：跨模块的耦合、抽象层次错位、违反单一职责、缺少扩展点、数据流或事件流不合理、违反 SOLID 原则。修复方式 = 先提出设计方案（说明动机、权衡、迁移路径），与用户对齐后再改，不允许直接打补丁绕过。

### 判定信号（出现任一即倾向"架构问题"）
- 同一现象在多个模块复现
- 修复需要改动 ≥3 个不相关文件
- 现象背后是"职责越界"（例如工具直接污染对话结构、UI 状态散落在多处）
- 现象背后是"事件/数据流断裂"（例如持久化层与内存状态不同步）
- 用 hack/兼容代码才能让现有抽象跑通

### 代码质量底线（任何改动必须满足）
1. **整洁**：命名表达意图，函数职责单一，无注释解释 *what*，只在 *why* 非显然时注释。
2. **可扩展**：新能力通过新增（策略/插件/注册项）而非修改核心路径实现（OCP）。
3. **鲁棒**：边界条件、空值、失败路径显式处理；失败 **fail loud**，不静默吞错。
4. **性能**：默认无 N+1、无全量重渲、无重复请求；大数据流式或分页。
5. **易定位**：关键路径有结构化日志/事件；错误能追溯到一个明确的层（工具 / 引擎 / 事件 / UI）。

### 报错处理与可观测性
- 重试**必须显式**告知用户（UI 上能看到"重试中 / 第 N 次 / 失败原因"），不允许静默重试或静默失败。
- LLM / 网络 / 工具失败要分层捕获：transport 层重试（网络抖动）→ 协议层重试（4xx 中可重试项）→ 业务层中断（不可恢复）。层与层之间不能互相吞错。
- 限流（rate limit / request_limit）应走"退避重试 + 用户可见"，而不是直接中断 agent。

> 违反上述任何一条时，优先写设计方案而不是打补丁。