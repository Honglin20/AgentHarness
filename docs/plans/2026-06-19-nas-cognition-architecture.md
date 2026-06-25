# NAS Cognition Architecture — 实施计划

> 日期: 2026-06-19
> 状态: 设计已与用户对齐，待执行
> 上游: [2026-06-18-nas-workflow-simplify.md](./2026-06-18-nas-workflow-simplify.md)（上一轮简化）
> 参考: [ASI-Arch paper](https://arxiv.org/abs/2507.18074) + `references/asi-arch/`（不入库）

---

## 1. 背景与动机

上一轮简化（2026-06-18）把 NAS 从 7 步串行压到 4 步（tier_planner → selector → 3 optimizer 并行 → collector），引入 business_analyzer + ask_user 契约，可跑通。但与 ASI-Arch 论文范式对比，仍缺三个核心能力：

1. **缺检索增强（RAG）**：business_analyzer 只靠 LLM 内置知识，无外部 cognition；optimizer_business 决策时不查 SOTA 库
2. **缺经验复盘 agent**：collector 只做简单 ranking，没有"为什么这个方向有效/无效"的综合分析，下一轮 planner 拿不到 actionable 指导
3. **缺跨 session 记忆**：同 project 跑第 2 次完全不知道第 1 次的经验，每次都从零开始

辅助痛点：
- 当前 `tier_planner + tier_baseline_runner` 过复杂，应同步论文简化为两阶段
- `selector` 的 `fitness + 0.3 × exploration_bonus` 公式不如论文的"分桶采样 + lineage"系统
- 无 motivation 去重机制（强重复会浪费 iter）

---

## 2. 设计原则（5 条）

| # | 原则 | 理由 |
|---|------|------|
| 1 | **文件系统优先，零外部依赖** | 不引入 MongoDB/Docker/FAISS（初期）。单机开发场景 JSON 完全够用 |
| 2 | **三层 cognition**：静态 L0 + 项目记忆 L1 + 会话 L2 | L0 全局共享，L1 跨 session 沉淀，L2 当前会话细节 |
| 3 | **两层复盘**：微观 analyzer（单实验）+ 宏观 summarizer（跨实验） | 对齐论文 analyzer + summarizer 双 agent 设计 |
| 4 | **两阶段 tier**：T1 快验证 + T2 全训练，**T2 可退化 T1** | 同步论文 short/full training；T2 不达标自动退回 T1 探索 |
| 5 | **Project 级断点重续**：跨 session 共享 L1 | 同 project 反复跑能累积经验，不只 session 内续跑 |

---

## 3. 架构总览

### 3.1 三层 Cognition 存储

```
┌─────────────────────────────────────────────────────────────────┐
│  L0: cognition_base (静态，全局跨 project)                       │
│  workflows/nas/cognition/<domain>/recipes.json                  │
│                                                                 │
│  每个 recipe:                                                   │
│  {                                                              │
│    "id": "cv-aug-rotation",                                     │
│    "symptom": "数据量小 / 过拟合 / acc 上不去",                 │
│    "technique": "Random rotation + translation augmentation",   │
│    "implementation_guide": "...",                               │
│    "applicable_domain": "cv",                                   │
│    "applicable_task": "classification",                         │
│    "cost": "low"                                                │
│  }                                                              │
└─────────────────────────────────────────────────────────────────┘
                              ↑ 读
┌─────────────────────────────────────────────────────────────────┐
│  L1: project_memory (动态，跨 session 共享)                      │
│  workflows/nas/memory/<project_name>/                           │
│                                                                 │
│  ├── candidates.json     # 跨 session top-K 候选集               │
│  │   每个 candidate 带: {id, score, tier, parent_id, ...}       │
│  ├── lineage.json        # 演化树 (parent chain)                │
│  ├── experience.md       # summarizer 综合，给 planner/optimizer │
│  ├── cognition.md        # 历史 RAG 检索结果累积                 │
│  └── dedup.idx           # 跨 session motivation hash 去重       │
└─────────────────────────────────────────────────────────────────┘
                              ↑ 读写
┌─────────────────────────────────────────────────────────────────┐
│  L2: session_state (per-session，已有，基本不变)                 │
│  workflows/nas/runs/<timestamp>_<project>/                      │
│  ├── iter_N/             # 当前 session 的实验细节               │
│  ├── running_memory/     # per-direction 跨 iter 记忆            │
│  ├── HISTORY.md          # 当前 session 索引                     │
│  └── setup_contract.json # SETUP 阶段契约                        │
└─────────────────────────────────────────────────────────────────┘
```

### 3.2 数据流（一图）

```
[SETUP 阶段]
  project_analyzer → adapter_generator → smoke_runner
       ↓
  business_analyzer ── 读 L0 (recipes by domain) ──┐
       │   └─ 检索结果写入 L1/cognition.md         │
       ↓                                            │
  metric_align → setup_align → baseline_runner     │
       │                                            │
       └─ 记录 target_metric_value（T2 判定用） ←──┘
                                                  │
[CYCLE 阶段]                                       │
  selector                                         │
       ├─ sample_parent_and_refs(L1/candidates) ←──┘
       │   ├─ elite 桶 (top 1-10, tier ∈ {T1, T2_passed})
       │   └─ diversity 桶 (top 11-50, 含 T2_failed 防重复)
       ├─ summarizer(parent)  →  写 L1/experience.md  ⭐ 新增
       └─ 输出 parent + refs
       ↓
  optimizer_{hyperparam, structural, business}  ←─ 读 L1/experience.md
       ├─ business 读 L0 (recipes)
       └─ T1 快验证 (epochs=1-3, data_ratio=0.1-0.2)
       ↓
  analyzer  ←─ 读 L1/lineage (parent + siblings)
       ├─ 微观分析 (5 维)
       ├─ 判定 T2 触发:
       │   if candidate.score > baseline*1.02 and rank<=5:
       │     enqueue T2
       └─ 写 L1 (candidates + lineage + cognition)
       ↓
  [T2 队列] tier2_runner ─→ 全训练 ─→ 判定:
       │   if metric >= target_metric_value: tier="T2_passed"
       │   else:                              tier="T2_failed"  ⭐ 退化
       └─ 更新 L1/candidates
       ↓
  reporter (cycle 结束)
```

---

## 4. 候选选择机制（对齐论文）

### 4.1 论文实际做法（事实依据）

**位置**: `pipeline/database/interface.py:29-30`

```python
parent_element = db.candidate_sample_from_range(1, 10, 1)[0]  # top 1-10 取 1 parent
ref_elements = db.candidate_sample_from_range(11, 50, 4)       # top 11-50 取 4 ref
```

**不是真 UCT**。虽然 `mongodb_database.py:1102-1184` 实现了 `uct_select_node`，但 pipeline 主流程实际用的是**分桶采样**：

| 桶 | 范围 | 采样数 | 角色 |
|----|------|--------|------|
| Elite | top 1-10 | 1 | parent（演化基础，保证基线） |
| Diversity | top 11-50 | 4 | reference（多样性参考，避免局部最优） |

**隐含设计意图**：
- top 1-10 都是"已验证好"的 → 选 1 个做 parent，保证演化方向
- top 11-50 是"次优但方向不同" → 选 4 个做参考，提供多角度视野
- 同 parent 可被多次选中 → 自然产生不同演化分支

### 4.2 NAS 落地（简化版）

**新增**: `workflows/nas/helpers/candidate_selector.py`

```python
def sample_parent_and_refs(candidates: list, elite_k=10, ref_k=4):
    """
    分桶采样：elite 选 parent，diversity 选 refs。
    tier 过滤规则：
      - elite 桶: tier ∈ {T1, T2_passed}（T2_failed 不进 elite）
      - diversity 桶: 包含 T2_failed（避免重复探索同方向）
    """
    eligible = [c for c in candidates if c['tier'] in ('T1', 'T2_passed')]
    eligible.sort(key=lambda c: c['score'], reverse=True)

    elite = eligible[:elite_k]
    refs_pool = candidates[elite_k:elite_k + 40]  # 含 T2_failed

    parent = random.choice(elite) if elite else None
    refs = random.sample(refs_pool, min(ref_k, len(refs_pool)))
    return parent, refs
```

**对 selector.md 的改造**：
- 删除 `score = fitness + 0.3 × exploration_bonus` 公式
- 改为调 `sample_parent_and_refs()`
- rotation rule 保留（禁止同方向连续 3 轮）

---

## 5. 两阶段 Tier（含 T2→T1 退化）⭐

### 5.1 当前问题

当前 `tier_planner + tier_baseline_runner` + `tier_state.json` 太复杂，且 tier 数量是人为分档（如 data_ratio 0.1 / 0.3 / 1.0），与论文逻辑不符。

### 5.2 新设计（两阶段）

| 阶段 | 目标 | 配置 | 触发条件 |
|------|------|------|---------|
| **T1: 快验证** | 判断结构方向是否 work | epochs=1-3, data_ratio=0.1-0.2 | 默认所有 optimizer 输出 |
| **T2: 全训练** | 确认最终性能 | epochs=full, data_ratio=1.0 | T1 分数过阈值 + rank ≤ 5 |

### 5.3 Candidate tier 字段（4 状态）

```json
{
  "id": "iter_3_opt_business",
  "score": 0.847,
  "tier": "T2_passed",   // T1 | T2_passed | T2_failed | T2_pending
  "t2_metric": 0.92,
  "t1_metric": 0.89,
  "parent_id": "iter_2_opt_business"
}
```

**4 状态语义**：
- `T1`：仅快验证，T1 cycle 中流转
- `T2_passed`：T2 全训练且 `metric >= target_metric_value`，进 elite 桶
- `T2_failed`：T2 全训练但 `metric < target_metric_value`，**降级退出 elite，但保留在 lineage**（防重复）
- `T2_pending`：在 T2 队列等待执行

### 5.4 T2 → T1 退化机制 ⭐

**触发条件**（任一即触发）：
1. **不达标**：T2 metric < `setup_contract.target_metric_value`
2. **倒退**：T2 metric < T1 metric × 0.95（过拟合或训练不稳定）
3. **崩溃**：T2 训练失败（如 OOM、发散）

**退化动作**：
```python
# tier2_runner 完成 T2 后
if t2_metric < target_metric_value:
    candidate.tier = "T2_failed"
    candidate.t2_metric = t2_metric
    candidate.t2_failure_reason = "below_target"  # | "regression" | "crash"

    # 写入 L1/experience.md，给下一轮 summarizer 用
    project_memory.append_experience({
        "candidate_id": candidate.id,
        "event": "T2_failed",
        "t1_metric": candidate.t1_metric,
        "t2_metric": t2_metric,
        "gap_to_target": target_metric_value - t2_metric,
        "analysis": "..."  # tier2_runner 的分析输出
    })

    # 不进 elite，cycle 自然继续探索其他方向
```

**关键设计决策**：

| 决策 | 选择 | 理由 |
|------|------|------|
| T2_failed 是否删除？ | **不删，保留在 lineage** | 防止下次 selector 重复探索同方向 |
| T2_failed 是否进 elite？ | **不进** | elite 必须是"已验证好"的 |
| T2_failed 是否进 diversity？ | **进** | 让 planner 看到失败案例，避免重蹈 |
| 多次 T2_failed 后？ | **触发 summarizer 反思** | 重新分析 elite 桶，调整探索方向 |

**反思触发**（连续 3 次 T2_failed）：

```python
# analyzer 在每次 T2 完成后检查
recent_t2_failures = project_memory.get_recent_events(
    event="T2_failed", limit=3)

if len(recent_t2_failures) >= 3 and not project_memory.has_recent_reflection():
    # 触发 summarizer 反思模式
    summarizer.reflect(elite_bucket, recent_t2_failures)
    project_memory.mark_reflection_done()
```

### 5.5 T2 异步执行

- T2 在后台跑，不阻塞 T1 cycle
- T2 队列长度限制（如 top-3），防止堆积
- T2 完成后回写 candidates.json，更新 tier + score

---

## 6. 两层经验复盘（核心创新）

### 6.1 论文实际做法（事实依据）

**双层结构**：

| 层 | Agent | 触发时机 | 输入 | 输出 |
|----|-------|---------|------|------|
| 微观 | `analyzer` | 每次实验完成 | result + motivation + ref_context（parent + siblings） | 5 维分析写入 `DataElement.analysis` |
| 宏观 | `summarizer` ⭐ | 每次 sample parent 时懒加载 | motivation + analysis + cognition | experience 字段给 planner |

**summarizer 的核心价值**（`database/prompt/summerizer.py`）：

输出 5 维深度综合：
1. Performance Pattern Extraction（性能模式提取）
2. Theoretical Validation Assessment（理论验证）
3. Root Cause Diagnosis（根因诊断）
4. Research Integration Analysis（结合论文）
5. Innovation Opportunity Identification（创新机会）

**关键**：summarizer 不是"实验 X 拿了 Y 分"，而是**"下次应该做什么"**——给 planner 的 actionable guidance。

### 6.2 NAS 落地

**新增 agent**:
- `agents/summarizer.md`（宏观复盘）

**修改 agent**:
- `agents/collector.md` → 重命名 `agents/analyzer.md`（微观复盘）

#### 6.2.1 analyzer（升级 collector）

**输入**:
- 当前实验 result + motivation + code
- L1/lineage.json 中的 parent + siblings（ref_context）

**输出**（5 维，对齐论文 analyzer prompt）:
1. Motivation and Design Evaluation
2. Experimental Results Analysis with Ablation Study
3. Expectation vs Reality Comparison
4. Theoretical Explanation with Evidence
5. Synthesis and Insights

**额外职责**（T2 触发判定）:
```python
# analyzer 在 5 维分析后判定
should_t2 = (
    candidate.score > baseline.score * 1.02
    and candidate.rank <= 5
    and candidate.tier == "T1"
)
if should_t2:
    candidate.tier = "T2_pending"
    tier2_queue.enqueue(candidate)
```

#### 6.2.2 summarizer（新增）

**触发时机**: selector 选 parent 后立即调（懒加载 + 缓存）

**输入**:
- parent.motivation + parent.analysis + parent.cognition

**输出**: experience 字符串，写入 `L1/experience.md`

**缓存策略**:
- 同一 parent 不重复调（用 `summarizer_cache.json` 记录已完成）
- T2_failed 后强制重算（因为状态变了）

**反思模式**（连续 3 次 T2_failed 触发）:
- 输入：elite 桶 + 最近失败案例
- 输出：方向调整建议（"应放弃 X 方向，转向 Y"）

---

## 7. Project 级断点重续

### 7.1 当前 vs 升级

| 维度 | 当前（session 级） | 升级后（project 级） |
|------|-------------------|---------------------|
| 命令 | `--session-id <id>` | `--project-id <name>` + `--session-id <id>`（可选） |
| 复用范围 | 单 session | 同 project 所有 session 的 L1 |
| 隔离 | session 隔离 | project 隔离（多个 project 互不干扰） |
| candidates | per-session | per-project（跨 session 合并） |
| lineage | per-session | per-project（跨 session 重建） |

### 7.2 --project-id 逻辑

```bash
# 第一次跑（新 project）
python run_nas.py --project-id cifar_cnn --inputs '...'

# 第二次跑（同 project，新 session，但复用 L1 经验）
python run_nas.py --project-id cifar_cnn --inputs '...'

# Resume 具体某个 session（原有功能保留）
python run_nas.py --session-id 20260617_074329_microxcaling --inputs '...'

# 同 project 新 session，但跳过 SETUP（已缓存）
python run_nas.py --project-id cifar_cnn --skip-setup --inputs '...'
```

### 7.3 L1 重建机制

**首次创建 `--project-id`**:
1. 检查 `workflows/nas/memory/<project_id>/` 是否存在
2. 不存在 → 创建空结构 + 标记 `created_at`
3. 扫描 `runs/*_<project_id>/` 把已有 session 的 candidates 合并到 L1
4. 重建 lineage 树

**后续 `--project-id`**:
1. L1 已存在 → 直接读取
2. 创建新 session（时间戳）
3. SETUP 阶段尝试从 L1 复用（business_context、setup_contract 等）

### 7.4 L1 并发保护

- L1 写入用 atomic write（tmpfile + os.replace，复用 `sidecar_io.atomic_write_json`）
- 多个 session 同时写 L1 → 文件锁（`fcntl.flock`）
- candidates.json 用 append-only 模式 + 定期 compaction

---

## 8. Agent 清单（新增 / 修改 / 删除）

### 8.1 新增（5 个）

| # | Agent / 文件 | 职责 | 触发 |
|---|-------------|------|------|
| A1 | `agents/summarizer.md` | 宏观经验复盘 + 反思模式 | selector 选 parent 后；T2_failed 连续 3 次后 |
| A2 | `agents/tier2_runner.md` | T2 全训练 + 退化判定 | candidate 进 T2_pending |
| A3 | `helpers/cognition_io.py` | L0 recipe 库读写 + 关键词检索 | business_analyzer / optimizer_business |
| A4 | `helpers/project_memory.py` | L1 读写 + lineage 重建 + 并发保护 | 多处调用 |
| A5 | `helpers/candidate_selector.py` | 分桶采样（elite + diversity） | selector 调用 |

### 8.2 修改（5 个）

| # | Agent / 文件 | 改什么 |
|---|-------------|--------|
| M1 | `agents/business_analyzer.md` | 增加 L0 检索 + L1 复用步骤，输出 cognition_retrieved |
| M2 | `agents/optimizer_business.md` | 决策前读 L1/experience.md + L0 recipes |
| M3 | `agents/collector.md` → `agents/analyzer.md` | 升级为 5 维分析 + T2 触发判定 + 写 L1 |
| M4 | `agents/selector.md` | 分桶采样替换 fitness 公式 + 调 summarizer |
| M5 | `workflows/nas/run_nas.py` + `workflow.json` | 加 `--project-id` + schema 加 cognition/tier 字段 |

### 8.3 删除（2 个）

| # | Agent | 理由 |
|---|-------|------|
| D1 | `agents/tier_planner.md` | 合并进 analyzer 的 T2 触发判定 |
| D2 | `agents/tier_baseline_runner.md` | 被 `tier2_runner.md` 替代 |

### 8.4 workflow.json 改动概览

```diff
agents:
-  tier_planner
-  tier_baseline_runner
-  collector
+  analyzer          (rename from collector + upgrade)
+  summarizer        (new)
+  tier2_runner      (new)

selector:
-  score_formula: "fitness + 0.3 * exploration_bonus"
+  sampling: "elite_k=10, ref_k=4, rotation_rule=true"

candidates schema:
+  tier: "T1 | T2_passed | T2_failed | T2_pending"
+  t1_metric, t2_metric, parent_id
```

---

## 9. 实施路线图（4 阶段）

| Phase | 工作量 | 内容 | 验证标准 |
|-------|--------|------|---------|
| **P1: L0 + L1 基础** | 1-2 天 | A3 cognition_io + A4 project_memory + 选 1 个 domain 填 recipes + M1 business_analyzer | business_analyzer 能从 L0 检索到 recipe，写入 L1/cognition.md |
| **P2: 两层复盘** | 2-3 天 | A1 summarizer + M3 collector→analyzer 升级 | analyzer 输出 5 维分析，summarizer 写入 L1/experience.md |
| **P3: 两阶段 tier + 退化** | 2 天 | D1/D2 删除 + A2 tier2_runner + M4 selector 分桶采样 + T2→T1 退化逻辑 | T1 cycle 流畅，T2 触发正确，T2_failed 时正确退化 |
| **P4: Project 级续跑** | 1 天 | M5 run_nas.py + project_memory 聚合 + --project-id flag | 同 project 跑第 2 次能看到第 1 次经验 |

**最小可见路径**：P1 + P2 完成后即有"带 RAG + 双层复盘"的 NAS，可跑 cifar_cnn 验证比当前版本探索效率更高。

---

## 10. 风险与缓解

| # | 风险 | 影响 | 缓解 |
|---|------|------|------|
| 1 | L0 recipe 库初期覆盖不全 | business_analyzer 检索不到合适的 | 先做 1 个 domain（cv 或 wireless），验证有效再扩；同时保留 LLM 内置知识 fallback |
| 2 | summarizer 增加 LLM 成本 | 每 cycle 多 1-2 次 LLM 调用 | 懒加载 + 缓存（同 parent 不重复调）；T2_failed 后强制重算 |
| 3 | 跨 session lineage 重建慢 | --project-id 启动慢 | 只在首次创建时重建；后续增量更新 |
| 4 | T2 异步可能堆积 | T2 队列长导致反馈延迟 | 限制队列长度（top-3），超过则跳过新 T1 |
| 5 | T2 频繁失败导致 cycle 无进展 | 用户看不到效果 | 连续 3 次 T2_failed 触发 summarizer 反思；reporter 提示用户调整 target |
| 6 | L1 并发写冲突 | 多 session 同时写 candidates.json | atomic write + fcntl.flock；写入失败 fail loud |
| 7 | L1 文件膨胀 | candidates.json 越来越大 | 定期 compaction（保留 top-50 + 全部 lineage） |
| 8 | motivation 去重 false positive | 误判创新想法为重复 | similarity threshold 可调；高置信度才 block，低置信度仅 warn |

---

## 11. 不引入清单（明确）

| # | 不引入 | 理由 |
|---|--------|------|
| ❌ | MongoDB / Docker | 单机开发不需要；运维成本高；调试困难；CI 不友好 |
| ❌ | FAISS（初期） | L0 几十个 recipe 用关键词匹配就够；L1 dedup 用 hash |
| ❌ | OpenSearch | 同上 |
| ❌ | Model Judger agent | fitness 已含性能，Complexity 维度优先级低，可后期加 |
| ❌ | 在线 arxiv search | 不稳定；速度慢；初期用预处理 recipe 库 |

---

## 12. 验收标准

P1-P4 全部完成后，以下场景必须 work：

1. **跨 session 复用**：跑 `cifar_cnn` 第 1 次 → 第 2 次启动时 SETUP 跳过，business_analyzer 读到第 1 次的 cognition.md
2. **Cognition 检索**：business_analyzer 输出包含 `cognition_retrieved` 字段，列出 ≥1 个 L0 recipe
3. **双层复盘**：analyzer 输出 5 维分析；summarizer 在 L1/experience.md 留下 ≥1 条 actionable 指导
4. **T1/T2 流转**：T1 candidate 分数过阈值 → 进 T2 队列 → T2 完成 → tier 更新为 `T2_passed` 或 `T2_failed`
5. **T2 退化**：T2 metric < target → candidate 标记 `T2_failed`，cycle 继续，下次 selector 不选它做 parent
6. **反思触发**：连续 3 次 T2_failed → summarizer 反思模式被调用，experience.md 出现"方向调整建议"
7. **Project 隔离**：跑 `cifar_cnn` 和 `wireless_ofdm` 两个 project，L1 数据完全隔离
8. **断点重续**：`--project-id cifar_cnn --skip-setup` 跳过 SETUP；`--session-id <id>` 仍能 resume 具体会话

---

## 13. 相关文档

- 上游 plan: [2026-06-18-nas-workflow-simplify.md](./2026-06-18-nas-workflow-simplify.md)
- 论文: [ASI-Arch arxiv 2507.18074](https://arxiv.org/abs/2507.18074)
- 参考代码: `references/asi-arch/`（gitignored）
- 框架契约: [CLAUDE.md](../../CLAUDE.md)
