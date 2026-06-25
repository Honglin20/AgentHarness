---
workflow: conditional_route
title: 条件路由（on_pass / on_fail）
---

# 条件路由（conditional_route）

这个 demo 专门演示 DAG 的**条件边**：`classifier` 节点带 `on_pass: summary` 和 `on_fail: debugger`，根据它的 `decision` 字段把流分别送到 `summary`（干净路径）或 `debugger`（异常路径）。两条分支不再汇聚，互不干扰。

## 分析输入 @analyzer

`analyzer` 是入口（`after: []`），拿到用户输入（一段文本、一份日志、一个错误堆栈等），做基础结构化：

- 提取关键信息
- 标注输入类型（正常数据 / 异常报告 / 待诊断问题）
- 把整理后的结果传给 classifier

## 分类裁决 @classifier

`classifier`（`after: [analyzer]`）是**整个 demo 的核心**。它必须输出：

- `decision`: `"pass"` 或 `"fail"`
- `reason`: 裁决理由

框架读到 `decision` 后自动路由：

| decision | 走向 | 含义 |
|----------|------|------|
| `"pass"` | `on_pass` → `summary` | 输入是正常数据，直接出汇总 |
| `"fail"` | `on_fail` → `debugger` | 输入有问题，进调试分支 |

任何其他取值（比如 `"maybe"`、`"error"`）路由失败，整个流挂死 —— 所以 `decision` 必须**严格**是 pass / fail。

## 汇总分支 @summary

`summary`（`after: null`，由 classifier 的 `on_pass` 触发）只在干净路径上跑：

- 接收 analyzer 传来的结构化数据
- 输出汇总报告（统计、关键指标、趋势）
- 不需要处理异常，假设输入是干净的

## 调试分支 @debugger

`debugger`（`after: null`，由 classifier 的 `on_fail` 触发，工具 `bash`）只在异常路径上跑：

- 接收 analyzer 标注的异常信息
- 用 bash 复现 / 抓日志 / 跑诊断命令
- 输出根因分析 + 修复建议

`debugger` 带 `bash` 而 `summary` 不带 —— 体现「分支可以有完全不同的工具集」。

---

## 演示 task

**触发 pass 路径**（→ summary）：

```
请汇总这份销售数据：Q1=1200, Q2=1500, Q3=1800, Q4=2100。算出全年总和和季度环比增长率。
```

**触发 fail 路径**（→ debugger）：

```
我的服务报错：ConnectionError: Failed to connect to db.internal:5432。日志显示每 5 分钟重试一次都失败，已经持续 2 小时。请诊断。
```

classifier 应当把第一段判定为正常数据汇总任务（pass → summary），第二段判定为故障排查任务（fail → debugger）。

## 调试要点

- 想看路由决策：在运行日志里搜 `conditional_route` 或 `on_pass` / `on_fail`
- 路由没生效（两个分支都没跑）：检查 classifier 的 `decision` 字段拼写和大小写
- 想加分支汇聚（summary 和 debugger 都进同一个 reporter）：需要新增汇聚节点并改 `after`，不能直接连
