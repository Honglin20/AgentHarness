# simple-nas Multi-Direction Mutator 改造计划（路径 C）

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** simple-nas 从单 mutator 串行改为多方向专属 mutator 并行（structural / hyperparam / lr / compute）；setup 阶段用户 multi_select 选方向，未选方向的 mutator 节点自跳过；每个 mutator 内部仍可 sub_agent 并发验证。

**Architecture:** 路径 C（mutator 自跳过）—— DAG 静态包含全部 4 个方向 mutator 节点；selector 输出 `active_directions` 集合；每个 mutator 头部 guard 步骤检查自身方向是否在集合内，不在则立即返回 `skipped` result；analyzer fan-in 后串行聚合 active 结果并更新 tree.json。LangGraph 原生 fan-out / barrier-join 实现 selector→mutators→analyzer。

**Tech Stack:** Python 3.11+, LangGraph（静态 fan-out + barrier join）, pydantic_ai（sub_agent 并发）

**Reference:** 路径 C 讨论见对话；现有 simple-nas 实现见 `workflows/simple-nas/`

---

## Key Design Decisions

1. **路径 C，不动核心 routing** —— 不扩展 `harness/engine/routing.py` / `builder.py`（不引入 multi-target conditional edge）；不引入双阶段编译。所有方向专属 mutator 静态存在于 DAG，未激活的通过节点内 guard 自跳过。鲁棒 + OCP + surgical。

2. **每轮激活策略 = (a) 全部用户选方向都跑** —— selector 不做"挑一个"的逻辑，每轮把 `active_directions` 原样透传，所有激活方向的 mutator 都干活。
   - 理由：最贴合用户"多 mutator 并行"原意；selector 逻辑最简单（无策略判断）；收敛快。
   - 代价：每轮 K 倍训练成本（K = 用户选的方向数）。simple-nas 是 V1，验证用；V2 再加"按潜力加权""轮转"。
   - 用户后期希望降成本，再迭代。

3. **selector 不再分配单方向** —— 现有 selector "为每轮选一个 parent + 分配一个 direction" 的逻辑废弃。新职责：选 parent（仍贪心 best promising）+ 声明 `active_directions`（从 setup.json 直读，每轮不变）。

4. **方向 → mutator 映射是配置而非硬编码** —— workflow.json 顶层声明 `direction_to_agent: {"structural": "mutator_structural", ...}`，selector/analyzer 都从这张表读，不在 MD 里枚举。

5. **tree.json 并发写规避** —— 4 个 mutator 并行写 tree.json 会竞争。**解决：mutator 只写自己的 variant 目录**（`variants/<vid>/`），**不直接改 tree.json**；analyzer 在 fan-in 后串行更新 tree.json（analyzer 是单节点，无并发）。

6. **保留 `directions` 字段做后向兼容** —— setup.json 现有 `directions` 字段保留（全部 4 个，作为可选枚举），新增 `active_directions`（用户 multi_select 选的子集）。

---

## Risks & Mitigations

| 风险 | 影响 | 缓解 |
|---|---|---|
| LangGraph fan-in 等待全部 mutator 完成 | analyzer 必须等所有激活 mutator 完成 + 所有 skip mutator 立即返回 | 验收阶段实测：skip mutator 1s 内返回；active mutator 完成才进 analyzer |
| mutator 并发读 selection.json | 4 个 mutator 同时读同一文件 | 只读无副作用，自然安全 |
| analyzer fan-in 输入 shape | analyzer 现期望单 mutator result，要改成 4 路 dict | result_type_schema 显式声明，schema 校验在编译期拦 |
| 用户在 cycle 中途改变方向 | setup.json 已写定，selector 每轮读同一份 | V1 不支持；写入 setup MD 严禁条款 |
| mutator MD 长度膨胀（4 个 ~150 行） | 维护成本 | 共用 guard 步骤模板；主体按方向裁剪现有 mutator.md |
| 现有 helpers（collect_status / candidate_pool）按 vid 隔离 | 多 mutator 并发用同一 helper 是否冲突 | 已按 vid 隔离，理论零冲突；Task 6 静态检查确认 |

---

## Task 1: workflow.json DAG 重构

**Files:**
- Modify: `workflows/simple-nas/workflow.json`

