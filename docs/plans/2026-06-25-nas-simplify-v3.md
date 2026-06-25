# NAS Workflow 简化 v3 — 2026-06-25

状态：设计已确认，待实施。
关联：`docs/guides/workflow-development-guide.md`（设计哲学）、`docs/plans/2026-06-18-nas-workflow-simplify.md`（前次简化）。

---

## 一、背景与目标

当前 NAS workflow（cognition-arch 2026-06-19）15 个 agent，结构过重：3 个独立
optimizer + tier2 两阶段 + 6 个 setup 子 agent。实测问题：

1. 长任务无法可靠完成（靠 LLM 记得轮询，经常丢）。
2. 优化塌缩成"只压层删组件"，不结合基线原理和业务背景做创新。
3. 硬编码接口（强制 `--config`、fitness 加权），换个项目就跑不了。

**本次目标**：简化到 6 个 agent，端到端打通；监控用 cron/后台轮询摘取训练输出；
评判以用户目标为准（不硬编码 fitness）；产物进 workflow 目录，支持断点续传。

---

## 二、设计原则（已固化至 workflow-development-guide.md）

1. **必要元素为导向，非硬编码**。不假设统一编码规范；让 agent 查阅项目、向用户确认
   必要元素。
2. **harness 只做通用原子能力**。本次 harness 唯一改动：后台任务 ack 暴露 PID（2 行）。
   不造 `wait_for_tasks` / `list_background_tasks`。
3. **上游 agent 把必要信息递给下游**，下游少读非必要文件。
4. **长任务监控靠组合现有原语**：后台拉起 + agent 写的轮询脚本（定时摘取训练输出）
  + PID 记录文件。
5. **评判以用户目标为准，不硬编码 fitness**。
6. **合并职责以保上下文**：变异 agent 自己拉起训练并监控，不设独立 runner。
7. **产物进 workflow 目录**（`<workflow_dir>/runs/<session_id>/`），不污染用户 working dir。

---

## 三、长任务监控机制（核心设计）

### 目标行为

agent 发起训练后，定时摘取训练脚本**被重定向后的输出**（`train.log`）的最新部分，
判断训练是否正常运行；训练真正完成时拿到结果。

### 落地机制（组合现有原语，不造专用工具）

agent 自己写一个轮询脚本（针对当前任务裁剪，灵活），用后台循环/cron 定时跑：

```
# agent 发起训练时（mutator 内）：
1. bash run_in_background=true "python train.py > variants/<vid>/train.log 2>&1 &"
   → 拿到后台 task_id + PID（harness 改动后可见）
2. 记录 {vid, pid, start, cmd} 到 running.md（单行 append，原子安全）
3. 写 monitor_<vid>.sh（agent 现场裁剪，不硬编码）：
     while PID 还活着 (kill -0 $PID) and 未超预算:
         tail -n 50 variants/<vid>/train.log   # 摘取最新输出
         判断是否正常（agent 在脚本里写判断逻辑，如含 loss 下降/OOM/error）
         追加进展到 progress.md                  # 定期汇报
         sleep <interval>
     训练完成（metrics 文件出现）→ 写 status.json {ok, metrics_path, exit_code}
     从 running.md 移除该 PID
   bash run_in_background=true 启动这个 monitor 脚本
4. agent 主体轮询：直到 status.json 出现（完成哨兵）或超预算
```

### 关键约定

- **完成信号 = `status.json` 存在**（哨兵），不是进程退出。堵死"进程 exit 0 但没产出
  metrics"的假成功。
- **摘取判断在脚本里**：agent 现场写"什么算正常"（loss 下降、无 OOM、step 推进等），
  不硬编码。不同项目、不同训练，判断逻辑不同。
- **agent 不常驻**：轮询是后台脚本做的事，agent 主体只发起 + 最后收 status。避免
  LLM 常驻烧 token。
- **调度器不绑定**：用 `while ... sleep` 后台循环（macOS/Linux 通用），cron 作为可选。
  不依赖系统 cron 守护进程（sandbox 下未必可靠）。
