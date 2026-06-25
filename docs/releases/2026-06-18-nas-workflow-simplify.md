# Release Note: NAS Workflow 简化重构

> 日期: 2026-06-18
> 关联计划: [`docs/plans/2026-06-18-nas-workflow-simplify.md`](../plans/2026-06-18-nas-workflow-simplify.md)
> 实际改动: 全部 5 个 Phase 完成 + mnist 实测验证

---

## 总览

将 15-agent 7-step NAS workflow 重构为 15-agent 4-step 简化版（agent 数不变，cycle 步数从 7 降到 4，3 optimizer 并行），加入断点续传、metric ask_user 确认、tier_baseline 条件触发、selector 综合公式等改进。

## 5 个 Phase 完成情况

### Phase 1: 4 helper + 单元测试 ✅
- refactor `measure_onnx_latency.py` 暴露纯函数 `measure_latency(onnx_path) -> dict`
- 新建 `parse_train_log.py`（regex-based metric 提取，取最后匹配）
- 新建 `check_resume.py`（文件存在 + JSON 有效性）
- 扩展 `history.py` 加 `write-running-memory` subcommand
- **测试**: 16 个单元测试全过（含真实 mnist 数据端到端验证）

### Phase 2: SETUP 6 agent ✅
- 改写 `project_analyzer.md`（加 resume check）
- 改写 `adapter_generator.md`（smoke 责任移交 smoke_runner）
- 新建 `business_analyzer.md`（替代 domain_analyzer，扩展业务背景分析）
- 新建 `smoke_runner.md`（替代旧 baseline_runner，跑 1 epoch + 小 data_ratio 捕获 log）
- 新建 `metric_align.md`（替代 metrics_identifier，加 ask_user 确认指标方向）
- 新建 `setup_align.md`（汇总 SETUP 总契约）
- 重写 `baseline_runner.md`（全量 epochs，跑后 ask_user 汇报）
- 删除 `metrics_identifier.md` / `domain_analyzer.md` / `scout.md`

### Phase 3: NAS CYCLE 7 agent ✅
- 改写 `tier_planner.md`（cycle 内每轮调用，复用 on_pass=stay/on_fail=upgrade 路由）
- 新建 `tier_baseline_runner.md`（条件触发，跑 tier 升级时 baseline 参考）
- 改写 `selector.md`（综合公式 score=fitness+0.3×exploration_bonus + 方向轮换硬规则）
- 新建 `optimizer_hyperparam.md` / `optimizer_structural.md` / `optimizer_business.md`（3 个并行专精 optimizer，每个自闭环 retry 到跑通，budget ≤3 change point）
- 新建 `collector.md`（合并 judger/analyzer/validator，deterministic stop/continue 决策）
- 删除 `planner.md` / `trainer.md` / `judger.md` / `analyzer.md` / `validator.md` / `refiner.md`
- 改写 `schemas.py`（重写顶层 result_types，保留底层文件 schemas）
- 改写 `register.py`（新拓扑，max_iterations=100 仅作安全网）

### Phase 4: reporter + 断点续传 + CLI ✅
- 改写 `reporter.md`（best_strategy 全量训练验证 + 跟 baseline 对比）
- 所有 SETUP agent Step 0 接入 `check_resume.py`（schema 校验）
- `run_nas.py` 加 `--session-id <id>` 参数（resume 支持）

### Phase 5: mnist 修 + 实测 ✅
- 修 mnist `model.py`（接受 kwargs，默认 relu + no BN；之前 GELU/BN 是 NAS 探索残留）
- 修 mnist `dummy_inputs`（返回 (N, 64) 匹配 sklearn digits）
- 实测观察到 SETUP 6 agent 全部完成 + CYCLE 进入 iter_1

---

## mnist 实测观察（session: 20260618_222921_mnist）

### ✅ 验证通过

| 阶段 | 现象 |
|---|---|
| project_analyzer | 正确探测 ConfigurableMLP + train:main + epochs=5 + weights_path |
| adapter_generator | 生成 _nas_adapter.py，smoke_result 占位 null（smoke_runner 接管） |
| smoke_runner | 1 epoch 训练成功，acc=0.789，捕获 train.log |
| metric_align | ask_user timeout 后用 business context 推断：primary=acc, direction=higher |
| setup_align | 生成 setup_contract + budget，2-tier 系统：tier_0=(1ep, 0.3 data), tier_1=(5ep, full) |
| baseline_runner | 全量 5 epoch 训练，acc=0.964, latency=0.016ms, params=8970 |
| tier_planner | iter_1 决策：stay tier 0，config={epochs:1, data_ratio:0.3} |
| selector | iter_1 parent=baseline（首轮特殊处理），exploration_bonus=1.0 |