**Steps:**
1. 删除现有单 mutator 节点
2. 新增 4 个 mutator 节点：
   - `mutator_structural` (`after: ["selector"]`)
   - `mutator_hyperparam` (`after: ["selector"]`)
   - `mutator_lr` (`after: ["selector"]`)
   - `mutator_compute` (`after: ["selector"]`)
3. analyzer 改为 `after: ["mutator_structural", "mutator_hyperparam", "mutator_lr", "mutator_compute"]`
4. 每个 mutator 的 `result_type_schema` 加 `skipped: bool`（required）
5. analyzer 的 `result_type_schema` 加 `evaluated_directions: array[str]`（required）
6. workflow 顶层加 `direction_to_agent` 映射表

**Verification（验收标准）:**
- [ ] `python -c "from harness.core.workflow import Workflow; Workflow.load('simple-nas').compile()"` 编译成功无异常
- [ ] workflow.json `dag.nodes` 含 9 个节点（setup / baseline / selector / 4 mutator / analyzer / reporter）
- [ ] workflow.json `dag.edges` 含 selector→每个 mutator（4 条）+ 每个 mutator→analyzer（4 条）
- [ ] 每个 mutator `result_type_schema` 含 `skipped` 必填字段（`required` 列表含 `"skipped"`）
- [ ] analyzer `result_type_schema` 含 `evaluated_directions` 必填字段
- [ ] workflow.json 顶层 `direction_to_agent` 含 4 个方向 → 4 个 agent 名映射

---

## Task 2: selector MD 改造

**Files:**
- Modify: `workflows/simple-nas/agents/selector.md`
- Modify: `workflows/simple-nas/workflow.json`（selector 节点 `result_type_schema`）

**Steps:**
1. 删除 Step 2 "分配方向（V1 简单轮转）" —— 废弃单方向分配
2. 新增 Step 2 "声明 active_directions" —— 从 setup.json 直读 `active_directions`，写入 selection.json
3. selection.json schema 调整：
   ```json
   {
     "iter_num": 3,
     "parent_id": "v2",
     "parent": { "model_file": "...", "metrics": {...}, "direction": "structural" },
     "active_directions": ["structural", "hyperparam"],
     "info_paths": { "baseline_understanding": "...", "experience": "...", "setup": "...", "parent_model": "..." }
   }
   ```
   （删除原 `direction` / `subgoal` 字段；subgoal 改由各 mutator 自己根据 direction + experience 判断）
4. SelectorResult schema：删除 `direction` 字段，加 `active_directions: array[str]`（required）

**Verification:**
- [ ] selector.md 明确"不分配单方向，只声明激活集合"
- [ ] SelectorResult schema `direction` 字段移除，`active_directions: array[str]` 加入 required
- [ ] 严禁条款含"分配单方向"
- [ ] 单测：mock setup.json 含 `active_directions=["structural","hyperparam"]`，跑 selector，selection.json 含同字段（值透传，无修改）

---

## Task 3: 4 个方向专属 mutator MD

**Files:**
- Create: `workflows/simple-nas/agents/mutator_structural.md`
- Create: `workflows/simple-nas/agents/mutator_hyperparam.md`
- Create: `workflows/simple-nas/agents/mutator_lr.md`
- Create: `workflows/simple-nas/agents/mutator_compute.md`
- Delete: `workflows/simple-nas/agents/mutator.md`（原单 mutator）

**每个 MD 结构：**

1. **Header**: `name: mutator_<direction>` + tools（bash/grep/glob/read_text_file/sub_agent）
2. **Step 0 (NEW) — guard**：读 selection.json 的 `active_directions`，自身 direction 不在 → 立即返回 skipped result，不创建 variant 目录、不调 helper、不跑训练：
   ```json
   {
     "summary": "skipped: direction 'lr' not in active_directions=['structural','hyperparam']",
     "vid": null,
     "iter_num": <from selection.json>,
     "parent_id": <from selection.json>,
     "direction": "<self>",
     "status_path": null,
     "metrics": {},
     "latency_ms": null,
     "ok": false,
     "skipped": true,
     "variant_dir": null
   }
   ```
3. **Step 1+ — 方向专属逻辑**（基于现有 mutator.md 派生 + 裁剪）：
   - **structural**: 替换核心算子/组件（MHA→线性 attention、新 block、容量重分配），禁止惰性压缩
   - **hyperparam**: 不动 model.py（复制 parent），改 batch_size / optimizer_type / scheduler / epochs
   - **lr**: 专注 lr / lr_scheduler / warmup_steps / weight_decay
   - **compute**: 修改计算逻辑（loss in forward / 数据增强 / mixup / label smoothing）
