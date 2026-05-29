# AgentHarness

> 双引擎 AI Agent 工作流框架 — LangGraph + Pydantic AI

定义多 Agent 工作流，一行 `wf.run()` 执行，Web UI 实时可视化。

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## 安装

### 前置要求

- Python 3.10+
- Node.js 18+ 和 npm（用于 MCP 文件系统工具 + Web UI）
- LLM API Key（支持 OpenAI、Anthropic、DeepSeek、Groq 等 Pydantic AI 支持的模型）

```bash
# 安装 MCP 文件系统工具（可选，提供 read_file/write_file 等工具）
npm install -g @modelcontextprotocol/server-filesystem
```

### 方式一：pip install（推荐）

```bash
pip install agent-harness
```

安装后即可在任意项目目录使用：

```bash
# 在你的项目目录下创建 workflows/ 并启动 UI
cd my-project
harness ui                # 自动以 CWD 为项目根目录
harness ui --port 3000    # 指定端口
harness ui --project-root /path/to/project  # 显式指定项目根
harness list              # 列出已发现的 workflow 和 benchmark
```

### 方式二：源码安装

```bash
git clone https://github.com/your-repo/AgentHarness.git
cd AgentHarness
python install.py          # 交互模式，会提示输入 API Key
python install.py --quick  # 非交互模式
```

### 验证

```python
from harness.api import Agent, Workflow

result = Workflow("hello", agents=[Agent("analyzer", after=[])]).run(
    {"task": "用一句话解释什么是 AI Agent。"}
)
print(result.outputs["analyzer"])
```

### API Key 配置

```python
from harness.config import configure, get_config

configure(api_key="sk-...", model="openai:gpt-4o", persist=True)  # 保存到 .env
print(get_config())
```

Key 解析顺序：`CWD/.env` → 项目根 `.env` → `ANTHROPIC_AUTH_TOKEN` 环境变量 → `ANTHROPIC_API_KEY` 环境变量。

也可以通过 REST API 或 Web UI 设置面板配置：
```bash
POST /api/config {"api_key":"sk-...", "model":"openai:gpt-4o"}
```

---

## 项目根目录解析

所有数据路径（workflows/、benchmarks/、runs/、.env）基于 **项目根目录** 解析。

### 解析优先级

`get_project_root()` 三级优先链：

| 优先级 | 来源 | 场景 |
|--------|------|------|
| 1 | `HARNESS_PROJECT_ROOT` 环境变量 | CI/CD、脚本调用、显式指定 |
| 2 | CWD heuristic（CWD 含 `workflows/` 或 `harness/`） | `cd my-project && harness ui` |
| 3 | 包目录的父目录（fallback） | 开发模式（editable install） |

### Workflow 发现机制

框架通过两层发现找到 workflow 定义：

| 层 | 路径 | 来源 |
|----|------|------|
| **Project** | `<project_root>/workflows/<name>/` | 用户创建的 workflow |
| **Builtin** | `harness/builtin/workflows/<name>/` | 随 pip 安装的内置 workflow（如 `demo_pipeline`） |

同名资源 Project 层优先。

### Agent MD 查找规则

每个 Agent 的 system prompt 从 Markdown 文件加载，查找顺序：

1. `workflows/<wf>/agents/<name>.md` — 私有（优先）
2. `workflows/_shared/agents/<name>.md` — 共享（fallback）

### 典型目录结构

```
my-project/                    ← 项目根目录
├── .env                       ← API Key 等配置
├── workflows/
│   ├── _shared/
│   │   ├── agents/            ← 共享 Agent prompt（如 runner.md）
│   │   └── scripts/           ← 跨 workflow 共享脚本
│   ├── <name>/
│   │   ├── workflow.json      ← Agent 定义 + DAG 拓扑
│   │   ├── agents/            ← 私有 Agent prompt
│   │   └── scripts/           ← 私有脚本
│   └── users/{id}/workflows/  ← 多用户私有 workflow
├── benchmarks/
│   └── <name>/
│       ├── benchmark.json
│       └── results/
└── runs/                      ← 运行记录 + checkpoints.db
```

---

## 快速开始

```python
from harness.api import Agent, Workflow

# 定义工作流
wf = Workflow("code_review", agents=[
    Agent("analyzer", after=[]),
    Agent("planner",  after=["analyzer"]),
    Agent("reviewer", after=["planner"]),
])

# 保存（可选，保存后可在 UI 中选择）
wf.save()

# 运行
result = wf.run({"task": "审查这段代码: def div(a,b): return a/b"})

# 运行（指定工作目录）
result = wf.run({"task": "..."}, work_dir="/path/to/project")

# 查看结果
for t in result.trace:
    print(f"{t.agent_name}: {t.status} {t.duration_ms}ms")
```