### ⚠️ 发现的问题（待修）

1. **business_context.md 未生成**（首次实测发现，本次手动补齐）
   - 现象：business_analyzer 应在 project_analyzer 后并行运行，但 session_dir 里没有 business_context.md
   - 影响：optimizer_business 失去业务背景输入（其他 optimizer 不受影响）
   - 可能原因：agent 失败被静默吞错 / framework 在某条件下跳过 / 输出路径写错
   - 调查方向：检查 business_analyzer 的 result_type 是否返回成功 + 框架日志是否有 fail 标记

2. **ask_user TIMEOUT**（首次 + resume 实测都出现）
   - 现象：metric_align / setup_align / baseline_runner 都触发 ask_user timeout（每次 10s）
   - 影响：用户决策被跳过，agent 用自身判断兜底
   - 缓解：跑 `--ui` 模式启用 WS 交互，或预设 inputs 减少 ask_user 触发

3. **`merge_dicts: key conflict overwritten` 框架警告**
   - 现象：每个 agent 完成后出现 3-6 次 `key conflict overwritten: {'<agent_name>'}`
   - 影响：可能 benign（framework 状态合并），也可能是 bug
   - 调查方向：查 `harness/engine/state.py` 或 langgraph 状态合并逻辑

4. **ONNX export 在 smoke 阶段失败（非阻塞）**
   - 现象：smoke_train.log 显示 `onnx export failed (non-blocking)`
   - 影响：smoke 阶段没拿到 latency，但 baseline_runner 后续成功 export 了
   - 原因：adapter 模板代码未跟上 refactor，可能调用了旧 helper 签名
   - 修复：更新 `_adapter_template.py` 内的 export 调用

5. **project_analyzer 误读 model 默认值**
   - 现象：报告 `activation='gelu', use_batchnorm=True`，但 model.py 默认 `activation='relu', use_batchnorm=False`
   - 影响：minor，adapter_generator 用了正确签名（带 kwargs override）
   - 原因：LLM 读 model.py docstring（提到 GELU variant）后被误导
   - 缓解：agent prompt 加 "ignore docstring, only read __init__ signature defaults"

6. **🔴 关键：SETUP agent 在 resume 时不 skip**（resume 实测发现）
   - 现象：`--session-id` resume 时，6 个 SETUP agent 仍全部重新执行（包括 ask_user），没有遵守自己 MD 里 "Step 0 check_resume → skip=true 时跳过" 的指令
   - 影响：resume 失效，每次都从头跑 SETUP（消耗 LLM API + 时间）
   - 根因：LLM-driven agent 没严格执行 MD 的 Step 0；缺框架级 resume 强制
   - 修复方向：
     - A) 加 framework-level pre-step（agent 调用前框架先 check_resume，skip=true 则不调 LLM）
     - B) 强化 MD prompt（"MANDATORY Step 0"，加 fail-loud 校验）
   - 推荐方案 A：彻底解耦 resume 与 LLM 行为

7. **🔴 关键：optimizer 不创建 worktree，直接污染用户项目**（cycle 实测发现）
   - 现象：optimizer_business 在 cycle iter_1 跑时，直接修改了 `projects/mnist/train.py` + `eval.py` + 新建 `model_v3.py` + 改 `_nas_adapter.py`，完全绕过 worktree 隔离
   - 影响：
     - 3 个 optimizer 并发改同一份 user code → 互相覆盖、冲突
     - 用户项目被污染（已用 `git checkout` 恢复）
     - parent_snapshot 概念失效（没有 isolated 起点可言）
   - 根因：
     - optimizer MD 写了"必须 worktree 隔离"但 LLM 没执行
     - harness 的 sub_agent 工具支持 `isolation="worktree"` 但 agent 没用
   - 修复方向：
     - A) optimizer 用 sub_agent 调内部 coder/trainer（强制 isolation=worktree）
     - B) 加 framework 检查：optimizer 启动时强制在 worktree 路径下
     - C) 改 optimizer MD：明确给 worktree 创建命令模板 + 校验 cwd 不在 working_dir
   - 推荐方案 A：用现成的 sub_agent worktree 机制