4. **每个 mutator 允许 sub_agent 并发验证** —— MD 里写明：可一次 issue K 个 sub_agent，每个 sub_agent 跑同一方向的不同 sub-strategy（如 structural 内部并发试 GELU vs SwiGLU vs 残差连接），但所有 sub_agent 都属于本方向
5. **严禁条款保留**：不污染 working_dir / 不假装成功 / 时延不退化 / 不直接改 tree.json

**Verification:**
- [ ] 4 个 MD 都存在，`name` frontmatter 分别为 `mutator_structural` / `mutator_hyperparam` / `mutator_lr` / `mutator_compute`
- [ ] 每个 MD 含 Step 0 guard，明确 skipped 返回 shape（含 `skipped: true`）
- [ ] 每个 MD 的方向职责清晰，方向间职责互斥（structural/hyperparam/lr/compute 不重叠）
- [ ] 每个 MD 严禁条款含"直接改 tree.json"
- [ ] 每个 MD 写明允许 sub_agent 并发（同方向多 strategy）
- [ ] 原 `workflows/simple-nas/agents/mutator.md` 已删除
- [ ] workflow.json 4 个 mutator 节点的 `name` 与文件对应

---

## Task 4: analyzer MD 改造（fan-in + 过滤 skipped）

**Files:**
- Modify: `workflows/simple-nas/agents/analyzer.md`
- Modify: `workflows/simple-nas/workflow.json`（analyzer 节点 `result_type_schema`）

**Steps:**
1. 输入从单 `state.outputs.mutator` 改为 4 个 `state.outputs.mutator_<direction>`（structural / hyperparam / lr / compute）
2. Step 0 过滤 skipped：丢弃 `skipped=true` 的结果（不参与评估、不进 tree）
3. 对剩余 active 结果逐一评估（promising / target_met / over_budget），**串行**更新 tree.json（fan-in 后单节点，无并发）
4. 决策逻辑：
   - 任一 active 方向 `target_met=true` → decision=pass（路由 reporter）
   - 全部 active 方向 `over_budget=true` → decision=pass（路由 reporter，未达标收尾）
   - 否则 → decision=fail（路由 selector，cycle 继续）
5. AnalyzerResult schema 加 `evaluated_directions: array[str]`（required，记录本轮实际评估的方向）

**Verification:**
- [ ] analyzer.md 明确输入是 4 个 mutator 的 outputs（不是单个 mutator）
- [ ] Step 0 含 skipped 过滤逻辑（skipped=true 不进评估）
- [ ] tree.json 更新逻辑保持串行（MD 里无 asyncio.Lock / 并发原语）
- [ ] AnalyzerResult schema 含 `evaluated_directions`（required）
- [ ] 决策逻辑三项（target_met / over_budget / 否则）写明
- [ ] 单测：mock 4 个 mutator outputs（2 active + 2 skipped），analyzer 正确聚合 + evaluated_directions 只含 active 2 个

---

## Task 5: setup MD 改造（ask_user 问方向）

**Files:**
- Modify: `workflows/simple-nas/agents/setup.md`

**Steps:**
1. Step 2 加 ask_user `multi_select=true`：「想要哪些变异方向？」
   - options:
     - `{label: "结构变异 (替换核心算子/block)", value: "structural"}`
     - `{label: "模型超参 (batch/optimizer/scheduler)", value: "hyperparam"}`
     - `{label: "学习率 (lr/scheduler/warmup)", value: "lr"}`
     - `{label: "计算逻辑 (loss/数据增强)", value: "compute"}`
   - `allow_custom_input: false`（方向是固定枚举，不允许自定义）
   - `header: "变异方向"`
2. 把用户选的写入 setup.json 的 `active_directions`
3. 保留 `directions` 字段（全部 4 个，作为可选枚举）
4. 严禁条款加："不允许在 setup 阶段不问用户就拍板方向"

**Verification:**
- [ ] setup.md Step 2 含 ask_user，参数 `multi_select=true`、`allow_custom_input=false`
- [ ] options 是 4 个方向，label 中文 + value 英文
- [ ] setup.json schema 含 `active_directions`
- [ ] 严禁条款含"不问用户就拍板方向"
- [ ] 端到端：跑 setup agent（mock UI），用户在 UI multi_select 选 2 个方向，setup.json 的 `active_directions` 正确写入

