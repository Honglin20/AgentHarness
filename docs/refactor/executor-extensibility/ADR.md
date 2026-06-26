# ADR: Executor Extensibility + Unified Error Flow + Layered Prompt

**Status**: Accepted (2026-06-26) — Phase 1 + 2 + 3 全部落地
**Scope**: `harness/engine/`, `harness/prompts/`, `harness/cli_profiles/` (new), `server/runner.py`, `harness/cli_runner.py`, `frontend/src/stores/workflowStore.ts`, `frontend/src/types/events.ts`

---

## Context

三个独立但相关的痛点（详见 `docs/status/CURRENT.md` 未解决项 + 用户反馈）：

1. **ask_user_demo 不调 ask_user**：`ClaudeCodeExecutor` 通过 `--append-system-prompt` 把 `assemble_static_prompt()` 的输出原样塞给 `claude -p`，但 base 层（`harness/prompts/base.md`）与 output_format 层都是为 pydantic-ai 写的 —— 强制 "Your first action MUST be `TodoTool`" + "call the `final_result` tool"。这些工具在 claude-code 路径上**不存在**（claude 的工具清单里没这俩），模型被命令调"不存在的工具" → 行为漂移、忽略真实任务。
2. **claude -p 报错前端看不到**：错误事件 payload 越往后越贫（`workflow.error` 只有 `{workflow_id, user_id, error}`）；翻译器 emit `node.failed` 与 executor 抛 `RuntimeError` 双发 → 后者覆盖前者；翻译器不翻 `system/api_retry`/`system/status` → 卡住感来源；`cli_runner.py` 与 `server/runner.py` 是两套独立错误流。
3. **claude CLI 硬编码**：`_claude_subprocess.DEFAULT_FLAGS` 钉死 claude-specific flag；加 opencode/codex 要改核心 spawn 代码；用户无法不动核心代码加自定义 CLI backend。

---

## Decisions

### Decision 1: Prompt 按 executor 范式分两层（pydantic-ai 范式 / minimal 范式）

**约定**：每个 executor 必须属于以下两个范式之一，不能混。

| 范式 | 适用 executor | 拼装层 |
|---|---|---|
| **pydantic-ai 范式** | `pydantic-ai`（pydantic-ai SDK 内置工具调用） | `[base_pydantic.md] + [agent_md_body] + [output_format_pydantic]` |
| **minimal 范式** | `claude-code` / `codex` / `opencode` / ...（CLI 子进程 + harness MCP 桥接） | `[base_minimal.md] + [agent_md_body] + [output_format_minimal]` |

**变更点**：

- 把现有 `harness/prompts/base.md` 拆成两份：
  - `base_pydantic.md`：保留 `TodoTool(op='create')` MUST + `final_result` tool 强制
  - `base_minimal.md`：去掉上述强制，保留 "Narrate before call / Handle failure loudly / Coordinate your tools" 等跨 executor 工作范式
- `harness/prompts/assembler.py:assemble_static_prompt` 签名变更：
  ```python
  def assemble_static_prompt(
      agent_md_body: str,
      result_type: Type[BaseModel] | None,
      *,
      executor: str = "pydantic-ai",  # 新增
  ) -> str
  ```
- `_OUTPUT_FORMAT_TEMPLATE` 拆成两份：
  - pydantic-ai：保留 "call the `final_result` tool"
  - minimal：改为 "respond with a JSON object matching this schema"（不引用 final_result tool）
- `node_factory.py:117` 调用处传 `executor=agent_def.executor`

**为什么这样分**：pydantic-ai 的 `final_result` / `TodoTool` 是 harness 注册的工具，靠 prompt 强制模型调用；CLI backend（claude/codex）有自己的工具协议（claude 走 MCP，codex 走自己的 function call），不需要 harness 的 pydantic-ai 强制契约，反而会被这些"不存在的工具"prompt 干扰。

### Decision 2: ErrorEvent 契约 + `agent.executor_error`（critical 不淘汰）

**新数据结构**（`harness/engine/error_event.py`，新建）：

