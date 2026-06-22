# 2026-06-21 — Token 计数显示修复（Q1）

## 背景

用户反映跑 NAS workflow 看到 BudgetBar 显示几百 K token，怀疑上下文炸了。诊断发现：

- **单位正确**：`record_usage` 直接读 pydantic-ai `Usage` 对象（API 返回的真实 token），不是字符也不是词
- **真 bug**：BudgetBar 把累计消耗（cumulative cost）当上下文窗口展示，且 cache 命中数无任何可视化
- **非 bug 但误导**：Cost bar 标签 "Cost" 不明确是「累计」还是「单次」

stage-2 单次/累计分离的后端字段（`last_input`、`cumulative_input`、`last_cache_hit` 等）早已就绪（见 `tests/engine/test_llm_executor.py::test_last_input_multi_request_is_delta`），但前端展示层未充分利用。

## 改动

### `frontend/src/components/diagnostics/BudgetBar.tsx`

1. **`ProgressBar` 新增 `hint?: string` 与 `title?: string` props**
   - `hint`：在 `current/max` 之后追加灰色小字，承载 cache 命中量
   - `title`：hover tooltip，澄清语义

2. **Cost bar 加 cache 提示**
   - 累计所有 node 的 `cacheHit`，>0 时显示 `(cache Xk)`
   - tooltip："累计消耗 — 所有 LLM 调用 input+output 之和（非当前上下文窗口）"

3. **Window bar 加 cache 提示**
   - 跟踪 worst-window 节点的 `lastCacheHit`（tie-break：等窗口大小时优先有 cache 数据的）
   - tooltip："最近一次单次请求的 input+output（model 实际看到的窗口）。cache 部分是已命中、未计费的"

### `frontend/vitest.config.ts`

- 加注释说明 vitest 4 + oxc + tsconfig `jsx:"preserve"` 的兼容问题，标记 component-level render test 暂不可行（TODO）

## 偏离 plan 处

- **未改 `HARNESS_REQUEST_LIMIT` 默认值（200→50）**：原计划改，但分析后判定这是配置选择而非 bug。NAS workflow 合理需要多 iter，全局降低 default 会破坏既有使用。用户可通过 env / settingsStore 自行调整。
- **未做 component 测试**：vitest 4 oxc parser 不支持 tsconfig `jsx:"preserve"`，写不了 `.tsx` 组件 render 测试。已注释 vitest.config.ts，依赖现有 `workflowStore.tokenUsage.test.ts`（数据层）+ TypeScript 类型检查 + 视觉验证。

## 验证

- `npx vitest run`：30 test files / 272 tests 全 pass
- `python -m pytest tests/harness/engine/test_token_aggregator.py`：10/10 pass
- `npx tsc --noEmit`：clean
- `npm run build`：✓ Compiled successfully（仅 2 个 pre-existing warning）

## Commit SHA

待 commit 后填入。

## 后续

- Q2 prompt 补齐（Claude Code 工作范式注入）—— 待讨论方案
- Q3 prompt 统一管理重构（base prompt 注入层）—— 待 ADR
- vitest oxc jsx 配置 —— 待 vitest API 稳定后回头处理
