# SPEC: AgentPrompt 封装 — 一期（收拢现有组件）

> 日期: 2026-05-31
> 状态: DRAFT
> 目标: 将散落在多处的 prompt 拼接逻辑收拢为 `AgentPrompt` 结构体，渲染结果与当前完全一致

---

## 1. 动机

当前 agent prompt 的构建分布在 3 个文件、5+ 个位置：

| 组件 | 文件 | 位置 |
|------|------|------|
| persona (MD) | `macro_graph.py` | L418 |
| output_format 拼接 | `macro_graph.py` | L419-430 |
| task / upstream / judgment / scripts | `micro_agent.py` | L75-121 |
| judge prompt | `macro_graph.py` | L922-948 |
| sub-agent prompt | `sub_agent.py` | L66 (硬编码) |

问题：
1. **开发者不知道 prompt 由什么组成** — 没有单一入口看清全貌
2. **添加新 section 需要找到正确位置手动拼接** — 容易遗漏或顺序错误
3. **无法在构建时校验** — section 缺失时静默跳过而非显式声明

---

## 2. 设计原则

1. **封装前后 prompt 完全一致** — 渲染结果逐字符相同
2. **数据与渲染分离** — `AgentPrompt` 只持有数据，`render()` 负责拼接
3. **最小改动面** — 不改变 `NodeCtx` / middleware 接口（二期考虑）
4. **渐进式迁移** — 普通节点 → judge → sub-agent，每步可独立验证

---

## 3. 当前 Prompt 参考快照

### 3.1 普通节点（以 code_review → planner 为例）

**System message:**

```
你是一个规划专家。请根据分析结果，制定执行计划。输出你的计划摘要。

你的输出必须是 JSON 格式，包含 "summary"（必填，简洁结论）和 "details"（可选，详细说明）字段。


## Output Format
Use tools freely. Before each tool call, briefly state what you intend to do and why.
When finished, respond with JSON matching this schema (no markdown fences):
{
  "type": "object",
  "properties": {
    "summary": {
      "type": "string"
    },
    "details": {
      "type": "string"
    }
  },
  "required": [
    "summary"
  ]
}
```

**User message:**

```
## Task
{
  "code_snippet": "def foo(): pass",
  "language": "python"
}

## Output from analyzer
{"summary": "该函数为空函数，无实际逻辑", "details": "建议添加具体实现"}

## Available scripts (call via bash tool)
- Private (workflow-specific): /path/to/workflows/code_review/scripts
- Shared (cross-workflow):     /path/to/workflows/_shared/scripts
```

> 注：若 `scripts/` 目录为空或不存在，则 `## Available scripts` 整段不出现。
> 若无 `result_type`，则 `## Output Format` 整段不出现。
> 若无 critique，则 `## Previous judgment` 不出现。

### 3.2 Judge 节点

**System message:**

```
你是一个评测员。你的任务是评估上游 agent 的输出质量。

## 评测标准
- decision: 'pass' 或 'fail'
- reason: 具体评语
- score: 0.0-1.0 之间的浮点数(可选)
```

> 若存在 `_judge_<target>.md` 文件，则覆盖为该 MD 的 prompt 内容。
> Judge 不追加 `## Output Format`（直接使用 `ReviewDecision` 作为 `output_type`，Pydantic AI 内部处理）。

**User message:**

```
## 上游 agent「analyzer」的任务与红线
<summarize_target 输出>

## Output from analyzer
{"summary": "...", "details": "..."}
```

### 3.3 Sub-agent

**System message:**

```
You are a sub-agent. Complete the assigned task concisely.
```

**User message:** 直接使用调用方传入的 `task` 字符串，无 section 结构。

---

## 4. Available Scripts 逻辑详解

