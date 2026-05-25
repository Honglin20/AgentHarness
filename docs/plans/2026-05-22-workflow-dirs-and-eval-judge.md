# Workflow 目录化 + EvalJudge 实现计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 把 workflow 从单文件 (workflows/<name>.json) 改造为目录结构 (workflows/<name>/{workflow.json, agents/, scripts/}),并实现 EvalJudge 扩展 — 一个通过 Agent(eval=True) 标记后,自动插入评测节点 + 失败回环 + 评分图表的 GraphMutator。

**Architecture:**
- 阶段 1:目录化基础设施 — Workflow 类支持 workflow_dir,新增 resolve_agent_md(workflow 优先,_shared 兜底),迁移脚本,server/前端配套改造。
- 阶段 2:EvalJudge 核心 — Agent.eval 字段、ReviewDecision.score、_judge_X 节点透传 outputs 写 judgment 到 metadata、lazy 总结被评 agent MD 并缓存、回环时注入 critique、自动 emit score chart。
- 阶段 3:示例 + 文档收尾。

**Tech Stack:** Python (pydantic, LangGraph), FastAPI, React/TypeScript, pytest。

---

## 前置说明

- 本计划在专用 worktree 中执行(由 brainstorming/using-git-worktrees 创建)。
- 严格 TDD:每个功能"先写失败测试 → 跑 → 实现 → 跑 → commit"。
- 严格 SDD:任一公开 API 改动 → 先改 SPEC.md → 再改实现。
- 频繁 commit:每个 Task 末尾必有 commit。

---

## Stage 0 — Worktree 准备

### Task 0.1: 创建 worktree

由 brainstorming/using-git-worktrees 流程创建专用 worktree,分支建议 `feat/workflow-dirs-and-evaljudge`。

进入 worktree 后跑一次烟测,确认环境干净:

```bash
python -c "from harness.api import Agent, Workflow; print('ok')"
pytest tests/ -q  # 应当现有测试全过
```

不 commit。后续 Task 全部在此 worktree 内执行。

---

## Stage 1 — Workflow 目录化基础设施

### Task 1.1: 更新 SPEC.md —— §WorkflowLayout 章节

**Files:**
- Modify: `SPEC.md`

**Step 1:** 在 §Workflow 之后新增 §WorkflowLayout 章节,内容覆盖:目录结构示意、`resolve_agent_md` 查找规则、新 workflow.json 形态(无 `agents_dir`,新增 `eval: bool`)。

**Step 2:** 更新 §Agent — Agent 类签名加 `eval: bool = False`;Agent MD frontmatter 支持 `eval: true`。

**Step 3:** 更新 §Workflow — `Workflow.__init__` 签名 `agents_dir: str` 替换为 `workflow_dir: Path | None`;`load`/`save` 描述改目录化语义;`to_dict`/`from_dict` 不再写 `agents_dir`。

**Step 4:** 更新 §AgentCRUD — query 参数 `agents_dir` → `workflow`;PUT body 加 `workflow` 和可选 `target: "private"|"shared"`。

**Step 5:** Commit:

```bash
git add SPEC.md
git commit -m "spec: workflow directory layout + Agent.eval (§WorkflowLayout)"
```

### Task 1.2: AgentNotFoundError + resolve_agent_md(TDD)

**Files:**
- Modify: `harness/compiler/md_parser.py`(新增 `AgentNotFoundError` + `resolve_agent_md`)
- Create: `tests/test_resolve_agent_md.py`

**Step 1:** 写失败测试 `tests/test_resolve_agent_md.py`:

```python
from pathlib import Path
import pytest
from harness.compiler.md_parser import resolve_agent_md, AgentNotFoundError

def test_private_wins(tmp_path, monkeypatch):
    wf = tmp_path / "wf"
    (wf / "agents").mkdir(parents=True)
    shared = tmp_path / "_shared" / "agents"
    shared.mkdir(parents=True)
    (wf / "agents" / "x.md").write_text("private")
    (shared / "x.md").write_text("shared")
    monkeypatch.setattr("harness.compiler.md_parser._SHARED_AGENTS_DIR", shared)
    assert resolve_agent_md("x", wf).read_text() == "private"

def test_fallback_to_shared(tmp_path, monkeypatch):
    wf = tmp_path / "wf"
    (wf / "agents").mkdir(parents=True)
    shared = tmp_path / "_shared" / "agents"
    shared.mkdir(parents=True)
    (shared / "y.md").write_text("shared")
    monkeypatch.setattr("harness.compiler.md_parser._SHARED_AGENTS_DIR", shared)
    assert resolve_agent_md("y", wf).read_text() == "shared"

def test_not_found_raises(tmp_path, monkeypatch):
    wf = tmp_path / "wf"
    (wf / "agents").mkdir(parents=True)
    shared = tmp_path / "_shared" / "agents"
    shared.mkdir(parents=True)
    monkeypatch.setattr("harness.compiler.md_parser._SHARED_AGENTS_DIR", shared)
    with pytest.raises(AgentNotFoundError) as exc:
        resolve_agent_md("missing", wf)
    assert "missing" in str(exc.value)
    assert len(exc.value.searched) == 2
```

**Step 2:** 跑测试,确认 3 个 fail(模块或类不存在):

```bash
pytest tests/test_resolve_agent_md.py -v
```

**Step 3:** 实现 `harness/compiler/md_parser.py` 中追加:

```python
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_SHARED_AGENTS_DIR = _BACKEND_DIR / "workflows" / "_shared" / "agents"

class AgentNotFoundError(FileNotFoundError):
    def __init__(self, name: str, searched: list[str]):
        self.name = name
        self.searched = searched
        super().__init__(
            f"Agent '{name}' not found. Searched:\n  - " + "\n  - ".join(searched)
        )

def resolve_agent_md(agent_name: str, workflow_dir: Path) -> Path:
    local = workflow_dir / "agents" / f"{agent_name}.md"
    if local.exists():
        return local
    shared = _SHARED_AGENTS_DIR / f"{agent_name}.md"
    if shared.exists():
        return shared
    raise AgentNotFoundError(agent_name, searched=[str(local), str(shared)])
```

