"""Basic agent creation and execution.

Shows: Agent, Workflow, compile(), run(), WorkflowResult, NodeTrace, TokenUsage

Usage (from project root):
    cd backend && python ../examples/basic_agent.py
"""

import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from harness.api import Agent, Workflow


def main():
    # Define agents
    agents = [Agent("analyzer", after=[])]

    backend_dir = os.path.join(os.path.dirname(__file__), "..", "backend")
    wf = Workflow("simple", agents=agents, agents_dir=os.path.join(backend_dir, "agents"))

    print("Compiling ...")
    graph = wf.compile()
    print(f"Graph: {graph}\n")

    print("Running ...")
    result = wf.run({"task": "Explain what 2+2 is in one sentence."})

    print(f"\nOutput: {result.outputs['analyzer'][:200]}")
    print(f"Trace: {len(result.trace)} node(s)")

    t = result.trace[0]
    print(f"Node: {t.agent_name} | {t.status} | {t.duration_ms}ms")
    if t.token_usage:
        print(f"Tokens: {t.token_usage.input} in / {t.token_usage.output} out / {t.token_usage.total} total")


if __name__ == "__main__":
    main()
