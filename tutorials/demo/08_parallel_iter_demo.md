---
workflow: parallel_iter_demo
title: 并行迭代脑暴（NAS 风格）
badge: Quick Start
---

# 并行迭代脑暴（parallel_iter_demo）

这是 DEMO 域里**最复杂的一个 workflow**，刻意把 NAS workflow 的三大结构特征压进一个最简单的任务（产品命名脑暴）里。如果你正在学 NAS 或想理解 harness 的 DAG 高级能力，从这个 demo 入手比直接看 NAS 直观得多。

## NAS 的三大特征，这里都有

| NAS 特征 | NAS 中的体现 | parallel_iter_demo 中的体现 |
|---------|------------|---------------------------|
| **Diamond fan-out + fan-in** | `project_analyzer` → [adapter_generator, domain_analyzer] → ... → `scout` | `decomposer` → [scout_a, scout_b] → `aggregator` |
| **多轮迭代 + 条件回边** | `selector → planner → trainer → judger → analyzer → validator` → (on_fail 回 selector / on_pass 进 refiner) | `selector → generator → judger → analyzer → validator` → (on_fail 回 selector / on_pass 进 reporter) |
| **sub_agent 并行展开** | `trainer` 内部展开 K 个 worker 跑候选 | `generator` 用 sub_agent 并行展开 N 个命名 worker |

下面按 DAG 顺序逐节讲解。

## 拆解产品定位 @decomposer

入口 agent（`after: []`）。输入是用户给的一段产品描述，输出 2 个互补的命名维度，让下游 scout_a / scout_b 并行展开。

示例：用户输入「面向程序员的智能水杯」→ decomposer 拆成「功能维度（提醒/记录/可视化）」×「情感维度（极客/健康/陪伴）」。

## 并行 Scout A @scout_a

`scout_a`（`after: [decomposer]`）和 scout_b **同时启动**（diamond 的左分支）。只负责一个维度的关键词收集，不碰另一个维度。

**关键观察**：在 portal 运行视图里，scout_a 和 scout_b 的卡片会同时变成 running，验证并行分支生效。

## 并行 Scout B @scout_b

`scout_b`（`after: [decomposer]`，diamond 的右分支）。和 scout_a 对称，负责另一个维度。

## 合并素材 @aggregator

`aggregator`（`after: [scout_a, scout_b]`）—— **fan-in 节点**。它必须等两个 scout 都完成才会启动（框架自动 join）。

合并去重后输出统一素材库，给下游迭代循环当输入。这一步对应 NAS 里 `scout` 等 5 个上游全部完成才启动的 join 语义。

## 选择迭代方向 @selector

迭代循环的**入口**（`after: [aggregator]`）。每一轮由 selector 决定：

- 本轮生成几个候选（建议 3-5）
- 参考哪个方向（iter 1 用 aggregator 素材；iter N 用上轮 judger 的 top-1）

只要 validator `on_fail` 路由回 selector，下一轮就从 selector 重新开始。

### iter_num 怎么知道？（history 文件机制）

迭代循环里最棘手的问题是「当前是第几轮」。如果只靠 agent 之间通过字段传递，很容易在 analyzer/validator 处误判（实测出现过 iter 2 的 analyzer 仍输出 iter_num=1）。

这个 demo 用**文件系统作为权威计数器**，类似 NAS 的 `$session_dir` 模式：

- `decomposer` 在 workflow 启动时清理 `.HISTORY/parallel_iter_demo/iter_*.md`
- 每轮 `selector` 启动时用 bash 数已有文件 +1 得到本轮 iter_num，然后写 `iter_{N}.md` 记录本轮 guidance/target_count
- `validator` 用 bash 数 history 文件数 = 当前 iter_num（不信任 analyzer 的字段）

`.HISTORY/` 在 project root 下，已加入 `.gitignore`，是纯运行时状态。

## 并行生成候选 @generator

`generator`（`after: [selector]`）—— **sub_agent 并行展开节点**。

CRITICAL 约束：generator **必须**用 `sub_agent` 工具并行发起 N 次调用（N = selector.target_count），每次给一个独立的子方向。所有 sub_agent 返回后才汇总输出。

**这一步是 demo 的灵魂** —— 在 portal 里你会看到 N 个 sub_agent 卡片同时 running，对应 NAS 里 trainer 同时跑 K 个候选结构的场景。

错误模式（agent 容易犯的错）：自己直接生成 N 个名字、串行调 sub_agent、或只调一次 sub_agent 让它返回 N 个。这些都违背了「并行展开」的演示意图。

## 排名候选 @judger

`judger`（`after: [generator]`）按 0.4×相关性 + 0.35×独特性 + 0.25×传播性 给候选打分排名。输出按 fitness 降序的 ranking。

## 分析收敛 @analyzer

`analyzer`（`after: [judger]`）判断本轮是否收敛：

