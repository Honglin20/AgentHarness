"""Static guard: every return path in node_func must include node_invocation_counts.

Plan F made node_invocation_counts a universal invariant — every return
dict from ``make_node_func``'s ``node_func`` must include it so the counter
survives LangGraph's state merge. This test parses ``node_factory.py`` and
asserts no return path forgets it.

If you add a new return path to node_func, this test will catch a missing
counter update at CI time.

Note: we walk only node_func's own scope, skipping nested function defs
(there are several inner helpers like ``_check_interrupt`` and
``_get_cancel_fn`` whose returns are not node_func state dicts).
"""
from __future__ import annotations

import ast
from pathlib import Path


def _find_node_func(tree: ast.AST) -> ast.AsyncFunctionDef | None:
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "node_func"
        ):
            return node
    return None


def _iter_returns_in_scope(func: ast.AsyncFunctionDef | ast.FunctionDef):
    """Yield ``Return`` statements directly in func's body, descending into
    conditionals/loops/try-except but NOT into nested function/class defs.

    Without this scoping, ``ast.walk`` would also surface returns from
    inner helpers like ``_check_interrupt`` / ``_get_cancel_fn`` that are
    not node_func state returns.
    """
    stack: list[ast.AST] = list(func.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef, ast.ClassDef)):
            continue  # skip nested scope — its returns aren't ours
        if isinstance(node, ast.Return):
            yield node
            continue  # returns have no meaningful body to descend into
        # Descend into compound statements that live in func's scope.
        for field in getattr(node, "body", None) or []:
            stack.append(field)
        for attr in ("orelse", "finalbody", "handlers"):
            for child in getattr(node, attr, None) or []:
                stack.append(child)


def _return_dict_has_counter(ret: ast.Return) -> bool:
    """True if the return statement is safe w.r.t. node_invocation_counts.

    Conservative: returns True (trusted) if the return value is a bare
    ``Name`` (variable reference — assume the builder included it) or any
    form other than a dict literal. Only dict literals are inspected
    strictly, because those are the obvious place someone could forget
    the counter key.
    """
    val = ret.value
    if val is None:
        return True  # bare return; not a node_func state path
    if isinstance(val, ast.Name):
        return True  # returns a variable (e.g. result_dict) — trust the builder
    if isinstance(val, ast.Dict):
        for key in val.keys:
            if isinstance(key, ast.Constant) and key.value == "node_invocation_counts":
                return True
        return False
    return True  # other forms (Constant, Call, ...) — be conservative


def test_every_return_in_node_func_has_counter():
    source = Path("harness/engine/node_factory.py").read_text()
    tree = ast.parse(source)
    node_func = _find_node_func(tree)
    assert node_func is not None, "node_func not found in node_factory.py"

    returns = [r for r in _iter_returns_in_scope(node_func) if r.value is not None]
    # As of Plan F there are 8 state-dict return paths (helper-function
    # returns are excluded by the scope walker). Bump if you intentionally
    # add a new path AND audit that it carries node_invocation_counts.
    assert len(returns) >= 8, (
        f"Expected at least 8 return paths in node_func, found {len(returns)}. "
        "If you added or removed a path, audit whether every state-dict "
        "return still includes node_invocation_counts."
    )

    missing_lines = []
    for ret in returns:
        if not _return_dict_has_counter(ret):
            missing_lines.append(ret.lineno)

    assert not missing_lines, (
        f"Return paths at lines {missing_lines} in node_func return dict "
        "literals without 'node_invocation_counts'. Every state-dict return "
        "must include it (Plan F invariant). Either add the counter key or "
        "return a pre-built variable (e.g. result_dict) that includes it."
    )
