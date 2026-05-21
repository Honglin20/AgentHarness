# Workflow 目录化 + EvalJudge — Design

> 2026-05-22 — 与用户对齐后产出。下游配套实施计划:`2026-05-22-workflow-dirs-and-eval-judge.md`。

## 目标

1. 把 workflow 改造为目录结构,每个 workflow 自包含 agents + scripts(类似 Claude Code skills)。
2. 实现 EvalJudge — 一个通过 `Agent(eval=True)` 标记自动插入评测节点 + 失败回环 + 评分图表的 GraphMutator。

## 范围(三阶段)

- 阶段 1 — 目录化基础设施(不依赖 EvalJudge)
- 阶段 2 — EvalJudge 核心实现
- 阶段 3 — 示例 + 文档收尾

---

## §1 目录结构与查找规则

### 新结构

```
workflows/
├── _shared/
│   ├── agents/                # 共享 agent(v1 只放 runner.md)
│   │   └── runner.md
│   └── scripts/               # 共享脚本(v1 留位空目录)
│
├── code_review/               # 每个 workflow = 一个文件夹
│   ├── workflow.json
│   ├── agents/
│   │   ├── analyzer.md
│   │   └── planner.md
│   └── scripts/
│       └── lint_runner.py
│
└── chart_demo/
    ├── workflow.json
    ├── agents/
    │   └── runner.md
    └── scripts/
        └── chart_script.py
```

### Agent 查找规则:workflow 优先,_shared 兜底

1. `workflows/<wf>/agents/<name>.md` 存在 → 使用
2. 否则查 `workflows/_shared/agents/<name>.md` 存在 → 使用
3. 都不存在 → `AgentNotFoundError(name, searched=[...])`

### workflow.json 形态

```json
{
  "name": "code_review",
  "agents": [
    {"name": "analyzer", "after": []},
    {"name": "planner", "after": ["analyzer"]},
    {"name": "reviewer", "after": ["planner"], "eval": true}
  ]
}
```

去掉 `agents_dir` 字段。新增 `eval: bool` 字段(EvalJudge 标记)。

### Scripts 路径注入

`MicroAgentFactory.build_node_prompt` 在 `## Task` 之后追加(仅当目录非空):

```
## Available scripts (call via bash tool)
- Private (workflow-specific): /abs/path/workflows/<name>/scripts/
- Shared (cross-workflow):     /abs/path/workflows/_shared/scripts/
```

bash 工具的 cwd 保持用户 cwd(沿用现有行为),agent 用完整绝对路径调用脚本。

---

## §2 加载与解析逻辑

### Workflow 改造

```python
# harness/api.py
_WORKFLOWS_DIR = _BACKEND_DIR.parent / "workflows"
_SHARED_AGENTS_DIR = _WORKFLOWS_DIR / "_shared" / "agents"
_SHARED_SCRIPTS_DIR = _WORKFLOWS_DIR / "_shared" / "scripts"

class Workflow:
    def __init__(self, name, agents, workflow_dir=None, ...):
        self.workflow_dir = workflow_dir or (_WORKFLOWS_DIR / name)
        # agents_dir 概念被取代

    @classmethod
    def load(cls, name):
        path = _WORKFLOWS_DIR / name / "workflow.json"
        # 加载并设置 workflow_dir

    def save(self):
        self.workflow_dir.mkdir(parents=True, exist_ok=True)
        (self.workflow_dir / "agents").mkdir(exist_ok=True)
        (self.workflow_dir / "scripts").mkdir(exist_ok=True)
        # 写 workflow.json
```

### MD 解析器新增

```python
# harness/compiler/md_parser.py
def resolve_agent_md(agent_name: str, workflow_dir: Path) -> Path:
    local = workflow_dir / "agents" / f"{agent_name}.md"
    if local.exists(): return local
    shared = _SHARED_AGENTS_DIR / f"{agent_name}.md"
    if shared.exists(): return shared
    raise AgentNotFoundError(agent_name, searched=[str(local), str(shared)])

class AgentNotFoundError(FileNotFoundError):
    ...
```

`MacroGraphBuilder` 内部读 MD 的地方全部改调 `resolve_agent_md`。

### Server / Frontend

- `GET /api/workflows/definitions` — 扫描 `workflows/*/workflow.json`
- `GET /api/agents/{name}/md?workflow=xxx` — query 参数从 `agents_dir` 改为 `workflow`
- `PUT /api/agents/{name}/md` — body 加 `workflow` + 可选 `target: "private"|"shared"`
- `POST /api/workflows` — 创建目录(若不存在)
- 前端 `AgentEditorModal.tsx` — 编辑 / 保存区分 private vs shared

### 测试

