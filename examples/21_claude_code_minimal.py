"""#21 — claude-code 后端最小示例：单节点 + `claude -p` 子进程。

验证 AgentHarness 通过 `claude -p` 子进程驱动 agent 的链路是否打通：
Agent(executor="claude-code") → ClaudeCodeExecutor → run_claude → claude -p。
对应的 agent 定义见 workflows/claude_code_demo/agents/greeter.md。

前置:
  - 安装 claude CLI（`which claude` 能找到）
  - .env 配好 ANTHROPIC_*（或 HARNESS_API_KEY）
  - root 环境下需要在 .env 加一行：
        HARNESS_CLAUDE_CODE_ENV_IS_SANDBOX=1
    （详见 harness/engine/claude_code_executor.py:_load_env_overlay 的 Layer 2）

用法:
    python examples/21_claude_code_minimal.py
"""

from harness.api import Agent, Workflow

wf = Workflow("claude_code_demo", agents=[
    Agent("greeter", after=[], executor="claude-code"),
])
wf.save()

print("spawn claude -p 作为后端 ...\n")
result = wf.run({"task": "用一句话证明你是 claude -p 子进程驱动的 agent"})

print("--- greeter 输出 ---")
print(result.outputs.get("greeter", "(no output)"))

t = result.trace[0]
tu = t.token_usage
print(
    f"\n追踪: {t.agent_name} | executor=claude-code | "
    f"{t.status} | {t.duration_ms}ms",
    end="",
)
if tu:
    print(f" | tokens {tu.input}/{tu.output}/{tu.total}")
else:
    print()