```python
@dataclass
class ErrorEvent:
    workflow_id: str
    node_id: str | None          # None = workflow-level
    agent_name: str | None
    executor: str                # "pydantic-ai" / "claude-code" / ...
    phase: str                   # "spawn" / "stream" / "result_parse" / "schema_validate" / "runtime"
    error_type: str              # 异常类名
    error_message: str
    stderr_tail: str | None      # CLI backend 专有
    exit_code: int | None
    timed_out: bool
    retry_attempt: int | None
    ts: float

class ExecutorError(RuntimeError):
    """Executor 抛出的统一异常基类。带 error_event 字段让上层无需重 emit。"""
    def __init__(self, message: str, error_event: ErrorEvent):
        super().__init__(message)
        self.error_event = error_event
```

**新事件类型**：`agent.executor_error`，加入 `harness/extensions/bus.py:CRITICAL_EVENT_TYPES` 白名单（永不淘汰）。

**emit 唯一性约束**（不变量）：每个错误**只在一个位置 emit**：

| 错误源 | emit 主体 | 上层动作 |
|---|---|---|
| spawn / stream / result_parse / schema_validate | `ClaudeCodeExecutor` 内部 | emit `agent.executor_error` + 抛 `ExecutorError` |
| `result.is_error=true`（stream-json 翻译） | **翻译器不再 emit** | executor 在 `_extract_pre_translate` 检测到后统一走 emit + raise |
| runtime / max_iterations / envelope | `node_factory` 现状 | 不变 |

**node_factory.py 改动**：`except Exception as e` 加分支：

```python
if isinstance(e, ExecutorError):
    # executor 已经 emit 过 agent.executor_error，不重 emit node.failed
    # 走 retry 决策即可（execute_with_retry 已经在外层）
    error_type = e.error_event.error_type
    extra["stderr_tail"] = e.error_event.stderr_tail
    extra["phase"] = e.error_event.phase
    # 然后正常 emit node.failed（但带富字段，不重 emit executor_error）
else:
    # 现有 RuntimeError 路径不变
```

**翻译器补全**（`harness/translator/stream_json.py`）：

- `result.is_error=true`：**移除** `_translate_result` 中 emit `node.failed` 的分支（让 executor 统一发）
- 新增 `system/api_retry` → `agent.api_retry`（payload: `{retry_count, max_retries, wait_seconds}`）
- 新增 `system/status` → `agent.status_update`（payload: `{status: "thinking"|"requesting"|...}`）

**workflow.error payload 扩字段**：

```python
{
    "workflow_id": ...,
    "user_id": ...,
    "error": str(e),
    "error_type": type(e).__name__,
    "executor": "claude-code",
    "phase": "spawn" | "stream" | ...,
    "stderr_tail": str | None,
    "failed_node": str | None,
    "batch_id": ...,
}
```

**CLI / server 统一**：`cli_runner.py` 与 `server/runner.py:_run_workflow` 共用 EventBus + 同样 emit `workflow.error`（带富字段）。`cli_runner.py:19-24` 关于"不动 server"的旧设计约束在 Phase 2 解掉 —— 错误流是两个路径的共享契约，必须对齐。

**前端**：

- `workflowStore` 加 `handleWorkflowError(payload)`：把 error 字段写入对应 node 的 `error` + 把 workflow 状态置 `failed`
- `agent.executor_error` handler：实时 toast 显示 stderr_tail + retry_attempt
- 路由 `eventRouter.ts` 加新事件分派
- `frontend/src/types/events.ts` 加 `ExecutorErrorPayload` / `ApiRetryPayload` / `StatusUpdatePayload`

### Decision 3: CliProfile 协议 + 入口点注册 + 项目级覆盖

**新数据结构**（`harness/engine/cli_profile.py`，新建）：

