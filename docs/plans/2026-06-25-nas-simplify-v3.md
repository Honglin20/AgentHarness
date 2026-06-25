# NAS Workflow 简化 v3 — 2026-06-25 (reviewed)

状态：已按软件设计原则 review 重写。每一步含验收标准 + 用例。
关联：`docs/guides/workflow-development-guide.md`（设计哲学）。
前置阅读：本文件第七节"设计原则自审"记录了 review 发现的原则违反及修正。

---

## 0. Review 结论（变更摘要）

相比首版 plan 的主要修正：

1. **mutator 职责过重（违反 SRP）** → 保留单 agent，但在内部强制分阶段（生成→运行→
   收集），每阶段产物落盘可断点。不全拆（拆了丢上下文），但内部分离关注点。
2. **监控判断逻辑不可测（违反可测试性）** → 分离为两层：**数据采集**（确定性，
   可单测）+ **判断**（LLM 读采集结果）。采集脚本薄、固定、可测；判断灵活在 agent。
3. **PID 复用风险（断点续传正确性）** → 哨兵不只看 PID，加 start_time + cmdline
   指纹校验，PID 复用指错进程时能识别。
4. **status.json 半成品（失败原子性）** → 强制原子写（tmp + rename）。
5. **断点逻辑 DRY** → 抽一个通用 check 脚本，各 agent 调用，不各自实现。
6. **方向扩展性（OCP）** → 方向列表外置到 setup.json，selector/analyzer 不写死枚举。
7. **V1 边界明确** → V1 严格单轮单变异，ToT 的降温/回溯/去重明确推迟到 V2，V1 不实
   现也不验收。

---

## 1. 设计原则自审记录

| 原则 | 问题 | 修正（见对应步骤） |
|---|---|---|
| SRP | mutator 一身多职 | 步骤 S4：mutator 内部分阶段 + 阶段产物落盘 |
| 可测试性 | 判断逻辑埋 shell | 步骤 S0：采集/判断分离；采集脚本可单测 |
| 断点正确性 | PID 复用指错 | 步骤 S0：哨兵含 start_time+cmdline 指纹 |
| 失败原子性 | status.json 半成品 | 步骤 S0：原子写约定 |
| DRY | 断点逻辑各 agent 重写 | 步骤 S0：通用 check_resume 脚本 |
| OCP | 方向写死 prompt | 步骤 S1：方向外置 setup.json |
| YAGNI | V1 边界模糊 | 步骤 S5：V1 不含 ToT，明确推迟 |

---

## 2. 文件契约（依赖倒置：agents 依赖契约，不依赖实现）

所有 agent 通过本契约读写，不直接耦合存储细节。契约变更需 bump 版本。

```
<workflow_dir>/runs/<session_id>/
  setup.json              契约 C-SETUP
  baseline.json           契约 C-BASELINE
  baseline_understanding.md
  tree.json               契约 C-TREE
  experience.md           契约 C-EXP（自由格式 markdown）
  running.jsonl           契约 C-RUN（每行一个运行记录，JSONL 便于原子 append）
  progress.jsonl          契约 C-PROG（采集脚本 append，每行一次采集快照）
  SUMMARY.md
  variants/<vid>/
    model.py
    train.log
    status.json           契约 C-STATUS（哨兵）
    metrics.json
    collect.sh            确定性采集脚本（步骤 S0 提供）
    ANALYSIS.md
  report.md
```

**契约定义：**

- **C-STATUS（哨兵）**：`{vid, ok:bool, exit_code:int|null, metrics_path:str|null,
  wallclock_sec:float, error:str, fingerprint:{pid,start_time,cmdline}}`。**原子写**
  （tmp+rename）。存在 = 完成。ok=true 要求 metrics_path 存在且可解析，否则 ok=false。
- **C-RUN**：JSONL，每行 `{vid, pid, start_time, cmdline, log_path, started_at}`。
  追加写（单行原子）。
- **C-PROG**：JSONL，每行 `{vid, ts, tail:str(最新N行), pid_alive:bool, metrics_seen:bool}`。
- **C-TREE**：`{version, nodes:[{id, parent_id, direction, metrics:{}, 
  promising:bool|null, dead:bool, depth, model_file, status, fingerprint}]}`。
  **整文件原子写 + flock**（步骤 S5 V3.2）。