> 完整示例: [examples/01_minimal.py](examples/01_minimal.py)

---

## Workflow 模式

Workflow 由多个 Agent 组成，Agent 之间的依赖关系（`after`）决定了 DAG 结构。
LangGraph 自动根据 DAG 调度执行：没有依赖关系的 Agent 并行运行，有依赖的依次执行。

### 串行流水线

最基础的模式：Agent 依次执行，上游输出自动传递给下游。

```
analyzer → planner → reviewer
```

```python
wf = Workflow("code_review", agents=[
    Agent("analyzer", after=[]),
    Agent("planner",  after=["analyzer"]),
    Agent("reviewer", after=["planner"]),
])
```

> 完整示例: [examples/02_serial_pipeline.py](examples/02_serial_pipeline.py)

### 并行执行

多个 Agent 同时启动，结果由下游 Agent 合并。

```
researcher_a ──┐
                ├── synthesizer
researcher_b ──┘
```

```python
wf = Workflow("parallel_research", agents=[
    Agent("researcher_a", after=[]),
    Agent("researcher_b", after=[]),
    Agent("synthesizer",  after=["researcher_a", "researcher_b"]),
])
```

`researcher_a` 和 `researcher_b` 没有依赖关系，LangGraph 自动并行执行。
`synthesizer` 等待两者都完成后才启动，此时可通过 `upstream_outputs` 访问两者的输出。

> 完整示例: [examples/03_parallel.py](examples/03_parallel.py)

### 条件路由

根据 Agent 输出决定下一步走哪个分支。

```
analyzer → classifier
                ├─ pass → summary
                └─ fail → debugger
```

```python
wf = Workflow("conditional_route", agents=[
    Agent("analyzer",    after=[]),
    Agent("classifier",  after=["analyzer"], on_pass="summary", on_fail="debugger"),
    Agent("summary",     after=[]),
    Agent("debugger",    after=[], tools=["bash"]),
])
```

通过 `on_pass` 和 `on_fail` 参数定义条件边。
Agent 的输出需要包含 `decision` 字段（`"pass"` 或 `"fail"`），
框架据此路由到对应节点。

> 完整示例: [examples/04_conditional_routing.py](examples/04_conditional_routing.py)

### 回环重试

有两种方式实现"写代码 → 审查 → 不通过则重写"的循环。

#### 方式一：DAG 级回环

```
coder → reviewer
           ├─ pass → END
           └─ fail → coder（注入审查意见，重试）
```

```python
wf = Workflow("loop_retry", agents=[
    Agent("coder",    after=[], tools=["bash"]),
    Agent("reviewer", after=["coder"], on_fail="coder"),
])
```

通过 `on_fail` 指回 `coder`，形成 DAG 级别的循环。
不通过时审查意见自动注入 coder 的上下文，重新执行。默认最多重试 3 次。

特点：每次重试是完整的 DAG 节点执行，全局可见。

> 完整示例: [examples/05_loop_retry.py](examples/05_loop_retry.py)

#### 方式二：sub_agent 工具级迭代

```
coder → reviewer_agent（内部通过 sub_agent 迭代）
```

```python
wf = Workflow("coder_review_loop", agents=[
    Agent("coder",          after=[], tools=["bash"]),
    Agent("reviewer_agent", after=["coder"], tools=["sub_agent"]),
])
```

reviewer_agent 在单次执行中使用 `sub_agent` 工具委托子 Agent 修复代码，
循环直到通过。对 DAG 来说只有两个节点。

特点：迭代是某个 Agent 的内部行为，DAG 更简洁。

> 完整示例: [examples/06_sub_agent_loop.py](examples/06_sub_agent_loop.py)

### 人机协作

Agent 在执行过程中通过 `ask_human` 工具向用户提问，等待回答后继续。

```
analyzer → decision_maker（ask_human → 等待 → 继续）
```

```python
wf = Workflow("ask_human_demo", agents=[
    Agent("analyzer",       after=[], tools=["bash"]),
    Agent("decision_maker", after=["analyzer"], tools=["ask_human"]),
])
```

注意：`ask_human` 需要通过 Web UI 使用（依赖 WebSocket 实时交互）。

> 完整示例: [examples/07_ask_human.py](examples/07_ask_human.py)

---

## 工具系统

每个 Agent 可配置可使用的工具。工具决定了 Agent 能做什么。

```python
Agent("coder", after=[], tools=["bash"])          # 只能用 bash
Agent("writer", after=[])                          # 无工具限制（默认）
Agent("analyst", after=[], tools=[])               # 不使用任何工具
```

