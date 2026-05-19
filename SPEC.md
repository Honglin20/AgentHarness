# SPEC.md — 接口规范

> 本文件在每个 Phase 开发前与用户敲定后更新。
> 任何实现必须先更新此文件获得确认，再开始编码。

---

## 状态

| Phase | 状态 | 最后更新 |
|-------|------|---------|
| Phase 1 | ✅ 已敲定 | 2026-05-19 |
| Phase 2 | 🟡 待敲定 | — |
| Phase 3 | ⬜ 未开始 | — |
| Phase 4 | ⬜ 未开始 | — |

---

## §Agent — Agent 定义接口

> Phase 1 敲定（2026-05-19）

```python
from pydantic import BaseModel
from typing import Type[BaseModel] | None

class Agent:
    name: str                    # agent 唯一标识，对应 agents/<name>.md
    after: list[str]             # 依赖的 agent 名称列表（仅 API 定义，MD 中不放）
    tools: list[str] | None      # 运行时追加的工具，与 MD 中的 tools 合并
    model: str | None            # 模型，None 时用默认
    retries: int = 3             # Pydantic AI 重试次数
    result_type: Type[BaseModel] | None  # 结构化输出类型，仅 API 指定

# 用法
agent = Agent("refactorer", after=["analyzer"], tools=["bash", "fs"])
```

### Agent Markdown 格式

```markdown
---
name: refactorer
tools:
  - bash
  - fs
model: claude-sonnet-4-6
retries: 3
---

你是一个代码重构专家。你的任务是：
- 根据分析结果进行重构
- 保持测试通过
- 遵循项目代码规范
```

### 设计决策

- [x] YAML frontmatter 不放 `after` 字段 — 依赖关系是工作流拓扑属性，不属于单个 agent 自身，由 `Workflow` 统一管理
  - Why: 同一 agent 被不同 workflow 复用时依赖会冲突；MD 之间会产生隐式耦合
  - How: MD 只定义 agent 自身属性（name, tools, model, prompt），`after` 只在 API 中指定

- [x] `tools` 默认加载全部工具 — 除非用户显式声明
  - Why: 减少配置负担，大多数 agent 需要全部工具能力；显式声明仅用于限制工具范围（如只读 agent）
  - How: `Agent(tools=None)` → 加载所有已注册工具；`Agent(tools=["bash"])` → 只加载 bash；MD 中 `tools: [read_file]` → 只加载 read_file
  - 合并策略：MD 指定时以 MD 为准；API 可追加；两者都不指定时加载全部

- [x] 不单独设 `description` 字段 — 用 MD 的首行非 frontmatter 文本作为 description
  - Why: 避免重复维护，MD 开头写一句总结本来就该有
  - How: DAG 可视化时提取 MD 首行作为节点描述

- [x] `result_type` 不在 MD 中声明，仅在 API 中指定
  - Why: result_type 是 Pydantic model 类，本质是代码，不是自然语言能表达的
  - How: MD 定义"agent 是什么"，API 定义"agent 返回什么结构"

---

## §Workflow — 工作流定义接口

> Phase 1 敲定（2026-05-19）

```python
from langgraph.graph import StateGraph

class Workflow:
    name: str
    agents: list[Agent]

    def compile(self) -> CompiledStateGraph: ...  # 返回编译后的 LangGraph 图
    def run(self, inputs: dict) -> WorkflowResult: ...
    async def arun(self, inputs: dict) -> WorkflowResult: ...

# 用法
wf = Workflow("code_pipeline", agents=[
    Agent("analyzer", after=[]),
    Agent("refactorer", after=["analyzer"]),
    Agent("tester", after=["refactorer"]),
])
result = wf.run({"codebase_path": "/path/to/project", "task": "重构认证模块"})
```

### WorkflowResult 结构

```python
from typing import Any, Literal
from pydantic import BaseModel

class NodeTrace(BaseModel):
    agent_name: str
    status: Literal["success", "failed", "skipped"]
    duration_ms: int
    error: str | None = None

class WorkflowResult(BaseModel):
    outputs: dict[str, Any]       # {agent_name: result}
    errors: dict[str, str]        # {agent_name: error_message}
    trace: list[NodeTrace]        # 按执行顺序记录每个节点
```