---

## Task 6: helpers 静态检查（并发安全）

**Files:**
- Read: `workflows/simple-nas/helpers/candidate_pool.py`、`history.py`、`collect_status.py`
- Modify: 仅在发现并发问题时改（预期不需要）

**Steps:**
1. 静态分析每个 mutator MD 引用的 helpers，确认输出都落在 `$VD/` 自己的目录
2. 确认 analyzer 是唯一更新 `tree.json` / `experience.md` 的节点
3. grep 所有 mutator MD，确认无 "tree.json" 写操作（只允许读）
4. 检查 `running.jsonl`（C-RUN 记录）—— 应该是 append-only，多 mutator 并发 append 是否原子（POSIX 保证单行 write ≤ PIPE_BUF 时原子；helper 用 `with open(..., 'a')` 单行 write 应该 OK）

**Verification:**
- [ ] 4 个 mutator 的 MD 都明确"只写 $VD/ 目录，不直接改 tree.json"
- [ ] analyzer MD 明确"tree.json 更新在 fan-in 后串行"
- [ ] grep `\btree\.json\b` in mutator MDs：只允许出现 "读 tree.json" 上下文，无 write/open('w')/open('a') 上下文
- [ ] running.jsonl append 路径检查通过（或加显式 file lock）

---

## Task 7: 端到端验证

**Steps:**
1. 跑 simple-nas（`projects/mnist`），UI 模式
2. setup 阶段：用户 multi_select 选 2 个方向（如 structural + hyperparam）
3. 观察全流程：
   - ask_user 不再循环（bug 已修，commit 9288dc6）
   - baseline 跑通，写 tree.json v0
   - selector 输出 `active_directions = ["structural", "hyperparam"]`
   - 4 个 mutator 中：`mutator_structural` + `mutator_hyperparam` 真正干活（生成 variant + 跑训练），`mutator_lr` + `mutator_compute` 立即 skipped 返回
   - analyzer 收到 4 个结果，过滤 2 个 skipped，评估 2 个 active，更新 tree.json
   - cycle 继续（analyzer on_fail → selector）或结束（on_pass → reporter）
4. 检查 `runs/<wf_id>+events.json`：
   - 4 个 mutator 都有 `node.started` / `node.completed`
   - 2 个 skipped 的 `duration_ms < 5000`
   - 2 个 active 的 `duration_ms` = 训练耗时（>> 5s）
5. 检查 `runs/<wf_id>+iters+*.json`：
   - 4 个 mutator 的 iter sidecar 都生成
   - skipped mutator 的 result 含 `skipped: true`
6. 跑 `make lint-runs`（runs 持久化契约，CLAUDE.md 要求）

**Verification（端到端验收）:**
- [ ] workflow 跑到 reporter（无 hang / 无 crash）
- [ ] ask_user 在 setup 阶段只问 1 次（不重复）—— 验证 commit 9288dc6 在真实场景生效
- [ ] 用户未选方向的 mutator 节点 status=completed, result.skipped=true, duration_ms<5000
- [ ] 用户选的方向都有真实 variant 产物（`$VD/model.py` + `$VD/metrics.json` + `$VD/status.json`）
- [ ] tree.json 正确累积所有 active 方向的 variant（无并发写污染）
- [ ] reporter 输出 outcome 包含所有 active 方向的最终指标
- [ ] `make lint-runs` 退出码 0（无 schema 违规）

---

## 执行顺序

严格顺序：Task 1 → 2 → 3 → 4 → 5 → 6 → 7

每个 Task 完成后**先验收（勾选所有 Verification checkbox）再进下一个**。验收失败的 Task 不允许进下一个。

总工作量预估：~1 天（写代码 6-7h + 端到端验证 1.5h + 计划外调试 1-2h buffer）。

---

## Out of Scope（V2 再做）

- ❌ selector "按潜力加权"分配方向 —— V1 全部激活
- ❌ selector "轮转" —— V1 全部激活
- ❌ 用户 cycle 中途改方向 —— V1 setup 阶段固定
- ❌ multi-target conditional edge（路径 B）—— V1 用路径 C
- ❌ 双阶段编译（路径 A）—— V1 用路径 C
- ❌ 方向动态新增（用户自定义第 5 个方向）—— V1 固定 4 个
