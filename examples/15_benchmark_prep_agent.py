"""#15 — Benchmark Prep Agent：用 LLM Agent 做前置准备。

本示例展示 prep 的 agent 类型：
  用一个 LLM Agent 代替 shell 脚本完成准备工作。

与 #14（script prep）的区别：
  - #14: prep(type="script", command="bash setup.sh")  — 确定性脚本
  - #15: prep(type="agent", agent="setup_agent")       — LLM Agent 执行

Agent 通过 bash 工具创建目录和文件，效果和 script 一样，
但适合需要模型判断的场景（如：根据 benchmark 任务动态决定准备什么）。

用法:
    python examples/15_benchmark_prep_agent.py             # 创建 + 保存 + 运行
    python examples/15_benchmark_prep_agent.py --save-only  # 仅保存，用 UI 跑
"""

import sys
from pathlib import Path

from harness.api import Benchmark
from harness.extensions.console import ConsoleOutput

BM_NAME = "benchmark-prep-agent-demo"
WF_NAME = "chart_demo"

# ── 1. 创建 prep agent MD ──────────────────────────────────
# Agent MD 放在 benchmarks/<name>/agents/ 下，自动被 resolve_agent_md 找到
bm_dir = Path(__file__).resolve().parent.parent / "benchmarks" / BM_NAME
agents_dir = bm_dir / "agents"
agents_dir.mkdir(parents=True, exist_ok=True)

agent_md = agents_dir / "setup_agent.md"
agent_md.write_text("""\
---
name: setup_agent
tools:
  - bash
---

你是一个环境准备 Agent。你的任务是：

1. 创建目录 `/tmp/benchmark-agent-demo/`
2. 在该目录下创建 3 个项目：`project-x`、`project-y`、`project-z`
3. 每个项目下创建 `src/main.py`，内容为 `print('Hello from <项目名>')`
4. 每个项目下创建 `README.md`，内容为 `# <项目名>`

用 bash 工具完成所有操作。完成后报告创建了哪些目录和文件。
""")
print(f"Agent MD written to {agent_md}")
print()

# ── 2. 定义 Benchmark ──────────────────────────────────────
bm = Benchmark(BM_NAME, description="演示 agent prep — 用 LLM Agent 做前置准备")
bm.prep(type="agent", agent="setup_agent")
bm.task("检查 project-x", inputs={"task": "读取 /tmp/benchmark-agent-demo/project-x/src/main.py 的内容，一句话总结"})
bm.task("检查 project-y", inputs={"task": "读取 /tmp/benchmark-agent-demo/project-y/README.md 的内容，一句话总结"})
bm.task("检查 project-z", inputs={"task": "列出 /tmp/benchmark-agent-demo/project-z/ 目录下所有文件"})

bm.save()
print(f"Benchmark '{BM_NAME}' saved with {len(bm._tasks)} tasks")
print(f"  Prep: agent — setup_agent")
print(f"  Tasks:")
for t in bm._tasks:
    print(f"    - {t['label']}")
print()

# ── 3. 运行 ────────────────────────────────────────────────
if "--save-only" in sys.argv:
    print("Saved only. Run via UI:")
    print(f"  1. bash examples/launch_ui.sh")
    print(f"  2. Select '{BM_NAME}' in sidebar → Run Benchmark")
    sys.exit(0)

print("Running benchmark with ConsoleOutput...")
print("=" * 60)

result = bm.run(
    workflow=WF_NAME,
    plugins=[ConsoleOutput(stream=False, verbose=False)],
)

print()
print("=" * 60)
print("Results:")
print("=" * 60)
for t in result.tasks:
    icon = "✓" if t.status == "completed" else "✗"
    print(f"  {icon} {t.label}: {t.status}")
    if t.status == "completed" and t.result:
        for tr in t.result.trace:
            print(f"      {tr.agent_name}: {tr.status} ({tr.duration_ms}ms)")
    if t.error:
        print(f"      Error: {t.error}")

print()
print(f"All completed: {result.all_completed}")
