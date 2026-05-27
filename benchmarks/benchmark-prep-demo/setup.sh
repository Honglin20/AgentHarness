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