| 工具 | 来源 | 说明 |
|------|------|------|
| `bash` | 内置 | 执行 shell 命令 |
| `sub_agent` | 内置 | 委托子 Agent 执行任务（最大深度 1） |
| `ask_human` | 内置 | 向用户提问，等待回答（需要 UI） |
| `read_file`, `write_file` 等 | MCP | 文件系统操作（需要安装 MCP server） |

Agent 的行为和工具配置也可以通过 `agents/<name>.md` 文件定义：

```markdown
---
name: coder
tools:
  - bash
  - sub_agent
retries: 3
---
你是一个程序员。根据任务要求编写代码，使用 bash 工具验证。
```

---

## 扩展系统

扩展系统提供三层抽象，按 **能做什么** 区分：

| | 主数据流 | 副产物 | DAG 结构 |
|---|---|---|---|
| **Hook** | 只读 | 读写（`ctx.emit`） | 不能 |
| **Middleware** | 读写 | 读写（`ctx.emit`） | 不能 |
| **GraphMutator** | 不能 | 不能 | 读写 |

- **Hook** — 观察生命周期，产生副产物（图表、追踪、指标）。不修改任何数据，并发执行，不阻塞。**内置 Hook 自动加载，无需 `.use()`。**
- **Middleware** — 修改或拒绝 Agent 执行（压缩对话、注入记忆、预算控制）。按优先级顺序执行，可抛出 `RejectAction` 中止或 `RetryAction` 重试。
- **GraphMutator** — 编译时改写 DAG（插入评审节点、展开子图）。执行前运行一次。

Middleware 和 GraphMutator 通过 `wf.use()` 注册：

```python
wf = (
    Workflow("name", agents=[...])
    .use(EvalJudge())           # GraphMutator
    .use(AutoCompact())         # Middleware
)
# Hook plugins (EvalChartPlugin, PerfMetricsPlugin 等) 自动加载，无需手动注册
```

### 内置扩展

#### EvalJudge — 自动评审 + 评分 + 重试（GraphMutator）

给需要评审的 Agent 标记 `eval=True`，注册 `EvalJudge` 即可自动插入评审节点。

```python
from harness.extensions.eval import EvalJudge

wf = (
    Workflow("eval_code_quality", agents=[
        Agent("coder",    after=[], eval=True, tools=["bash"]),
        Agent("reviewer", after=["coder"]),
    ])
    .use(EvalJudge(max_retries=2))
)
```

编译时 DAG 变化：
```
原始:  coder → reviewer
改写:  coder → _judge_coder → reviewer
                  │
                fail → coder（注入批评意见，重试最多 max_retries 次）
```

工作原理：
- 编译时：在每个 `eval=True` 的 Agent 后自动插入 `_judge_<name>` 节点
- 自动生成 `_judge_<name>.md` 到 workflow 的 agents 目录，用户可通过 Agent Editor 自定义评审标准
- 运行时：从 MD 读取 system prompt，自动注入目标 Agent 的任务总结 + 实际输出
- 评审输出 `ReviewDecision`：`pass/fail` + `reason` + `score`（0.0-1.0，可选）
- Pass：原始输出透传给下游（下游看不到 ReviewDecision）
- Fail：将 reason 注入目标 Agent 上下文，重新执行
- Score：通过 `EvalChartPlugin`（自动加载）实时推送到 UI 折线图

> 完整示例: [examples/08_eval_judge.py](examples/08_eval_judge.py)

#### AutoCompact — 自动压缩对话（Middleware）

当对话历史超过 token 阈值时，自动压缩历史消息，避免超出上下文窗口。

```python
from harness.extensions.compact.auto_compact import AutoCompact

wf = Workflow(...).use(AutoCompact(threshold_tokens=8000))
```

#### 内置 Plugins（Hook）— 自动加载

Plugins 是 `BaseHook` 子类，通过 `ctx.emit()` 产生观测副产物。**所有内置 Hook 在 compile 时自动注册，无需手动 `.use()`。** 新增 Hook plugin 会自动被发现并加载。

如需禁用某个 Hook，在 compile 前调用 `bus.unregister("plugin-name")`。

| Plugin | 触发条件 | 输出 |
|--------|---------|------|
| `EvalChartPlugin` | `_judge_*` 节点完成 | `chart.render` 评分折线图 → UI Analysis tab |
| `AgentTracePlugin` | 任意节点完成 | `trace.step` 事件 |
| `ReasoningVizPlugin` | 检测到思维链 | `reasoning.render` 可视化数据 |
| `PerfMetricsPlugin` | 有 token_usage 数据 | `chart.render` 用量柱状图 → UI Analysis tab |
| `StepCounterPlugin` | 任意节点完成 | `step.summary` tool/LLM 调用计数 → UI Analysis tab |
| `CircularDetectorPlugin` | 连续相同 tool 调用 ≥3 | `circular.warning` 循环检测 → UI Errors tab |

