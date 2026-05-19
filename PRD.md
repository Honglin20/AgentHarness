# AgentHarness — 需求、技术路径与开发计划

---

## 一、原始需求

### 核心原则
**避免重复造轮子，能用什么用什么，达不到要求再自建。**

### 1. Web UI
- DAG 拓扑图：显示整个工作流，当前节点高亮，校验状态，重试状态
- Agent 状态面板：显示 agent 在做什么
- 对话框：与 agent 双向交流（类似 Claude 的 AskUserQuestion）
- 富文本展示：LABEL+TITLE 形式显示图片和表格，同 label 可折叠
- 视觉风格：Apple / OpenAI 极简风

### 2. 工作流构建
- API 极简：声明式定义，`Agent(after=["A", "B"])` 即可
- MD 文件定义 agent（人设、prompt、工具），拒绝在代码中写长篇 prompt
- 工具节点可内嵌于 agent
- 依赖只需知道上游重要输出，无需感知全局状态
- 对比 LangGraph 原生：必须定义大量边和状态，太复杂 → 需要模板/编译层屏蔽

### 3. Agent 工具能力
- 需要文件操作、debug、bash、sub-agent 等 Claude Code 级工具
- 核心场景是写代码，基础工具不想自建
- 需分析 MCP vs LangGraph 工具生态差异

### 4. 回溯与可观测性
- 记录哪个节点容易出问题、出什么问题
- 方便开发 debug

### 5. 扩展机制
- Memory：文件级记忆，人类可干预
- Evaluation：自动校验结果，获取 agent 原 prompt 知道该做什么
- Hook：agent 开始/结束时插入逻辑（如"总结到某文件夹"）
- 反思等机制补充

---

## 二、技术选型 — 双引擎架构

### 核心决策：LangGraph (宏观编排) + Pydantic AI (微观执行)

| 模块 | 核心诉求 | 选型 | 替代的自建部分 |
|------|---------|------|---------------|
| 宏观编排 | 并发依赖(Fan-in/out)、状态流转、断点记忆、HITL | **LangGraph** | — |
| 微观执行 | Prompt 构造、Tool 调用循环、结构化输出、重试 | **Pydantic AI** | 消除 micro_loop、tools/registry、输出校验 |
| 开发者 API | 极简声明式 | **自定义 Harness API** | — |
| Agent 定义 | 拒绝代码中写长 prompt | **Markdown + YAML Front Matter** | — |
| 工具能力 | 拒绝手写基础工具 | **MCP → mcp_bridge 适配为 Pydantic AI Tool** | — |
| 鲁棒性 | 自修复、评估 | **Pydantic AI retries + LangGraph conditional edge** | — |
| 记忆机制 | 人类可干预 | **File-based Memory** | — |
| 可观测性 | 报错定位、耗时、拓扑图 | **LangSmith / Langfuse** | — |
| 前端 UI | Apple/OpenAI 风 | **Next.js + Tailwind + shadcn/ui + React Flow** | — |

### 为什么双引擎比纯 LangGraph 更省

| 原方案需自建 | Pydantic AI 替代 | 省下的工作量 |
|-------------|-----------------|-------------|
| `micro_loop.py` — LLM→Tool→Error→Retry 循环 | `Agent` 类原生 tool loop + `retries` 参数 | **整个文件删除** |
| `tools/registry.py` — 工具注册中心 | `@agent.tool` 装饰器 + `Tool` 类 | **大幅简化** |
| 自定义输出校验 + 重试 | `result_type: Type[BaseModel]` + 自动 validation retry | **消除手写校验** |
| 上下文拼接格式不确定 | 结构化输出 → 下游用 Pydantic model 解析 | **隐式传递更可靠** |
| sub-agent 编排 | Pydantic AI 原生 `agent.run()` 委托 | **不需要自建** |

### 职责分界

```
LangGraph (宏观)                    Pydantic AI (微观)
─────────────────────              ──────────────────
DAG 拓扑与状态流转                   单节点内 Agent 执行
节点间依赖等待 (Fan-in/out)          Tool 调用循环 + 自动重试
Checkpoint 持久化                    结构化输入/输出 (result_type)
HITL interrupt / resume             Prompt 构造 + 依赖注入
Conditional Edge 打回                Result validation + retry
```

### MCP → Pydantic AI 适配

Pydantic AI 不原生支持 MCP 协议，需要 `mcp_bridge.py` 做一层薄适配：

```
MCP Server Tool Schema → Pydantic Model (参数) → 包装函数 → Pydantic AI Tool
```

工作量小，但无法省略。基础工具（bash, fs）直接用 Pydantic AI `@agent.tool` 定义，不经过 MCP。