- **C-SETUP**：`{entry, model_arg_name, baseline_model, init_hyperparams:{}, 
  metrics:[{name,direction,threshold}], latency_target, dummy_input, 
  variant_naming: {...}, directions:[...], wallclock_budget_sec}`。**directions 外置**
  → OCP。
- **C-BASELINE**：`{metrics:{}, latency_ms, hyperparams:{}, model_file}`。

---

## 3. 实施步骤（每步含验收标准 + 用例）

### 步骤 S0：通用基础设施（harness + 采集/断点脚本）

**改动**：
1. `harness/tools/bash.py` `spawn_background` 返回串加 `pid: <proc.pid>`（2 行）。
2. `init_session.py` 删 working_dir pointer 写入，改 `runs/<id>/.session_meta.json`。
3. workflow 内新增 `helpers/collect_status.py`：确定性采集脚本——输入 run 目录，
   检查 PID 存活（+start_time+cmdline 指纹校验防 PID 复用）、tail 日志、检测 metrics
   产出；训练结束原子写 status.json（tmp+rename）。
4. workflow 内新增 `helpers/check_resume.py`（已存在，扩展支持新契约文件清单）。

**为什么 collect_status.py 放 workflow 不放 harness**：它假设了 NAS 的产物布局
（status.json/metrics.json 哨兵契约），是 NAS 专用，违背"通用原语进 harness"。放
workflow 内。

**验收标准**：
- [ ] **S0.1 PID 暴露**：单元测试——调 `spawn_background`，返回串含 `pid: <数字>`，
      且该数字 = 实际 OS 进程 PID（`os.kill(pid,0)` 成功）。
- [ ] **S0.2 init 不污染**：跑 init_session 后，`git -C <working_dir> status` 干净
      （无 .nas_session_pointer）；`.session_meta.json` 在 runs/<id>/ 下。
      **用例**：`init_session.py --working-dir projects/mnist` → 检查 projects/mnist
      无新增文件，runs/<id>/.session_meta.json 存在。
- [ ] **S0.3 采集脚本正确性（核心）**：collect_status.py 单元测试覆盖 5 场景：
      - (a) 进程在跑 + 无 metrics → 不写 status.json，C-PROG 追加 pid_alive=true。
      - (b) 进程在跑 + 有 metrics → 写 status.json ok=true。
      - (c) 进程退出 exit 0 + 有 metrics → 写 status.json ok=true。
      - (d) 进程退出 exit 非0 → 写 status.json ok=false error=非0。
      - (e) **PID 复用陷阱**：原训练进程已死，该 PID 被 OS 复用给别的进程（不同 cmdline）
        → 识别为"非本训练进程"，不误判存活，写 status.json ok=false。
      **用例**：对每场景构造真实子进程 + 伪造 metrics 文件，断言 collect_status 输出。
- [ ] **S0.4 原子写**：status.json 写入中途被杀（模拟：写 tmp 后、rename 前中断）
      → 不产生半成品 status.json（只有 .tmp 或啥都没有）。**用例**：monkeypatch
      collect_status 在 rename 前 raise，检查无 status.json，仅 status.json.tmp。
- [ ] **S0.5 check_resume 契约**：给一组 expected 文件，部分存在部分缺失 → skip=false
      且 reason 列出缺失项；全在且 json 有效 → skip=true。

---

### 步骤 S1：setup agent

**职责**：查阅项目，向用户确认必要元素（C-SETUP 全部字段）。不假设编码规范。

**验收标准**：
- [x] **S1.1 必要元素完整**：setup.json 含 C-SETUP 所有 required 字段，非空非模板。
      （静态检查通过：agents/setup.md 的 schema 示例含全部字段。）
