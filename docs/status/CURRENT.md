# Current Task

**当前任务**: ask_user 结构化提问工具（方案 B）
**状态**: 实现完成，待 E2E 验证

---

## 已完成

- B-1: 后端 ask_user 工具 + _human_io 抽取 + ask_human 薄壳 + 单测
- B-2: 事件 payload 扩展 + WS handler 兼容新旧 answer + 单测
- B-3: 前端消息类型 + store action 重写 + 事件路由改动
- B-4: AgentQuestionCard 组件 + ConversationTab/ScopedConversationTab 渲染分发
- B-5: 主输入框去耦（pendingQuestionId 不再由新工具设置）
- B-6: 前端构建通过 + CLAUDE.md 更新

## 必读文件

- `docs/specs/2026-05-30-ask-user-structured-question.md` — SPEC
- `harness/tools/ask_user.py` — 核心工具实现
- `frontend/src/components/conversation/AgentQuestionCard.tsx` — UI 卡片

---

## 待做

- 手动 E2E 验证（启动 workflow + LLM 调 ask_user + 卡片交互）
- 内置 workflow agent prompt 更新（告知 LLM 可用 ask_user + options 参数）