8. **新加：cycle iter_1 在 selector 后卡住**
   - 现象：tier_decision + selector_decision 都写了，但 3 个 optimizer 跑了 5+ 分钟都没产出 iter_1/optimizer_<X>/ 目录或 candidates.json entry
   - 影响：cycle 无法完成首轮
   - 根因：和 #7 相关——optimizer 在 user dir 改代码 + 训练，可能训练失败 + 重试循环，或者 LLM 调用缓慢
   - 调查方向：单独跑一个 optimizer 看完整 trace

### 📊 mnist 项目状态确认

| 用户假设 | 实际 | 备注 |
|---|---|---|
| "没有 CLI 入口" | ❌ `train.py` + `eval.py` 都有完整 argparse + main() | 但 workflow 正常处理 CLI 项目 |
| "epochs 不为 1" | ✅ `--epochs default=5` | 符合预期 |
| model.py 状态 | 已修复（之前 GELU/BN 是 NAS 残留，已改回 relu/no_BN baseline） | 干净起点供 NAS 探索 |

---

## 改动文件清单

### 新建（10 个）
- `workflows/nas/helpers/parse_train_log.py`
- `workflows/nas/helpers/check_resume.py`
- `workflows/nas/agents/business_analyzer.md`
- `workflows/nas/agents/smoke_runner.md`
- `workflows/nas/agents/metric_align.md`
- `workflows/nas/agents/setup_align.md`
- `workflows/nas/agents/tier_baseline_runner.md`
- `workflows/nas/agents/optimizer_hyperparam.md`
- `workflows/nas/agents/optimizer_structural.md`
- `workflows/nas/agents/optimizer_business.md`
- `workflows/nas/agents/collector.md`
- `tests/test_nas_helpers.py`
- `docs/plans/2026-06-18-nas-workflow-simplify.md`
- `docs/releases/2026-06-18-nas-workflow-simplify.md`（本文）

### 重写（4 个）
- `devkit/nas/schemas.py`
- `devkit/nas/register.py`
- `workflows/nas/run_nas.py`
- `workflows/nas/workflow.json`（生成产物）

### 修改（5 个）
- `workflows/nas/helpers/measure_onnx_latency.py`（refactor 暴露纯函数）
- `workflows/nas/helpers/history.py`（加 write-running-memory）
- `workflows/nas/agents/project_analyzer.md`
- `workflows/nas/agents/adapter_generator.md`
- `workflows/nas/agents/baseline_runner.md`（语义改变：1ep → 全量）
- `workflows/nas/agents/tier_planner.md`（setup → cycle）
- `workflows/nas/agents/selector.md`（top-1 → 综合公式）
- `workflows/nas/agents/reporter.md`
- `projects/mnist/model.py`（修 kwargs 一致性 + dummy_inputs 形状）

### 删除（9 个）
- `workflows/nas/agents/metrics_identifier.md`
- `workflows/nas/agents/domain_analyzer.md`
- `workflows/nas/agents/scout.md`
- `workflows/nas/agents/planner.md`
- `workflows/nas/agents/trainer.md`
- `workflows/nas/agents/judger.md`
- `workflows/nas/agents/analyzer.md`
- `workflows/nas/agents/validator.md`
- `workflows/nas/agents/refiner.md`

---

## 不变量保持

1. ✅ `MAX_CHANGE_COUNT=3` 硬编码（fitness.py + schemas.py 同步）
2. ✅ workflow.json 由 devkit/nas/register.py 生成（不手改）
3. ✅ 所有 SETUP agent 带 resume check
4. ✅ log_parse_rules.json 全 cycle 复用（metric_align 写入后不改）
5. ✅ candidates.json 每个 entry 含 source/parent_id/iter_num（collector 维护）
6. ✅ tier_baseline 在 selector 之前完成（条件路由）
7. ✅ selector 禁止同方向连续 3 轮（硬规则）
8. ✅ 复用现有 on_pass/on_fail 路由（零框架改动）

---

## 下一步建议（Phase 6+，未做）

1. **business_analyzer 输出丢失调查**（高优先级）— 影响 optimizer_business 质量
2. **merge_dicts 警告调查**（中优先级）— 可能是 framework bug
3. **adapter_template ONNX export 跟上新 helper 签名**（中优先级）
4. **完整 cycle iter 跑通**（需 LLM API + 时间，建议用户跑 `--ui` 模式实测）
5. **resume 测试**：跑一次中断后用 `--session-id` resume 验证 skip 生效