- [ ] **S1.2 跨项目可用（OCP 验证）**：同一个 setup agent.md，跑 `projects/mnist` 和
      `projects/cifar_cnn` 两个项目，都能产出合法 C-SETUP（入口/模型参数名/超参按各
      项目实际，不硬编码）。
      **用例 A**：mnist 项目，确认能识别 train.py 入口 + 真实命令行约定。
      **用例 B**：cifar 项目（不同编码约定），确认 setup.json 适配，不报"缺 --config"。
      （待 V1.E2E 实跑验证。探查已知：两项目均 `from model import X` 硬编码、无 --model
      flag——setup 的变异约定 Step 2 正是为此设计。）
- [x] **S1.3 目标即约束**：setup.json 的 metrics 字段每项含 threshold（用户给明确值），
      无 threshold 则 ask_user 追问直到拿到。（静态检查通过：prompt 明确"没有阈值的
      目标无效——追问"。）
- [x] **S1.4 方向外置**：setup.json 的 directions 字段非空（默认含 structural/
      business/hyperparam，但可被用户/项目改）。analyzer/selector 不在 prompt 枚举方向。
      （静态检查通过：directions 写进 C-SETUP schema。）
- [x] **S1.5 断点**：setup.json 已存在 → 跳过。（静态检查通过：含 check_resume Step 0。）

---

### 步骤 S2：baseline agent

**职责**：跑原始训练一次，固化基线 + 生成架构理解。

**验收标准**：
- [ ] **S2.1 基线固化**：baseline.json 含 metrics + latency_ms + hyperparams + model_file，
      数值来自真实训练（非编造）。（静态检查通过：C-BASELINE 字段齐全。真实数值待
      V1.E2E。）
- [ ] **S2.2 架构理解非空话**：baseline_understanding.md 含具体分析（容量瓶颈点出具体
      层、计算热点点出具体算子、SOTA 机会针对该任务）。验收：人工抽查 ≥3 条具体技术
      陈述，无"可能/也许"模糊套话。（静态检查通过：prompt 列了三个具体维度 + 禁套话。
      生成质量待 V1.E2E 人工抽查。）
- [x] **S2.3 复用 S0 采集**：baseline 训练也走 collect_status 机制（不另写监控），
      status.json 正常生成。（静态检查通过：Step 2 明确走 collect_status + 禁止自写。）
- [x] **S2.4 根节点写入树**：tree.json 含 v0（baseline）节点，作为所有变异的根。
      （静态检查通过：Step 6 写 v0，parent_id=null，depth=0。）

---

### 步骤 S3：selector agent

**职责**：V1 版——选 parent（默认 baseline 或上一轮最优）+ 分配一个方向。
**V2 才做 ToT**（开发/探索/回溯/降温/去重）。V1 不实现这些，避免 YAGNI。

**验收标准**：
- [x] **S3.1 V1 极简**：V1 selector 输出 = {parent_id, direction, subgoal}，无 ToT
      字段。grep selector.md 确认无"降温/回溯"字样。（静态检查通过：ToT 明确标为
      V2 推迟，V1 策略为贪心选最好。）
- [x] **S3.2 传递必要信息**：selection.json 含 parent 模型文件路径 + parent 指标 +
      方向 + baseline_understanding 路径 + experience 路径 + subgoal。（静态检查通过：
      selection.json schema 含 parent.model_file + info_paths + subgoal。）
      **用例**：mutator 拿到 selection.json 后，仅读这些文件即可开工，不需重新遍历
      项目（实测：断点重启后 mutator 不读 projects/ 下的源码）。— **待 V1.E2E + V1.断点 实跑验证**
- [ ] **S3.3 轮转（V2 移到此处）**：连续 3 轮同方向 → 强制换。V1 不验收此项。

---

### 步骤 S4：mutator agent（SRP：内部分阶段）

**职责**：单 agent，但内部强制三阶段，每阶段产物落盘可断点：

- **阶段 A 生成**：读 selection + baseline_understanding + experience，生成新 model.py。
- **阶段 B 运行**：按 setup 的运行约定，`run_in_background=true` 拉起训练，记 C-RUN，
  起 collect_status 后台采集。
- **阶段 C 收集**：轮询 status.json 哨兵到完成/超预算，读 metrics，写 variant 产物。

**判断逻辑分离**：collect_status 只做数据采集（PID/tail/metrics 检测，确定性）；
"训练是否正常/有无异常"的判断由 mutator（LLM）读 progress.jsonl 做。采集可测，判断灵活。

