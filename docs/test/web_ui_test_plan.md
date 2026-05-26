# Web UI 端到端测试计划

**测试日期**: 2026-05-26
**测试范围**: 所有 workflows 和 benchmarks 在 Web UI 上的功能验证

---

## 测试执行记录 (API 自动化测试)

| Workflow | Status | Notes |
|----------|--------|-------|
| chart_demo | ✅ PASS | agent_io 和 trace 正常，输出正确 |
| parallel_research | ✅ PASS | 3 个 agent 并行执行，fan-in 正确 |
| conditional_route | ✅ PASS | 条件边正确显示，路径选择正确 |
| eval_demo | ⬜ | 需要调试 (eval 模式) |
| loop_retry | ⬜ | DAG 构建问题 (on_fail 边导致没有入口点) |
| test-quick benchmark | ⬜ | 500 错误 (需要修复 benchmark API) |
| code-review-v1 benchmark | ⬜ | 500 错误 (需要修复 benchmark API) |

---

## 已修复问题

1. **WebSocket 路由丢失** - 添加了 `/ws/workflows/{workflow_id}` 和 `/ws/batch/{batch_id}` 端点
2. **workflow 目录解析错误** - `_validate_workflow_dir` 现在正确查找 `_shared/workflows/` 子目录
3. **agent_io 不返回** - `RunDetail` schema 和 `get_run` API 现在返回 `agent_io` 字段

---

## 剩余问题

1. **Benchmark API 500 错误** - 需要调试 `run_benchmark` 端点
2. **loop_retry DAG 构建** - LangGraph 要求有从 START 的入口点，`on_fail` 回环导致问题
3. **eval 模式** - 需要验证 EvalJudge 插件是否正常工作

---

## 下一步

1. 通过 Web UI 手动测试以下功能点：
   - Conversation 面板的工具调用记录显示
   - Results 面板的 JSON 格式解析
   - DAG 面板的节点状态着色和条件边标签
   - Sidebar 的 Run History 记录加载

2. 修复 benchmark API 问题

3. 调试 loop_retry 的 DAG 构建