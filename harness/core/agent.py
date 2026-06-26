"""``Agent`` — declarative agent definition.

An ``Agent`` describes one node in the workflow DAG: its name, upstream
dependencies, optional model/tools overrides, conditional edges, and
eval configuration. The Markdown file (``agents/<name>.md``) carries the
prompt; the API definition carries the runtime config.
"""
from __future__ import annotations

from pathlib import Path
from typing import Type

from pydantic import BaseModel

from harness.compiler.md_parser import resolve_agent_md
from harness.types import AgentResult

# Static builtin executor whitelist. ``pydantic-ai`` is the default and
# historically the only in-process option; ``claude-code`` is the canonical
# CLI subprocess backend (registered by harness/cli_profiles/claude.py).
#
# P3-T5: VALID_EXECUTORS is now a FUNCTION (dynamic) so user-registered
# CliProfiles (opencode / codex / project-level) merge into the valid set
# at runtime. The static ``BUILTIN_EXECUTORS`` frozenset is kept for
# code that needs the unchanging builtin set (e.g. serialization tests).
BUILTIN_EXECUTORS = frozenset({"pydantic-ai", "claude-code"})
DEFAULT_EXECUTOR = "pydantic-ai"


def VALID_EXECUTORS() -> frozenset[str]:
    """Return the set of currently-valid executor names.

    Merges ``BUILTIN_EXECUTORS`` with all profile names registered in the
    CliProfile registry (builtins via harness/cli_profiles/, project-level
    via <cwd>/.harness/cli_profiles/, disabled profiles included so users
    see the failure rather than silently dropping).

    Why a function not a frozenset: CliProfile registration happens at
    runtime (server / CLI startup); a static frozenset cannot reflect
    project-level overrides without re-import.
    """
    # Lazy import to avoid circular dependency (cli_profile imports from
    # harness.translator which transitively touches harness.types).
    try:
        from harness.engine.cli_profile import registered_profile_names
        return BUILTIN_EXECUTORS | registered_profile_names()
    except ImportError:
        # cli_profile unavailable during early bootstrap — return builtins.
        return BUILTIN_EXECUTORS


def _extract_description(agent_name: str, workflow_dir: Path) -> str:
    """Return the first non-heading, non-frontmatter, non-empty line of the agent MD.

    Used by ``Workflow.list_saved`` to surface a one-line description for
    each agent in the DAG. Returns ``""`` if the MD is missing/unreadable.
    """
    try:
        path = resolve_agent_md(agent_name, workflow_dir)
        content = path.read_text(encoding="utf-8")
    except Exception:
        return ""  # intentional silent fallback — missing/unreadable agent.md yields empty description
    in_frontmatter = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            continue
        if not stripped or stripped.startswith("#"):
            continue
        return stripped
    return ""


class Agent:
    """Declarative agent definition.

    ``after`` semantics:
      - ``None``  : only reachable via conditional edges (not an entry node)
      - ``[]``    : entry node (connected to START)
      - ``[...]`` : has static dependencies
    """

    def __init__(
        self,
        name: str,
        after: list[str] | None = None,
        tools: list[str] | None = None,
        model: str | None = None,
        retries: int = 3,
        result_type: Type[BaseModel] | None = None,
        on_pass: str | None = None,
        on_fail: str | None = None,
        eval: bool = False,
        eval_target: str | None = None,
        executor: str = DEFAULT_EXECUTOR,
    ):
        self.name = name
        # None 表示仅通过条件边触发，不作为入口节点
        # [] 表示入口节点（从 START 开始）
        # [...] 表示有静态依赖
        if after is None:
            self.after = None
        else:
            self.after = after  # 保持原值，包括 []
        self.tools = tools
        self.model = model
        self.retries = retries
        self.result_type = result_type if result_type is not None else AgentResult
        self.on_pass = on_pass
        self.on_fail = on_fail
        self.eval = eval
        # executor 字段必须经白名单校验，fail-loud；任何新 backend 需先在
        # VALID_EXECUTORS() 注册（动态函数 — builtin + profile registry）。
        valid = VALID_EXECUTORS()
        if executor not in valid:
            raise ValueError(
                f"executor must be one of {sorted(valid)}, got {executor!r}"
            )
        self.executor = executor
        # eval_target: set on materialized judge agents; survives save/load so
        # the engine can route them through _make_judge_node_func after reload.
        # Stored as a public attr (also assigned to the legacy _eval_target
        # alias for back-compat with code that still reads the private form).
        self.eval_target = eval_target
        if eval_target is not None:
            self._eval_target = eval_target

    @property
    def has_conditional_edges(self) -> bool:
        return self.on_pass is not None or self.on_fail is not None

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "after": self.after,
            "tools": self.tools,
            "model": self.model,
            "retries": self.retries,
        }
        if self.on_pass is not None:
            d["on_pass"] = self.on_pass
        if self.on_fail is not None:
            d["on_fail"] = self.on_fail
        if self.eval:
            d["eval"] = True
        if self.eval_target is not None:
            d["eval_target"] = self.eval_target
        if self.result_type is not None and self.result_type is not AgentResult:
            d["result_type_name"] = self.result_type.__name__
            d["result_type_schema"] = self.result_type.model_json_schema()
        # executor 字段：仅在非默认值时写入 workflow.json，保证旧文件零变化。
        # from_dict 缺省读 DEFAULT_EXECUTOR，所以旧 workflow.json 自动兼容。
        if self.executor != DEFAULT_EXECUTOR:
            d["executor"] = self.executor
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Agent:
        from harness.schema_utils import safe_reconstruct_result_type

        result_type = safe_reconstruct_result_type(
            d.get("result_type_name"), d.get("result_type_schema")
        )
        return cls(
            name=d["name"],
            after=d.get("after"),
            tools=d.get("tools"),
            model=d.get("model"),
            retries=d.get("retries", 3),
            result_type=result_type,
            on_pass=d.get("on_pass"),
            on_fail=d.get("on_fail"),
            eval=bool(d.get("eval", False)),
            eval_target=d.get("eval_target"),
            executor=d.get("executor", DEFAULT_EXECUTOR),
        )
