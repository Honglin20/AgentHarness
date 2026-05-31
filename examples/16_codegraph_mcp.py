"""#16 — codegraph MCP：让 agent 用代码图谱分析仓库结构。

展示三件事:
  1. 默认即用 — Workflow 启动时自动连接 codegraph MCP（如果本地装了）
  2. 精细控制 — 用 enable_filesystem_mcp / enable_codegraph_mcp 单独开关
  3. 自定义 MCP — 用 mcp_servers= 追加其他 MCP server

agent 用到的工具:
  - codegraph_search   : 按符号/关键字搜索代码
  - codegraph_callers  : 找谁调用了某符号
  - codegraph_impact   : 改某符号会影响哪些代码
  - bash               : 必要时跑 `codegraph init -i` 等命令

前置:
  - .env 配好 HARNESS_API_KEY / HARNESS_MODEL（真实 LLM）
  - codegraph CLI 已安装（install.py 会装）
  - 项目根目录已经 `codegraph init -i` 过

用法:
    python examples/16_codegraph_mcp.py
    python examples/16_codegraph_mcp.py --only-codegraph   # 关掉 filesystem
    python examples/16_codegraph_mcp.py --only-filesystem  # 关掉 codegraph
"""

import sys

from harness.api import Agent, Workflow
from harness.config import configure
from harness.tools.mcp_bridge import McpServerConfig


configure()

# ── 配置开关：按命令行参数决定开哪些默认 MCP ─────────────────
enable_fs = "--only-codegraph" not in sys.argv
enable_cg = "--only-filesystem" not in sys.argv

print(f"[example] filesystem MCP: {enable_fs}, codegraph MCP: {enable_cg}")

# ── 定义一个 agent：让它用 codegraph 工具分析仓库 ───────────
analyzer = Agent(
    "code_explorer",
    after=[],
    tools=[
        "bash",
        "codegraph_search",
        "codegraph_callers",
        "codegraph_impact",
        "codegraph_status",
    ],
)

wf = Workflow(
    "codegraph_demo",
    agents=[analyzer],
    enable_filesystem_mcp=enable_fs,
    enable_codegraph_mcp=enable_cg,

    # 想再挂一个自定义 MCP server 就放这里；不要可以省略。
    # mcp_servers=[
    #     McpServerConfig(name="brave", command="npx",
    #                     args=["-y", "@modelcontextprotocol/server-brave-search"]),
    # ],
)

# ── 写一个让 LLM 必须用到 codegraph 的任务 ────────────────────
task = (
    "在这个仓库里找到名为 'McpBridge' 的类，告诉我："
    "1) 它定义在哪个文件；"
    "2) 哪些函数/类调用了它；"
    "3) 如果我修改它会影响哪些代码。"
    "请优先使用 codegraph_search / codegraph_callers / codegraph_impact 工具，"
    "不要用 bash grep。如果 codegraph_status 显示索引不存在，"
    "用 bash 跑 `codegraph init -i` 后重试。"
)

result = wf.run({"task": task})

print()
print("=" * 70)
print("OUTPUT:")
print("=" * 70)
print(result.outputs.get("code_explorer", "<no output>"))

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