> 组合扩展示例: [examples/11_all_extensions.py](examples/11_all_extensions.py)

### 自定义扩展

#### 自定义 Hook

Hook 用于观察和记录，不修改数据。适合做日志、指标、持久化。

```python
from harness.extensions.base import BaseHook, NodeCtx

class MyLogger(BaseHook):
    name = "my-logger"

    async def on_node_end(self, ctx: NodeCtx, output) -> None:
        print(f"[{ctx.agent_name}] 完成，输出 {len(str(output))} 字符")
        ctx.emit("custom.event", {"agent": ctx.agent_name, "output_len": len(str(output))})

wf = Workflow(...).use(MyLogger())
```

#### ConsoleOutput — 命令行美化输出（Rich）

`ConsoleOutput` 是一个内置 Hook，使用 [Rich](https://github.com/Textualize/rich) 库美化命令行输出。

**特点：**
- 🎨 彩色面板、自动换行、边框样式
- 📊 JSON/Markdown 自动高亮
- 📤 上游输出表格展示
- 🖨️ 不影响 Web UI，仅命令行使用

**安装依赖：**
```bash
pip install rich
# 或
pip install -e ".[console]"
```

```python
from harness.extensions.console import ConsoleOutput

wf = Workflow("test", agents=[...])

# 手动注册，不影响 UI
wf.use(ConsoleOutput(
    stream=False,         # 流式打印 LLM 输出
    verbose=True,         # 显示详细信息
    show_system=True,     # 显示 system prompt 框
    show_upstream=True,   # 显示上游 agent 输出
    show_model=True,      # 显示 agent 使用的 LLM model
    show_tools=True,      # 显示 agent 可用的 tools (name + description)
    show_critique=True,   # 显示 eval 评审反馈（重试时）
    show_config=False,    # 显示 agent_md_path / retries / result_type
    use_colors=True,      # 使用颜色
))

result = wf.run({"task": "..."})
```

**输出示例：**
```
╭─ 🔹 analyzer 开始执行 ─╮
│                           │
╰───────────────────────────╯

╭─ 📌 System Prompt ─╮
│ You are a code analyst.  │
╰────────────────────────╯

╭─ 📌 User Prompt ────────────╮
│ ## Task                       │
│ {"task": "分析这段代码"}       │
╰───────────────────────────────╯

╭─ Model ─╮
│ gpt-4o  │
╰─────────╯

╭─ Tools ─────────────────╮
│ Tool     Description     │
│ bash     Execute shell   │
╰─────────────────────────╯

╭─ ✓ analyzer 执行完成 ─╮
╰────────────────────────╯
```

> 完整示例: [examples/13_console_output.py](examples/13_console_output.py)

#### 自定义 Middleware

Middleware 用于修改数据流。适合做内容过滤、注入上下文、预算控制。

```python
from harness.extensions.base import BaseMiddleware, NodeCtx, RejectAction

class PrefixMiddleware(BaseMiddleware):
    name = "prefix"
    priority = 30  # 数字越小越先执行

    async def before_node(self, ctx: NodeCtx) -> NodeCtx | RejectAction:
        # 修改 Agent 的输入提示
        ctx.prompt = f"[系统注入] 当前时间: {__import__('datetime').datetime.now()}\n\n{ctx.prompt}"
        return ctx

wf = Workflow(...).use(PrefixMiddleware())
```

#### 自定义 GraphMutator

GraphMutator 在编译时改写 DAG。适合插入新节点、修改依赖关系。

```python
from harness.extensions.base import BaseGraphMutator

class DoubleCheck(BaseGraphMutator):
    name = "double-check"

    def mutate(self, workflow):
        # 在每个 Agent 后插入一个验证节点
        new_agents = []
        for agent in workflow.agents:
            new_agents.append(agent)
            check = Agent(f"verify_{agent.name}", after=[agent.name])
            new_agents.append(check)
        workflow.agents = new_agents
        return workflow

wf = Workflow(...).use(DoubleCheck())
```

---

## Chart 可视化

Agent 通过 `bash` 执行的脚本中可以调用 `render_chart()` 推送图表到 UI。

### 基础图表

```python
from harness.tools.chart import render_chart

data = [{"iter": 1, "score": 0.3, "loss": 0.9, "method": "A"},
        {"iter": 2, "score": 0.5, "loss": 0.7, "method": "A"},
        {"iter": 3, "score": 0.7, "loss": 0.4, "method": "B"}]

render_chart(data, chart_type="line",  x="iter", y="score", hue="method")
render_chart(data, chart_type="bar",   x="iter", y="loss",  hue="method")
render_chart(data, chart_type="scatter", x="iter", y="score", hue="method")
render_chart(data, chart_type="area",  x="iter", y="score", hue="method")
```

### 高级图表

```python
# 气泡图 — 第三维度控制气泡大小
render_chart(bubble_data, chart_type="bubble", x="x", y="y", size="weight", hue="group")

# 帕累托前沿 — 多目标优化
render_chart(data, chart_type="pareto", x="cost", y="quality", pareto_direction="max")

# 最优线 — 追踪历史最优值
render_chart(data, chart_type="optimal_line", x="iter", y="score", optimal_line="max")

# 雷达图 — 多维模型对比
render_chart(radar_data, chart_type="radar", x="metric", y="score", hue="model")
```

### 统计与数据

```python
# 箱线图 — 分组分布对比
render_chart(data, chart_type="box", x="group", y="value")

# 热力图 — 矩阵可视化
render_chart(matrix_data, chart_type="heatmap", x="col", y="row")

# 数据表格 — 可排序
render_chart(data, chart_type="table")
```

### 支持的全部图表类型

| 类型 | `chart_type` | 说明 | 特有参数 |
|------|-------------|------|---------|
| 折线图 | `line` | 趋势变化，支持 `hue` 多线 | — |
| 柱状图 | `bar` | 分类对比，支持 `hue` 分组 | — |
| 散点图 | `scatter` | 相关性分析，支持 `hue` 分色 | — |
| 面积图 | `area` | 趋势+量感，支持 `hue` 多层 | — |
| 气泡图 | `bubble` | 三维关系（x, y, 大小） | `size` |
| 帕累托图 | `pareto` | 多目标最优前沿 | `pareto_direction` |
| 最优线 | `optimal_line` | 追踪历史最优值 | `optimal_line` |
| 雷达图 | `radar` | 多维度对比 | — |
| 箱线图 | `box` | 分布统计 | — |
| 热力图 | `heatmap` | 矩阵强度可视化 | — |
| 瀑布图 | `waterfall` | 执行时序甘特图（每 Agent 一行） | — |
| 数据表格 | `table` | 可排序数据表 | — |

图表通过 EventBus → WebSocket → 前端实时渲染。

> 完整示例: [examples/09_charts.py](examples/09_charts.py)

---

## Benchmark 批量评测

Benchmark 是一组持久化的测试任务，可一键用任意 Workflow 跑全部任务，收集分数并对比结果。

### Python API

```python
from harness.api import Benchmark

# 创建 Benchmark
bm = Benchmark("code-review-v1", description="代码审查能力评测")
bm.task("审查 auth.ts 的安全性", inputs={"task": "审查 auth.ts"})
bm.task("审查 api.ts 的错误处理", inputs={"task": "审查 api.ts"})
bm.task("审查 utils.ts 的性能", inputs={"task": "审查 utils.ts"})
bm.save()

# 直接运行（同步，所有 task 并行）
result = bm.run(workflow="eval_code_quality")
print(result.all_completed)

# 带插件运行
from harness.extensions.console import ConsoleOutput
result = bm.run(workflow="eval_code_quality", plugins=[ConsoleOutput()])

# 加载已保存的 Benchmark
bm = Benchmark.load("code-review-v1")
```

### Prep 前置准备

Benchmark 支持 prep 阶段——在所有 task 执行前先运行一次准备工作（如 git clone、环境搭建）。

```python
from harness.api import Benchmark

bm = Benchmark("quantize-benchmark", description="模型量化评测")
bm.prep(type="script", command="bash setup.sh", work_dir="/tmp/repos")
bm.task("Quantize ResNet", inputs={"model": "resnet50"})
bm.task("Quantize BERT", inputs={"model": "bert-base"})
bm.save()
```

**Prep 类型：**

| 类型 | 说明 | 文件位置 |
|------|------|---------|
| `script` | 执行 shell 命令 | 脚本放 `benchmarks/<name>/`，自动加入 PATH |
| `agent` | 运行 LLM Agent | Agent MD 放 `benchmarks/<name>/agents/` 或 `workflows/_shared/agents/` |

**执行流程：** prep 执行完成 → 所有 task 并行运行（和没有 prep 时完全一样）

> 完整示例: [examples/14_benchmark_prep.py](examples/14_benchmark_prep.py)

### 通过 UI 运行

1. 侧边栏 Benchmarks 区点击 benchmark 名称
2. 选择一个 Workflow
3. 点击 Run Benchmark
4. 查看 Checklist 进度 → 点击单个任务查看详情
5. Compare Tab 查看对比：Score / Charts / Workflow / History

### 对比维度

| 维度 | 说明 |
|------|------|
| **Scores** | 同一 Workflow 在不同 Task 上的分数柱状图 |
| **Charts** | 各 Task 生成的图表按类型分组并排展示 |
| **Workflows** | 同一 Benchmark 跑不同 Workflow，分组柱状图对比 |
| **History** | 同 Benchmark + Workflow 的分数随时间变化趋势 |
| **Regression** | 对比最新两次运行，检测 score/cost/latency/tokens 回归 |

### REST API

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/api/benchmarks` | 列出所有 Benchmark |
| `POST` | `/api/benchmarks` | 创建 Benchmark |
| `GET` | `/api/benchmarks/{name}` | 获取定义 |
| `PUT` | `/api/benchmarks/{name}` | 更新任务列表 |
| `DELETE` | `/api/benchmarks/{name}` | 删除 |
| `POST` | `/api/benchmarks/{name}/run` | 用指定 Workflow 运行 |
| `GET` | `/api/benchmarks/{name}/results` | 所有运行历史 |
| `GET` | `/api/benchmarks/{name}/regression` | 回归检测（对比最新两次运行） |
| `GET` | `/api/benchmarks/{name}/results/{run_id}` | 单次结果详情 |

> 完整示例: [examples/12_benchmark.py](examples/12_benchmark.py)

---

## 持久化与 UI

### 保存与加载

```python
# 保存工作流定义
wf.save()                    # → workflows/<name>/workflow.json

# 加载已保存的工作流
wf2 = Workflow.load("code_review")

# 列出所有已保存的工作流
for w in Workflow.list_saved():
    print(w["name"], w["dag"]["nodes"])
```

### Web UI

```bash
# 方式一：启动脚本（自动构建前端 + 启动后端）
bash examples/launch_ui.sh

# 方式二：直接启动后端（前端已构建）
python -m uvicorn server.app:app --host 0.0.0.0 --port 8000
```

打开 http://localhost:8000，选择工作流 → 输入任务 → 运行 → 实时查看 DAG、流式输出、Token 追踪。

> 完整示例: [examples/10_save_load_ui.py](examples/10_save_load_ui.py)

---

## API 参考

### Agent

```python
Agent(
    name: str,                          # 对应 agents/<name>.md
    after: list[str] = [],             # 上游依赖
    tools: list[str] | None = None,    # None=全部可用, []=无, ["bash"]=仅 bash
    model: str | None = None,          # 默认读 HARNESS_MODEL
    retries: int = 3,                  # 重试次数
    eval: bool = False,               # 标记为需要 EvalJudge 评审
    on_pass: str | None = None,       # 条件边：通过时跳转到的节点
    on_fail: str | None = None,       # 条件边：失败时跳转到的节点
)
```

### Workflow

```python
wf = Workflow(name, agents=[...])
wf.save()                        # → workflows/<name>/workflow.json
wf.compile()                     # → LangGraph CompiledStateGraph
result = wf.run(inputs)          # 同步运行
result = await wf.arun(inputs)   # 异步运行
wf.use(extension)                # 注册扩展，返回 self（链式调用）
wf = Workflow.load("name")       # 从文件加载
Workflow.list_saved()            # 列出所有已保存工作流
```

#### 预算控制（Envelope）

通过 `envelope` 参数设置 workflow 级别的执行预算，超限时自动终止：

```python
wf = Workflow("safe_run", agents=[...],
    envelope={"max_tokens": 50000, "max_steps": 30, "max_duration_ms": 60000}
)
```

| 参数 | 说明 |
|------|------|
| `max_tokens` | 总 token 上限（input + output） |
| `max_steps` | 总 tool 调用次数上限 |
| `max_duration_ms` | 总执行时长上限（毫秒） |

配置后 Web UI Diagnostics 面板顶部会显示 BudgetBar 进度条（>80% 黄色，>100% 红色）。

### WorkflowResult

```python
result.outputs    # dict[str, Any]   agent_name → 输出
result.errors     # dict[str, str]   agent_name → 错误信息
result.trace      # list[NodeTrace]  每个 agent 的执行记录

# NodeTrace
trace[0].agent_name    # str
trace[0].status        # "success" | "failed" | "skipped"
trace[0].duration_ms   # int
trace[0].error         # str | None
trace[0].token_usage   # TokenUsage | None
trace[0].token_usage.input    # int
trace[0].token_usage.output   # int
trace[0].token_usage.total    # int
```

---

## REST API

| Method | Path | 说明 |
|--------|------|------|
| `GET` | `/health` | 健康检查 |
| `GET` | `/api/me` | 获取当前用户信息 |
| `GET` | `/api/agents` | 列出可用 Agent |
| `GET` | `/api/agents/{name}` | 获取 Agent 定义 |
| `GET` | `/api/tools` | 列出已注册工具 |
| `GET` | `/api/config` | 获取配置（Key 已脱敏） |
| `POST` | `/api/config` | 设置 API Key / Model |
| `GET` | `/api/workflows/definitions` | 列出已保存工作流 |
| `POST` | `/api/workflows` | 创建并启动工作流 |
| `POST` | `/api/batch` | 批量启动多个工作流 |
| `GET` | `/api/batch/{batch_id}` | 查询批量运行状态 |
| `GET` | `/api/benchmarks` | 列出所有 Benchmark |
| `POST` | `/api/benchmarks` | 创建 Benchmark |
| `GET` | `/api/benchmarks/{name}` | 获取 Benchmark 定义 |
| `POST` | `/api/benchmarks/{name}/run` | 运行 Benchmark |
| `GET` | `/api/benchmarks/{name}/results` | 运行历史 |
| `GET` | `/api/workflows/{id}` | 获取工作流状态 |
| `GET` | `/api/workflows/{id}/dag` | 获取 DAG 结构 |
| `GET` | `/api/workflows/{id}/trace` | 获取执行追踪 |
| `POST` | `/api/workflows/{id}/cancel` | 取消工作流 |
| `GET` | `/api/runs` | 列出历史运行 |
| `POST` | `/api/runs/{id}/rerun` | 重新运行 |
| `POST` | `/api/runs/{id}/resume` | 从检查点恢复 |
| `POST` | `/api/charts` | Chart HTTP 回调 |
| `WS` | `/ws/workflows/{id}` | 实时事件流 |

**认证**: 通过 `X-API-Key` Header 进行用户认证。未提供时使用默认用户。

---

## 用户管理

多用户隔离确保每个用户只能看到和操作自己的私有 workflow 和运行记录。

### 用户配置

用户配置存储在 `users.json`（gitignore，不提交）：

```json
{
  "dev_alice": {
    "user_id": "alice",
    "name": "Alice",
    "role": "developer",
    "level": 1
  },
  "admin": {
    "user_id": "admin",
    "name": "Admin",
    "role": "admin",
    "level": 11
  }
}
```

### 管理用户

使用命令行脚本管理用户：

```bash
# 列出所有用户
python scripts/manage_users.py list

# 创建用户（自动生成 API Key）
python scripts/manage_users.py create alice "Alice Developer" --role developer --level 1

# 创建用户（指定 API Key）
python scripts/manage_users.py create bob "Bob" --api-key "custom_key" --role admin

# 更新用户
python scripts/manage_users.py update alice --name "Alice Smith"
python scripts/manage_users.py update alice --role admin --level 5

# 删除用户
python scripts/manage_users.py delete alice

# 重新生成 API Key
python scripts/manage_users.py regenerate bob
```

### 权限规则

| 资源 | developer | admin |
|------|-----------|-------|
| 查看 workflow | 仅自己 | 全部 |
| 创建 workflow | 是 | 是 |
| 删除 workflow | 仅私有 | 任何 |
| 查看 runs | 仅自己 | 全部 |
| 删除 runs | 仅自己 | 任何 |

### 前端认证

前端通过 `X-API-Key` Header 发送请求：

```typescript
fetch('/api/workflows', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/json',
    'X-API-Key': 'dev_alice',
  },
  body: JSON.stringify({...}),
})
```

WebSocket 连接时自动从 Header 解析用户 ID，实现事件级隔离。

---

## 架构

```
┌─ 用户代码 ─────────────────────────────────┐
│                                             │
│  wf = Workflow("name", agents=[...])        │
│  wf.save()                                  │
│  result = wf.run({"task": "..."})           │
│                                             │
└──────────────┬──────────────────────────────┘
               │
               ▼