**Step 4:** 跑测试通过:

```bash
pytest tests/test_resolve_agent_md.py -v
```

**Step 5:** Commit:

```bash
git add harness/compiler/md_parser.py tests/test_resolve_agent_md.py
git commit -m "feat(compiler): resolve_agent_md with workflow-first, shared-fallback"
```

### Task 1.3: parse_agent_md 支持 `eval: true` frontmatter

**Files:**
- Modify: `harness/compiler/md_parser.py`(parse_agent_md 提取 `eval` 字段)
- Create: `tests/test_md_parser_eval.py`

**Step 1:** 测试 `tests/test_md_parser_eval.py`:

```python
from harness.compiler.md_parser import parse_agent_md

def test_parse_eval_true(tmp_path):
    p = tmp_path / "a.md"
    p.write_text("---\nname: a\neval: true\n---\nbody")
    parsed = parse_agent_md(p)
    assert parsed["eval"] is True

def test_parse_eval_default_false(tmp_path):
    p = tmp_path / "b.md"
    p.write_text("---\nname: b\n---\nbody")
    parsed = parse_agent_md(p)
    assert parsed.get("eval", False) is False
```

**Step 2:** 跑测试 fail。

**Step 3:** 在 `parse_agent_md` 输出中加 `eval` 字段(默认 False)。

**Step 4:** 跑测试通过。

**Step 5:** Commit:

```bash
git add harness/compiler/md_parser.py tests/test_md_parser_eval.py
git commit -m "feat(compiler): parse_agent_md supports eval frontmatter"
```

### Task 1.4: Workflow 类改造为 workflow_dir(TDD)

**Files:**
- Modify: `harness/api.py`(`Workflow.__init__`、`load`、`save`、`to_dict`、`from_dict`、`list_saved`;`Agent.eval` 字段)
- Create: `tests/test_workflow_dir_layout.py`

**Step 1:** 测试 `tests/test_workflow_dir_layout.py`:

```python
import json
from pathlib import Path
from harness.api import Workflow, Agent

def test_save_creates_workflow_dir_and_subdirs(tmp_path, monkeypatch):
    monkeypatch.setattr("harness.api._WORKFLOWS_DIR", tmp_path)
    wf = Workflow("demo", agents=[Agent("a")])
    path = wf.save()
    assert path == tmp_path / "demo" / "workflow.json"
    assert (tmp_path / "demo" / "agents").is_dir()
    assert (tmp_path / "demo" / "scripts").is_dir()
    data = json.loads(path.read_text())
    assert "agents_dir" not in data

def test_load_uses_new_layout(tmp_path, monkeypatch):
    monkeypatch.setattr("harness.api._WORKFLOWS_DIR", tmp_path)
    wf_dir = tmp_path / "demo"
    (wf_dir / "agents").mkdir(parents=True)
    (wf_dir / "scripts").mkdir()
    (wf_dir / "workflow.json").write_text(json.dumps({
        "name": "demo",
        "agents": [{"name": "a", "after": [], "eval": True}],
    }))
    wf = Workflow.load("demo")
    assert wf.workflow_dir == wf_dir
    assert wf.agents[0].eval is True

def test_agent_eval_default_false():
    a = Agent("x")
    assert a.eval is False
```

**Step 2:** 跑测试 fail。

**Step 3:** 修改 `harness/api.py`:
- `Agent.__init__` 加 `eval: bool = False` 参数,`to_dict`/`from_dict` 含 `eval`
- `Workflow.__init__` 移除 `agents_dir` 参数,新增 `workflow_dir: Path | None = None`(默认 `_WORKFLOWS_DIR / name`)
- `save()` 创建 workflow_dir + agents/ + scripts/,写 `workflow.json`
- `load()` 从 `_WORKFLOWS_DIR / name / "workflow.json"` 读取,自动设 `workflow_dir`
- `to_dict()` 去掉 `agents_dir`
- `from_dict()` 不再读 `agents_dir`,改用调用方传入 `workflow_dir`
- `list_saved()` 扫描 `_WORKFLOWS_DIR.glob("*/workflow.json")` 而非 `*.json`

**Step 4:** 跑测试通过。

**Step 5:** Commit:

```bash
git add harness/api.py tests/test_workflow_dir_layout.py
git commit -m "feat(api): Workflow uses workflow_dir; Agent.eval field"
```

### Task 1.5: MacroGraphBuilder 改用 resolve_agent_md

**Files:**
- Modify: `harness/engine/macro_graph.py`(读 agent MD 处改 `resolve_agent_md(name, workflow.workflow_dir)`)
- Modify: `harness/run_store.py`(snapshot agent MD 时同样用 `resolve_agent_md`)

**Step 1:** 找到 macro_graph.py 中所有 `Path(workflow.agents_dir) / f"{name}.md"` 之类的拼接,替换为 `resolve_agent_md(name, workflow.workflow_dir)`。

**Step 2:** run_store.py 中 snapshot 逻辑同样替换。

**Step 3:** 已有测试用例(test_workflow_dir_layout 等)端到端验证:跑 `pytest tests/ -q`,期望 macro_graph 相关测试通过。

**Step 4:** Commit:

```bash
git add harness/engine/macro_graph.py harness/run_store.py
git commit -m "feat(engine): macro_graph + run_store use resolve_agent_md"
```

### Task 1.6: build_node_prompt 注入 scripts 路径(TDD)

**Files:**
- Modify: `harness/engine/micro_agent.py`(`build_node_prompt` 末尾若 scripts 目录非空,追加 `## Available scripts` 段)
- Create: `tests/test_script_path_injection.py`

**Step 1:** 测试:

```python
from pathlib import Path
from harness.engine.micro_agent import MicroAgentFactory

def test_injects_when_private_scripts_exist(tmp_path, monkeypatch):
    wf_dir = tmp_path / "demo"
    (wf_dir / "scripts").mkdir(parents=True)
    (wf_dir / "scripts" / "x.py").write_text("# noop")
    monkeypatch.setattr("harness.engine.micro_agent._SHARED_SCRIPTS_DIR",
                         tmp_path / "_empty")
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        inputs={"task": "run x"},
        upstream_outputs={},
        workflow_dir=wf_dir,
    )
    assert "## Available scripts" in prompt
    assert str(wf_dir / "scripts") in prompt

def test_no_injection_when_both_empty(tmp_path, monkeypatch):
    wf_dir = tmp_path / "demo"
    (wf_dir / "scripts").mkdir(parents=True)
    monkeypatch.setattr("harness.engine.micro_agent._SHARED_SCRIPTS_DIR",
                         tmp_path / "_empty_shared")
    factory = MicroAgentFactory()
    prompt = factory.build_node_prompt(
        inputs={"task": "x"},
        upstream_outputs={},
        workflow_dir=wf_dir,
    )
    assert "## Available scripts" not in prompt
```

**Step 2:** 跑测试 fail。

**Step 3:** 实现:
- `MicroAgentFactory.build_node_prompt` 加 `workflow_dir: Path | None = None` 参数
- 末尾检查私有 + 共享 scripts 目录,只要至少一边有文件(非空、忽略 .gitkeep)就追加 `## Available scripts ...` 段
- 调用方(MacroGraphBuilder)传入 `workflow.workflow_dir`

**Step 4:** 跑测试通过。

**Step 5:** Commit:

```bash
git add harness/engine/micro_agent.py tests/test_script_path_injection.py
git commit -m "feat(engine): inject scripts paths into node prompt when present"
```

### Task 1.7: server/routes.py 改造

**Files:**
- Modify: `server/routes.py`(`GET /api/workflows/definitions` 扫目录;`/api/agents/{name}/md` 改 query 参数)
- Modify: `server/schemas.py`(`AgentDef.eval: bool = False`,请求字段加 `workflow` / `target`)
- Modify: `server/runner.py`(创建 Workflow 时传 workflow_dir 而非 agents_dir)

**Step 1:** schemas.py 调整:
- `AgentDef` 加 `eval: bool = False`
- `CreateWorkflowRequest` 去掉 `agents_dir`,默认 workflow_dir 由 name 推导
- agent MD 请求/响应字段 `agents_dir` → `workflow`,PUT body 加可选 `target: Literal["private","shared"] = "private"`

**Step 2:** routes.py:
- `definitions` 端点扫 `_WORKFLOWS_DIR.glob("*/workflow.json")`,排除 `_shared` 目录
- `GET /api/agents/{name}/md?workflow=xxx` — 用 `resolve_agent_md(name, _WORKFLOWS_DIR / workflow)`
- `PUT /api/agents/{name}/md` — `target=private` 写 `workflow_dir/agents/<name>.md`;`target=shared` 写 `_SHARED_AGENTS_DIR/<name>.md`
- `POST /api/workflows` — 创建时 `Workflow(name, agents).save()` 自动建目录

**Step 3:** runner.py 用 `Workflow.load(name)` 即可,workflow_dir 自动设。

**Step 4:** 测试用现有 server 测试集 + 新增 `tests/test_routes_new_layout.py`(definitions 扫描、agent MD CRUD 双 target)。

**Step 5:** Commit:

```bash
git add server/ tests/test_routes_new_layout.py
git commit -m "feat(server): API + schemas for workflow directory layout"
```

### Task 1.8: 前端 — AgentEditor 支持 workflow query + target

**Files:**
- Modify: `frontend/src/types/events.ts`(Workflow 类型加 `eval` 字段;agent MD API 调用 query 参数 `workflow`)
- Modify: `frontend/src/components/agent/AgentEditorModal.tsx`(打开/保存路径区分 private vs shared)

**Step 1:** types/events.ts 中 `WorkflowDefinition.agents[].eval?: boolean`;API 客户端调用 `?workflow=xxx`。

**Step 2:** AgentEditorModal.tsx:
- 加载时传 `workflow` query
- 保存时 body 含 `workflow` 字段;UI 加单选 "保存到 workflow 私有 / 保存到共享池"(默认私有);PUT 时把选择传入 `target`

**Step 3:** 启动前端 `npm run dev`,在 UI 点开一个 agent,验证读写都走新参数(浏览器 Network 面板查看)。

**Step 4:** Commit:

```bash
git add frontend/
git commit -m "feat(ui): agent editor uses workflow query + private/shared target"
```

### Task 1.9: 迁移脚本(TDD)

**Files:**
- Create: `scripts/migrate_workflows_to_dirs.py`
- Create: `workflows/_shared/agents/runner.md`(新通用 runner)
- Create: `workflows/_shared/scripts/.gitkeep`
- Create: `tests/test_migrate_workflows.py`
- Modify: `.gitignore`(加 `.backup_pre_migration/`)

**Step 1:** 测试 `tests/test_migrate_workflows.py`:

```python
import json
import shutil
from pathlib import Path
from scripts.migrate_workflows_to_dirs import migrate

def _setup_old_layout(root: Path) -> None:
    (root / "agents").mkdir(parents=True)
    (root / "agents" / "a.md").write_text("---\nname: a\n---\nA")
    (root / "agents" / "b.md").write_text("---\nname: b\n---\nB")
    (root / "agents" / "orphan.md").write_text("---\nname: orphan\n---\nO")
    (root / "workflows").mkdir()
    (root / "workflows" / "wf1.json").write_text(json.dumps({
        "name": "wf1",
        "agents": [{"name": "a", "after": []}],
    }))
    (root / "workflows" / "wf2.json").write_text(json.dumps({
        "name": "wf2",
        "agents": [{"name": "a", "after": []}, {"name": "b", "after": ["a"]}],
    }))

def test_dry_run_writes_nothing(tmp_path):
    _setup_old_layout(tmp_path)
    snap = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    migrate(root=tmp_path, dry_run=True)
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert snap == after

def test_creates_workflow_dirs(tmp_path):
    _setup_old_layout(tmp_path)
    migrate(root=tmp_path, dry_run=False)
    assert (tmp_path / "workflows" / "wf1" / "workflow.json").exists()
    assert (tmp_path / "workflows" / "wf1" / "agents" / "a.md").exists()
    assert (tmp_path / "workflows" / "wf2" / "agents" / "a.md").exists()  # 复制一份
    assert (tmp_path / "workflows" / "wf2" / "agents" / "b.md").exists()
    new_json = json.loads((tmp_path / "workflows" / "wf1" / "workflow.json").read_text())
    assert "agents_dir" not in new_json

def test_orphan_to_backup(tmp_path):
    _setup_old_layout(tmp_path)
    migrate(root=tmp_path, dry_run=False)
    assert (tmp_path / ".backup_pre_migration" / "orphan_agents" / "orphan.md").exists()

def test_originals_backed_up(tmp_path):
    _setup_old_layout(tmp_path)
    migrate(root=tmp_path, dry_run=False)
    assert (tmp_path / ".backup_pre_migration" / "agents").exists()
    assert (tmp_path / ".backup_pre_migration" / "workflows" / "wf1.json").exists()
```

**Step 2:** 跑测试 fail(模块不存在)。

**Step 3:** 实现 `scripts/migrate_workflows_to_dirs.py`:

```python
"""一次性迁移:workflows/*.json + agents/*.md → workflows/<name>/{workflow.json, agents/, scripts/}

用法:
    python scripts/migrate_workflows_to_dirs.py --dry-run    # 预览
    python scripts/migrate_workflows_to_dirs.py              # 执行
"""
from __future__ import annotations
import argparse, json, shutil
from pathlib import Path

def migrate(root: Path, dry_run: bool = False) -> None:
    old_workflows = sorted((root / "workflows").glob("*.json"))
    old_agents_dir = root / "agents"
    new_root = root / "workflows"
    backup = root / ".backup_pre_migration"

    # 收集每个 workflow 引用的 agent
    refs: dict[str, list[str]] = {}
    for wf_json in old_workflows:
        data = json.loads(wf_json.read_text())
        refs[data["name"]] = [a["name"] for a in data.get("agents", [])]
    used = {n for names in refs.values() for n in names}

    actions: list[str] = []
    for wf_json in old_workflows:
        data = json.loads(wf_json.read_text())
        wf_dir = new_root / data["name"]
        actions.append(f"mkdir {wf_dir}/agents, {wf_dir}/scripts")
        for a in data.get("agents", []):
            src = old_agents_dir / f"{a['name']}.md"
            if src.exists():
                actions.append(f"copy {src} → {wf_dir}/agents/{a['name']}.md")
        # 去除 agents_dir 字段
        new_data = {"name": data["name"], "agents": data.get("agents", [])}
        actions.append(f"write {wf_dir}/workflow.json (without agents_dir)")
    for md in sorted(old_agents_dir.glob("*.md") if old_agents_dir.exists() else []):
        if md.stem not in used:
            actions.append(f"move {md} → {backup}/orphan_agents/{md.name}")
    actions.append(f"move {old_agents_dir} → {backup}/agents")
    for wf_json in old_workflows:
        actions.append(f"move {wf_json} → {backup}/workflows/{wf_json.name}")

    if dry_run:
        print("DRY RUN — planned actions:")
        for a in actions:
            print("  ", a)
        return

    # 执行
    backup.mkdir(parents=True, exist_ok=True)
    (backup / "workflows").mkdir(exist_ok=True)
    (backup / "orphan_agents").mkdir(exist_ok=True)
    for wf_json in old_workflows:
        data = json.loads(wf_json.read_text())
        wf_dir = new_root / data["name"]
        (wf_dir / "agents").mkdir(parents=True, exist_ok=True)
        (wf_dir / "scripts").mkdir(exist_ok=True)
        for a in data.get("agents", []):
            src = old_agents_dir / f"{a['name']}.md"
            if src.exists():
                shutil.copy2(src, wf_dir / "agents" / f"{a['name']}.md")
        new_data = {"name": data["name"], "agents": data.get("agents", [])}
        (wf_dir / "workflow.json").write_text(
            json.dumps(new_data, indent=2, ensure_ascii=False)
        )
    if old_agents_dir.exists():
        for md in sorted(old_agents_dir.glob("*.md")):
            if md.stem not in used:
                shutil.move(str(md), backup / "orphan_agents" / md.name)
        shutil.move(str(old_agents_dir), backup / "agents")
    for wf_json in old_workflows:
        if wf_json.exists():
            shutil.move(str(wf_json), backup / "workflows" / wf_json.name)
    print(f"✓ Migration complete. Originals backed up to {backup}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--root", default=".", type=Path)
    args = parser.parse_args()
    migrate(args.root, dry_run=args.dry_run)
```

**Step 4:** 跑测试通过。

**Step 5:** 创建 `workflows/_shared/agents/runner.md` 内容:

```markdown
---
name: runner
tools: [bash]
---

你是一个脚本执行器。任务流程:
1. 根据用户给的命令或脚本名,找到要执行的命令(私有脚本在 ./scripts/,共享脚本在 ../_shared/scripts/)
2. 创建 logs/ 目录(若不存在)
3. 执行命令时把 stdout 和 stderr 重定向到 logs/<script_name>.log:
   bash -c "<command> > logs/<name>.log 2>&1 &"
4. 持续 tail / 检查日志,直到看到完成标志或进程退出
5. 返回执行结果摘要(成功/失败 + 关键日志片段)
```

**Step 6:** 创建 `workflows/_shared/scripts/.gitkeep`(空文件)。

**Step 7:** `.gitignore` 追加:

```
.backup_pre_migration/
```

**Step 8:** 实际跑迁移(在项目根):

```bash
python scripts/migrate_workflows_to_dirs.py --dry-run
python scripts/migrate_workflows_to_dirs.py
```

确认 `workflows/code_review/`, `workflows/demo_pipeline/` 等目录生成,旧 `agents/` 和 `workflows/*.json` 进 `.backup_pre_migration/`。

**Step 9:** Commit:

```bash
git add scripts/migrate_workflows_to_dirs.py tests/test_migrate_workflows.py \
        workflows/_shared/ .gitignore
git add workflows/  # 迁移后新生成的 workflow 目录
git commit -m "feat: migrate workflows to per-directory layout + shared runner"
```

### Task 1.10: Stage 1 验收 — examples 1-9 全通过

**Files:** 跑现有 examples 而非改动。

**Step 1:** 跑全部测试:

```bash
pytest tests/ -q
```

期望:绿。

**Step 2:** 手动跑每个 example,确认运行不报错:

```bash
python examples/01_quickstart.py
python examples/02_save_load.py
python examples/03_pipeline.py
python examples/04_chart_demo.py    # 注意:此 example 之后 Task 3.1 会改文案
python examples/05_trace_demo.py
python examples/06_agent_to_ui.py
python examples/07_parallel.py
python examples/08_coder_review_loop.py
python examples/09_ask_human.py
```

**Step 3:** 如发现 example 使用旧 `agents_dir` API 报错,逐个修复(应在 Task 1.4 已兼容,但保留兜底空间)。每个修复独立 commit。

**Step 4:** 阶段性 commit(若有 example 修复):

```bash
git add examples/
git commit -m "fix(examples): adapt to workflow directory layout"
```

**Stage 1 完成。暂停,人工 review 后再进入 Stage 2。**

---

## Stage 2 — EvalJudge 核心

### Task 2.1: 更新 SPEC.md §Eval + extensions/eval/SPEC.md

**Files:**
- Modify: `SPEC.md`(§Eval 章节从占位填充)
- Modify: `harness/extensions/eval/SPEC.md`(透传 / lazy summarizer / score / 错误处理)

**Step 1:** SPEC.md §Eval 写入:接口签名(EvalJudge 构造参数、ReviewDecision 含 score)、用法示例、与 §ConditionalEdge / §RunStore / §Chart 的关系交叉引用。

**Step 2:** extensions/eval/SPEC.md 增补 4 节:
- "Pass 时透传 outputs":`_judge_X` 节点写 `outputs[judge_name] = outputs[target_name]`,judgment 写 `metadata[judge_name]["judgment"]`
- "Lazy summarizer":首次执行 judge 时调 LLM 总结 target MD,缓存到 `.eval_cache/_judge_<target>_summary.md`,SHA256 key
- "score 字段":可选,非 None 时 emit line chart(EventBus 通道,label="Eval Scores")
- "Judge 错误":exception 当 node 失败(写 errors),不静默放过

**Step 3:** Commit:

```bash
git add SPEC.md harness/extensions/eval/SPEC.md
git commit -m "spec: EvalJudge — passthrough, lazy summarizer, score, errors"
```

### Task 2.2: ReviewDecision 新增 score(TDD)

**Files:**
- Create: `harness/extensions/eval/decisions.py`
- Create: `harness/extensions/eval/__init__.py`(导出)
- Create: `harness/extensions/eval/test_decisions.py`

**Step 1:** 测试:

```python
from harness.extensions.eval import ReviewDecision

def test_score_optional_default_none():
    r = ReviewDecision(decision="pass", reason="ok")
    assert r.score is None

def test_score_accepts_float():
    r = ReviewDecision(decision="pass", reason="ok", score=0.85)
    assert r.score == 0.85
```

**Step 2:** 跑测试 fail。

**Step 3:** 实现 `decisions.py`:

```python
from pydantic import BaseModel
from typing import Literal

class ReviewDecision(BaseModel):
    decision: Literal["pass", "fail"]
    reason: str
    score: float | None = None
```

`__init__.py`:

```python
from harness.extensions.eval.decisions import ReviewDecision
__all__ = ["ReviewDecision"]
```

**Step 4:** 跑测试通过。

**Step 5:** Commit:

```bash
git add harness/extensions/eval/
git commit -m "feat(eval): ReviewDecision with optional score"
```

### Task 2.3: EvalJudge GraphMutator — 改 DAG(TDD)

**Files:**
- Create: `harness/extensions/eval/judge.py`(`EvalJudge(BaseGraphMutator)`)
- Modify: `harness/extensions/eval/__init__.py`(导出 `EvalJudge`)
- Create: `harness/extensions/eval/test_judge_mutate.py`

**Step 1:** 测试 — 验证 DAG 改造,不跑 LLM:

```python
from harness.api import Agent, Workflow
from harness.extensions.eval import EvalJudge

def test_inserts_judge_node():
    wf = Workflow("t", agents=[
        Agent("x", eval=True),
        Agent("y", after=["x"]),
    ])
    EvalJudge().mutate(wf)
    names = [a.name for a in wf.agents]
    assert "_judge_x" in names

def test_skips_when_no_eval_true():
    wf = Workflow("t", agents=[Agent("x"), Agent("y", after=["x"])])
    original = [a.name for a in wf.agents]
    EvalJudge().mutate(wf)
    assert [a.name for a in wf.agents] == original

def test_downstream_rewired():
    wf = Workflow("t", agents=[
        Agent("x", eval=True),
        Agent("y", after=["x"]),
    ])
    EvalJudge().mutate(wf)
    y = next(a for a in wf.agents if a.name == "y")
    assert "_judge_x" in y.after
    assert "x" not in y.after

def test_on_fail_loops_back():
    wf = Workflow("t", agents=[Agent("x", eval=True), Agent("y", after=["x"])])
    EvalJudge().mutate(wf)
    j = next(a for a in wf.agents if a.name == "_judge_x")
    assert j.on_fail == "x"

def test_on_pass_routes_to_single_downstream():
    wf = Workflow("t", agents=[Agent("x", eval=True), Agent("y", after=["x"])])
    EvalJudge().mutate(wf)
    j = next(a for a in wf.agents if a.name == "_judge_x")
    assert j.on_pass == "y"

def test_multi_downstream_uses_passthrough():
    wf = Workflow("t", agents=[
        Agent("x", eval=True),
        Agent("y", after=["x"]),
        Agent("z", after=["x"]),
    ])
    EvalJudge().mutate(wf)
    names = [a.name for a in wf.agents]
    assert "_judge_x_passthrough" in names
    j = next(a for a in wf.agents if a.name == "_judge_x")
    assert j.on_pass == "_judge_x_passthrough"
    pt = next(a for a in wf.agents if a.name == "_judge_x_passthrough")
    assert set(pt.after) == {"_judge_x"}
    y = next(a for a in wf.agents if a.name == "y")
    z = next(a for a in wf.agents if a.name == "z")
    assert "_judge_x_passthrough" in y.after
    assert "_judge_x_passthrough" in z.after
```

**Step 2:** 跑测试 fail。

**Step 3:** 实现 `judge.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
from harness.api import Agent
from harness.extensions.base import BaseGraphMutator

@dataclass
class EvalJudge(BaseGraphMutator):
    name: str = "eval-judge"
    judge_model: str | None = None
    max_retries: int = 2

    def mutate(self, workflow):
        targets = [a for a in workflow.agents if getattr(a, "eval", False)]
        for x in targets:
            judge_name = f"_judge_{x.name}"
            downstream = [a for a in workflow.agents if x.name in a.after]
            if len(downstream) <= 1:
                on_pass_target = downstream[0].name if downstream else None
                passthrough = None
            else:
                pt_name = f"_judge_{x.name}_passthrough"
                passthrough = Agent(pt_name, after=[judge_name])
                on_pass_target = pt_name
            judge = Agent(
                judge_name,
                after=[x.name],
                model=self.judge_model,
                on_pass=on_pass_target,
                on_fail=x.name,
            )
            # 标记便于运行时识别
            judge._eval_target = x.name
            for d in downstream:
                d.after = [
                    (on_pass_target if passthrough else judge_name) if dep == x.name else dep
                    for dep in d.after
                ]
            workflow.agents.append(judge)
            if passthrough:
                workflow.agents.append(passthrough)
        return workflow
```

`__init__.py`:

```python
from harness.extensions.eval.decisions import ReviewDecision
from harness.extensions.eval.judge import EvalJudge
__all__ = ["ReviewDecision", "EvalJudge"]
```

**Step 4:** 跑测试通过。

**Step 5:** Commit:

```bash
git add harness/extensions/eval/judge.py harness/extensions/eval/__init__.py \
        harness/extensions/eval/test_judge_mutate.py
git commit -m "feat(eval): EvalJudge GraphMutator (DAG rewrite + passthrough)"
```

### Task 2.4: Lazy summarizer + cache

**Files:**
- Create: `harness/extensions/eval/summarizer.py`
- Create: `harness/extensions/eval/test_summarizer.py`
- Modify: `.gitignore`(加 `.eval_cache/`)

**Step 1:** 测试 — mock LLM 调用,只验证缓存读写逻辑:

```python
import hashlib
from pathlib import Path
from harness.extensions.eval.summarizer import summarize_target, _cache_path

def test_cache_path_uses_sha256(tmp_path):
    md = "---\nname: x\n---\nbody"
    h = hashlib.sha256(md.encode()).hexdigest()[:16]
    assert _cache_path(tmp_path, "x", md).name == f"_judge_x_summary.{h}.md"

def test_returns_cached_when_present(tmp_path):
    md = "---\nname: x\n---\nbody"
    p = _cache_path(tmp_path, "x", md)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("cached summary")
    result = summarize_target("x", md, workflow_dir=tmp_path, llm_call=lambda *_: "FRESH")
    assert result == "cached summary"

def test_writes_cache_when_missing(tmp_path):
    md = "---\nname: y\n---\nbody"
    result = summarize_target("y", md, workflow_dir=tmp_path, llm_call=lambda *_: "FRESH")
    assert result == "FRESH"
    p = _cache_path(tmp_path, "y", md)
    assert p.read_text() == "FRESH"

def test_cache_invalidates_on_md_change(tmp_path):
    summarize_target("z", "v1", workflow_dir=tmp_path, llm_call=lambda *_: "S1")
    new = summarize_target("z", "v2", workflow_dir=tmp_path, llm_call=lambda *_: "S2")
    assert new == "S2"
```

**Step 2:** 跑测试 fail。

**Step 3:** 实现:

```python
"""Lazy summarizer for EvalJudge: read target agent MD → ask LLM to summarize
its task and red lines → cache by SHA256 of the MD content under .eval_cache/.
"""
from __future__ import annotations
import hashlib
from pathlib import Path
from typing import Callable

_CACHE_DIRNAME = ".eval_cache"

def _cache_path(workflow_dir: Path, target_name: str, md_content: str) -> Path:
    h = hashlib.sha256(md_content.encode()).hexdigest()[:16]
    return workflow_dir / _CACHE_DIRNAME / f"_judge_{target_name}_summary.{h}.md"

def _default_llm_call(target_name: str, md_content: str) -> str:
    """Real LLM call. Imports lazily to keep test isolation cheap."""
    from harness.engine.llm_client import LLMClient
    client = LLMClient()
    agent = client.agent(
        system_prompt=(
            "你的任务:阅读下面的 agent Markdown 定义,用 2-3 段简要总结:\n"
            "1. 这个 agent 的目标和职责\n"
            "2. 它必须遵守的红线/约束(若有)\n"
            "输出纯文本,作为评测员的判断依据。"
        ),
        output_type=str,
    )
    result = agent.run_sync(md_content)
    return str(result.output)

def summarize_target(
    target_name: str,
    md_content: str,
    workflow_dir: Path,
    llm_call: Callable[[str, str], str] | None = None,
) -> str:
    cache = _cache_path(workflow_dir, target_name, md_content)
    if cache.exists():
        return cache.read_text()
    fn = llm_call or _default_llm_call
    summary = fn(target_name, md_content)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(summary)
    return summary
```