---

## 三、系统架构

### 四层分离

```
┌──────────────────────────────────────────────────────┐
│  User API 层 (声明式定义)                             │
│  Agent("name", after=[...], tools=[...])              │
├──────────────────────────────────────────────────────┤
│  Compiler 层 (解析与编译)                             │
│  MD 解析 → 依赖图 → 拓扑排序 → LangGraph DAG          │
├──────────────────────────────────────────────────────┤
│  Engine 层 (双引擎运行时)                             │
│  LangGraph (macro_graph) + Pydantic AI (micro_agent)  │
├──────────────────────────────────────────────────────┤
│  Server/UI 层 (可视化与交互)                          │
│  FastAPI + WebSocket + Next.js + React Flow           │
└──────────────────────────────────────────────────────┘
```

### 项目目录结构

```
harness_project/
├── frontend/                  # Next.js + React Flow 前端代码
│
├── backend/
│   ├── harness/               # 核心框架 (无需改动业务代码)
│   │   ├── __init__.py
│   │   ├── api.py             # 暴露 Workflow, Agent 声明式类
│   │   ├── compiler/          # Markdown 解析与 DAG 依赖排序
│   │   │   ├── md_parser.py   # YAML frontmatter + prompt 提取
│   │   │   └── dag_builder.py # 依赖解析 + 拓扑排序 + 循环检测
│   │   │
│   │   ├── engine/            # [核心改动区：双引擎]
│   │   │   ├── macro_graph.py # LangGraph 拓扑构建与状态管理
│   │   │   └── micro_agent.py # Pydantic AI 实例生成器 (Prompt, Tools, Retry)
│   │   │
│   │   ├── tools/             # 工具库
│   │   │   ├── builtins/      # 基础工具 (bash.py, fs.py)
│   │   │   └── mcp_bridge.py  # 将 MCP 工具包装为 Pydantic AI Tool 的适配器
│   │   │
│   │   └── extensions/        # [扩展插槽]
│   │       ├── memory_hook.py # 在 LangGraph 节点切换时触发本地文件读写
│   │       └── evaluator.py   # 生成基于 Pydantic AI 的独立验证节点
│   │
│   ├── server/                # FastAPI 路由与 WebSocket 通信
│   │   ├── app.py
│   │   ├── routes.py
│   │   └── ws_handler.py
│   │
│   ├── agents/                # [用户工作区] Markdown 人设与 Prompt
│   │   └── refactorer.md
│   │
│   └── main.py                # [用户入口]
│
├── CLAUDE.md
├── PRD.md                     # 本文件
└── SPEC.md                    # 接口规范 (每步敲定后更新)
```

### 核心模块职责

#### 1. 声明式 API 与编译 (api + compiler)
- `Agent("analyzer")` 自动寻找 `agents/analyzer.md`
- `after=["A", "B"]` 字符串寻址，`dag_builder.py` 拓扑排序
- 循环依赖 / 找不到 agent → 启动前报错 (Fail Fast)
- 上下文隐式传递：上游 Pydantic AI 结构化输出 → 自动注入下游 prompt

#### 2. 双引擎运行 (engine)
- **macro_graph.py**：将编译后的 DAG 转为 LangGraph StateGraph，每个节点调用 micro_agent
- **micro_agent.py**：为每个节点生成 Pydantic AI Agent 实例，注入 prompt + tools + retries
- LangGraph 节点函数 = `micro_agent.run(prompt_with_context)`

#### 3. 工具生态 (tools)
- `builtins/` — bash, fs 用 `@agent.tool` 直接定义，轻量且安全
- `mcp_bridge.py` — MCP tool schema → Pydantic model → 包装函数 → Pydantic AI Tool
- 业务代码只写工具名，不写实现

#### 4. 前端通信 (HITL + 状态)
- LangGraph `.stream()` → WebSocket 推送节点状态
- DAG 对应节点高亮 + 打字机效果
- `ask_human` 工具 → LangGraph `interrupt` → WebSocket 通知前端 → 用户输入 → resume 接口继续

#### 5. 回溯与可观测
- 每个节点的输入/输出/耗时/错误记录到 Trace
- LangSmith / Langfuse 集成，可点开看完整 prompt 和报错
- 节点失败模式自动归档（哪个节点、什么错误、第几次重试成功）

---

## 四、开发计划

### Phase 1: 最小可行核心 (Core Engine & Declarative API) — 1 周
**目标：** 声明式 API 跑通，终端可见节点按序执行，上下文隐式传递

