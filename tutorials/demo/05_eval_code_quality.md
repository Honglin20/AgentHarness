---
workflow: eval_code_quality
title: Eval 标记 + 评测闭环
---

# Eval 标记 + 评测闭环（eval_code_quality）

这个 demo 演示 workflow 里两个关键能力：

1. **`eval: true` 标记** —— 标在 `coder` 上，告诉框架这是一个「被评测」的 agent，下游 `reviewer` 自动作为评测者（无需手动声明 `target`）
2. **`on_fail` 回边** —— `reviewer` 决定 fail 时，框架自动把判反馈回 coder，coder 修订后再次进入 reviewer，形成自动修复闭环

## 编码 agent @coder

`coder` 带 `eval: true` 标记 + `bash` 工具。它的工作流：

1. 读取任务描述（用户输入或上游传递）
2. 写代码到文件
3. 用 bash 跑测试验证
4. 输出代码 + 简短说明

如果 reviewer 上一轮 fail 了，coder 会在上下文里看到 `## Previous judgment` 区块，必须**针对 critique 中提到的每一个问题**做修订，不能只改一处。

`eval: true` 的效果：框架自动注入「我正在被评测」的语境，并且把下游 reviewer 的输出格式约束为评测 schema（`decision` / `reason` / 可选 `score`）。

## 评测 agent @reviewer

`reviewer`（`after: [coder]`）作为隐式评测者，按标准评测维度判断 coder 输出：

| 维度 | 关注点 |
|------|--------|
| 正确性 | 逻辑是否正确、边界情况 |
| 安全性 | 注入 / 溢出 / 越权 |
| 可读性 | 命名、结构、注释 |
| 鲁棒性 | 错误处理、异常路径 |

输出 JSON：
- `decision`: `"pass"` 或 `"fail"`（必填）
- `reason`: 评语（必填）
- `score`: 0-1 浮点（可选）

`decision=fail` 时框架自动把这份 judgment 作为 `## Previous judgment` 注入下一轮 coder 的上下文，触发自动修订。

---

## 演示 task

```
实现一个函数 is_palindrome(s: str) -> bool：判断 s 是否是回文（忽略大小写、忽略非字母数字字符）。要求：
- 处理空串和单字符（视为回文）
- 输入非字符串时抛 TypeError
- 至少 3 个测试用例
```

工作流目录里已经放了一个参考实现 `agents/palindrome.py` 和评测 agent 配置 `_judge_coder.md`，运行时 coder 会基于这些素材生成自己的版本，reviewer 按上面的标准评测。

## 调试要点

- 想看 eval 自动注入是否生效：在运行日志里搜 `eval.inject` 或 `Previous judgment` 关键字
- coder 陷入死循环（反复 fail）：检查 max_iterations 设置，或调 reviewer 的判定阈值
- 想自定义评测维度：编辑 `workflows/eval_code_quality/agents/_judge_coder.md` 的「评测标准」段