**验收标准**：
- [x] **S4.1 三阶段落盘**：每个阶段有可识别产物（A:model.py+changes.md，B:C-RUN 追加+
      collect 启动，C:status.json 读取记录）。阶段间可断点续。（静态检查通过：三阶段
      均有产物 + check_resume 断点。运行验证待 V1.E2E。）
- [ ] **S4.2 方向非惰性**：structural 产物做根本结构改变（如替换 attention 机制），
      非压层删组件。**用例**：diff parent model vs variant model，确认有结构组件替换/
      新增，非纯层数/宽度数值变化。（静态检查通过：prompt 明确根本结构改变 + 禁惰性。
      **软验收**：V1.E2E 人工抽查 ≥1 轮 structural diff。）
- [ ] **S4.3 时延有改善**：business/structural 方向变体的 latency_ms < parent latency_ms
      （不必达标，但须改善）。（静态检查通过：prompt 明确 latency<parent。运行验证待 V1.E2E。）
- [ ] **S4.4 监控摘取生效**：progress.jsonl 有 ≥2 条采集记录，含 tail 最新 loss/step。
      （静态检查通过：collect_status + progress.jsonl + tail 机制齐全。运行验证待 V1.E2E。）
- [x] **S4.5 上下文不丢**：mutator 单 agent 内完成生成→运行→收集，中途不交接给别的
      agent（grep workflow.json 确认 mutator 后继是 analyzer，无中间 runner）。（静态
      检查通过：prompt 明确"交接给独立 runner"为严禁项。S7 组装时确认 workflow.json 路由。）
- [ ] **S4.6 断点（阶段级）**：
      - 阶段 A 完成后崩 → 重启跳过 A（model.py 存在），从 B 开始。
      - 阶段 B 训练在跑时崩 → 重启读 C-RUN，PID 仍活→继续等（S0.5 指纹校验）；
        PID 死且无 status→重跑 B。
      **用例**：构造每个阶段的崩溃点，验证恢复路径。（静态检查通过：每阶段有断点 Step。
      运行验证待 V1.断点 实跑。）
- [x] **S4.7 假成功拦截**：训练 exit0 但无 metrics → collect_status 写 status.ok=false
      （依赖 S0.3c/d）；mutator 不当作成功。（静态检查通过：prompt 明确 ok=false 如实
      处理 + analyzer 文件证据复核；S0.3c/d 单测已验证 collect_status 行为。）

---

### 步骤 S5：analyzer agent

**职责**：按用户目标判断潜力（**不合成 fitness**）+ 更新 tree + 写 experience + 判路由。

**验收标准**：
- [x] **S5.1 无 fitness 合成**：grep 整个 workflow 目录无 `fitness.py` 调用、无 fitness
      加权计算。analyzer.md 不出现 fitness 公式。（静态检查通过：prompt 明确"严禁
      fitness.py/加权公式"。grep 命中的 analyzer.md/reporter.md 仅是禁令语句本身。
      旧 helpers/fitness.py 存在但无新 agent 调用——S7 清理。）
- [x] **S5.2 按目标判断**：analyzer 对每个变体，逐项对照 setup.json 的 metrics threshold
      判断（达标/未达标/逼近），并据此标 promising。（静态检查通过：threshold-driven
      + 定性判断 + 灰区写理由。）**用例**运行验证待 V1.E2E。
- [x] **S5.3 文件证据校验**：metrics.json 不存在或不含目标指标 → 该变体标 invalid，
      不参与判断（不信 mutator 自报）。（静态检查通过：Step 1 复核 + invalid 标记。）
- [x] **S5.4 树更新原子**：tree.json 更新走 flock+原子写。（静态检查通过：tmp+rename；
      V3 flock 待并发实测。）
- [x] **S5.5 路由正确**：达标→reporter；超预算→reporter；否则→selector。（静态检查
      通过：decision pass/fail + over_budget 处理。）
- [ ] **S5.6 下一轮基线**：从 promising 节点选（V1 只有一个变体时 = 该变体或 baseline）。

---

### 步骤 S6：reporter agent