| 测试 | 目的 |
|---|---|
| `test_resolve_agent_md_private_wins` | private 和 shared 都有,private 优先 |
| `test_resolve_agent_md_fallback_to_shared` | 只 shared 有时,返回 shared 路径 |
| `test_resolve_agent_md_not_found_raises` | 抛 AgentNotFoundError 含 searched 列表 |
| `test_workflow_load_uses_new_layout` | 从新格式加载 |
| `test_workflow_save_creates_subdirs` | save 创建 agents/ 和 scripts/ |
| `test_script_paths_injected_into_prompt` | scripts 非空时,prompt 含路径提示 |

---

## §3 迁移脚本

### 脚本位置 & 用法

```bash
python scripts/migrate_workflows_to_dirs.py --dry-run    # 预览
python scripts/migrate_workflows_to_dirs.py              # 执行
```

### 执行逻辑

1. 扫描 `workflows/*.json`(旧格式),收集每个 workflow 引用的 agents
2. 对每个旧 workflow:
   - 建 `workflows/<name>/{agents/, scripts/}`
   - 写新 `workflow.json`(去 `agents_dir`)
   - 把引用的 `agents/<name>.md` **各自复制**到 `workflows/<name>/agents/`(多 workflow 引用同一 agent → 各复制一份,允许后续独立演化)
3. 没被任何 workflow 引用的 agents → 移到 `.backup_pre_migration/orphan_agents/`
4. `examples/chart_script.py` 复制(不删原)到 `workflows/chart_demo/scripts/`
5. 旧 `agents/` 和 `workflows/*.json` 整体移动到 `.backup_pre_migration/`
6. 打印 "迁移成功" + 备份位置提示

### `_shared/agents/` 只放 runner.md

```markdown
---
name: runner
tools: [bash]
---

你是一个脚本执行器。任务流程:
1. 根据用户给的命令或脚本名,找到要执行的命令(私有脚本在 ./scripts/,
   共享脚本在 ../_shared/scripts/)
2. 创建 logs/ 目录(若不存在)
3. 执行命令时把 stdout 和 stderr 重定向到 logs/<script_name>.log:
   bash -c "<command> > logs/<name>.log 2>&1 &"
4. 持续 tail / 检查日志,直到看到完成标志或进程退出
5. 返回执行结果摘要(成功/失败 + 关键日志片段)
```

### 备份目录

`.backup_pre_migration/` 加 .gitignore。

### 测试

- `test_migrate_dry_run` — dry-run 不写文件
- `test_migrate_creates_workflow_dirs` — 目录结构正确
- `test_migrate_orphan_agents_backed_up` — 未引用 agent 进备份
- `test_migrate_backs_up_originals` — 原文件移到备份目录

---

## §4 EvalJudge 整体架构

### 触发方式

```python
from harness.api import Agent, Workflow
from harness.extensions.eval import EvalJudge

wf = Workflow("research", agents=[
    Agent("researcher", eval=True),
    Agent("writer", after=["researcher"]),
]).use(EvalJudge(judge_model=None, max_retries=2))
```

`Agent.eval: bool = False` 新字段,MD 中也可声明 `eval: true`。

### GraphMutator 改造步骤(对每个 eval=True 的 agent X)

1. 收集下游 `D = {Y : X in Y.after}`
2. 创建虚拟 Agent `_judge_X`:
   - `after = [X]`
   - `result_type = ReviewDecision`
   - `on_fail = X`(回环)
   - `on_pass = <下游 hub>`
3. 把 `Y ∈ D` 的 `after` 中的 X 替换为 `_judge_X`
4. 多下游处理:
   - `|D| ≤ 1` → `on_pass` 直接指向那个下游(或 END)
   - `|D| > 1` → 引入虚拟 pass-through 节点 `_judge_X_passthrough`(no-op),`on_pass = _judge_X_passthrough`,passthrough 节点 fan-out 到所有 D
5. 把 `_judge_X`(和可能的 passthrough)追加到 `workflow.agents`,RunStore 自动 snapshot

### Judge prompt 三段式组装(lazy first-call)

`_judge_X` 的 system_prompt 在节点函数第一次执行时构造:

```
[第一段 — 预制]
你是一个评测员。以下是上一个 agent 的任务和任务结果,你来判断它是否完成。

[第二段 — 自动总结被评 agent 的任务/红线(lazy 生成,缓存)]
## 上游 agent 的任务与红线(自动总结)
<让 LLM 总结 X 的 MD 得到的简要描述>

[第三段 — 框架自动注入(现有 build_node_prompt 行为)]
## Task
<原 inputs>
## Output from X
<X 的产出>
```