**Step 4:** 跑测试通过。

**Step 5:** `.gitignore` 追加 `.eval_cache/`。

**Step 6:** Commit:

```bash
git add harness/extensions/eval/summarizer.py harness/extensions/eval/test_summarizer.py .gitignore
git commit -m "feat(eval): lazy summarizer with SHA256-keyed cache"
```

### Task 2.5: MacroGraphBuilder — judge 节点函数 + 透传 + critique 注入

**Files:**
- Modify: `harness/engine/macro_graph.py`
- Modify: `harness/engine/micro_agent.py`(`build_node_prompt` 注入 `## Previous judgment` + 显示名重写)
- Create: `tests/test_judge_runtime.py`

**Step 1:** 测试(集成测试,使用 mock LLM):

```python
import pytest
from unittest.mock import patch
from harness.api import Agent, Workflow
from harness.extensions.eval import EvalJudge, ReviewDecision

def _stub_judge(*, decisions):
    """Replace judge agent runs with a sequence of ReviewDecision results."""
    it = iter(decisions)
    async def run(*a, **kw):
        return next(it)
    return run

@pytest.mark.asyncio
async def test_passthrough_outputs_to_downstream(tmp_path):
    # … workflow with 1 eval target + 1 downstream
    # Stub: target returns "RESULT"; judge returns pass.
    # Assert: downstream node receives "RESULT" in its upstream_outputs (not ReviewDecision).
    ...

@pytest.mark.asyncio
async def test_critique_injected_on_loopback(tmp_path):
    # Stub: judge first returns fail(reason="bad"), then pass.
    # Capture prompt of target's 2nd execution. Assert "## Previous judgment" and "bad" appear.
    ...

@pytest.mark.asyncio
async def test_judge_error_marks_failed():
    # Stub: judge raises. Assert workflow result.errors["_judge_X"] is set; downstream skipped.
    ...

@pytest.mark.asyncio
async def test_max_iterations_bounded():
    # Stub: judge always returns fail. Confirm loop exits after max_iterations.
    ...
```

(测试骨架先写,真正实现 stub 在 Step 3 完成后回填。)

**Step 2:** 跑测试 fail。

**Step 3:** 实现 `MacroGraphBuilder`(在 `build()` 方法中)处理 `_judge_X` 节点的特殊节点函数:

```python
# 伪代码
def _build_judge_node_fn(self, judge_agent, target_name, summarizer):
    async def fn(state):
        # 1. lazy 总结(首次)
        target_md = resolve_agent_md(target_name, workflow.workflow_dir).read_text()
        summary = summarize_target(target_name, target_md, workflow.workflow_dir)

        # 2. 拼装 judge system_prompt(三段)
        sys = (
            "你是一个评测员。以下是上一个 agent 的任务和任务结果,你来判断它是否完成。\n\n"
            f"## 上游 agent 的任务与红线(自动总结)\n{summary}\n\n"
            "## 评测标准\n"
            "- decision: 'pass'/'fail'\n"
            "- reason: 具体评语\n"
            "- score: 0.0-1.0(可选)\n"
        )
        target_output = state[STATE_OUTPUTS].get(target_name)

        # 3. 跑 judge agent
        try:
            review = await _run_pydantic_agent(
                sys_prompt=sys,
                user_msg=f"## Output from {target_name}\n{target_output}",
                model=judge_agent.model,
                result_type=ReviewDecision,
            )
        except Exception as e:
            return {STATE_ERRORS: {judge_agent.name: str(e)}}

        # 4. emit score chart(若有)
        history = (state.get(STATE_METADATA, {}).get(judge_agent.name, {}).get("score_history", []) or [])
        new_history = history + ([review.score] if review.score is not None else [])
        if review.score is not None and self.event_bus is not None:
            self.event_bus.emit("chart.render", {
                "node_id": judge_agent.name,
                "chart_type": "line",
                "data": [{"iteration": i+1, "score": s} for i, s in enumerate(new_history)],
                "x": "iteration", "y": "score",
                "label": "Eval Scores",
                "title": f"{target_name} quality",
            })

        # 5. 透传 outputs[judge] = outputs[target];judgment 写 metadata
        return {
            STATE_OUTPUTS: {judge_agent.name: target_output},
            STATE_METADATA: {judge_agent.name: {
                "judgment": review.model_dump(),
                "score_history": new_history,
                "target": target_name,
            }},
        }
    return fn
```

**Step 4:** `MacroGraphBuilder.build()` 中识别 `getattr(agent, '_eval_target', None)`:`None` 走原 LLM 节点函数;非 None 走 `_build_judge_node_fn`。

**Step 5:** condition_fn 修改 — 对 judge 节点从 `metadata[judge_name]["judgment"]["decision"]` 读路由(不是 `outputs[judge].decision`)。

**Step 6:** passthrough 节点函数:no-op — 输出来自 `outputs[_judge_X]`(已是 target 的原始输出),透传不变。

**Step 7:** `build_node_prompt` 改造:
- 增加 `judge_metadata: dict | None = None` 参数,接收 `state[STATE_METADATA]`
- 遍历当前 agent 的 `after`,对每个 dep 若 metadata 里有对应 `_judge_dep` 的 `judgment` 字段 → 注入 `## Previous judgment (from _judge_<dep>)` 段
- 显示名重写:upstream_outputs 中 key 名 `_judge_X` 在 prompt 里渲染为 `X`

**Step 8:** 补全 Step 1 中测试的实现细节,跑全部 judge runtime 测试通过。