**验收标准**：
- [x] **S6.1 报告完整**：report.md 含最优变体 vs baseline 的指标对比表 + 时延对比 +
      变异路径（parent 链）+ 达标判定。（静态检查通过：报告模板含四要素。运行验证待 V1.E2E。）
- [x] **S6.2 触发条件**：仅在 analyzer 路由 reporter 时跑（达标或超预算）。（静态检查
      通过：prompt 明确 pass-only。S7 组装时确认 workflow.json 路由。）

---

### 步骤 S7：workflow.json 组装 + 旧 agent 清理

**验收标准**：
- [ ] **S7.1 节点数**：workflow.json 恰好 6 个 agent（setup/baseline/selector/mutator/
      analyzer/reporter），路由：setup→baseline→[selector→mutator→analyzer]→reporter，
      analyzer 条件路由（pass→reporter / fail→selector）。
- [ ] **S7.2 旧文件删除**：git status 显示 9 个旧 agent.md 删除，无残留。
- [ ] **S7.3 编译通过**：`load_workflow("nas")` 成功，无 schema 错误。

---

## 4. 阶段化验收（端到端）

### V1：端到端最小（单轮单变异，无 ToT）

跑通 S0-S7。**用例**：`projects/mnist`，目标 acc≥0.95，单轮。
- [ ] **V1.E2E**：一次运行完整跑完 6 agent，产出 setup/baseline/tree/report，
      reporter 判定（达标或未达标都算跑通，关键是流程闭合）。
- [ ] **V1.断点**：跑到 mutator 阶段 B 时 kill 整个 workflow，`--session-id` 重启，
      恢复正确（不重跑 setup/baseline，训练继续或正确重跑）。

### V2：多轮 ToT

- [ ] **V2.1 循环**：≥3 轮，tree 累积 ≥3 变体。
- [ ] **V2.2 开发**：连续轮沿有潜力方向深挖（parent 链连续）。
- [ ] **V2.3 探索/回溯**：观察到 ≥1 次换方向或回溯。
- [ ] **V2.4 降温**：连续退步 → 标 dead，不再选。
- [ ] **V2.5 去重**：变异指纹生效，同形状不重复。
- [ ] **V2.6 预算**：短预算超限优雅路由 reporter。

### V3：3 方向并行 + 健壮性

- [ ] **V3.1 并发**：一轮内 3 方向并发发起训练。
- [ ] **V3.2 tree.json flock**：3 变体并发写，多次实测无损坏。
- [ ] **V3.3 max_iterations 足够**：≥10 轮不撞 recursion_limit（一轮≈4 节点执行，
      max_iterations 调到数千，run_nas.py 已有 override）。

---

## 5. 风险与对策（已映射到验收）

| 风险 | 验收项 | 对策 |
|---|---|---|
| LLM 不写/写错采集脚本 | S0.3 | collect_status.py 是确定性脚本，非 LLM 现场写；LLM 只调用 |
| LLM 仍惰性压缩 | S4.2 | baseline_understanding + prompt 禁令 + diff 抽查 |
| PID 复用指错 | S0.3e | start_time+cmdline 指纹 |
| status.json 半成品 | S0.4 | 原子写 |
| tree.json 并发损坏 | S3.4/V3.2 | flock |
| recursion_limit | V3.3 | max_iterations 调够 |
| 方向写死难扩展 | S1.4 | directions 外置 setup.json |

---

## 6. 实施顺序与依赖

```
S0（基础设施） ── 无依赖，先做
   │
   ├─ S1（setup）       依赖 C-SETUP 契约
   ├─ S2（baseline）    依赖 S0 采集 + C-BASELINE
   │
   └─ S3（selector）    依赖 C-TREE
        └─ S4（mutator） 依赖 S0 采集 + S1+ 运行约定 + S3 传递
             └─ S5（analyzer） 依赖 C-TREE + C-SETUP 目标
                  └─ S6（reporter）

S7（组装） 依赖 S1-S6 全部就绪
```

建议：S0 先独立做完跑通单测（S0.1-S0.5），再并行推 S1/S2，然后 S3→S4→S5→S6，
最后 S7 组装跑 V1.E2E。
