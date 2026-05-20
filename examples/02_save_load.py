"""#2 — Save, load, run, and inspect a workflow in detail.

Shows every API a developer can use to inspect workflow results:
  result.outputs     — what each agent produced
  result.errors      — any failures per agent
  result.trace       — duration, tokens, status per agent
  wf.save() / wf.load() — persistence
  Workflow.list_saved() — discover saved workflows

Usage:
    python examples/02_save_load.py
"""

from harness.api import Agent, Workflow


# ── 1. Define and save ──────────────────────────────────────────

wf = Workflow("code_review", agents=[
    Agent("analyzer", after=[]),
    Agent("planner", after=["analyzer"]),
    Agent("reviewer", after=["planner"]),
])
path = wf.save()
print(f"Saved: {path}\n")


# ── 2. List all saved workflows ─────────────────────────────────

print("Saved workflows:")
for w in Workflow.list_saved():
    nodes = w["dag"]["nodes"]
    edges = w["dag"]["edges"]
    print(f"  {w['name']}")
    print(f"    agents: {' → '.join(nodes)}")
    print(f"    edges:  {edges}")
print()


# ── 3. Load and run ─────────────────────────────────────────────

wf2 = Workflow.load("code_review")
result = wf2.run({"task": "Say hello in exactly three words."})


# ── 4. Inspect the result ───────────────────────────────────────
#
#  result.outputs   → dict[str, str]   agent_name → what it said
#  result.errors    → dict[str, str]   agent_name → error message (empty if ok)
#  result.trace     → list[NodeTrace]  per-agent timing, tokens, status
#
#  NodeTrace fields:
#    .agent_name    — str
#    .status        — "success" | "failed" | "skipped"
#    .duration_ms   — int
#    .error         — str | None
#    .token_usage   — TokenUsage | None
#      .input       — int
#      .output      — int
#      .total       — int

print("=" * 60)
print("Result — per-agent output")
print("=" * 60)
for agent in wf2.agents:
    name = agent.name
    output = result.outputs.get(name, "")
    error = result.errors.get(name, "")

    print(f"\n── {name} ──")
    if output:
        print(f"{output.strip()}")
    if error:
        print(f"  ✗ ERROR: {error}")


print("\n" + "=" * 60)
print("Result — execution trace")
print("=" * 60)
print(f"{'Agent':<12} {'Status':<10} {'Duration':<10} {'Tokens (in/out/total)':<30}")
print("-" * 62)
for t in result.trace:
    status = t.status.upper() if t.status == "failed" else t.status
    tu = t.token_usage
    tokens = f"{tu.input}/{tu.output}/{tu.total}" if tu else "—"
    print(f"{t.agent_name:<12} {status:<10} {t.duration_ms} ms{'':>5} {tokens:<30}")

print()


# ── 5. Error summary ────────────────────────────────────────────

if result.errors:
    print("=" * 60)
    print(f"Errors ({len(result.errors)} agent(s) failed)")
    print("=" * 60)
    for name, err in result.errors.items():
        print(f"  {name}: {err[:120]}")
    print()
