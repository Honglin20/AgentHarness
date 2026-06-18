---
workflow: ask_user_demo
title: ask_user 交互演示
badge: Quick Start
---

# ask_user 结构化问答演示

通过三个串联 agent 演示 `ask_user` 工具的三种典型用法：单选、多选、自由输入。点击右上角 **Try it** 加载工作流进入运行视图，亲身体验人机交互闭环。

## 招呼用户 @greeter

第一个 agent 用**单选模式**询问语言偏好：

- `options=[{label, value}]` 给出三个固定选项（English / 中文 / 日本語）
- `multi_select: false`（默认）强制只能选一个
- `allow_custom_input: true` 允许用户在三个选项之外输入任意语言
- `header: "Language"` 显示在问题卡片标题旁，作为话题标签

agent 收到答案后输出 `{language, greeting}` JSON，下游 agent 通过 state 拿到选择结果。

## 多选调查 @survey

承接上游的语言选择，用**多选模式**询问感兴趣的功能：

- `multi_select: true` 启用复选框（多选）
- `allow_custom_input: true` 同时允许补充自由文本
- 返回字符串形如 `"feature_a, feature_b | other: 自定义补充"`

## 汇总报告 @reporter

汇总前两步的用户输入，按选择的语言生成一段总结报告。本 agent 不调用 `ask_user`，只读取上游 state 输出。

---

## 调试要点

`ask_user` 是人机交互的锚点，但前端 **"已回答" 标记是点击时的乐观更新**（`ScopedConversationTab.tsx` 调 `answerUserQuestion` 在 WS 发送同时立刻把本地状态标成 answered），不代表答案真的回到后端 future。

要确认答案是否真正回到 LLM，看运行结束后的 `runs/<run_id>+snapshot.json` 里 `agent_io.<agent>.tool_calls` 对应 ask_user 条目的 `tool_result` 字段 —— 非空才是真到了 LLM。

运行时如果想看 future 注册 / 解析的过程，搜索日志里以 `ask_user.register` / `ask_user.resolve` / `ask_user.wait` / `ask_user.return` 开头的行，能看到 question_id、event loop id、payload、最终 answer_str 等关键信号。
