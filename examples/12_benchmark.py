"""#12 — Benchmark：批量评测 workflow 能力，对比结果 + 图表。

本示例展示 Benchmark 功能：
  1. 创建一个包含多个任务的 benchmark
  2. 用指定的 workflow 跑全部任务
  3. 收集 eval_judge 分数，生成对比图表

Benchmark 数据保存在 benchmarks/<name>/ 目录，可复用。
用 UI 触发更佳 — 侧边栏选择 Benchmark → 选 Workflow → 一键运行。

用法:
    python examples/12_benchmark.py            # 创建 benchmark 并保存
    python examples/12_benchmark.py --save     # 仅保存，用于 UI
"""

import sys
from harness.benchmark_store import BenchmarkStore

store = BenchmarkStore()

# Create a benchmark with sample tasks
store.save_benchmark(
    "code-review-v1",
    tasks=[
        {"label": "审查 auth.ts 的安全性", "inputs": {"task": "审查以下代码的安全性，找出潜在的漏洞：auth.ts"}},
        {"label": "审查 api.ts 的错误处理", "inputs": {"task": "审查以下代码的错误处理是否完善：api.ts"}},
        {"label": "审查 utils.ts 的性能", "inputs": {"task": "审查以下代码的性能问题：utils.ts"}},
        {"label": "审查 db.ts 的 SQL 注入风险", "inputs": {"task": "审查以下代码是否有 SQL 注入风险：db.ts"}},
    ],
    description="代码审查能力评测 — 4 个不同场景",
)

print("Benchmark 'code-review-v1' saved!")
print()
print("Tasks:")
bm = store.load_benchmark("code-review-v1")
for t in bm["tasks"]:
    print(f"  [{t['id']}] {t['label']}")
print()
print("Usage:")
print("  1. Start UI:    bash examples/launch_ui.sh")
print("  2. In sidebar, click 'code-review-v1' under Benchmarks")
print("  3. Select a workflow (e.g., eval_code_quality)")
print("  4. Click 'Run Benchmark'")
print("  5. Watch progress, then compare results in Compare tab")
print()
print("Or use API directly:")
print("  curl -X POST http://localhost:8001/api/benchmarks/code-review-v1/run \\")
print("    -H 'Content-Type: application/json' \\")
print("    -d '{\"workflow\": \"eval_code_quality\"}'")