### 设计决策

- [x] `inputs` 不做 schema 验证 — Phase 1 用 `dict` 就够，schema 验证是增强不阻塞核心
  - Why: 跑通优先，过早约束降低灵活性
  - How: `inputs` 作为 `dict` 传入，需要时通过 metadata 扩展

- [x] 不加 `Workflow.add_agent()` — 用构造函数一步到位
  - Why: Phase 1 工作流是静态定义，无运行时动态增删场景（YAGNI）
  - How: 需要时再加不过几行代码

- [x] `WorkflowResult` 包含 outputs + errors + trace
  - Why: outputs 是核心产出，errors 是失败定位，trace 是可观测性基础
  - How: token_usage 等增强字段留给 Phase 4 Langfuse 集成，通过 metadata 扩展

---

## §Engine — 双引擎接口

> Phase 1 敲定（2026-05-19）

### micro_agent.py — Pydantic AI 实例生成器

```python
from pydantic_ai import Agent as PydanticAgent

class MicroAgentFactory:
    """为每个 DAG 节点生成 Pydantic AI Agent 实例"""

    def create(
        self,
        name: str,
        prompt: str,                  # 从 MD 解析的 system prompt
        tools: list[str],             # 工具名称列表（MD 默认 + API 追加，已合并）
        model: str | None,
        retries: int,
        result_type: Type[BaseModel] | None,
    ) -> PydanticAgent: ...

    def build_node_prompt(
        self,
        inputs: dict,                 # 工作流初始输入（贯穿所有节点）
        upstream_outputs: dict,       # {agent_name: structured_output}
    ) -> str:
        """生成上下文部分（user message），agent 自身指令通过 system_prompt 设置"""
        parts = []

        if inputs:
            parts.append(f"## Task\n{json.dumps(inputs, indent=2, ensure_ascii=False)}")

        for name, output in upstream_outputs.items():
            if isinstance(output, BaseModel):
                parts.append(f"## Output from {name}\n{output.model_dump_json(indent=2)}")
            else:
                parts.append(f"## Output from {name}\n{output}")

        return "\n\n".join(parts)
```

### macro_graph.py — LangGraph 拓扑构建

```python
class MacroGraphBuilder:
    """将编译后的 DAG 转为 LangGraph StateGraph"""

    def build(self, workflow: Workflow) -> StateGraph: ...
    def add_conditional_edge(self, from_node, condition_fn, targets): ...
    def add_evaluator_edge(self, eval_node, pass_target, fail_target): ...
```

### State 定义

```python
from typing import TypedDict, Annotated
from operator import add

class HarnessState(TypedDict):
    inputs: dict                                   # 工作流初始输入，贯穿所有节点
    outputs: Annotated[dict, merge_dicts]          # {agent_name: result} — reducer 自动合并 fan-out
    errors: Annotated[dict, merge_dicts]           # {agent_name: error_info}
    metadata: Annotated[dict, merge_dicts]         # 可扩展插槽：token_usage, timestamps, 自定义标记等
```

### 三层上下文模型

| 概念 | 谁定义 | 作用 | 注入方式 |
|------|--------|------|---------|
| `inputs` | 调用方（用户/程序） | 告诉整个工作流"做什么" | 自动注入每个节点的 prompt（## Task） |
| `prompt` | agent 作者（MD 文件） | 告诉 agent "你是谁、怎么做" | 设为 Pydantic AI 的 system_prompt |
| `upstream outputs` | 上游 agent 运行时产生 | 告诉下游"上一步产出了什么" | 自动注入到 user message（## Output from X） |

节点 prompt = **system_prompt (md_prompt) + user message (inputs + upstream outputs)**

### 设计决策

