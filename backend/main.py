"""E2E demo: 3-agent serial workflow running in terminal."""
import sys
from pathlib import Path

# Add backend to path so we can import harness
sys.path.insert(0, str(Path(__file__).parent))

from harness.api import Agent, Workflow


def main():
    wf = Workflow(
        "demo_pipeline",
        agents=[
            Agent("analyzer", after=[]),
            Agent("planner", after=["analyzer"]),
            Agent("reviewer", after=["planner"]),
        ],
        agents_dir=str(Path(__file__).parent / "agents"),
    )

    print("Compiling workflow...")
    wf.compile()
    print("Workflow compiled successfully.\n")

    print("Running workflow...")
    result = wf.run({"task": "为一个 Python Web 项目设计用户认证模块"})

    print("\n=== Workflow Result ===")
    for agent_name, output in result.outputs.items():
        print(f"\n--- {agent_name} ---")
        print(output)

    if result.errors:
        print("\n=== Errors ===")
        for agent_name, error in result.errors.items():
            print(f"{agent_name}: {error}")

    print("\n=== Trace ===")
    for t in result.trace:
        print(f"  {t.agent_name}: {t.status} ({t.duration_ms}ms)")


if __name__ == "__main__":
    main()