```
workflow_dir 非空？
├─ No → 不渲染此 section
└─ Yes
   ├─ private_scripts = workflow_dir / "scripts"
   ├─ shared_scripts  = PROJECT_ROOT / "workflows" / "_shared" / "scripts"
   ├─ has_private = _dir_has_real_files(private_scripts)
   │   └─ 目录存在 且 含至少一个非隐藏文件（不以 . 开头）
   ├─ has_shared  = _dir_has_real_files(shared_scripts)
   │   └─ 同上
   └─ has_private OR has_shared？
       ├─ No → 不渲染此 section
       └─ Yes → 渲染：
           ## Available scripts (call via bash tool)
           - Private (workflow-specific): <private_scripts 绝对路径>    ← 仅 has_private 时
           - Shared (cross-workflow):     <shared_scripts 绝对路径>    ← 仅 has_shared 时
```

**目的**：让 agent 知道可以通过 bash 工具执行这些脚本，给出绝对路径方便直接调用。

---

## 5. AgentPrompt 数据结构

```python
# harness/engine/agent_prompt.py

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from pydantic import BaseModel


# ── 辅助 dataclass ──────────────────────────────────────────────


@dataclass
class UpstreamOutput:
    """Single upstream agent's output."""
    agent_name: str          # 原始名称，如 "_judge_analyzer"
    display_name: str        # 展示名称，如 "analyzer"
    content: str             # 序列化后的内容


@dataclass
class ScriptPaths:
    """Resolved script directories for the prompt."""
    private: Path | None = None   # workflow_dir / "scripts"
    shared: Path | None = None    # _SHARED_SCRIPTS_DIR


@dataclass
class OutputFormat:
    """JSON schema + instruction for structured output."""
    schema_json: str         # _strip_schema(...).dumps() 后的 JSON 字符串


@dataclass
class JudgmentCritique:
    """Critique from a judge that returned 'fail' — triggers retry."""
    reason: str


# ── AgentPrompt ─────────────────────────────────────────────────


@dataclass
class AgentPrompt:
    """Complete, explicit description of everything that goes into an agent's prompt.

    All sections are declared upfront.  Adding a new section = adding a field.
    Missing sections are None/empty — they simply don't render.

    Rendering is deterministic: `render_system()` and `render_user()` produce
    the exact same string as the current scattered concatenation logic.
    """

    # ── System message sections ──
    persona: str                              # Agent .md body
    output_format: OutputFormat | None = None  # JSON schema (if result_type)

    # ── User message sections ──
    task_inputs: dict | None = None           # ## Task
    upstream: list[UpstreamOutput] = field(default_factory=list)  # ## Output from X
    critique: JudgmentCritique | None = None   # ## Previous judgment
    scripts: ScriptPaths | None = None         # ## Available scripts

    # ── Rendering ───────────────────────────────────────────────

    def render_system(self) -> str:
        """Render the system message (persona + optional output format)."""
        parts = [self.persona]
        if self.output_format is not None:
            parts.append(
                "\n\n## Output Format\n"
                "Use tools freely. Before each tool call, briefly state what you intend to do and why.\n"
                "When finished, respond with JSON matching this schema (no markdown fences):\n"
                + self.output_format.schema_json
            )
        return "".join(parts)

    def render_user(self) -> str:
        """Render the user message (task + upstream + critique + scripts)."""
        parts = []

        if self.task_inputs:
            parts.append(
                f"## Task\n{json.dumps(self.task_inputs, indent=2, ensure_ascii=False)}"
            )

        for up in self.upstream:
            parts.append(f"## Output from {up.display_name}\n{up.content}")

        if self.critique is not None:
            parts.append(f"## Previous judgment\n{self.critique.reason}")

        if self.scripts is not None:
            script_lines = self._render_scripts()
            if script_lines:
                parts.append(script_lines)

        return "\n\n".join(parts)

    def render_messages(self) -> list[dict]:
        """Render as [system, user] message pair."""
        return [
            {"role": "system", "content": self.render_system()},
            {"role": "user", "content": self.render_user()},
        ]

    # ── Internal helpers ────────────────────────────────────────

    @staticmethod
    def _dir_has_real_files(d: Path) -> bool:
        """Return True iff directory exists and contains at least one non-dotfile."""
        if not d.exists() or not d.is_dir():
            return False
        return any(not p.name.startswith(".") for p in d.iterdir())

    def _render_scripts(self) -> str:
        """Render ## Available scripts section. Returns empty string if no scripts."""
        if self.scripts is None:
            return ""

        has_private = (
            self.scripts.private is not None
            and self._dir_has_real_files(self.scripts.private)
        )
        has_shared = (
            self.scripts.shared is not None
            and self._dir_has_real_files(self.scripts.shared)
        )

        if not has_private and not has_shared:
            return ""

        lines = ["## Available scripts (call via bash tool)"]
        if has_private:
            lines.append(f"- Private (workflow-specific): {self.scripts.private}")
        if has_shared:
            lines.append(f"- Shared (cross-workflow):     {self.scripts.shared}")
        return "\n".join(lines)

    # ── Factory: from current scattered logic ───────────────────

    @classmethod
    def from_node(
        cls,
        *,
        persona: str,
        result_type: type[BaseModel] | None,
        inputs: dict,
        upstream_outputs: dict,
        workflow_dir: Path | None,
        critique: str | None,
    ) -> "AgentPrompt":
        """Build an AgentPrompt from the same inputs as the current scattered logic.

        This is the single migration point: once all callers use this factory,
        the old concatenation code can be removed.
        """
        # output_format
        output_format = None
        if result_type is not None:
            from harness.engine.macro_graph import _strip_schema
            schema = _strip_schema(result_type.model_json_schema())
            output_format = OutputFormat(
                schema_json=json.dumps(schema, indent=2, ensure_ascii=False)
            )

        # upstream
        upstream: list[UpstreamOutput] = []
        for name, output in upstream_outputs.items():
            display = cls._display_name(name)
            if isinstance(output, BaseModel):
                content = output.model_dump_json(indent=2)
            else:
                content = str(output)
            upstream.append(UpstreamOutput(
                agent_name=name,
                display_name=display,
                content=content,
            ))

        # scripts
        scripts = None
        if workflow_dir is not None:
            from harness.paths import get_shared_scripts_dir
            scripts = ScriptPaths(
                private=Path(workflow_dir) / "scripts",
                shared=get_shared_scripts_dir(),
            )

        # critique
        crit = JudgmentCritique(reason=critique) if critique is not None else None

        return cls(
            persona=persona,
            output_format=output_format,
            task_inputs=inputs or None,
            upstream=upstream,
            critique=crit,
            scripts=scripts,
        )

    @staticmethod
    def _display_name(upstream_name: str) -> str:
        """Rewrite _judge_X → X so downstream agents see the target name."""
        if upstream_name.startswith("_judge_"):
            return upstream_name[len("_judge_"):]
        return upstream_name
```