- top-1 fitness ≥ 8.0 → 达标
- 相比上轮提升 ≥ 0.5 → 仍在进步
- 两者都不满足 → 停滞

输出 `converged` / `plateau_detected` 标志给 validator。

## 裁决路由 @validator

`validator`（`after: [analyzer]`，**带 `on_pass: reporter` / `on_fail: selector`**）是**条件回边**的关键节点。

**这个 demo 强制至少迭代 2 轮** —— 即使 iter 1 的 fitness 已经超过阈值，validator 也会判 fail 回到 selector，保证用户能完整看到「迭代收敛」的全过程（这是教学意图，不是 NAS 的真实行为）。

| 条件 | decision | 框架路由 |
|------|----------|---------|
| `iter_num < 2`（**第一轮强制 fail，无视 fitness**） | `"fail"` | → selector |
| `iter_num >= 2` 且 `best_fitness ≥ 8.0`（达标） | `"pass"` | → reporter |
| `iter_num >= 3`（用尽预算强制收尾） | `"pass"` | → reporter |
| `iter_num < 3` 且未达标 | `"fail"` | → selector |

这就是 NAS 里 validator 的翻版 —— 一个 agent 决定「继续搜」还是「收工」。

### iter_num 的权威来源 = history 文件数

validator **不信任** analyzer.iter_num 字段（实测会被误判）。它用 bash 自己数：

```bash
COMPLETED=$(ls .HISTORY/parallel_iter_demo/iter_*.md 2>/dev/null | wc -l | tr -d ' ')
```

`COMPLETED` 就是当前 iter_num。这就是 selector 写 history 文件的全部意义 —— 给 validator 提供一个**只增不减、可被 bash 直接计数**的权威信号。

### validator 还需要 `result_type_schema`

workflow.json 里 validator 声明了 `result_type_name: ValidatorResult` + `result_type_schema`（`decision: enum[pass, fail]`）。这是**必须的** —— 引擎的 `_extract_decision` 在拿不到结构化 `decision` 字段时会默认路由到 `on_pass`，没有 schema 你的 fail 决策永远到不了 selector。

## 输出报告 @reporter

`reporter`（由 validator `on_pass` 触发，`after: null`）汇总所有迭代的 Top-3 候选，附理由 + 最终 outcome（`达标成功` 或 `部分成功`）。

---

## 演示 task

```
为一款「面向程序员的智能水杯」设计 3 个产品命名。这款水杯能：定时提醒喝水、记录每日饮水量、和 IDE 插件联动显示「咖啡因 vs 水」的摄入平衡。目标用户是 25-40 岁的男性程序员。
```

或更简单的：

```
给一款 AI 辅助的中文写作工具起 3 个名字，强调「让写作像聊天一样自然」。
```

预期跑完会看到：

1. decomposer 拆出 2 个维度
2. scout_a 和 scout_b 同时跑（diamond 左右分支并行）
3. aggregator 合并素材
4. selector → generator（展开 N 个 sub_agent 并行命名）→ judger → analyzer → validator
5. **validator 第一轮强制 fail**（即使 fitness 已达标），回到 selector 跑第二轮
6. 第二轮再走一遍 generator → judger → analyzer → validator，达标则 pass
7. 最终 reporter 输出 Top-3 命名

> Demo 强制至少 2 轮，是为了让用户完整看到「diamond 并行 → 迭代收敛」全过程；想看真实的「达标即停」行为可以参考 NAS workflow 的 validator。

## 调试要点

- **看不到 diamond 并行**：portal 上 scout_a / scout_b 应当同时 running。如果串行，检查 `workflow.json` 里 scout_a 和 scout_b 是否都 `after: [decomposer]`，aggregator 是否 `after: [scout_a, scout_b]`
- **看不到 sub_agent 并行展开**：generator 的 agent prompt 必须强约束「FIRST action MUST be sub_agent」，参考 [sub_agent_test](07_sub_agent_test.md) 的 delegator 写法
- **迭代不终止**：检查 validator 的 `decision` 是否严格 `"pass"` / `"fail"`，以及 `max_iterations` 是否合理（demo 设了 3）
- **iter 1 就 pass 了**（不符合「强制至少 2 轮」预期）：检查 validator 是否漏掉了 `iter_num < 2` 一律 fail 的硬约束
- **iter 2 validator 还是 fail**（误判 iter_num）：检查 `.HISTORY/parallel_iter_demo/` 下文件数是否正确；validator 是否真的用 `ls ... | wc -l` 计数而不是依赖 analyzer.iter_num 字段
- **validator fail 没回 selector 反而进 reporter**：检查 workflow.json 里 validator 是否声明了 `result_type_schema`（含 `decision: enum[pass, fail]`）。没有 schema 时引擎拿不到结构化 decision，会默认 pass
- **想对比 NAS 真实复杂度**：切到 [NAS 领域的 01_搜索空间基础](../nas/01_search_space.md)，parallel_iter_demo 是它的最小化镜像
