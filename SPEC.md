# SPEC.md — 接口规范

> 本文件在每个 Phase 开发前与用户敲定后更新。
> 任何实现必须先更新此文件获得确认，再开始编码。

---

## 状态

| Phase | 状态 | 最后更新 |
|-------|------|---------|
| Phase 1 | ✅ 已敲定 | 2026-05-19 |
| Phase 2 | ✅ 已敲定 | 2026-05-20 |
| Phase 3 | ✅ 已敲定 + 已实现 | 2026-05-20 |
| Phase 4 | 🔄 敲定中 | 2026-05-20 |

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

    def to_dict(self) -> dict: ...          # 序列化为 dict（用于 save/load）
    @classmethod
    def from_dict(cls, d: dict) -> Agent: ...  # 从 dict 反序列化

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
    agents_dir: str
    mcp_servers: list[McpServerConfig]
    tool_registry: ToolRegistry

    def compile(self) -> CompiledStateGraph:
        """编译为 LangGraph StateGraph。仅使用 registry 中已有工具，
        不连接 MCP Server。如果 registry 为空，注册默认自建工具（sub_agent + bash）。"""

    async def setup(self) -> None:
        """连接 MCP Server + 注册工具 + compile。arun() 前须调用。
        run() 内部自动调用，不需要手动 setup()。"""

    async def cleanup(self) -> None:
        """断开 MCP Server 连接。Best-effort，不抛异常。"""

    def run(self, inputs: dict, ui: bool = False) -> WorkflowResult:
        """同步运行。内部调用 setup() → arun() → cleanup()。
        ui=True 时自动启动服务器并打开浏览器。"""

    async def arun(self, inputs: dict) -> WorkflowResult:
        """异步运行。调用方负责 MCP 生命周期（先 setup 再 arun）。"""

    def save(self) -> Path: ...                    # 保存到 workflows/<name>.json
    @classmethod
    def load(cls, name: str) -> Workflow: ...      # 从 workflows/<name>.json 加载
    @staticmethod
    def list_saved() -> list[dict]: ...            # 列出所有已保存 workflow 定义
    def to_dict(self) -> dict: ...                 # 序列化（含 agents_dir）
    @classmethod
    def from_dict(cls, data: dict, agents_dir: str | None = None) -> Workflow: ... # 反序列化

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

class TokenUsage(BaseModel):
    input: int
    output: int
    total: int

class NodeTrace(BaseModel):
    agent_name: str
    status: Literal["success", "failed", "skipped"]
    duration_ms: int
    error: str | None = None
    token_usage: TokenUsage | None = None  # 每个 agent 的 token 使用量

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

- [x] `WorkflowResult` 包含 outputs + errors + trace + token_usage
  - Why: outputs 是核心产出，errors 是失败定位，trace 是可观测性基础，token_usage 是成本追踪
  - How: token_usage 通过 metadata 扩展插槽存入，Phase 4 Langfuse 集成时增强

- [x] `setup()` / `cleanup()` 分离 MCP 生命周期 — `run()` 内部自动管理，`arun()` 需手动调用
  - Why: 同步调用方便，异步调用需要灵活性（如复用 MCP 连接跑多次）
  - How: `run()` 调用 `_execute()` 包含 setup → arun → cleanup；`arun()` 前须手动 `setup()`

- [x] `compile()` 不连接 MCP Server — 仅编译 DAG
  - Why: compile 是纯拓扑操作，不应有 IO 副作用
  - How: MCP 连接在 `setup()` 中完成；`compile()` 仅在 registry 已有工具时工作

---

## §Engine — 双引擎接口

> Phase 1 敲定（2026-05-19）

### LLMClient — LLM 客户端管理

> 实际实现中从 MicroAgentFactory 提取出来，集中管理 httpx/Provider/Model 创建。

```python
class LLMClient:
    """管理 httpx client, OpenAI provider, model, 和 agent 创建。

    所有配置从环境变量读取，支持显式参数覆盖。
    环境变量: HARNESS_MODEL, HARNESS_API_KEY, HARNESS_API_URL, HARNESS_PROXY, HARNESS_SSL_VERIFY
    """

    def __init__(
        self,
        model: str | None = None,       # 覆盖 HARNESS_MODEL
        api_key: str | None = None,      # 覆盖 HARNESS_API_KEY
        api_url: str | None = None,      # 覆盖 HARNESS_API_URL
        proxy: str | None = None,        # 覆盖 HARNESS_PROXY
        ssl_verify: bool | None = None,  # 覆盖 HARNESS_SSL_VERIFY
    ): ...

    @property
    def model_name(self) -> str: ...

    @property
    def api_url(self) -> str: ...

    def agent(
        self,
        system_prompt: str,
        output_type: type = str,
        retries: int = 3,
        tools: list | None = None,
        deps_type: type | None = None,
    ) -> PydanticAgent:
        """创建配置好的 PydanticAgent 实例"""
        ...
```

### micro_agent.py — Pydantic AI 实例生成器