- [x] `build_node_prompt` 自动注入，无模板语法 — agent 作者只需写 MD prompt，框架透明注入 inputs 和上游输出
  - Why: MD 文件不应包含框架模板语法，保持纯自然语言；下游 agent 不应关心注入机制
  - How: 框架自动拼接 md_prompt + inputs + upstream_outputs，agent 作者无感知

- [x] `HarnessState` 精简 + `metadata` 扩展插槽 — 不预设 token_usage/timestamps 等，通过 metadata 按需扩展
  - Why: 核心状态保持简单普适；扩展字段通过 metadata 动态添加，不需要改 state 定义
  - How: Phase 4 Langfuse 集成时往 metadata 写 token_usage/timestamps，接口不变

- [x] Fan-out 输出合并用 `Annotated[dict, add]` reducer — 多节点各自写 `{agent_name: result}`，LangGraph 自动合并
  - Why: dict 按 key 天然无冲突，reducer 自动处理并发写入
  - How: 每个节点输出 `{"agent_name": result}`，reducer 做 dict merge

- [x] 砍掉 `current_node` 和 `pending_human_input` — 前者从 LangGraph 内部获取，后者留给 Phase 3 HITL

---

## §Tools — 工具注册与解析

> Phase 2 敲定（2026-05-19）

### 设计原则

1. **不自建基础工具**：bash、fs 等通过 MCP Server 获取，`mcp_bridge` 是工具注册的核心入口
2. **默认加载，无需声明**：框架自动连接标准 MCP Server（bash + fs），用户 MD 中直接写工具名即可
3. **统一注册表**：所有工具（MCP 来源 + 自建如 sub_agent）注册到同一个 `ToolRegistry`
4. **高可扩展性**：`ToolFactory` 抽象 + `ToolRegistry` 开放注册，未来新工具只需实现 `create()` 并 `register()`
5. **工具分类对齐 Claude Code**：Read/Search、Write/Edit、Execute、Agent 四大类
6. **工具安全**：通过 `AgentDeps` 传递运行时上下文（工作目录等），工具内部做安全校验

### 工具分类

| 类别 | 工具名 | 来源 | 说明 |
|------|--------|------|------|
| **Read/Search** | `read_file` | MCP (server-filesystem) | 读取文件内容 |
| | `list_directory` | MCP (server-filesystem) | 列出目录内容 |
| | `search_files` | MCP (server-filesystem) | 搜索文件内容 |
| **Write/Edit** | `write_file` | MCP (server-filesystem) | 写入/创建文件 |
| | `edit_file` | MCP (server-filesystem) | 精确编辑文件（搜索替换） |
| **Execute** | `bash` | MCP (mcp-server-bash) | 执行 shell 命令 |
| **Agent** | `sub_agent` | 自建 (SubAgentToolFactory) | 委托子任务给临时 agent |
| **UI** *(Phase 3)* | `ask_human` | 自建 (AskHumanToolFactory) | 向用户提问并等待回答 |

### 默认 MCP Server（自动加载，无需声明）

```python
DEFAULT_MCP_SERVERS = [
    McpServerConfig(
        name="",  # 默认工具不加前缀
        command="npx",
        args=["-y", "@modelcontextprotocol/server-filesystem", "."],
    ),
    McpServerConfig(
        name="",  # 默认工具不加前缀
        command="npx",
        args=["-y", "@anthropic/mcp-server-bash"],
    ),
]
```

用户无需配置 `mcp_servers` 即可使用上表所有 MCP 工具。只有添加**自定义** MCP Server 时才需声明（此时加前缀防冲突）。

```python
# 默认即可用 bash、read_file 等工具
wf = Workflow("name", agents=[...])

# 添加自定义 MCP Server
wf = Workflow("name", agents=[...], mcp_servers=[
    McpServerConfig(name="github", command="npx", args=["-y", "@mcp/github"]),
    # → github_create_pr, github_list_issues
])
```

### ToolRegistry — 工具注册与解析