| # | 任务 | 交付物 |
|---|------|--------|
| 1.1 | 设计并敲定 `Agent` / `Workflow` / `micro_agent` 接口规范 | SPEC.md §Agent, §Workflow, §Engine |
| 1.2 | 实现 `md_parser.py` — YAML frontmatter + prompt 提取 | 解析器 + 单测 |
| 1.3 | 实现 `dag_builder.py` — 字符串依赖 → 拓扑排序 + 循环检测 | 编译器 + 单测 |
| 1.4 | 实现 `micro_agent.py` — Pydantic AI 实例生成器 | Agent 工厂 + 单测 |
| 1.5 | 实现 `macro_graph.py` — 编译为 LangGraph StateGraph | 引擎 + 单测 |
| 1.6 | 实现 `outputs` 字典 + 上下文隐式注入 | 集成测试 |
| 1.7 | 端到端验证：3 agent 串行工作流在终端跑通 | E2E 脚本 |

### Phase 2: 工具化与鲁棒性 (Tooling & Robustness) — 1 周
**目标：** Agent 能写代码、跑 Bash，报错自重试，MCP 工具可接入

| # | 任务 | 交付物 |
|---|------|--------|
| 2.1 | 敲定 builtins 工具与 mcp_bridge 接口规范 | SPEC.md §Tools, §MCP |
| 2.2 | 实现 `builtins/bash.py` + `builtins/fs.py` — Pydantic AI tools | 工具 + 单测 |
| 2.3 | 实现 `mcp_bridge.py` — MCP → Pydantic AI Tool 适配 | 适配器 + 集成测试 |
| 2.4 | Pydantic AI retries 集成 — 验证结构化输出 + 自动重试 | 鲁棒性测试 |
| 2.5 | 端到端验证：agent 用 bash 写文件 → 读取 → 自修复 | E2E 脚本 |

### Phase 3: 前端可视化与交互 (Web UI) — 1.5 周
**目标：** 浏览器 Apple 风格界面，DAG + 对话 + 富文本

| # | 任务 | 交付物 |
|---|------|--------|
| 3.1 | 敲定 WebSocket 事件协议与 API 路由规范 | SPEC.md §WS, §API |
| 3.2 | FastAPI server + WebSocket handler | 服务端 + 手动测试 |
| 3.3 | 拦截 LangGraph stream → 统一事件格式推送 | 事件桥接 + 测试 |
| 3.4 | Next.js + React Flow DAG 面板 | 前端 DAG 组件 |
| 3.5 | Chat UI — AskUser (HITL) 机制 | 对话组件 + 集成测试 |
| 3.6 | 富文本组件 — Markdown + 折叠 Label/Title + 图片 | 渲染组件 |
| 3.7 | 端到端验证：完整工作流在浏览器可视化运行 | E2E 演示 |

### Phase 4: 扩展插槽 (Memory, Evaluation, Reflection) — 优先级最低
**目标：** 智能、可审计、可进化

| # | 任务 | 交付物 |
|---|------|--------|
| 4.1 | 敲定 Hook / Memory / Eval 接口规范 | SPEC.md §Hook, §Memory, §Eval |
| 4.2 | Hook 机制 — `on_node_start`, `on_node_end` | Hook 框架 + 单测 |
| 4.3 | Memory — 文件级读写，`.workspace_state.md` | Memory 插件 + 单测 |
| 4.4 | Eval 节点 — 基于 Pydantic AI 的独立验证 + 条件回退边 | Eval 逻辑 + 集成测试 |
| 4.5 | 反思 Hook — 节点结束后自动总结/改进建议 | Reflection 插件 |
| 4.6 | Trace 埋点 — LangSmith 全局接入 | 可观测性集成 |
| 4.7 | 端到端验证：带 Eval 打回的工作流完整跑通 | E2E 演示 |

---

## 五、开发规范

详见 CLAUDE.md 中的开发规范章节。核心：
1. **SDD (Spec-Driven Development)**：每步先敲定接口规范 → 更新 SPEC.md → 再开发
2. **不重复造轮子**：优先用成熟库，自建仅作最后手段
3. **12-rule template**：继承自 harness/CLAUDE.md

---

## 六、风险与缓解

| 风险 | 影响 | 缓解 |
|------|------|------|
| Pydantic AI API 不稳定 (v0.x) | 迁移成本 | 使用标准用法 (tool/result_type/retries)，不依赖边缘 API；micro_agent.py 是唯一依赖点，替换成本低 |
| MCP bridge 适配层维护 | MCP 协议变动 | 适配层极薄，仅做 schema → model 映射 |
| LangGraph 与 Pydantic AI 状态同步 | 上下文丢失 | outputs dict 是唯一状态源，Pydantic AI 输出结构化后写入，LangGraph 读取 |