- **断点续传（run 级）**：重启时读 `running.md`，PID 还活着 → 继续监控；已写
  status.json → 直接收结果；都不在 → 视为未发起，重跑。

### 为什么不造 wait_for_tasks / list_background_tasks

- `wait_for_tasks`（阻塞等待）：定期摘取 + 汇报对用户更有价值，比静默阻塞强。
- `list_background_tasks`：agent 把任务记进 `running.md`，读文件即列表。

对照 Claude Code 的同类缺陷（issue #61568 后台任务无限运行无可见性、#7069 缺原生
任务管理）——本方案用 `running.md` + `status.json` 哨兵 + PID 解决，不引入专用工具。

---

## 四、Agent 编排（6 个）

```
setup → baseline → ┌─ selector → mutator → analyzer ─┐ → reporter
                   └─────────────────────────────────┘
```

| Agent | 职责 | 读 | 写 |
|---|---|---|---|
| setup | 查阅项目，向用户确认必要元素 | 用户项目 | setup.json |
| baseline | 跑原始训练；固化基线 + 生成架构理解 | 入口, setup.json | baseline.json, baseline_understanding.md |
| selector | ToT 选基线 + 分配方向 | tree.json, experience.md | selection.json |
| mutator | 生成变异 + 直接拉起训练 + 监控到完成 | selection, baseline_understanding, experience | variants/<vid>/ |
| analyzer | 按用户目标判断潜力 + 更新树 + 提炼 insight + 判路由 | variants, tree, setup(目标) | tree.json, experience.md |
| reporter | 达标/预算耗尽时汇总 | tree, baseline | report.md |

### 删除（15 → 6）

project_analyzer / adapter_generator / smoke_runner / metric_align / setup_align /
business_analyzer / summarizer / tier2_runner / 3 个独立 optimizer。

### 各 agent 要点

**setup** — 必要元素（非统一接口）：训练入口文件 + 命令行约定（怎么传模型文件/参数）
、基线模型文件、初始超参、每个指标的目标约束（指标名+方向+阈值）、时延目标 + dummy
input、变异约定（新模型文件命名/位置/入口指向）。断点：setup.json 存在则跳过。

**baseline** — 跑原始训练一次，固化三样：
- baseline.json（基线各指标 + 时延，后续对比根）。
- baseline_understanding.md（架构理解：容量瓶颈/计算热点/针对任务的 SOTA 机会）—
  **治惰性变异的知识地基**，所有 mutator 永久引用。
- 默认训练参数快照（参照基准）。
baseline 是搜索树根节点 v0。

**selector** — ToT 策略：
- 开发：从 analyzer 标记"有潜力"的架构深挖。
- 探索（ε 概率）：回溯到高 fitness 祖先，换方向分支。
- 轮转：连续 3 轮同方向强制换。
- 降温：某分支连续 N 次退步标 dead，回到最佳祖先。
- 去重：变异指纹（改了什么）不重复分配。
递给 mutator 的必要信息：parent 模型文件路径 + parent 指标 + 方向 +
baseline_understanding 相关要点 + 该方向 experience + 本轮子目标。

**mutator** — 方向是指导原则（非硬编码约束）：
- **structural：根本结构改变**（如 MHA→线性 attention、替换为 SOTA 组件），非简单压
  层调宽。
- business：在**遵循原逻辑**上修改方法。
- hyperparam：训练配方。
行为约束（写在 prompt）：禁惰性压缩（减层/删组件），除非目标本身就是压缩；
**时延不必一次达标，但每轮须有时延优化**。
变异后**直接拉起训练 + 监控到完成**（不交接 runner，保上下文）。监控用第三节机制。

**analyzer** — **不合成 fitness 公式**。按用户给的每个指标约束判断：
- 哪些变体"有潜力"（指标改善/逼近目标/时延有优化）——analyzer 自行按目标权衡。
- 更新 tree.json（标 promising/dead、fitness_delta_vs_parent、深度）。
- 写 experience.md（什么有效/什么没用/下一步提示）。
- 判路由：达标 → reporter；超预算 → reporter（优雅收尾）；否则 → selector。
  下一轮基线从标记"有潜力"的架构中选（结合方向多样性 + 树深度）。