```python
@dataclass
class CliProfile:
    """描述一个 CLI backend 的"语法"——如何构造命令行、如何传 prompt、
    如何翻译 stream 输出、如何提取结果。"""
    
    name: str                            # "claude-code" / "opencode" / "codex"
    prompt_paradigm: Literal["pydantic-ai", "minimal"]  # Decision 1 范式归属
    cli_path_env: str                    # "HARNESS_CLAUDE_CLI" — env 覆盖入口
    default_cli_path: str                # "claude"
    flags: tuple[str, ...]               # CLI 特定固定 flag
    prompt_channel: Literal["stdin", "argv"]
    mcp_flag_template: str | None        # "--mcp-config {path}" — None = 不支持 MCP
    env_overlay_prefixes: tuple[str, ...]  # 从 .env 提取的 key 前缀（"ANTHROPIC_" / "OPENCODE_"）
    translator: Callable[[dict, TranslateContext], list[TranslatedEvent]]
    result_extractor: Callable[[str, Type[BaseModel] | None], Any]
    spawn_factory: Callable[..., Awaitable[CliRunResult]]  # 默认走通用 spawn，可定制

class CliExecutorBase(BaseExecutor):
    """通用 spawn + stream + translate + extract 框架，按 profile 分派。
    现有 ClaudeCodeExecutor 退化为 CliExecutorBase + ClaudeCliProfile。"""
```

**Profile 持久化路径**（与 `harness/config.py:15-20` `.env` fallback 同范式）：

```
优先级（高 → 低）：
  1. $HARNESS_CLI_PROFILES_DIR/<name>.py     # env 覆盖整个目录
  2. <cwd>/.harness/cli_profiles/<name>.py   # 项目级（最高默认优先级）
  3. <install_dir>/harness/cli_profiles/<name>.py  # builtin
```

**Profile 规范**：每个 profile module 必须导出 `PROFILE: CliProfile` 变量（模块级常量，启动时一次性加载到 registry）。

**注册 API**：

```python
# harness/cli_profiles/__init__.py
def register_cli_profile(profile: CliProfile) -> None:
    """运行时注册，同名 profile 后注册覆盖前注册。"""

def load_builtin_profiles() -> None:
    """启动时扫描 harness/cli_profiles/*.py，自动加载 builtin profile。"""

def load_project_profiles(cwd: Path) -> None:
    """启动时扫描 <cwd>/.harness/cli_profiles/*.py，覆盖同名 builtin。"""

def get_profile(name: str) -> CliProfile:
    """查表；未注册抛 KeyError(fail-loud)。"""
```

**VALID_EXECUTORS 改动**（`harness/core/agent.py:23`）：

```python
# builtin 白名单（静态，向后再也不删）
BUILTIN_EXECUTORS = frozenset({"pydantic-ai", "claude-code"})

# 运行时有效集合（builtin + 已注册 profile）
def VALID_EXECUTORS() -> frozenset[str]:
    return BUILTIN_EXECUTORS | _registry_keys()
```

`agent.py:92` 的白名单校验改为调用 `VALID_EXECUTORS()` 函数（动态）。

**executor_factory.py 改动**：

```python
def make_executor(...):
    backend = agent_def.executor
    if backend == "pydantic-ai":
        return LLMExecutor(...)  # 不变
    if backend in cli_profile_registry:
        profile = get_profile(backend)
        return CliExecutorBase(profile=profile, ...)
    raise ValueError(f"unknown executor {backend!r}")
```

**env overlay 改动**（替换现有 `_load_env_overlay`）：

```python
def _load_env_overlay(profile: CliProfile) -> dict[str, str]:
    """从 .env 提取 profile 声明的 prefix key + HARNESS_<NAME>_ENV_* 覆盖。"""
    # 1. 读 .env，提取 profile.env_overlay_prefixes 列出的 key
    # 2. 读 env 中 HARNESS_<NAME>_ENV_<KEY>=val 形式的覆盖
    # 3. 读 HARNESS_<NAME>_CLI 覆盖 cli_path
```

**Builtin profile 列表**（初始迁移）：

| 文件 | profile.name | 状态 |
|---|---|---|
| `harness/cli_profiles/claude.py` | `"claude-code"` | 从 `_claude_subprocess.DEFAULT_FLAGS` 迁移 |

后续 `harness/cli_profiles/opencode.py` / `codex.py` 等 builtin 由后续 PR 加；用户项目级 `./.harness/cli_profiles/<name>.py` 即写即用。