```python
from pydantic_ai import Tool as PydanticAITool

class ToolRegistry:
    """工具名 → ToolFactory 的注册表。所有工具的统一入口。"""

    def register(self, name: str, factory: ToolFactory) -> None:
        """注册工具工厂。覆盖同名工具。"""
        ...

    def resolve(self, tool_names: list[str] | None = None, exclude: list[str] | None = None) -> list[PydanticAITool]:
        """将工具名列表解析为 Pydantic AI Tool 实例列表

        Args:
            tool_names: 工具名列表。None 时加载全部已注册工具
            exclude: 需要排除的工具名（sub_agent 用于防止嵌套）

        Raises:
            ToolNotFoundError: 如果指定了工具名但未注册
        """
        ...

    def list_tools(self) -> list[str]:
        """列出所有已注册的工具名"""
        ...


class ToolFactory:
    """工具工厂抽象 — 生成 Pydantic AI Tool 实例"""

    name: str
    description: str

    def create(self) -> PydanticAITool:
        """创建 Pydantic AI Tool 实例"""
        ...


class ToolNotFoundError(Exception):
    pass
```

### SubAgentTool — 子代理委托工具

```python
class SubAgentToolFactory(ToolFactory):
    """sub_agent 工具 — agent 委托子任务给临时 agent，最多一层，不可嵌套"""

    name = "sub_agent"
    description = (
        "Launch a sub-agent to handle a specific task. "
        "Provide the task description and any relevant context. "
        "The sub-agent executes independently and returns its result. "
        "Sub-agents cannot spawn further sub-agents. "
        "Use for focused work that benefits from dedicated attention."
    )

    def __init__(
        self,
        registry: ToolRegistry,
        model: str | None = None,     # 子 agent 使用的模型，None 时继承父 agent
        max_depth: int = 1,           # 最大委托深度，1 = 只允许一层
    ): ...

    def create(self, depth: int = 0) -> PydanticAITool:
        """创建 sub_agent Tool

        Tool 函数签名:
            def sub_agent(ctx: RunContext, task: str) -> str

        参数:
            task: 子任务的完整描述，包含目标和上下文

        行为:
            1. 创建临时 Pydantic AI Agent
            2. 注册所有工具，但排除 sub_agent（物理防止嵌套）
            3. 注入 task 作为 prompt，运行并返回结果

        嵌套保护:
            depth=0 的 agent 可以有 sub_agent 工具
            depth>=1 的 agent 创建时 exclude=["sub_agent"]，物理上不可能嵌套
        """
        ...
```

**嵌套保护机制：**

```
orchestrator (depth=0, tools=[bash, fs, sub_agent])
  └─ sub_agent("研究XX") → 创建临时 agent (depth=1, tools=[bash, fs])  ← 没有 sub_agent
       └─ 只能直接执行，不能再委托
```

不是运行时检查拒绝嵌套，而是**子 agent 根本不注册 sub_agent 工具** — 从结构上杜绝。

### AgentDeps — 运行时依赖注入

```python
from pydantic import BaseModel

class AgentDeps(BaseModel):
    """通过 Pydantic AI RunContext.deps 传递给工具的运行时上下文"""
    workdir: str = "."               # 工作目录
    agent_name: str = ""             # 当前 agent 名称
    depth: int = 0                   # 当前委托深度
    model_config = {"extra": "allow"}  # 可扩展：未来加 workflow_id 等
```

这不是用户 API，是实现细节 — 让 MCP 工具和 sub_agent 知道"在哪个目录执行"、"当前是第几层委托"。

### MicroAgentFactory 更新

Phase 1 的 `MicroAgentFactory.create()` 需要扩展：

```python
class MicroAgentFactory:
    def __init__(self, tool_registry: ToolRegistry | None = None):
        self.tool_registry = tool_registry or ToolRegistry()

    def create(
        self,
        name: str,
        prompt: str,
        tools: list[str] | None,           # None = 加载全部工具；list = 只加载指定工具
        model: str | None,
        retries: int,
        result_type: Type[BaseModel] | None,
        deps: AgentDeps | None = None,     # Phase 2: 运行时依赖
        exclude_tools: list[str] | None = None,  # 排除的工具（sub_agent 嵌套保护）
    ) -> PydanticAgent:
        resolved_tools = self.tool_registry.resolve(tools, exclude=exclude_tools)
        agent = PydanticAgent(
            model=agent_model,
            system_prompt=prompt,
            retries=retries,
            output_type=result_type or str,
            defer_model_check=True,
            tools=resolved_tools,
            deps_type=AgentDeps,
        )
        return agent
```