**Step 9:** Commit:

```bash
git add harness/engine/macro_graph.py harness/engine/micro_agent.py tests/test_judge_runtime.py
git commit -m "feat(engine): judge node fn — passthrough, critique inject, score chart"
```

### Task 2.6: Snapshot 处理 — _judge_X 的 md_content

**Files:**
- Modify: `harness/run_store.py`

**Step 1:** snapshot 收集时,对 `getattr(agent, "_eval_target", None) is not None` 的 agent:
- 不调用 `resolve_agent_md`(没有 MD 文件)
- `md_content` 写入"完整组装后的 system_prompt"(三段拼接 — 通过运行时缓存或重新组装)
- frontmatter 写入 `auto_generated: true`, `target: <X>`, `result_type: ReviewDecision`

**Step 2:** 新增测试 `tests/test_judge_snapshot.py` — 跑 mini workflow 后从 `runs/` 读出 snapshot,断言 `_judge_X` 出现且 md_content 含 "评测员" 关键词。

**Step 3:** Commit:

```bash
git add harness/run_store.py tests/test_judge_snapshot.py
git commit -m "feat(run_store): synthesize md_content for _judge_X snapshot"
```

### Task 2.7: Stage 2 验收

**Step 1:** 跑全套测试:

```bash
pytest tests/ harness/ -q
```

期望:绿。

**Step 2:** 手跑 examples 1-9 一遍,确认 EvalJudge 没破坏现有功能(因为 Agent 加了 `eval: bool = False` 默认 False,所有现有 workflow 不受影响)。

**Step 3:** Stage 2 完成。暂停,人工 review 后进入 Stage 3。

---

## Stage 3 — 示例 + 文档收尾

### Task 3.1: 改造 examples/04_chart_demo.py

**Files:**
- Modify: `examples/04_chart_demo.py`
- 注意:`examples/chart_script.py` 已在 Task 1.9 复制到 `workflows/chart_demo/scripts/`

**Step 1:** 修改 04 的 print 提示:任务示例从 `python examples/chart_script.py` 改为 `运行 chart_script.py`(让 runner agent 自己从 prompt 注入的 scripts 路径里找)。

**Step 2:** 跑一次 e2e:

```bash
python examples/04_chart_demo.py
bash examples/launch_ui.sh
# 在 UI 选 chart_demo,task 输入 "运行 chart_script.py",确认 chart 显示
```

**Step 3:** Commit:

```bash
git add examples/04_chart_demo.py
git commit -m "chore(examples): 04 uses relative script name + runner-resolved path"
```

### Task 3.2: 新增 examples/10_eval_judge.py

**Files:**
- Create: `examples/10_eval_judge.py`
- Create: `workflows/eval_demo/workflow.json`
- Create: `workflows/eval_demo/agents/researcher.md`
- Create: `workflows/eval_demo/agents/writer.md`

**Step 1:** 写 researcher.md(简单做某个调研任务)、writer.md(基于 researcher 输出写文档)。

**Step 2:** examples/10_eval_judge.py:

```python
"""#10 — EvalJudge demo: insert an auto judge between researcher and writer."""
from harness.api import Agent, Workflow
from harness.extensions.eval import EvalJudge

wf = (
    Workflow("eval_demo", agents=[
        Agent("researcher", eval=True),
        Agent("writer", after=["researcher"]),
    ])
    .use(EvalJudge(max_retries=2))
)
wf.save()
print("Saved workflows/eval_demo/")
print("Run via UI: bash examples/launch_ui.sh → select eval_demo")
```

**Step 3:** 跑 e2e + 在 UI 验证:
- 评测节点出现在 DAG 中(虚线 + pass/fail 标签)
- 触发 fail 回环时 critique 被注入,researcher 第二次执行的 prompt 含 reason
- chart 面板出现 "Eval Scores" 折线图(若 judge 返回了 score)

**Step 4:** Commit:

```bash
git add examples/10_eval_judge.py workflows/eval_demo/
git commit -m "feat(examples): 10_eval_judge — EvalJudge end-to-end demo"
```

### Task 3.3: 文档收尾

**Files:**
- Modify: `README.md`(workflow 目录结构示意 + EvalJudge 简介 + 链接)
- Modify: `contribute.md`(新增 agent 时说明 private vs shared 决策)
- Modify: `harness/extensions/_docs/02_choosing_extension_type.md`(GraphMutator 案例追加 EvalJudge)

**Step 1:** 文档改动小,逐文件 Edit。

**Step 2:** Commit:

```bash
git add README.md contribute.md harness/extensions/_docs/
git commit -m "docs: workflow layout + EvalJudge usage"
```

### Task 3.4: 最终验收

**Step 1:** 全套测试:

```bash
pytest tests/ harness/ -q
```

**Step 2:** Lint / typecheck(若项目配置):

```bash
ruff check .
```

**Step 3:** 手跑全部 examples 一遍:1, 2, 3, 4, 5, 6, 7, 8, 9, 10。

**Step 4:** UI 端到端冒烟:`bash examples/launch_ui.sh`,选 `eval_demo` 触发跑通 + 看到回环 + 看到评分图。

**Step 5:** 准备进入 `finishing-a-development-branch` 决定如何合并。

---

## 关键决策与不变量

| 不变量 | 出处 |
|---|---|
| workflow.json 不含 `agents_dir` | §1 |
| agent 查找:workflow 优先,_shared 兜底 | §1 |
| `_shared/agents/` 只放框架级 runner | §3 |
| bash cwd = 用户 cwd;脚本路径在 prompt 中以绝对路径提示 | §3 |
| pass 时下游收到 X 的原始输出(透传) | §4 |
| judge 错误当节点失败,不静默 | §5 |
| judge MD 由框架运行时组装(三段),用户不写 | §4 |
| judgment 写 metadata,outputs 用于透传 | §4 |

如执行中发现某个不变量与现实冲突,**先回到设计文档讨论再改实现**。