- **不信自报**：用文件证据（metrics 文件存在 + 含目标指标）校验。

**reporter** — 达标/预算耗尽，从 tree.json 选最优，对比基线出报告。

---

## 五、文件管理

```
<workflow_dir>/runs/<session_id>/
  setup.json                # 必要元素
  baseline.json
  baseline_understanding.md
  tree.json                 # 候选树（id/parent_id/direction/指标/潜力标记/深度/model_file）
  experience.md             # 跨方向经验
  running.md                # 运行中 PID 清单（mutator 写，可随时 kill）
  progress.md               # 轮询脚本定期汇报（追加）
  SUMMARY.md                # 所有实验汇总（每轮一行）
  variants/
    v1/
      model.py              # 变异模型文件
      train.log             # 训练输出（重定向落点）
      status.json           # 完成哨兵 {ok, metrics_path, exit_code, wallclock}
      metrics.json
      monitor.sh            # 轮询脚本（agent 现场写）
      ANALYSIS.md           # 该实验细粒度分析记录
  report.md
```

分层级：SUMMARY.md（纵览）+ 每个 variant 的 ANALYSIS.md（细粒度）。

---

## 六、Harness 改动（极小）

### 1. 后台任务 ack 暴露 PID

文件：`harness/tools/bash.py`，函数 `spawn_background`。
返回串加一行 `pid: <proc.pid>`。

```python
# 现在
return (
    f"[background task started]\n"
    f"task_id: {task_id}\n"
    ...
)
# 改为
return (
    f"[background task started]\n"
    f"task_id: {task_id}\n"
    f"pid: {proc.pid}\n"
    ...
)
```

2 行改动，完全通用。任何用 `run_in_background` 的 agent 都能 kill 进程。

### 2. init_session.py 不污染 working dir

文件：`workflows/nas/helpers/init_session.py`。
删除写入 `<working_dir>/.nas_session_pointer`（第 69-79 行）。改为只在 workflow 内
部 `runs/<id>/.session_meta.json` 存 pointer。session_id 仍可获取（已注入 inputs/env）。

**无其他 harness 改动**。不造专用工具。

---

## 七、实施顺序（增量打通）

### 阶段 0：harness 改动（前置）
- bash.py 暴露 PID。
- init_session.py 去掉 working dir pointer。

### 阶段 1：端到端最小打通（单轮单变异）
- 6 个 agent.md 写 prompt。
- workflow.json：6 节点 + 路由。
- 删除 15 个旧 agent。
- 跑通：setup → baseline → selector → mutator(1 变异) → analyzer → reporter。
- **验收**：见第八节验收清单 V1。

### 阶段 2：多轮 + ToT
- selector/analyzer 实现 ToT（开发/探索/回溯/降温/去重）。
- max_iterations 调到支持多轮（注意 LangGraph recursion_limit 语义，NAS 需要几千）。
- **验收**：V2。

### 阶段 3：3 方向并行 + 健壮性
- 一轮内 3 方向（structural/business/hyperparam）并发变异。
- tree.json 并发写加 flock。
- 全局预算守卫（selector/analyzer 入口 check）。
- **验收**：V3。

---

## 八、验收清单

### V1：端到端最小打通

**功能验收**（每一项必须实测通过，非"应该行"）：

- [ ] **V1.1 setup**：对一个真实测试项目（如 `projects/mnist`），setup agent 能正
      确识别入口文件、模型文件、初始超参，并向用户确认目标。产物 setup.json 内容
      完整且非硬编码（即换 cifar 项目也能跑）。
- [ ] **V1.2 baseline**：跑完原始训练，baseline.json 含基线指标 + 时延；
      baseline_understanding.md 非空（含架构分析，不是模板套话）。
- [ ] **V1.3 断点续传-产物级**：用 `--session-id` 重启，已完成的 agent（如 setup）
      检测到产物存在则跳过，不重跑。