### 默认工具注册

```python
def default_tool_registry() -> ToolRegistry:
    """创建默认工具注册表：sub_agent 自建工具"""
    registry = ToolRegistry()
    registry.register("sub_agent", SubAgentToolFactory(registry=registry))
    return registry

async def setup_default_mcp(registry: ToolRegistry, workdir: str = ".") -> list[McpBridge]:
    """连接默认 MCP Server 并注册工具。在 Workflow.compile() 中自动调用。"""
    bridges = []
    for config in DEFAULT_MCP_SERVERS:
        # 注入 workdir 到 fs server 的 args
        effective_config = config.with_workdir(workdir)
        bridge = McpBridge(effective_config, registry=registry)
        await bridge.connect()
        await bridge.register_tools()
        bridges.append(bridge)
    return bridges
```

### Phase 3 预留接口

```python
class AskHumanToolFactory(ToolFactory):
    """ask_human 工具 — agent 向用户提问并等待回答（Phase 3 实现）"""

    name = "ask_human"
    description = (
        "Ask the user a question and wait for their response. "
        "Use when you need clarification, confirmation, or input from the user."
    )

    def create(self) -> PydanticAITool:
        """Phase 2: stub。Phase 3: 实现 LangGraph interrupt + WebSocket 通知"""
        raise NotImplementedError("ask_human requires WebSocket (Phase 3)")
```

### 设计决策

- [x] 不自建 bash/fs — 通过 MCP Server 获取，mcp_bridge 是工具注册核心入口
  - Why: 不重复造轮子，MCP 生态已有成熟的 bash/fs server
  - How: 用户配置 MCP Server，McpBridge 连接并注册工具到 ToolRegistry

- [x] sub_agent 自建，最多一层，物理防嵌套
  - Why: agent 委托是核心能力，MCP 无法提供；嵌套会导致不可控的递归和成本
  - How: depth=1 的 agent 创建时 exclude=["sub_agent"]，从结构上不可能嵌套

- [x] sub_agent 无 role 参数 — 由上层 agent 在 task 描述中决定子任务内容
  - Why: role 是冗余抽象，上层 agent 的 task 描述已经包含了角色和目标
  - How: sub_agent(task="你是一个研究员，请研究XX") 即可

- [x] 工具 description 简洁精确 — 参考 Claude Code 风格，一句话说清功能和使用场景

- [x] ask_human Phase 3 实现，Phase 2 预留 stub
  - Why: ask_human 需要 LangGraph interrupt + WebSocket，依赖 Phase 3
  - How: ToolFactory stub 抛 NotImplementedError，ToolRegistry 中预留注册位

---

## §MCP — MCP 适配接口

> Phase 2 敲定（2026-05-19）

### 核心流程

```
MCP Server (stdio) → list_tools() → [MCPTool] → McpBridge 逐个转为 McpToolFactory → 注册到 ToolRegistry
```

基础工具（bash, fs）来自 MCP Server，不自建。用户在 Workflow 级别配置 MCP Server，McpBridge 负责连接、发现工具、注册。

### McpBridge — MCP 工具适配器