第二段由 `harness/extensions/eval/summarizer.py` 处理:首次运行调 LLM 总结 X 的 MD,写入 `workflows/<wf>/.eval_cache/_judge_<X>_summary.md`。缓存 key = X 的 MD 的 SHA256;X 的 MD 变 → 缓存失效 → 重新总结。`.eval_cache/` 加 .gitignore。

### ReviewDecision

```python
# harness/extensions/eval/decisions.py
from pydantic import BaseModel
from typing import Literal

class ReviewDecision(BaseModel):
    decision: Literal["pass", "fail"]
    reason: str
    score: float | None = None    # 新增,可选
```

向后兼容(原 reviewer 节点不传 score 也正常)。

### Pass 时 outputs 透传(关键)

下游 Y 看到的应是被评 X 的原始输出,不是 ReviewDecision。

```python
# _judge_X 节点函数(伪代码)
async def _judge_node_fn(state):
    review = await run_judge_agent(...)   # 拿到 ReviewDecision
    
    # 1. outputs[judge_name] 直接复刻 outputs[target_name] —— 透传
    # 2. judgment 写到 metadata(condition_fn 路由用、回环时注入 critique 用)
    return {
        "outputs": {judge_name: state["outputs"][target_name]},
        "metadata": {judge_name: {"judgment": review.model_dump(), "score_history": [...]}},
    }

def _route_judgment(state, judge_name):
    return state["metadata"][judge_name]["judgment"]["decision"]   # "pass" or "fail"
```

下游 Y 自动从 `outputs[_judge_X]` 拿到 X 的原始输出(只是 key 名带前缀)。`build_node_prompt` 做"显示名重写",在 prompt 里把 `_judge_X` 显示为 `X`,避免下游迷惑。

### 回环时注入 critique

`build_node_prompt` 检测 `state["metadata"]` 里 X 的下游 judge 有 judgment 时,额外注入:

```
## Previous judgment (from _judge_X)
- decision: fail
- reason: <critique>
```

让 X 重跑时看到为什么被打回。

---

## §5 评分可视化 + Snapshot

### 评分自动可视化

`_judge_X` 节点完成时,若 `review.score is not None` → emit chart 事件:

```python
get_event_bus().emit("chart.render", {
    "node_id": judge_name,
    "chart_type": "line",
    "data": [{"iteration": i+1, "score": s} for i, s in enumerate(score_history)],
    "x": "iteration",
    "y": "score",
    "label": "Eval Scores",
    "title": f"{target_name} quality",
})
```

走 EventBus(同进程),不需要 HTTP fallback。score_history 累计在 `metadata[judge_name]["score_history"]`,每次回环追加一个分数,前端按"同 label + 同 title"自动刷新一张折线图。

### Snapshot 处理

`_judge_X` 没有 MD 文件,RunStore 在 snapshot 时:

```python
{
    "name": "_judge_researcher",
    "after": ["researcher"],
    "md_content": <完整组装后的 system_prompt(三段拼起来)>,
    "tools": null,
    "model": "<EvalJudge.judge_model 或默认>",
    "retries": 3,
    "on_pass": "writer",
    "on_fail": "researcher",
}
```

md_content 写法:

```markdown
---
name: _judge_researcher
model: claude-opus-4-7
result_type: ReviewDecision
auto_generated: true
target: researcher
---

<完整三段 system_prompt>
```

回放时前端能看到 `_judge_X` 节点 + 完整 prompt + 历史评分曲线。

### Judge LLM 错误处理(不静默)

```python
try:
    review = await run_judge_agent(...)
except Exception as e:
    return {"errors": {judge_name: str(e)}}    # 不写 outputs → 下游中断
```

`node.failed` 事件 emit,前端节点红色显示。

---

## §6 文件清单 + 实施顺序

### Part A — Workflow 目录化

| 文件 | 改动 |
|---|---|
| `harness/api.py` | `Workflow` 加 `workflow_dir`,去 `agents_dir`;`load`/`save`/`list_saved` 改目录;`Agent` 加 `eval: bool = False` |
| `harness/compiler/md_parser.py` | 新增 `resolve_agent_md` + `AgentNotFoundError`;`parse_agent_md` 解析 `eval` |
| `harness/engine/micro_agent.py` | `build_node_prompt` 注入 scripts 绝对路径 |
| `harness/engine/macro_graph.py` | 读 agent MD 改 `resolve_agent_md` |
| `harness/run_store.py` | snapshot 按 workflow_dir 解析 |
| `server/routes.py` | `definitions` 扫目录;agent MD 端点改 query |
| `server/schemas.py` | `AgentDef.eval`;请求字段对齐 |
| `server/runner.py` | 传 workflow_dir |
| `frontend/src/types/events.ts` | `Workflow.eval`;API query 参数 |
| `frontend/src/components/agent/AgentEditorModal.tsx` | private vs shared |
| `scripts/migrate_workflows_to_dirs.py` | **新文件** — 迁移脚本 |
| `workflows/_shared/agents/runner.md` | **新文件** |
| `workflows/_shared/scripts/.gitkeep` | **新文件** |
| `SPEC.md` | §WorkflowLayout 新增,§Agent/§Workflow/§AgentCRUD 更新 |
| `tests/test_workflow_dir_layout.py` | **新文件** |
| `tests/test_migrate_workflows.py` | **新文件** |
| `.gitignore` | 加 `.backup_pre_migration/` |