┌─ 后端 (Python / FastAPI) ──────────────────┐
│                                             │
│  harness/api.py      Agent, Workflow, Result│
│  harness/engine/     LangGraph + Pydantic AI│
│  harness/tools/      bash, sub_agent, chart │
│  harness/extensions/ EvalJudge, Plugins...  │
│  server/             REST + WebSocket       │
│                                             │
└──────────────┬──────────────────────────────┘
               │ EventBus / WebSocket
               ▼
┌─ 前端 (Next.js 14) ────────────────────────┐
│                                             │
│  DAG 面板       React Flow 可视化           │
│  输出面板       流式 Markdown 渲染           │
│  Chat 面板      ask_human 交互              │
│  追踪面板       节点级 Token 统计 + 预算条   │
│  图表面板       Recharts + 自定义 SVG       │
│  Analysis      Waterfall + 评分 + Token 图  │
│                                             │
└─────────────────────────────────────────────┘
```

## 项目结构

```
.
├── harness/
│   ├── api.py              Agent, Workflow, WorkflowResult
│   ├── config.py           configure(), .env 自动加载
│   ├── paths.py            项目根目录解析（get_project_root）
│   ├── registry.py         资源发现（Project + Builtin 两层）
│   ├── cli.py              harness ui / harness list 命令
│   ├── builtin/            随 pip 安装的内置资源
│   │   ├── workflows/      内置 workflow（demo_pipeline）
│   │   ├── benchmarks/     内置 benchmark（smoke-test）
│   │   └── frontend/       预构建前端
│   ├── engine/             LangGraph 状态图 + Pydantic AI 执行
│   ├── tools/              bash, sub_agent, ask_human, chart
│   ├── compiler/           DAG 构建, Markdown 解析, Agent 查找
│   └── extensions/         扩展系统（Hook / Middleware / GraphMutator）
│       ├── eval/           EvalJudge: 自动评审 + 评分 + 重试
│       ├── compact/        AutoCompact: 对话压缩
│       ├── envelope.py     预算控制（token/step/duration 限制）
│       ├── cost.py         模型定价 + USD 费用计算
│       └── plugins/        内置 Hook（EvalChart, Trace, Perf, StepCounter, CircularDetector...）
├── server/                 FastAPI 应用, 路由, WebSocket, EventBus
├── frontend/               Next.js 14 Web UI
├── workflows/              工作流定义目录
│   ├── <name>/
│   │   ├── workflow.json   Agent 定义 + DAG 拓扑
│   │   ├── agents/         私有 Agent 提示词（优先级 > _shared）
│   │   └── scripts/        私有脚本（路径注入到 Agent prompt）
│   └── _shared/
│       ├── agents/         共享 Agent（如 runner.md）
│       └── scripts/        跨 Workflow 共享脚本
├── benchmarks/             Benchmark 评测定义 + 结果
│   └── <name>/
│       ├── benchmark.json  任务列表 + prep 配置
│       ├── setup.sh        Prep 脚本（可选）
│       ├── agents/         Prep Agent MD（可选）
│       └── results/        运行历史（含分数 + 图表）
├── runs/                   运行记录 + checkpoints.db
├── examples/               可运行的示例（01-15）
├── tests/                  测试
└── docs/plans/             设计文档
```

## 示例索引

| # | 文件 | 模式 | 需要 LLM |
|---|------|------|----------|
| 1 | `01_minimal.py` | 单 Agent | 是 |
| 2 | `02_serial_pipeline.py` | 串行流水线 | 是 |
| 3 | `03_parallel.py` | 并行 + 合并 | 是 |
| 4 | `04_conditional_routing.py` | 条件路由 | 是 |
| 5 | `05_loop_retry.py` | DAG 级回环 | 是 |
| 6 | `06_sub_agent_loop.py` | sub_agent 迭代 | 是 |
| 7 | `07_ask_human.py` | 人机协作（需 UI） | 是 |
| 8 | `08_eval_judge.py` | EvalJudge 自动评审 + 评分 + 重试 | 是 |
| 9 | `09_charts.py` | Chart 可视化（需 UI） | 是 |
| 10 | `10_save_load_ui.py` | 持久化 + UI | 是 |
| 11 | `11_all_extensions.py` | 组合扩展 | 是 |
| 12 | `12_benchmark.py` | Benchmark 批量评测 | 是 |
| 13 | `13_console_output.py` | ConsoleOutput 命令行美化输出 | 是 |
| 14 | `14_benchmark_prep.py` | Benchmark Prep 前置准备 | 是 |
| 15 | `15_benchmark_prep_agent.py` | Benchmark Prep Agent 类型 | 是 |

---

## CLI 命令

`pip install` 后提供 `harness` 命令：

```bash
harness ui                              # 启动 Web UI（端口 8000）
harness ui --port 3000                  # 指定端口
harness ui --project-root /path/to/prj  # 显式指定项目根目录
harness ui --open                       # 自动打开浏览器
harness list                            # 列出已发现的 workflow 和 benchmark
harness list --scope builtin            # 只列出内置资源
harness list --scope project            # 只列出项目级资源
```

---

## 许可证

MIT