---

## 不变量

1. **Prompt 范式二选一**：每个 executor（builtin 或用户注册）必须 `prompt_paradigm ∈ {"pydantic-ai", "minimal"}`，assembler 按 paradigm 选 base 文件，禁止混用。
2. **ErrorEvent 唯一性**：每个错误只在一个位置 emit。`ExecutorError` 异常带 `error_event` 字段，上层捕获时**只走 retry / 路由**，不重 emit。
3. **Profile 注册幂等**：同名 profile 后注册覆盖前注册；项目级（cwd）覆盖 builtin。Registry 是 process-global singleton。
4. **持久化契约**：用户编辑 `./.harness/cli_profiles/*.py` 后**下次 server / cli 启动自动加载**，无需修改 harness 核心代码、无需重复声明。
5. **CLI / server 错误流对齐**：`workflow.error` payload schema 必须一致；前端 sink = WebSocket，CLI sink = Rich TUI / stderr，但**消费的事件源相同**。

---

## Out of scope

- **profile.json**：用户提到的"和 profile.json 同理"指 fallback 范式（cwd > install），本 ADR **不**引入 profile.json 配置文件；profile 是 Python module，类型安全。
- **LLMExecutor 重构为 CliExecutorBase**：pydantic-ai 不是 CLI backend，不走 CliProfile 协议；保持现状。
- **翻译器补全 G2-G7**：本 ADR 只补 `api_retry` / `status` / `result.is_error` 调整；其他 stream 事件（hook / partial delta）保持现状。
- **现有 retry 策略重构**：`execute_with_retry` 保持现状；`ExecutorError` 作为新异常类型接入即可。
- **测试 baseline 重生成**：`tests/test_prompt_baseline.py` 黄金 fixture 需要重新生成（pydantic-ai 路径 prompt 内容不变，但生成方式变了）。

---

## 风险与对策

| 风险 | 对策 |
|---|---|
| R1: 拆 base.md 影响 pydantic-ai 路径已有 fixture | `tests/test_prompt_baseline.py` 重生成；byte-level diff 必须为 0（pydantic-ai 路径拼接结果不变） |
| R2: 翻译器不再 emit `node.failed` 后，前端老 replay 数据行为不一致 | 老 events buffer 里仍有 `node.failed`，replay 兼容；新 run 走新契约 |
| R3: 用户自定义 profile 出错（translator bug）导致整个 server 启动失败 | profile 加载失败 fail-loud 但**不阻塞 server 启动**——记录 warning + 该 profile 标 disabled，agent 用到时再 fail |
| R4: cwd 优先级让多用户共享同一个项目时配置漂移 | 加 `HARNESS_DISABLE_PROJECT_PROFILES=1` env 关闭项目级加载（CI / 共享目录场景） |

---

## 验证计划

1. **Phase 1 验证**：`ask_user_demo` 跑通，前端能看到 `agent.tool_call: tool_name=mcp__harness__ask_user` + 弹问题卡片
2. **Phase 2 验证**：故意配错 `ANTHROPIC_BASE_URL` → 前端 toast 显示 stderr_tail + phase="spawn" + retry_attempt；CLI 路径打印同样字段到 stderr
3. **Phase 3 验证**：写一个 mock opencode profile（`./.harness/cli_profiles/opencode.py`）跑通端到端；重启 server 后无需重声明自动加载

---

## 后续 PR 拆分建议

- **PR-1（Phase 1）**: Prompt 分层 — 仅改 `harness/prompts/`、`assembler.py`、`node_factory.py` 调用处
- **PR-2（Phase 2）**: ErrorEvent 契约 — 新建 `error_event.py`、改 ClaudeCodeExecutor、翻译器、cli/server runner、前端 store
- **PR-3（Phase 3）**: CliProfile 抽象 — 新建 `cli_profile.py`、`cli_profiles/`、改 executor_factory / agent.py、迁移 ClaudeCodeExecutor
- **PR-4（可选）**: 加 builtin opencode / codex profile