```python
from pydantic_ai import Agent as PydanticAgent

class MicroAgentFactory:
    """为每个 DAG 节点生成 Pydantic AI Agent 实例"""

    def __init__(self, tool_registry: ToolRegistry | None = None):
        self.tool_registry = tool_registry or ToolRegistry()

    def create(
        self,
        name: str,
        prompt: str,                  # 从 MD 解析的 system prompt
        tools: list[str] | None,      # None = 加载全部工具；list = 只加载指定工具
        model: str | None,
        retries: int,
        result_type: Type[BaseModel] | None,
        deps: AgentDeps | None = None,           # 运行时依赖
        exclude_tools: list[str] | None = None,  # 排除的工具（sub_agent 嵌套保护）
    ) -> PydanticAgent:
        resolved_tools = self.tool_registry.resolve(tools, exclude=exclude_tools)
        client = LLMClient(model=model) if model else LLMClient()
        agent = client.agent(
            system_prompt=prompt,
            output_type=result_type or str,
            retries=retries,
            tools=resolved_tools,
            deps_type=AgentDeps,
        )
        return agent

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

    def __init__(self, tool_registry: ToolRegistry, event_bus: Any | None = None): ...
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

State 的 key 在 `harness/constants.py` 中定义为常量：`STATE_INPUTS`, `STATE_OUTPUTS`, `STATE_ERRORS`, `STATE_METADATA`。

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

1. **bash 自建，fs 通过 MCP**：bash 在 npm 上无标准 MCP server，自建为最小方案；fs 通过 MCP server-filesystem 获取
2. **默认加载，无需声明**：框架自动连接标准 MCP Server（fs），用户 MD 中直接写工具名即可
3. **统一注册表**：所有工具（MCP 来源 + 自建如 sub_agent）注册到同一个 `ToolRegistry`
4. **高可扩展性**：`ToolFactory` 抽象 + `ToolRegistry` 开放注册，未来新工具只需实现 `create()` 并 `register()`
5. **工具分类对齐 Claude Code**：Read/Search、Write/Edit、Execute、Agent、UI 五大类
6. **工具安全**：通过 `AgentDeps` 传递运行时上下文（工作目录等），工具内部做安全校验

### 工具分类

| 类别 | 工具名 | 来源 | 说明 |
|------|--------|------|------|
| **Read/Search** | `read_file` | MCP (server-filesystem) | 读取文件内容 |
| | `list_directory` | MCP (server-filesystem) | 列出目录内容 |
| | `search_files` | MCP (server-filesystem) | 搜索文件内容 |
| **Write/Edit** | `write_file` | MCP (server-filesystem) | 写入/创建文件 |
| | `edit_file` | MCP (server-filesystem) | 精确编辑文件（搜索替换） |
| **Execute** | `bash` | 自建 (BashToolFactory) | 执行 shell 命令（npm 无标准 bash MCP server） |
| **Agent** | `sub_agent` | 自建 (SubAgentToolFactory) | 委托子任务给临时 agent |
| **UI** | `ask_human` | 自建 (AskHumanToolFactory) | 向用户提问并等待回答 |

### 默认 MCP Server（自动加载，无需声明）

```python
DEFAULT_MCP_SERVERS = [
    # 自动发现 filesystem server 二进制路径，找不到时回退到 npx
    # 优先级：本地二进制 > npx
]
```

实际连接逻辑在 `setup_default_mcp()` 中：
1. 先搜索本地 `mcp-server-filesystem` 二进制路径
2. 找到则直接使用，否则回退到 `npx -y @modelcontextprotocol/server-filesystem`

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

### BashToolFactory — 自建 Bash 工具

> npm 上无标准 bash MCP server（`@anthropic/mcp-server-bash` 不存在），因此 bash 作为自建工具直接注册到 ToolRegistry。

```python
class BashToolFactory(ToolFactory):
    """bash 工具 — 执行 shell 命令，自建为最小方案"""

    name = "bash"
    description = (
        "Execute a bash command and return its output. "
        "Use for running shell commands, scripts, and system operations. "
        "Commands execute in the agent's working directory."
    )

    def __init__(self, timeout: int = 30):
        """可配置超时时间，默认 30 秒"""

    def create(self) -> PydanticAITool:
        """创建 bash Tool

        Tool 函数签名:
            def bash(ctx: RunContext, command: str) -> str

        参数:
            command: 要执行的 shell 命令

        行为:
            1. 使用 subprocess.run 执行命令
            2. 返回 stdout + stderr
            3. 超时保护（默认 30s，可通过构造函数配置）
        """
        ...
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
            async def sub_agent(ctx: RunContext, task: str) -> str

        参数:
            task: 子任务的完整描述，包含目标和上下文

        行为:
            1. 检查 depth >= max_depth → 返回错误信息
            2. 创建临时 Pydantic AI Agent（通过 LLMClient）
            3. 注册所有工具，但排除 sub_agent（物理防止嵌套）
            4. 注入 task 作为 prompt，运行并返回结果

        嵌套保护:
            两层保护：
            a) depth 检查：depth >= max_depth 时直接返回错误
            b) 工具排除：子 agent 创建时 exclude=["sub_agent"]，物理上不可能嵌套
        """
        ...
```

**嵌套保护机制：**

```
orchestrator (depth=0, tools=[bash, fs, sub_agent])
  └─ sub_agent("研究XX") → depth >= max_depth? → No → 创建临时 agent (depth=1, tools=[bash, fs])  ← 没有 sub_agent
       └─ 若尝试 sub_agent → depth >= max_depth? → Yes → 返回错误
```

不是运行时检查拒绝嵌套，而是**子 agent 根本不注册 sub_agent 工具** — 从结构上杜绝。`depth >= max_depth` 是额外防线。

### AskHumanToolFactory — 向用户提问工具

```python
class AskHumanToolFactory(ToolFactory):
    """ask_human 工具 — agent 向用户提问并等待回答"""

    name = "ask_human"
    description = (
        "Ask the user a question and wait for their response. "
        "Use when you need clarification, confirmation, or input from the user. "
        "The user's response will be returned to you as plain text."
    )

    def __init__(self, event_bus: Any | None = None): ...

    def create(self) -> PydanticAITool:
        """创建 ask_human Tool

        Tool 函数签名:
            async def ask_human(ctx: RunContext, question: str) -> str

        参数:
            question: 向用户提出的问题

        行为:
            1. 生成 question_id，创建 asyncio.Future
            2. bus.emit("chat.question", {question_id, question, node_id, agent_name})
            3. await future（超时 300s，返回 "User disconnected. Proceed with your best judgment."）
            4. WebSocket handler 收到 chat.answer 时 resolve_question() 解除等待
        """
        ...


async def resolve_question(question_id: str, answer: str) -> None:
    """由 WebSocket handler 调用，解析用户的回答并 set_result Future"""
    ...
```

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
        deps: AgentDeps | None = None,     # 运行时依赖
        exclude_tools: list[str] | None = None,  # 排除的工具（sub_agent 嵌套保护）
    ) -> PydanticAgent:
        resolved_tools = self.tool_registry.resolve(tools, exclude=exclude_tools)
        client = LLMClient(model=model) if model else LLMClient()
        agent = client.agent(
            system_prompt=prompt,
            output_type=result_type or str,
            retries=retries,
            tools=resolved_tools,
            deps_type=AgentDeps,
        )
        return agent
```

### 默认工具注册

```python
def default_tool_registry(event_bus=None) -> ToolRegistry:
    """创建默认工具注册表：sub_agent + bash 自建工具。
    当 event_bus 不为 None 时，额外注册 ask_human 工具。"""
    registry = ToolRegistry()
    registry.register("sub_agent", SubAgentToolFactory(registry=registry))
    registry.register("bash", BashToolFactory())
    if event_bus:
        registry.register("ask_human", AskHumanToolFactory(event_bus=event_bus))
    return registry

async def setup_default_mcp(registry: ToolRegistry, workdir: str = ".", server_path: str | None = None) -> list[McpBridge]:
    """连接默认 MCP Server 并注册工具。在 Workflow.setup() 中自动调用。

    自动发现 filesystem server 二进制路径：
    1. 搜索本地路径（/tmp/mcp-servers/, ~/.local/bin/）
    2. 找到则直接使用二进制
    3. 找不到则回退到 npx -y @modelcontextprotocol/server-filesystem
    """
    ...
```

### 设计决策

- [x] bash 自建，fs 通过 MCP — bash MCP server 不存在于 npm，自建为最小方案；fs 通过 MCP server-filesystem 获取
  - Why: npm 上 `@anthropic/mcp-server-bash` 返回 404，无法通过 MCP 获取 bash 工具；filesystem MCP server 可用
  - How: BashToolFactory 自建并注册到 ToolRegistry；McpBridge 连接 server-filesystem 注册 fs 工具

- [x] sub_agent 自建，最多一层，物理防嵌套 + depth 检查双保险
  - Why: agent 委托是核心能力，MCP 无法提供；嵌套会导致不可控的递归和成本
  - How: depth 检查（depth >= max_depth 返回错误）+ 子 agent 创建时 exclude=["sub_agent"]（结构上不可能嵌套）

- [x] sub_agent 无 role 参数 — 由上层 agent 在 task 描述中决定子任务内容
  - Why: role 是冗余抽象，上层 agent 的 task 描述已经包含了角色和目标
  - How: sub_agent(task="你是一个研究员，请研究XX") 即可

- [x] 工具 description 简洁精确 — 参考 Claude Code 风格，一句话说清功能和使用场景

- [x] ask_human 已实现 — 通过 WebSocket Future 方案，不需 LangGraph interrupt
  - Why: Pydantic AI 的 tool loop 是封闭循环，interrupt 打断它与双引擎架构冲突
  - How: 原生 async/await + Future，在 tool 层面自然解决

---

## §MCP — MCP 适配接口

> Phase 2 敲定（2026-05-19）

### 核心流程

```
MCP Server (stdio) → list_tools() → [MCPTool] → McpBridge 逐个转为 McpToolFactory → 注册到 ToolRegistry
```

fs 等文件操作工具来自 MCP Server，bash 自建。用户在 Workflow 级别配置 MCP Server，McpBridge 负责连接、发现工具、注册。

### McpBridge — MCP 工具适配器

```python
from mcp import ClientSession, StdioServerParameters

class McpToolFactory(ToolFactory):
    """将单个 MCP Tool 适配为 Pydantic AI Tool — 适配层极薄"""

    def __init__(
        self,
        session: ClientSession,
        mcp_tool_name: str,            # MCP Server 上的原始工具名
        registered_name: str,          # 注册到 ToolRegistry 的名称（可能含前缀）
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
        """关闭 MCP Server 进程。Best-effort — 不抛异常"""
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
    name: str = ""                    # 服务名，作为工具名前缀（如 "fs" → fs_read, fs_write）；空串不加前缀
    command: str                      # 启动命令，如 "npx"
    args: list[str] = []              # 命令参数，如 ["-y", "@modelcontextprotocol/server-filesystem", "/path"]
    env: dict[str, str] = {}          # 环境变量

    def tool_name(self, mcp_tool_name: str) -> str:
        """生成注册名：有前缀则 prefix_name，无前缀则 name"""
        return f"{self.name}_{mcp_tool_name}" if self.name else mcp_tool_name

    def to_stdio_params(self) -> StdioServerParameters:
        """转为 MCP SDK 的 StdioServerParameters"""
        ...
```

### Workflow 扩展

```python
class Workflow:
    def __init__(
        self,
        name: str,
        agents: list[Agent],
        agents_dir: str = "agents",
        mcp_servers: list[McpServerConfig] | None = None,
        tool_registry: ToolRegistry | None = None,
        event_bus: Any | None = None,  # 可选 EventBus，用于实时事件推送
    ): ...
```

### MCP 生命周期

- **默认 MCP Server 自动加载**：Workflow.setup() 时自动连接 fs MCP Server，无需用户声明
- **自定义 MCP Server 用户声明**：通过 `Workflow(mcp_servers=[...])` 添加，name 作为工具名前缀
- **Workflow 级别生命周期**：setup 时连接，cleanup 时断开
- **Phase 2/3 只支持 stdio**：SSE 传输（远程 MCP Server）留给后续
- **工具名前缀规则**：默认 Server name="" → 不加前缀（`read_file`）；自定义 Server name="github" → 加前缀（`github_create_pr`）

### 设计决策

- [x] bash 自建，fs 通过 MCP — bash MCP server 不存在于 npm；fs 通过 MCP server-filesystem 获取
  - Why: 不重复造轮子，MCP 生态已有成熟 fs 工具；bash 则必须自建
  - How: BashToolFactory 自建注册；McpBridge 连接 server-filesystem 注册 fs 工具

- [x] 默认 MCP Server 不加前缀，自定义 MCP Server 加前缀
  - Why: 默认工具是标准集，用户期望直接用 `read_file`；自定义 Server 可能有命名冲突
  - How: `McpServerConfig(name="")` → `read_file`；`McpServerConfig(name="github")` → `github_create_pr`

- [x] Phase 2/3 只支持 stdio 传输 — SSE 留给后续
  - Why: stdio 最简单，本地 MCP Server 够用；SSE 需要额外处理 HTTP 连接管理
  - How: 使用 `mcp.ClientSession` + `StdioServerParameters`

- [x] MCP 连接生命周期绑定 Workflow — setup 时连接，cleanup 时断开
  - Why: 最简单的资源管理，不泄漏进程；全局单例增加复杂度
  - How: `Workflow.setup()` 中 `await bridge.connect()` + `register_tools()`

---

## §Config — 配置系统

> 实现中提取，SPEC 补充记录。

### 环境变量

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `HARNESS_MODEL` | LLM 模型名 | 无（必须设置） |
| `HARNESS_API_KEY` | Provider API key | 空 |
| `HARNESS_API_URL` | API base URL | 空 |
| `HARNESS_PROXY` | HTTP proxy | 空 |
| `HARNESS_SSL_VERIFY` | SSL 验证 | `"true"` |
| `HARNESS_HOST` | 服务器绑定地址 | `"localhost"` |
| `HARNESS_PORT` | 服务器绑定端口 | `"8000"` |
| `HARNESS_SERVER_URL` | 服务器完整 URL（自动设置） | `http://{host}:{port}` |

### 配置 API

```python
# harness/config.py

def configure(
    api_key: str | None = None,
    model: str | None = None,
    api_url: str | None = None,
    proxy: str | None = None,
    ssl_verify: str | None = None,
    persist: bool = True,
) -> dict:
    """设置 API key / model / URL / proxy / SSL verify。可选持久化到 .env 文件。
    自动将 HARNESS_API_KEY 映射到 provider-specific 环境变量（DEEPSEEK_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY）。"""

def get_config() -> dict:
    """返回当前配置（key 已脱敏）。"""
```

### 自动加载

`harness/config.py` 在 import 时自动：
1. 加载 `.env` 文件
2. 将 `HARNESS_API_KEY` 映射到 provider 环境变量（DeepSeek, OpenAI, Anthropic）

---

## §WS — WebSocket 事件协议

> Phase 3 敲定（2026-05-20）

### 统一事件格式

```json
{
  "type": "workflow.started",
  "ts": 1716000000000,
  "payload": { ... }
}
```

所有事件包含 `ts` 时间戳字段（毫秒级 Unix 时间）。

### 事件类型

| 事件类型 | 方向 | 触发时机 |
|----------|------|---------|
| `workflow.started` | S→C | run() 调用时，含完整 DAG 结构和 inputs |
| `workflow.completed` | S→C | 所有节点完成，含 outputs/errors/trace |
| `workflow.cancelled` | S→C | 工作流被取消 |
| `workflow.error` | S→C | 工作流执行异常 |
| `node.started` | S→C | 节点开始执行 |
| `node.completed` | S→C | 节点成功完成（含耗时） |
| `node.failed` | S→C | 节点失败（含错误、是否重试） |
| `agent.text_delta` | S→C | LLM 逐 token 流式输出 |
| `agent.tool_call` | S→C | agent 调用工具 |
| `agent.tool_result` | S→C | 工具返回结果 |
| `chart.render` | S→C | chart 数据就绪，前端渲染 |
| `chat.question` | S→C | agent 需要人类回答 |
| `chat.answer` | C→S | 用户回答问题 |
| `workflow.interrupt` | C→S | 用户主动打断当前 agent |
| `workflow.resumed` | S→C | agent 已恢复执行 |

### 架构

```
LangGraph 节点函数 → bus.emit() → EventBus（asyncio.Queue per subscriber）
  → WebSocket handler → websocket.send_json() → 前端 zustand store → React
```

### EventBus

```python
# server/event_bus.py — 进程级单例 pub/sub

class EventBus:
    async def subscribe(self) -> tuple[str, asyncio.Queue]: ...
    async def unsubscribe(self, sub_id: str) -> None: ...
    def emit(self, event_type: str, payload: dict) -> None:  # 同步，fire-and-forget

def get_event_bus() -> EventBus:  # 单例
    ...
```

### 设计决策

- [x] ask_human 用 WebSocket Future，不用 LangGraph interrupt
  - Why: Pydantic AI 的 tool loop 是封闭循环，interrupt 打断它与双引擎架构冲突
  - How: 原生 async/await + Future，在 tool 层面自然解决
- [x] chart 不是 Pydantic AI tool，是代码调用的纯函数（见 §Chart）

---

## §RunStore — 运行持久化

> Phase 3 补充（2026-05-21）

### 定位

将已完成的 workflow 运行记录持久化到文件系统，支持历史回看和 agent diff 对比。

### 接口

```python
# harness/run_store.py

class RunStore:
    """文件系统运行记录持久化。每条记录 = runs/{run_id}.json"""

    def __init__(self, runs_dir: str | Path | None = None): ...

    def save(
        self,
        run_id: str,
        workflow_name: str,
        agents_snapshot: list[dict],
        status: str,
        inputs: dict,
        result: dict | None,
    ) -> Path: ...

    def list_runs(self, workflow_name: str | None = None) -> list[dict]:
        """列出运行记录，最新优先。可选按 workflow_name 过滤。"""

    def get_run(self, run_id: str) -> dict | None:
        """获取单条运行记录，不存在返回 None。"""
```

### agents_snapshot 结构

每次运行完成时，Runner 自动快照所有 agent 的 MD 文件内容：

```python
{
    "name": "analyzer",
    "after": [],
    "md_content": "---\nname: analyzer\n---\n你是一个代码分析专家...",  # 完整 MD 文件内容
    "tools": null,
    "model": null,
    "retries": 3
}
```

### 运行记录文件格式

```json
{
  "run_id": "uuid",
  "workflow_name": "code_review",
  "agents_snapshot": [...],
  "status": "completed",
  "inputs": {"task": "review foo"},
  "result": {
    "outputs": {"analyzer": "ok"},
    "errors": {},
    "trace": [...]
  },
  "created_at": "2026-05-21T14:30:00+00:00"
}
```

### 设计决策

- [x] 文件系统持久化，每条记录一个 JSON 文件
  - Why: 简单、可调试、无需数据库依赖；当前不需要复杂查询
  - How: `runs/{run_id}.json`，list_runs 扫描目录并按 created_at 降序排列
- [x] agents_snapshot 包含完整 MD 内容
  - Why: 支持 agent diff 对比 — 比较两次运行间 agent 定义的变更
  - How: Runner 完成时读取每个 agent 的 .md 文件全文存入 snapshot

---

## §AgentCRUD — Agent Markdown 读写

> Phase 3 补充（2026-05-21）

### write_agent_md

```python
# harness/compiler/md_parser.py

def write_agent_md(
    path: Path,
    name: str,
    prompt: str,
    tools: list[str] | None = None,
    model: str | None = None,
    retries: int = 3,
    on_pass: str | None = None,
    on_fail: str | None = None,
) -> None:
    """写入 agent Markdown 文件（YAML frontmatter + prompt）。"""
```

### API 端点

- `GET /api/agents/{name}/md?agents_dir=xxx` — 返回 `{"name", "md_content", "agents_dir"}`
- `PUT /api/agents/{name}/md` — 更新 agent MD 文件，body: `{"agents_dir", "md_content"}`

### 设计决策

- [x] 写入后立即 re-parse 验证
  - Why: 防止写入无效 MD 导致后续工作流启动失败
  - How: PUT 端点写入后调用 parse_agent_md，解析失败返回 400

---

## §API — RESTful 接口

> Phase 3 敲定（2026-05-20）

| 方法 | 路径 | 用途 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `GET` | `/api/agents` | 列出可用 agent |
| `GET` | `/api/agents/{name}` | 获取 agent 定义 |
| `GET` | `/api/tools` | 列出已注册工具 |
| `POST` | `/api/workflows` | 创建并启动工作流 |
| `GET` | `/api/workflows/{id}` | 查询工作流状态 |
| `POST` | `/api/workflows/{id}/cancel` | 取消运行中的工作流 |
| `GET` | `/api/workflows/{id}/dag` | 获取 DAG 结构 |
| `GET` | `/api/workflows/{id}/trace` | 获取执行 trace |
| `POST` | `/api/charts` | chart HTTP 通道（子进程 / 外部脚本） |
| `GET` | `/api/config` | 获取当前配置（key 已脱敏） |
| `POST` | `/api/config` | 设置 API key / model 等 |
| `GET` | `/api/workflows/definitions` | 列出已保存的 workflow 定义 |
| `GET` | `/api/runs` | 列出持久化的运行记录 |
| `GET` | `/api/runs/{run_id}` | 获取单条运行记录 |
| `GET` | `/api/agents/{name}/md` | 获取 agent 原始 Markdown |
| `PUT` | `/api/agents/{name}/md` | 更新 agent Markdown |
| `WS` | `/ws/workflows/{id}` | WebSocket 实时事件流 |

### HARNESS_SERVER_URL

服务启动时自动设环境变量，子进程继承：

```python
# server/app.py lifespan
host = os.environ.get("HARNESS_HOST", "localhost")
port = os.environ.get("HARNESS_PORT", "8000")
os.environ["HARNESS_SERVER_URL"] = f"http://{host}:{port}"
```

注：环境变量名为 `HARNESS_SERVER_URL`（不是 `HARNESS_API_URL`）。后者是 LLM API 的 base URL。

### 前端静态服务

后端自动 serve `frontend/out/` 目录，支持单端口部署：
- 如果 `frontend/out/` 存在 → 挂载为静态文件
- 如果不存在 → 返回提示页面，API 仍可用

### API 数据模型

```python
# server/schemas.py

class AgentDef(BaseModel):
    name: str
    after: list[str] = []

class CreateWorkflowRequest(BaseModel):
    name: str
    agents: list[AgentDef]
    agents_dir: str = "agents"
    inputs: dict = {}

class CreateWorkflowResponse(BaseModel):
    workflow_id: str
    status: str = "running"
    dag: dict | None = None

class WorkflowStatusResponse(BaseModel):
    workflow_id: str
    name: str
    status: str
    result: dict[str, Any] | None = None

class AgentInfo(BaseModel):
    name: str
    description: str | None = None
    model: str | None = None
    retries: int = 3
    tools: list[str] = []

class ToolInfo(BaseModel):
    name: str
    description: str

class HealthResponse(BaseModel):
    status: str = "ok"

class AgentSnapshot(BaseModel):
    """运行时 agent 定义的快照。"""
    name: str
    after: list[str] = []
    md_content: str = ""
    tools: list[str] | None = None
    model: str | None = None
    retries: int = 3

class RunDetail(BaseModel):
    """持久化的完整运行记录。"""
    run_id: str
    workflow_name: str
    agents_snapshot: list[AgentSnapshot] = []
    status: str
    inputs: dict = {}
    result: dict[str, Any] | None = None
    created_at: str
```

---

## §Runner — 工作流执行管理器

> 实现中提取，SPEC 补充记录。

```python
# server/runner.py

class WorkflowRunner:
    """管理后台工作流执行。支持并发限制和取消。"""

    def __init__(self, max_concurrent: int = 4): ...

    async def submit(
        self,
        workflow_id: str,
        workflow: Workflow,
        inputs: dict,
        event_bus: EventBus,
    ) -> None:
        """提交工作流到后台执行。如果 workflow_id 已在运行则抛 RuntimeError。"""

    async def cancel(self, workflow_id: str) -> bool:
        """取消运行中的工作流。返回是否成功取消。"""

    @property
    def running_count(self) -> int: ...

def get_runner() -> WorkflowRunner:  # 单例
    ...
```

### 行为

- 通过 `asyncio.Semaphore` 限制并发工作流数量（默认 4）
- `submit()` 创建 `asyncio.Task` 在后台执行
- 执行前检查是否已取消，执行后 emit `workflow.completed` 事件
- 异常时 emit `workflow.error` 事件
- 结果存储到 `routes._workflows` 供 REST 端点查询

---

## §Chart — 图表渲染接口

> Phase 3 敲定（2026-05-20）

### 定位

chart **不是** Pydantic AI tool，是代码直接调用的**纯函数**。agent 通过 bash 工具执行 Python 脚本时调用，或自定义节点代码中调用。

### 接口

```python
# harness/tools/chart.py

def render_chart(
    data: list[dict[str, Any]],      # 行数据（DataFrame.to_dict("records")）
    chart_type: str,                 # "line" | "bar" | "scatter" | "pareto"
                                     # | "optimal_line" | "heatmap" | "box" | "table"
    x: str | None = None,            # x 轴列名
    y: str | None = None,            # y 轴列名
    label: str = "default",          # 分组标签（同 label = 同折叠组）
    title: str = "",                 # 标题（同 label + 同 title = 原地刷新）
    hue: str | None = None,          # 颜色分组列
    pareto_direction: str | None = None,  # "max" | "min"（仅 pareto）
    optimal_line: str | None = None,      # "max" | "min"（仅 optimal_line）
    node_id: str = "",               # 调用方 agent 名
) -> str:
    ...
```

### 双通道投递

| 优先级 | 通道 | 触发条件 |
|--------|------|---------|
| 1 | EventBus | 同进程，直接 `get_event_bus().emit()` |
| 2 | HTTP POST `/api/charts` | 子进程 / 外部脚本，地址从 `HARNESS_SERVER_URL` 环境变量读取 |
| 3 | no-op | 都没有，返回提示不报错 |

### 用户使用方式

```python
import pandas as pd
from harness.tools.chart import render_chart

df = pd.DataFrame({"iter": [1,2,3], "score": [0.3, 0.5, 0.7]})
render_chart(df.to_dict("records"), chart_type="line", x="iter", y="score", label="Training")
```

### 前端 chart 数据模型

```
chart.render 事件 → chartStore.addChart() →

groups: {
  "Training": {                        // key = label
    label: "Training",
    collapsed: false,
    charts: {
      "Score Graph": { chart_type, data, ... },  // key = title
    },
    table: { columns, rows } | null     // chart_type="table"
  }
}
```

**三条规则**：
1. 同 label 不同 title → 同折叠组内并排
2. 同 label + 同 title → 替换（实时刷新）
3. chart_type="table" → 存为组表格（每组最多一个）

### 支持的图表类型

| chart_type | 前端组件 | 说明 |
|------------|---------|------|
| line | Recharts LineChart | 折线图 |
| bar | Recharts BarChart | 柱状图 |
| scatter | Recharts ScatterChart | 散点图 |
| pareto | ScatterChart + 高亮 | 帕累托前沿（O(n²) 支配算法） |
| optimal_line | ScatterChart + LineChart | 散点 + 累积最优线 |
| heatmap | 自定义 SVG | 热力图 |
| box | 自定义 SVG | 箱线图（分位数计算） |
| table | shadcn Table | 可排序数据表格 |

### 设计决策

- [x] chart 是纯函数，不是 Pydantic AI tool
  - Why: chart 的参数（DataFrame）由代码构造，LLM 无法生成；agent 通过代码调用，不是 tool 选择
  - How: 移除 ToolFactory/async/RunContext，同步函数直接 emit
- [x] 双通道投递解决跨进程问题
  - Why: bash 工具用 subprocess，子进程拿不到父进程 EventBus 单例
  - How: 优先 EventBus（快），其次 HTTP（兜底），服务器自动设 HARNESS_SERVER_URL
- [x] pandas.DataFrame 不直接作为参数类型
  - Why: DataFrame 无法 JSON Schema 化（即使走 HTTP 通道也不行）
  - How: 用户用 `df.to_dict("records")` 转换，服务端和 HTTP 通道都接受 list[dict]

---

## §ConditionalEdge — DAG 条件边

> Phase 4 敲定（2026-05-20）

### 定位

当前 DAG 只支持静态拓扑（Kahn 拓扑排序 + 严格无环）。条件边允许节点根据运行时输出路由到不同目标，实现 reviewer → pass → END / fail → coder 的回环。

### 接口

```python
# Agent 类扩展
class Agent:
    name: str
    after: list[str]
    tools: list[str] | None
    model: str | None
    retries: int = 3
    result_type: Type[BaseModel] | None
    on_pass: str | None = None    # 审查通过 → 路由目标（None = END）
    on_fail: str | None = None    # 审查失败 → 路由目标（None = END）
```

```yaml
# Agent MD 扩展字段
---
name: reviewer
on_pass: null        # null → END
on_fail: coder       # → 回到 coder
---
```

### 自动 result_type

当 agent 声明了 `on_pass` 或 `on_fail` 时，引擎自动注入 `result_type`：

```python
from typing import Literal
from pydantic import BaseModel

class ReviewDecision(BaseModel):
    decision: Literal["pass", "fail"]
    reason: str
```

- 如果用户已指定 `result_type` 且包含 `decision` 字段 → 使用用户的
- 如果用户未指定 → 自动注入 `ReviewDecision`
- `condition_fn` 从 `HarnessState.outputs[node_name]` 读取 `decision` 字段路由

### LangGraph 实现

```python
# MacroGraphBuilder.build() 中
if agent.on_pass is not None or agent.on_fail is not None:
    targets = {}
    if agent.on_pass is not None:
        targets["pass"] = agent.on_pass
    else:
        targets["pass"] = END
    if agent.on_fail is not None:
        targets["fail"] = agent.on_fail
    else:
        targets["fail"] = END

    graph.add_conditional_edges(
        agent_name,
        condition_fn=lambda state: _route_decision(state, agent_name),
        then=targets,
    )
else:
    # 原有逻辑：叶子节点 → END
    ...
```

### 循环检测策略

| 边类型 | 循环检测 |
|--------|---------|
| 静态 `after` 边（A→B→A） | 拒绝（`CycleError`），保持原有行为 |
| 条件边回环（reviewer on_fail→coder） | 放行，运行时限制 `max_iterations`（默认 3） |

### max_iterations 限制

- `HarnessState` 新增 `iteration_counts: dict[str, int]`，记录每个条件边的回环次数
- 每次条件边路由到非 END 目标时，计数 +1
- 超过 `max_iterations`（默认 3）时，强制路由到 END 并 emit `node.failed` 事件
- 可通过 `Workflow(max_iterations=5)` 覆盖默认值

### 前端 DAG 可视化

- 条件边用**虚线** + 标签（"pass" / "fail"）表示
- 回环边用**弧线**绕过其他节点回到源

### 设计决策

- [x] 只支持 on_pass/on_fail 二分路由，不支持多路
  - Why: 80% 场景是审查通过/失败二分；多路路由增加复杂度且需求不明确
  - How: 声明式 on_pass/on_fail，未来如需多路可扩展为 `routes` 列表
- [x] 条件边回环放行，运行时限制迭代次数
  - Why: 静态循环检测无法区分"无条件死循环"和"条件边有限回环"
  - How: Kahn 算法对条件边不参与拓扑排序；运行时用 iteration_counts 计数器限制
- [x] 自动注入 ReviewDecision result_type
  - Why: 减少用户配置负担；大多数审查场景只需要 pass/fail + reason
  - How: 引擎检测 on_pass/on_fail 存在时自动设置；用户显式指定则优先

### 待讨论

- [ ] max_iterations 默认值 3 是否合适？是否需要按 agent 可配置？
- [ ] 条件边回环时，coder 节点重新执行是否需要读取前次错误信息？如何注入上下文？

---

## §Interrupt — 主动打断 Agent

> Phase 4 敲定（2026-05-20）

### 定位

当前 HIL 只有 agent 主动调 `ask_human` 才触发。主动打断允许用户在 agent 执行过程中随时中断，注入指令后恢复执行。

### 事件协议

```
用户点击"打断" + 输入指令
→ 前端发送 workflow.interrupt 事件
→ 后端停止当前节点 streaming
→ 保存当前 state（LangGraph checkpoint）
→ 用户输入新指令后发送 workflow.interrupt（含 directive）
→ 后端 Command(resume=directive) 恢复
→ agent 带着新指令继续执行
```

### WebSocket 事件

```json
// C→S: 用户请求打断
{
  "type": "workflow.interrupt",
  "ts": 1716000000000,
  "payload": {
    "workflow_id": "...",
    "directive": "不要用递归，改用迭代方式重写"
  }
}

// S→C: agent 已恢复
{
  "type": "workflow.resumed",
  "ts": 1716000000001,
  "payload": {
    "workflow_id": "...",
    "node_id": "coder",
    "directive": "不要用递归，改用迭代方式重写"
  }
}
```

### 后端实现

```python
# harness/engine/macro_graph.py — 节点函数中的 interrupt 检查点

async def node_func(state: HarnessState) -> dict:
    ...
    if bus:
        async with pydantic_agent.run_stream(context, deps=deps) as streamed:
            async for chunk in streamed.stream_text(delta=True):
                bus.emit("agent.text_delta", {...})

                # 检查是否有 pending interrupt
                if _has_pending_interrupt(workflow_id):
                    directive = _consume_interrupt(workflow_id)
                    # 将 directive 注入上下文，继续 streaming
                    # Pydantic AI 不支持 mid-stream 注入，
                    # 因此：停止当前 stream → 用新 prompt 重新 run
                    break

            if directive:
                # 用原始 context + directive 重新执行
                new_context = context + f"\n\n[用户打断指令]: {directive}"
                async with pydantic_agent.run_stream(new_context, deps=deps) as streamed2:
                    async for chunk in streamed2.stream_text(delta=True):
                        bus.emit("agent.text_delta", {...})
                output = await streamed2.get_output()
                bus.emit("workflow.resumed", {
                    "workflow_id": workflow_id,
                    "node_id": agent_def.name,
                    "directive": directive,
                })
            else:
                output = await streamed.get_output()
```

### 中断信号存储

```python
# harness/engine/macro_graph.py — 模块级 interrupt 管理

_pending_interrupts: dict[str, str] = {}  # workflow_id → directive
_interrupt_lock = asyncio.Lock()

async def request_interrupt(workflow_id: str, directive: str) -> None:
    async with _interrupt_lock:
        _pending_interrupts[workflow_id] = directive

def _has_pending_interrupt(workflow_id: str) -> bool:
    return workflow_id in _pending_interrupts

def _consume_interrupt(workflow_id: str) -> str | None:
    return _pending_interrupts.pop(workflow_id, None)
```

### WebSocket 处理

```python
# server/ws_handler.py — 新增 interrupt 事件处理

if message.get("type") == "workflow.interrupt":
    workflow_id = message.get("payload", {}).get("workflow_id")
    directive = message.get("payload", {}).get("directive", "")
    if workflow_id and directive:
        from harness.engine.macro_graph import request_interrupt
        await request_interrupt(workflow_id, directive)
```

### 前端实现

- ChatInput 常驻底部（Phase B 已实现）
- 新增"打断"按钮（红色闪电图标），仅当 `status === "running"` 时显示
- 打断时：发送 `workflow.interrupt` 事件，输入框中的文字作为 `directive`
- 收到 `workflow.resumed` 事件后，在 agent 输出中显示 `[用户打断指令]` 标记

### 设计决策

- [x] 不使用 LangGraph interrupt()，用 streaming 循环内检查点
  - Why: LangGraph interrupt 需要 checkpointer 且与 Pydantic AI 的 run_stream 交互复杂；streaming 循环中每个 chunk 都检查更简单可靠
  - How: `_has_pending_interrupt()` 在每次 emit text_delta 后检查，发现 interrupt 则 break 当前 stream + 用新 context 重新 run
- [x] directive 注入方式为拼接到 context 末尾
  - Why: 最简单，不改变 Pydantic AI 的 tool loop 结构
  - How: `new_context = context + f"\n\n[用户打断指令]: {directive}"`

### 待讨论

- [ ] 是否需要打断时保留当前已生成的部分输出？还是清除后重新生成？
- [ ] 多次打断（同一节点打断两次）是否需要支持？

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