### Part B — EvalJudge

| 文件 | 改动 |
|---|---|
| `harness/extensions/eval/__init__.py` | **新** — 导出 EvalJudge |
| `harness/extensions/eval/judge.py` | **新** — `EvalJudge(BaseGraphMutator)` |
| `harness/extensions/eval/decisions.py` | **新** — `ReviewDecision` 加 `score` |
| `harness/extensions/eval/summarizer.py` | **新** — lazy 总结 + `.eval_cache/` |
| `harness/engine/macro_graph.py` | `_judge_X` 节点函数:透传 outputs,写 metadata,emit chart,condition_fn 从 metadata 读 |
| `harness/engine/micro_agent.py` | `build_node_prompt` 注入 `## Previous judgment` + 显示名重写 |
| `harness/extensions/eval/SPEC.md` | 更新现有 SPEC(透传 / lazy / score / 错误处理) |
| `harness/extensions/eval/test_eval.py` | **新** — 现 SPEC 列的 6 个 test + 新增 5 个 |
| `SPEC.md` | §Eval 完整化(不再占位) |
| `.gitignore` | 加 `.eval_cache/` |

### Part C — 示例

| 文件 | 改动 |
|---|---|
| `examples/04_chart_demo.py` | task 提示用简洁脚本名 |
| `examples/chart_script.py` | 复制(保留原)到 `workflows/chart_demo/scripts/` |
| `examples/10_eval_judge.py` | **新** — 最小 EvalJudge demo |

### 实施顺序

**阶段 1 — 目录化基础设施**
1. SPEC 更新 §WorkflowLayout / §Agent / §Workflow / §AgentCRUD
2. `resolve_agent_md` + Workflow 重构
3. server / frontend 配套
4. 迁移脚本 + 跑迁移
5. 测试,验证 examples 1-9 全通过

**阶段 2 — EvalJudge 核心**
1. 更新 `extensions/eval/SPEC.md`
2. `ReviewDecision.score`、`EvalJudge.mutate`
3. `MacroGraphBuilder` judge 节点(透传/metadata/condition/chart)
4. `build_node_prompt` 注入 critique + 显示名重写
5. lazy summarizer + cache
6. 测试
7. `examples/10_eval_judge.py`

**阶段 3 — 整合 & 文档**
1. SPEC.md §Eval 填充
2. README / contribute.md 更新
3. e2e 跑通 EvalJudge 回环 + UI 评分图

每阶段结束暂停,人工 review 后再推进下一阶段。

---

## 关键设计决策回顾

| 决策 | 选择 | 原因 |
|---|---|---|
| Workflow 自包含 | 每 workflow 一目录,引用 agent 复制一份 | 用户决定 — 隔离演化,不共享漂移 |
| 共享池 | `workflows/_shared/agents/` 只放 runner;`_shared/scripts/` 留位 | 用户决定 — 框架级通用 agent 集中 |
| scripts cwd | bash cwd = 用户 cwd,prompt 注入完整绝对路径 | 用户决定 — 沿用现行为 |
| EvalJudge 触发 | `Agent(eval=True)` + `Workflow.use(EvalJudge(...))` | SPEC 原设计 |
| judge prompt 组装 | 三段(预制头 / lazy 总结 / 框架注入) | 用户决定 — 自适应,免用户写 judge MD |
| 多下游 | 虚拟 passthrough 节点 fan-out | 改动小,语义清晰 |
| Pass 透传 | judge 节点 `outputs[judge] = outputs[X]`;judgment 写 metadata | 用户强调 — pass 时下游拿 X 的输出 |
| 评分 | `ReviewDecision.score` 可选,自动 emit line chart | 采纳,可视化趋势 |
| Judge 错误 | 不静默,当节点失败 | 用户决定 — judge 可靠性是要求 |
| Lazy 总结 | 首次运行生成,缓存到 `.eval_cache/`,SHA256 验证 | 简单 + 可复现 |
| Snapshot | `_judge_X` 自动入 agents 列表,md_content 写完整 prompt | 回放完整还原 |
