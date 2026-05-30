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
├── tools/                      # 工具系统
│   ├── ask_user.py             # ask_user: 结构化提问（单选/多选/自由输入）
│   ├── ask_human.py            # ask_human: 旧版薄壳，转调 ask_user
│   ├── _human_io.py            # 共享 Future 注册表（ask_user/ask_human 共用）
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