---

## 6. 迁移路径

### Phase 1a: 新增文件，不改旧行为

1. 创建 `harness/engine/agent_prompt.py`，内容如上
2. 编写 `tests/harness/engine/test_agent_prompt.py`：
   - 测试 `render_system()` / `render_user()` 的输出与当前拼接逻辑**逐字符一致**
   - 覆盖：有/无 output_format、有/无 critique、有/无 scripts、有/无 private scripts、empty inputs
   - **黄金文件测试**：硬编码第 3 节的参考快照作为 expected

### Phase 1b: 普通节点迁移

1. 在 `macro_graph.py` 的 `_make_node_func` 中：
   - 用 `AgentPrompt.from_node(...)` 替代 L418-430 的 `augmented_prompt` 拼接
   - 用 `prompt.render_user()` 替代 L525-530 的 `micro_factory.build_node_prompt(...)`
   - 用 `prompt.render_system()` 传给 `micro_factory.create(prompt=...)`
2. `MicroAgentFactory.build_node_prompt()` 标记 `@deprecated`，保留但不删除
3. 运行全量测试验证无回归

### Phase 1c: Judge 节点迁移

1. 在 `_make_judge_node_func` 中构建 `AgentPrompt`：
   - `persona` = judge MD prompt（或 `_default_judge_prompt`）
   - `output_format` = None（judge 使用 `output_type=ReviewDecision`，Pydantic AI 自动处理）
   - `task_inputs` = None
   - `upstream` = `[UpstreamOutput(target_name, target_name, output_text)]`
   - `critique` = None
   - `scripts` = None（judge 不需要脚本）
   - user message 需要特殊处理：judge 的 user message 格式不同于普通节点
     - 含 `## 上游 agent「X」的任务与红线` section

