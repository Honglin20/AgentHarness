# Current Task

**当前任务**: AgentPrompt 封装一期（收拢现有 prompt 组件）
**状态**: SPEC 完成，待确认

---

## 已完成

- 分析当前 prompt 全部组成（6 个 section，散落 3 文件）
- 确认 Available Scripts 逻辑（双目录扫描 + 非隐藏文件检测）
- 输出当前 prompt 参考快照（普通节点 / Judge / Sub-agent）
- 撰写 SPEC: `docs/specs/2026-05-31-agent-prompt-encapsulation.md`

## 必读文件

- `docs/specs/2026-05-31-agent-prompt-encapsulation.md` — 本期 SPEC
- `harness/engine/macro_graph.py` — 当前 prompt 拼接主逻辑
- `harness/engine/micro_agent.py` — build_node_prompt

---

## 待做

- Phase 1a: 新增 `agent_prompt.py` + 单测（黄金文件验证渲染一致）
- Phase 1b: 普通节点迁移（macro_graph.py 用 AgentPrompt 替代散落拼接）
- Phase 1c: Judge 节点迁移（JudgePrompt 子类）
- Phase 1d: deprecated 标记 + 全量测试
