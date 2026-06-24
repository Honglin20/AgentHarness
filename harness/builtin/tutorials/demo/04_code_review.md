---
workflow: code_review
title: 三段式代码审查
---

# 三段式代码审查（code_review）

最经典的「分析 → 规划 → 评审」三 agent 串行流水线。三个 agent 都不挂工具，纯靠 model 推理 —— 演示如何用 DAG 把一个复杂任务拆成多个专注的 agent。

## 分析代码 @analyzer

`analyzer` 是入口 agent（`after: []`），拿到用户提交的代码片段或文件路径，做静态分析：

- 识别代码意图和主要逻辑
- 标注潜在风险点（正确性 / 安全性 / 性能）
- 不做改写建议，只做事实判断

输出会传给下游 `planner` 作为规划依据。

## 规划审查重点 @planner

`planner`（`after: [analyzer]`）拿到 analyzer 的事实清单后，**规划审查的重点和优先级**：

- 哪些风险点必须深究
- 按严重度排序
- 给 reviewer 一份 checklist

这步把「审查什么」和「怎么判」分离 —— planner 决定 agenda，reviewer 执行判断。

## 输出评审意见 @reviewer

`reviewer`（`after: [planner]`）按 planner 给的 checklist 逐项给出评审意见：

- 每个 checklist 项 pass / fail
- 整体 decision：通过 / 打回
- 具体修改建议（如打回）

最终输出一份结构化的 code review 报告。

---

## 演示 task

```
请审查下面这段 Python 代码：

def login(username, password):
    query = f"SELECT * FROM users WHERE name='{username}' AND pw='{password}'"
    user = db.execute(query).fetchone()
    if user:
        return create_token(user['id'])
    return None
```

reviewer 应该能识别出 SQL 注入和密码明文比对两个严重问题。

## 调试要点

- 三个 agent 都 `tools: null`，验证 model-only 推理链路是否畅通
- 想加自动修复闭环：参考 [eval_code_quality](05_eval_code_quality.md) 的 coder ↔ reviewer 循环
