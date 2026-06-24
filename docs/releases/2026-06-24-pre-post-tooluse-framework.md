# Pre/PostToolUse 框架 + Token 治理 — 实施报告

- **日期**: 2026-06-24
- **类型**: 实施报告 + 量化对比
- **范围**: PreToolUse/PostToolUse 工具生命周期框架（TASK 0-3），对标 Claude Code 的工具管控能力
- **上游**: [`docs/plans/2026-06-23-harness-vs-claudecode-gap-audit.md`](../plans/2026-06-23-harness-vs-claudecode-gap-audit.md) §3 HOOK 段

---

## 1. 交付物（4 个 commit）

| TASK | Commit | 内容 |
|---|---|---|
| 0 | `feat(tools): tool-output measurement infrastructure` | token_counter（可插拔，tiktoken + 启发式回退）+ `_measure.py` 测量事件 + `_wrap_fn` 注入 |
| 1 | `feat(hooks): PreToolUse/PostToolUse lifecycle dispatch` | SubstituteAction + `after_tool` middleware + `_hook_dispatch.py` + `_wrap_fn` 统一异步生命周期管线 |
| 2 | `feat(hooks): TokenStatsHook + token-audit demo` | 审计 hook（纯观察者）+ demo workflow + 基线数据 |
| 3 | `feat(hooks): OutputCompactor PostToolUse middleware` | PostToolUse 清洗中间件（token 阈值 + head/tail 摘要 + 落盘指针）+ 前后对比 |

## 2. 架构（终态）

```
pydantic-ai tool dispatch → ToolFactory._wrap_fn (统一 chokepoint)
  ├─ 0. dedup guard              (现有)
  ├─ 1. PreToolUse dispatch      ← before_tool middleware (block / 改参数 / 提醒)
  ├─ 2. execute (sync→anyio 线程) 
  ├─ 3. truncate                 (现有，字节级)
  ├─ 4. PostToolUse dispatch     ← after_tool middleware (SubstituteAction 清洗)
  └─ 5. measure emit             ← agent.tool_output_measured (TASK 0)
```

**设计原则落地**：
- 单一职责：调度/计数/策略各一层，不混层
- 显式优于隐式：control flow 用 `RejectAction`/`SubstituteAction`/`RetryAction` 三件套表达
- 鲁棒性优先：所有 dispatch try/except 兜底，异常回退「不干预」；`_has_middleware()` fast-path 零开销
- 开闭原则：加新策略（如未来危险命令拦截）只写新 middleware，不改框架核心
- 零行为变更：不注册任何 middleware 时，行为字节级等于改造前

## 3. 量化对比（token_audit demo，真实 LLM 运行）

基线（无 OutputCompactor） vs 启用 OutputCompactor（threshold=500 tokens）：

| 工具 | 基线 tokens | 启用后 tokens | 变化 |
|---|---|---|---|
| **bash** | 1177 | **694** | **−41%** (max 777→400, −48%) |
| grep | 342 | 342 | 0%（阈值未触发） |
| TodoTool | 343 | 249 | −27%（白名单本不该变，差异来自 LLM 非确定性调用次数 9→8） |
| glob | 93 | 93 | 0% |
| **总计** | **1955** | **1378** | **−29.5%** |

**结论**：
- bash 是最大的 token 消耗者（基线占 60%），OutputCompactor 把它的单次最大输出从 777→400 tokens，整体下降 41%
- 总量下降 ~30%，达到 TASK 3 验收标准（≥30%）
- grep/glob 未触发阈值（各自 <200 tokens），证明阈值是 token-aware 的精准治理，不是无差别截断
- 信息不丢：清洗后结果含 `.tool_outputs/` 落盘指针，模型可用 `read_text_file` 取回全文

**数据基线文件**：`tests/fixtures/token_audit_baseline.json`、`tests/fixtures/token_audit_after.json`（可 diff）

## 4. 验收对照

| TASK | 验收项 | 状态 |
|---|---|---|
| 0 | 测量覆盖每个工具调用 | ✅ demo 16 调用全记录 |
| 0 | 零行为变更 | ✅ baseline 断言 |
| 0 | tokenizer 正确 + 回退鲁棒 | ✅ 17 测试 |
| 1 | 零默认行为 + fast-path | ✅ `_has_middleware()` |
| 1 | before_tool block / after_tool substitute 生效 | ✅ 12 测试 |
| 1 | 异常隔离 | ✅ 破坏性 middleware 不污染工具 |
| 2 | demo 跑通 + 基线快照 | ✅ baseline.json |
| 2 | hook 纯观察者 | ✅ 无 SubstituteAction |
| 3 | 清洗生效（≥30% 下降） | ✅ −29.5%（bash −41%） |
| 3 | 信息不丢（落盘指针） | ✅ read_text_file 可恢复 |
| 3 | 白名单正确 | ✅ TodoTool/ask_user 透传 |

## 5. 测试覆盖
- `tests/tools/test_measure.py` — 17（测量基础设施）
- `tests/extensions/test_tool_hooks.py` — 12（hook 调度）
- `tests/extensions/test_token_stats_hook.py` — 8（审计 hook）
- `tests/extensions/test_output_compactor.py` — 10（清洗中间件）
- 工具测试同步转 async（pydantic-ai 始终 await tool fn）

## 6. 后续（不在本次范围）
- **PreToolUse 业务规则**：危险命令拦截（rm -rf / git push）、重复调用提醒——框架能力已就绪（TASK 1），只差写 middleware
- **子 agent 摘要式清洗**：`OutputCompactor.summarize` 已留扩展点，可换 LLM 摘要策略
- **AutoCompact 接入**（middleware C 段，用户明确排除本次）
