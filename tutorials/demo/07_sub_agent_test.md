---
workflow: sub_agent_test
title: Sub-agent 委派
---

# Sub-agent 委派（sub_agent_test）

最小化的 sub_agent 演示：只有一个 `delegator` agent，它不直接做事，而是**必须**通过 `sub_agent` 工具把任务委派给一个临时子 agent，子 agent 完成后把结果汇总返回。这是 NAS workflow 中 trainer 展开 K 个并行 worker 的最小验证场景。

## 委派者 @delegator

`delegator` 拿到任务后的硬性约束：

1. **第一个动作必须是调 `sub_agent`** —— 不能先输出文本、不能先思考 aloud
2. **不能直接回答任务** —— 即使任务很简单，也要走 sub_agent 路径
3. sub_agent 返回后，**汇总**作为最终输出（不是原样转发）

工具集：`[sub_agent, bash]`。`bash` 用来做轻量辅助（比如验证 sub_agent 输出的格式），主任务必须靠 sub_agent 完成。

输出 JSON：`{summary, details?}`。

### 何时用这个模式

- 任务可以拆成独立的子任务，主 agent 只做调度
- 想让子任务在自己的子上下文里执行，避免污染主 agent 的对话
- NAS 场景里 trainer 同时展开 K 个 worker —— 那是 `sub_agent` 的并行变体，本 demo 是单线程版

---

## 演示 task

```
帮我调研 Python 的三种主流 web 框架（Django / Flask / FastAPI），各自的核心特点、典型场景、性能特征。然后给出一个推荐：构建实时 API 服务用哪个。
```

delegator 应当把这个任务委派给 sub_agent，sub_agent 完成调研后返回，delegator 汇总成最终推荐。

更简单的版本：

```
用 sub_agent 计算斐波那契数列的第 20 项，并验证结果是否正确。
```

## 调试要点

- delegator 直接回答了任务（没调 sub_agent）：检查 agent prompt 是否强化了「FIRST action MUST be sub_agent」，必要时调 retries 让框架重试
- 想看并行展开（一次发起多个 sub_agent）：参考 [parallel_iter_demo](08_parallel_iter_demo.md) 的 `generator` agent，那是并行版本
- sub_agent 调用失败：在日志里搜 `sub_agent.invoke` / `sub_agent.error`，常见原因是 task 描述太模糊导致子 agent 无法产出结构化输出
