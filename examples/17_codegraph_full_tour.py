"""#17 — codegraph 全工具演练：让 agent 在 fixture 项目里依次调用 10 个 codegraph 工具。

目标：用真实 LLM 验证 codegraph MCP 集成端到端可用，且每个工具都能被 agent 正确调用。

测试 fixture：
    examples/fixtures/mini_lib/
        ├── __init__.py
        ├── pipeline.py    # main → run_pipeline → load_data / process / save_results
        │                  # process → normalize / validate
        └── helpers.py     # batch_clean 也调用 normalize / validate

预期 agent 行为（在 prompt 里硬约束顺序）：
    1. codegraph_status   — 看索引是否存在
    2. bash: codegraph init -i  — 如果没索引就初始化
    3. codegraph_status   — 再确认一次
    4. codegraph_files    — 列出索引到的文件
    5. codegraph_search   — 搜 normalize
    6. codegraph_node     — 看 normalize 节点详情
    7. codegraph_callers  — 看谁调用了 normalize
    8. codegraph_callees  — 看 process 调用了什么
    9. codegraph_impact   — 改 normalize 影响什么
    10. codegraph_explore — 从 main 出发探索
    11. codegraph_trace   — 跟踪从 main 到 normalize 的路径
    12. codegraph_context — 用一段文字生成上下文

前置：
    .env 配好 HARNESS_API_KEY / HARNESS_MODEL
    codegraph CLI 已安装

用法:
    python examples/17_codegraph_full_tour.py
"""

import os
import sys
from pathlib import Path

from harness.api import Agent, Workflow
from harness.config import configure

configure()

FIXTURE = (Path(__file__).parent / "fixtures" / "mini_lib").resolve()

print(f"[example] fixture project: {FIXTURE}")
print(f"[example] fixture has init?: {(FIXTURE / '.codegraph').exists()}")

# Disable filesystem MCP — we only want to validate codegraph here so the trace
# is unambiguous. codegraph_path scopes the MCP server to the fixture.
wf = Workflow(
    "codegraph_full_tour",
    agents=[Agent("cg_tourist", after=[], tools=[
        "bash",
        "codegraph_*",
    ])],
    enable_filesystem_mcp=False,
    enable_codegraph_mcp=True,
    codegraph_path=str(FIXTURE),
)

task = (
    f"项目路径: {FIXTURE}\n\n"
    "请严格按下面 12 步顺序执行，每步调用一次对应工具，不要跳步，不要并行调用：\n"
    "步骤 1: 调用 codegraph_status 查看索引状态。\n"
    "步骤 2: 如果上一步显示 No CodeGraph index found / not initialized，"
    f"使用 bash 在工作目录 {FIXTURE} 运行 `codegraph init -i`（用 `cd {FIXTURE} && codegraph init -i`）。"
    "如果已存在索引则跳过这一步并明确说明跳过。\n"
    "步骤 3: 再次 codegraph_status，确认 Files >= 2、Nodes > 0。\n"
    "步骤 4: codegraph_files 列出索引到的文件。\n"
    "步骤 5: codegraph_search 搜索符号 'normalize'。\n"
    "步骤 6: codegraph_node 查看 normalize 的节点详情（用上一步返回的 node id 或 fqname）。\n"
    "步骤 7: codegraph_callers 查询 normalize 的调用者。\n"
    "步骤 8: codegraph_callees 查询 process 调用了什么。\n"
    "步骤 9: codegraph_impact 评估修改 normalize 的影响。\n"
    "步骤 10: codegraph_explore 从 main 出发探索调用图。\n"
    "步骤 11: codegraph_trace 跟踪 main → normalize 的调用路径。\n"
    "步骤 12: codegraph_context 用 task=\"explain how normalize is used\" 生成上下文。\n\n"
    "执行完后输出一份编号清单，每步一行，格式为：\n"
    "  N. 工具名 — 关键结果（一句话总结）\n"
    "如果某一步失败，写：\n"
    "  N. 工具名 — FAILED: <错误说明>\n"
    "不要复述工具的原始 JSON，给我自然语言总结。\n"
)

result = wf.run({"task": task})

print()
print("=" * 70)
print("AGENT OUTPUT:")
print("=" * 70)
out = result.outputs.get("cg_tourist", "<no output>")
print(out)

print()
print("=" * 70)
print("TRACE:")
print("=" * 70)
for t in result.trace:
    tu = t.token_usage
    line = f"  {t.agent_name} | {t.status} | {t.duration_ms}ms"
    if tu:
        line += f" | tokens {tu.input}/{tu.output}/{tu.total}"
    print(line)

if result.errors:
    print()
    print("ERRORS:", result.errors)
    sys.exit(1)