- [ ] **V1.4 后台 PID 可见**：mutator 发起训练后，从 bash ack 能读到 `pid:`，且
      `kill <pid>` 能实际停止训练（实测）。
- [ ] **V1.5 完成哨兵生效**：训练正常完成 → status.json 生成且 ok=true；
      训练崩溃（手动 kill 训练进程模拟）→ status.json 生成且 ok=false（或监控脚本
      检测到 PID 消失并写失败状态），**不存在"进程死但无 status.json"的悬空状态**。
- [ ] **V1.6 假成功被拦**：构造"训练 exit 0 但没写 metrics.json"的场景（改训练脚本
      提前 return），analyzer 不标该变体为有潜力（用文件证据校验生效）。
- [ ] **V1.7 mutator 监控摘取**：progress.md 有定时追加的训练进展摘录（含最新 loss/
      step），证明轮询摘取机制工作。
- [ ] **V1.8 analyzer 按目标判断**：用户给了明确指标约束时，analyzer 据此判断潜力，
      不出现任何加权 fitness 计算（grep 确认无 fitness.py / 无 fitness 字段合成）。
- [ ] **V1.9 reporter**：产 report.md，含最优变体对比基线的指标 + 时延。
- [ ] **V1.10 产物不污染 working dir**：测试项目目录下不出现 .nas_session_pointer 或
      其他 workflow 产物（git status 干净，除项目自身文件）。

**鲁棒性验收**：

- [ ] **V1.11 运行级恢复**：mutator 监控中途整 workflow 崩溃，重启后读 running.md，
      若训练 PID 仍在跑 → 继续等；已完成 → 直接收；status.json 缺失且 PID 不在 →
      重跑该变异（不重跑已完成的 baseline）。

### V2：多轮 ToT

- [ ] **V2.1 多轮循环**：连续 ≥3 轮 cycle，tree.json 累积 ≥3 个变体，每轮 analyzer
      正确更新树。
- [ ] **V2.2 开发**：连续轮次沿有潜力方向深挖（parent 链连续）。
- [ ] **V2.3 探索/回溯**：能观察到至少一次"换方向"或"回溯到祖先"。
- [ ] **V2.4 降温**：构造连续退步场景，analyzer 标 dead，selector 不再选该分支。
- [ ] **V2.5 去重**：变异指纹机制生效，同形状变异不重复分配。
- [ ] **V2.6 预算守卫**：设短预算（如 5 分钟），超预算优雅路由 reporter，不无限跑。

### V3：3 方向并行 + 健壮性

- [ ] **V3.1 三方向并发**：一轮内 structural/business/hyperparam 三变体并发发起。
- [ ] **V3.2 tree.json 并发安全**：3 变体并发写 tree.json，flock 生效，无数据丢失
     （实测多次，无 JSON 损坏）。
- [ ] **V3.3 structural 非惰性**：structural 方向产物确实做了根本结构改变（如替换
      attention 机制），非简单压层。抽查 ≥1 轮。
- [ ] **V3.4 时延优化**：每轮至少一个变体时延优于 parent（不必达标，但有改善）。
- [ ] **V3.5 max_iterations 足够**：NAS 跑 ≥10 轮不撞 LangGraph recursion_limit
      （需把 max_iterations 调到几千；实测一轮 = ~4 节点执行，10 轮 = 40，留足余量）。

---

## 九、风险与对策

| 风险 | 对策 |
|---|---|
| LLM 不写监控脚本 / 写错 | 验收 V1.5/V1.7 卡住；prompt 里给明确模板 + 例子 |
| LLM 仍惰性压缩 | 验收 V3.3 抽查；baseline_understanding.md + prompt 禁令 |
| cron/后台循环在 sandbox 不跑 | 机制不绑调度器，用 `while sleep` 循环（通用） |
| tree.json 并发损坏 | V3.2 flock 验收 |
| recursion_limit 撞顶 | V3.5 把 max_iterations 调够，run_nas.py 已有 override 入口 |
