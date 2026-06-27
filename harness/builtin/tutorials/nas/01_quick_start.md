---
workflow: simple-nas
title: SIMPLE NAS 快速入门
badge: Quick Start
---

# SIMPLE NAS 快速入门

5 分钟体验一次神经网络结构搜索。`simple-nas` 是 NAS workflow 的**精简版**——6 个 agent 串行执行，适合快速跑通「探测 → 基线 → 变异搜索 → 报告」整条链路，理解框架如何围绕你已有的训练项目做结构优化。

> 需要完整的并行 setup（5 节点并行探测）、tier 渐进升级、多维 fitness？改用复杂版 `nas`（15 agents），见 [NAS 端到端流程总览](#)。

工作流由 6 个 agent 组成，分三个阶段：**Setup → Cycle（迭代变异）→ Report**。

---

## 阶段 0：探测必要元素 @setup

入口 agent，**只读不改**。它扫描你的项目目录，确认让 workflow 跑起来所需的必要元素，记录到 `setup.json`，并和用户对齐「变异约定」：

- 识别 `nn.Module` 入口、训练/评估函数、权重路径
- 确认 epochs 是否可控（决定能否按 tier 调训练时长）
- 对齐变异范围（哪些层可改、哪些超参可调）

**目的导向，非硬编码**：setup 不假设任何项目的编码规范，而是基于探测结果动态决定后续 agent 需要的信息。不直接调用户的训练代码。

---

## 阶段 1：固化基线 @baseline

用**原始**（未变异）模型 + 原始超参，跑一次完整训练，固化基线——它是搜索树的根节点 `v0`，后续所有变体的指标/时延都以它为参照。基线就位后，cycle 阶段才能判断每个变异是「改进」还是「退化」。

---

## 阶段 2：迭代变异 Cycle（selector → mutator → analyzer）

每轮迭代三个 agent 串成循环，**无 framework 级并行**（精简版的核心简化点）：

### @selector —— 选父代 + 定方向
为本轮变异选一个 **parent**（变异起点：首轮是 baseline，后续按潜力取 top）+ 分配一个**变异方向**（structural / parametric / hybrid）。纯决策，不跑训练。

### @mutator —— 生成变异 + 训练 + 收集
按 selector 给的方向，**生成变异 + 自己拉起训练 + 监控到完成 + 收集结果**。这是**合并了 runner 的单 agent**——变异完成后直接跑，不交接给别的 agent（精简版把复杂版的 planner/trainer/judger 三步合一）。小步迭代：每个变异改动 ≤3 个位置，让结果可归因。

### @analyzer —— 判潜力 + 路由
按**用户给的目标**判断本轮变异的潜力，更新候选树，提炼经验，决定路由：
- 还有潜力、未达标、预算未耗尽 → 回 `selector` 开下一轮
- 达标 或 超预算 → `decision=pass` → 路由到 reporter

---

## 阶段 3：最终报告 @reporter

搜索结束（达标 或 超预算）时，analyzer 路由 pass 后唯一到达的终点 agent。汇总整轮搜索，选最优变体对比基线，出报告：变异路径 lineage、指标对比、经验总结。

---

## SIMPLE NAS vs NAS WORKFLOW

| 维度 | `simple-nas`（6 agents） | `nas`（15 agents） |
|------|--------------------------|---------------------|
| Setup | 1 个 setup agent 串行探测 | 5 个并行 DAG 节点 + scout 汇聚 |
| Cycle | selector→mutator→analyzer 三合一循环 | selector→planner→trainer→judger→analyzer→validator/refiner 六步 |
| 训练 | mutator 单 agent 内联训练 | trainer 并发 K 个 sub_agent + tier 自判 |
| Fitness | analyzer 基于「目标潜力」判断 | judger 多维 fitness 公式（精度/延迟/参数/稳定性） |
| 适用 | 快速跑通、小项目、学习框架 | 生产级搜索、多维优化、tier 渐进升级 |

点击左下角**「试一试」**加载 `simple-nas` workflow。建议先用一个小项目（如 MNIST MLP）跑通整个流程。