```python
from mcp import ClientSession, StdioServerParameters

class McpToolFactory(ToolFactory):
    """将单个 MCP Tool 适配为 Pydantic AI Tool — 适配层极薄"""

    def __init__(
        self,
        session: ClientSession,
        mcp_tool_name: str,            # MCP Server 上的原始工具名
        description: str,
        input_schema: dict,            # JSON Schema → Pydantic model 参数
    ): ...

    def create(self) -> PydanticAITool:
        """创建 Pydantic AI Tool，内部调用 session.call_tool()

        适配逻辑:
            MCP inputSchema (JSON Schema) → Pydantic model (参数)
            session.call_tool(name, args) → str (输出)
        """
        ...


class McpBridge:
    """连接 MCP Server，发现工具并注册到 ToolRegistry"""

    def __init__(
        self,
        config: McpServerConfig,
        registry: ToolRegistry,
    ): ...

    async def connect(self) -> None:
        """启动 MCP Server 进程并建立连接（stdio 传输）"""
        ...

    async def register_tools(self) -> list[str]:
        """发现所有工具并注册到 registry

        Returns:
            注册的工具名列表（含前缀）
        """
        ...

    async def disconnect(self) -> None:
        """关闭 MCP Server 进程"""
        ...

    @property
    def tools(self) -> list[str]:
        """已注册的 MCP 工具名列表"""
        ...
```

### MCP Server 配置

```python
from pydantic import BaseModel

class McpServerConfig(BaseModel):
    """MCP Server 连接配置 — 用户在 Workflow 级别指定"""
    name: str                         # 服务名，作为工具名前缀（如 "fs" → fs_read, fs_write）
    command: str                      # 启动命令，如 "npx"
    args: list[str] = []              # 命令参数，如 ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
    env: dict[str, str] = {}          # 环境变量
```

### Workflow 扩展

```python
class Workflow:
    def __init__(
        self,
        name: str,
        agents: list[Agent],
        agents_dir: str = "agents",
        mcp_servers: list[McpServerConfig] | None = None,  # Phase 2: MCP 服务器配置
    ): ...
```

### MCP 生命周期

- **默认 MCP Server 自动加载**：Workflow.compile() 时自动连接 bash + fs MCP Server，无需用户声明
- **自定义 MCP Server 用户声明**：通过 `Workflow(mcp_servers=[...])` 添加，name 作为工具名前缀
- **Workflow 级别生命周期**：compile 时连接，工作流结束时断开
- **Phase 2 只支持 stdio**：SSE 传输（远程 MCP Server）留给 Phase 3
- **工具名前缀规则**：默认 Server name="" → 不加前缀（`read_file`）；自定义 Server name="github" → 加前缀（`github_create_pr`）

### 设计决策

- [x] MCP 是工具注册的核心入口 — bash/fs 等基础工具不自建，通过 MCP Server 获取
  - Why: 不重复造轮子，MCP 生态已有成熟工具；工具升级只需换 MCP Server 版本
  - How: 默认 MCP Server 自动加载，用户无需声明即可使用 bash、read_file 等工具

- [x] 默认 MCP Server 不加前缀，自定义 MCP Server 加前缀
  - Why: 默认工具是标准集，用户期望直接用 `read_file`；自定义 Server 可能有命名冲突
  - How: `McpServerConfig(name="")` → `read_file`；`McpServerConfig(name="github")` → `github_create_pr`

- [x] Phase 2 只支持 stdio 传输 — SSE 留给 Phase 3
  - Why: stdio 最简单，本地 MCP Server 够用；SSE 需要额外处理 HTTP 连接管理
  - How: 使用 `mcp.ClientSession` + `StdioServerParameters`

- [x] MCP 连接生命周期绑定 Workflow — compile 时连接，结束时断开
  - Why: 最简单的资源管理，不泄漏进程；全局单例增加复杂度
  - How: `Workflow.compile()` 中 `await bridge.connect()` + `register_tools()`

---

## §WS — WebSocket 事件协议

> Phase 3 敲定

（待 Phase 2 完成后讨论）

---

## §API — RESTful 接口

> Phase 3 敲定

（待 Phase 2 完成后讨论）

---

## §Hook — Hook 机制接口

> Phase 4 敲定

（待 Phase 3 完成后讨论）

---

## §Memory — 记忆机制接口

> Phase 4 敲定

（待 Phase 3 完成后讨论）

---

## §Eval — 评估节点接口

> Phase 4 敲定

（待 Phase 3 完成后讨论）