**决策**：Judge prompt 与普通节点结构差异较大（不同的 user section 格式），采用独立子类：

```python
@dataclass
class JudgePrompt(AgentPrompt):
    """Judge agent prompt — different user message format."""
    target_name: str = ""
    target_summary: str = ""  # summarize_target() 输出

    def render_user(self) -> str:
        parts = []
        if self.target_summary:
            parts.append(
                f"## 上游 agent「{self.target_name}」的任务与红线\n{self.target_summary}"
            )
        for up in self.upstream:
            parts.append(f"## Output from {up.display_name}\n{up.content}")
        return "\n\n".join(parts)
```

### Phase 1d: Sub-agent 迁移

Sub-agent 的 prompt 是硬编码的单行字符串，结构极简。不封装为 `AgentPrompt`：
- 改动收益 ≈ 0，增加不必要的复杂度
- 保持现状，仅在其 docstring 中注明"参见 AgentPrompt 设计"

---

## 7. 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `harness/engine/agent_prompt.py` | **新增** | AgentPrompt + 辅助 dataclass |
| `tests/harness/engine/test_agent_prompt.py` | **新增** | 渲染一致性测试 + 黄金文件 |
| `harness/engine/macro_graph.py` | **修改** | 用 AgentPrompt 替代散落拼接 |
| `harness/engine/micro_agent.py` | **修改** | `build_node_prompt` 标记 deprecated |
| `docs/status/CURRENT.md` | **修改** | 更新当前任务 |
| `docs/status/CHANGELOG.md` | **修改** | 完成后追加记录 |

---

## 8. 验证标准

1. **渲染一致性**：`AgentPrompt.render_system()` + `render_user()` 的输出与当前拼接逻辑**逐字符一致**（黄金文件测试）
2. **全量单测通过**：`pytest` 无回归
3. **不改变外部接口**：`MicroAgentFactory.create()` 签名不变，只是 `prompt` 参数的内容来源从手动拼接变为 `AgentPrompt.render_system()`
4. **NodeCtx 兼容**：`ext_ctx.prompt` 仍为 str（`render_user()` 的结果），middleware 无感知

---

## 9. 风险与缓解

| 风险 | 概率 | 缓解 |
|------|------|------|
| 渲染结果不一致（空格/换行差异） | 中 | 黄金文件测试覆盖所有分支 |
| `_strip_schema` 循环依赖（agent_prompt 导入 macro_graph） | 低 | 将 `_strip_schema` 提取到独立模块 `harness/engine/schema_utils.py` |
| Judge prompt 的 `## 上游 agent` section 不适合 AgentPrompt 框架 | 低 | 用 `JudgePrompt` 子类覆盖 `render_user()` |

---

## 10. 不在范围内（二期）

- `WorkflowContext` section（workflow 名称/路径/节点位置）
- `CustomSection` 扩展点（plugin 注入 section）
- `NodeCtx` 持有 `AgentPrompt` 对象（而非 `str`）
- Sub-agent prompt 封装
- Prompt 模板引擎（Jinja2 等）
