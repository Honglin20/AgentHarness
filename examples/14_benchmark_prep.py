"""#14 — Benchmark + Prep：前置准备 + 批量评测。

本示例展示 Benchmark 的 prep 功能：
  1. 创建一个 prep 脚本（setup.sh）
  2. 定义 benchmark，绑定 prep 脚本
  3. 添加多个 task
  4. 用 Python API 直接 run（带 ConsoleOutput 插件）
  5. 或保存后通过 Web UI 运行

流程：
  prep 脚本执行 → 完成后 → 所有 task 并行运行

用法:
    python examples/14_benchmark_prep.py             # 创建 + 保存 + 运行
    python examples/14_benchmark_prep.py --save-only  # 仅保存，用 UI 跑
"""

import sys
import json
from pathlib import Path

from harness.api import Benchmark
from harness.extensions.console import ConsoleOutput

BM_NAME = "benchmark-prep-demo"
WF_NAME = "chart_demo"

# ── 1. 创建 prep 脚本 ──────────────────────────────────────
# prep 脚本放在 benchmarks/<name>/ 下，执行时自动加入 PATH
bm_dir = Path(__file__).resolve().parent.parent / "benchmarks" / BM_NAME
bm_dir.mkdir(parents=True, exist_ok=True)

prep_script = bm_dir / "setup.sh"
prep_script.write_text("""\
#!/usr/bin/env bash
set -e
echo "🔧 [prep] Setting up environment..."

# 创建临时工作目录
mkdir -p /tmp/benchmark-prep-demo

# 模拟：准备 3 个项目目录
for proj in project-alpha project-beta project-gamma; do
  dir="/tmp/benchmark-prep-demo/$proj"
  mkdir -p "$dir/src"
  echo "def main(): print('Hello from $proj')" > "$dir/src/main.py"
  echo "# $proj" > "$dir/README.md"
done

echo "✅ [prep] Done: 3 projects ready in /tmp/benchmark-prep-demo/"
""")
prep_script.chmod(0o755)

print(f"Prep script written to {prep_script}")
print()

# ── 2. 定义 Benchmark ──────────────────────────────────────
bm = Benchmark(BM_NAME, description="演示 prep 前置准备 + 批量 task")
bm.prep(type="script", command="bash setup.sh")
bm.task("分析 project-alpha", inputs={"task": "读取 /tmp/benchmark-prep-demo/project-alpha/src/main.py 的内容，用一句话总结它的功能"})
bm.task("分析 project-beta", inputs={"task": "读取 /tmp/benchmark-prep-demo/project-beta/README.md 的内容，用一句话总结"})
bm.task("分析 project-gamma", inputs={"task": "列出 /tmp/benchmark-prep-demo/project-gamma/ 目录下所有文件"})

# ── 3. 保存（这样 Web UI 也能用）────────────────────────────
bm.save()
print(f"Benchmark '{BM_NAME}' saved with {len(bm._tasks)} tasks")
print(f"  Prep: script — bash setup.sh")
print(f"  Tasks:")
for t in bm._tasks:
    print(f"    - {t['label']}")
print()

# ── 4. 运行 ────────────────────────────────────────────────
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
