---
workflow: chart_demo
title: Bash 驱动数据 + 图表
---

# Bash 驱动数据 + 图表（chart_demo）

和 [demo_chart](02_demo_chart.md) 不同，这里只有一个 `runner` agent，唯一工具是 `bash`。它演示的是「agent 自己用 shell 命令生成/读取数据 → 自己组织成图表输入」的全流程，适合验证 bash 工具链是否畅通。

## 执行器 @runner

`runner` 拿到任务后，整条链路都在 bash 里完成：

1. 用 shell 命令（`echo` / `python -c` / `cat <<EOF`）生成或读取数据
2. 把数据整理成 `render_chart` 期望的格式
3. 通过 bash 调用图表渲染入口（具体方式取决于 harness 暴露的 CLI / IPC）

这种模式的好处是 agent 拥有完整的 shell 能力 —— 可以读 CSV、跑 awk、用 jq 处理 JSON，再交给渲染层。代价是 agent 必须自己处理数据格式转换，比 `demo_chart` 的「直接调工具」更底层。

---

## 演示 task

```
用 python 生成一份 30 天的随机股价序列（起始 100，每日 ±2% 波动），然后用 bash 把数据处理成 render_chart 需要的格式，画出折线图。
```

或更简单的版本：

```
用 seq 和 awk 生成 1-20 的平方数表，画一张散点图（x=原数, y=平方值）。
```

## 调试要点

- runner 没出图：先看 bash tool_call 的 stdout/stderr，多半是数据格式不对
- 想对比纯工具调用版：切到 [demo_chart](02_demo_chart.md)，看 `render_chart` 直接调用和 bash 间接调用的差异
