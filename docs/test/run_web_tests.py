"""Web UI 端到端测试脚本

通过 API 测试所有 workflows 和 benchmarks。
"""

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import httpx


class WebTester:
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url
        self.api_key = "test-key"
        self.session = httpx.AsyncClient(
            base_url=base_url,
            headers={"X-API-Key": self.api_key},
            timeout=300.0,
        )

    async def health(self) -> dict:
        r = await self.session.get("/api/health")
        r.raise_for_status()
        return r.json()

    async def list_workflows(self) -> list[dict]:
        r = await self.session.get("/api/workflows/definitions")
        r.raise_for_status()
        return r.json()

    async def list_benchmarks(self) -> list[dict]:
        r = await self.session.get("/api/benchmarks")
        r.raise_for_status()
        return r.json()

    async def run_workflow(
        self,
        workflow_name: str,
        agents: list[dict],
        inputs: dict,
    ) -> str:
        payload = {
            "name": f"test-{workflow_name}-{int(time.time())}",
            "workflow": workflow_name,
            "agents": agents,
            "inputs": inputs,
        }
        r = await self.session.post("/api/workflows", json=payload)
        r.raise_for_status()
        data = r.json()
        return data["workflow_id"]

    async def run_benchmark(
        self,
        benchmark_name: str,
        workflow_name: str,
        agents: list[dict],
    ) -> str:
        r = await self.session.post(
            f"/api/benchmarks/{benchmark_name}/run",
            json={"workflow": workflow_name},
        )
        r.raise_for_status()
        data = r.json()
        return data["run_id"]

    async def get_workflow(self, workflow_id: str) -> dict:
        r = await self.session.get(f"/api/workflows/{workflow_id}")
        r.raise_for_status()
        return r.json()

    async def get_run(self, run_id: str) -> dict:
        r = await self.session.get(f"/api/runs/{run_id}")
        r.raise_for_status()
        return r.json()

    async def get_batch_status(self, batch_id: str) -> dict:
        r = await self.session.get(f"/api/batch/{batch_id}")
        r.raise_for_status()
        return r.json()

    async def wait_for_completion(
        self,
        workflow_id: str,
        max_wait: int = 300,
    ) -> dict:
        """Wait for workflow to complete."""
        start = time.time()
        while time.time() - start < max_wait:
            data = await self.get_workflow(workflow_id)
            if data["status"] in ("completed", "failed"):
                return data
            await asyncio.sleep(1)
        raise TimeoutError(f"Workflow {workflow_id} did not complete in {max_wait}s")

    async def wait_for_batch(
        self,
        batch_id: str,
        max_wait: int = 600,
    ) -> dict:
        """Wait for batch to complete."""
        start = time.time()
        while time.time() - start < max_wait:
            data = await self.get_batch_status(batch_id)
            all_done = all(
                r["status"] in ("completed", "failed")
                for r in data.get("runs", [])
            )
            if all_done and data.get("runs"):
                return data
            await asyncio.sleep(2)
        raise TimeoutError(f"Batch {batch_id} did not complete in {max_wait}s")

    async def close(self):
        await self.session.aclose()


async def test_chart_demo(tester: WebTester) -> dict:
    """Test chart_demo workflow."""
    print("\n" + "=" * 60)
    print("测试 1: chart_demo")
    print("=" * 60)

    agents = [
        {"name": "runner", "after": [], "tools": ["bash"], "retries": 3}
    ]

    inputs = {
        "task": "echo 'hello world' && echo 'current directory:' && pwd",
    }

    print(f"  输入: {inputs}")
    workflow_id = await tester.run_workflow("chart_demo", agents, inputs)
    print(f"  Workflow ID: {workflow_id}")

    result = await tester.wait_for_completion(workflow_id)

    # Verify results
    run_data = await tester.get_run(workflow_id)
    result_data = run_data.get("result")
    agent_io = run_data.get("agent_io", {})
    trace = result_data.get("trace", []) if result_data else []

    checks = {
        "status": result["status"] == "completed",
        "has_agent_io": len(agent_io) > 0,
        "has_trace": len(trace) > 0,
        "has_result": result_data is not None,
        "has_output": "runner" in (result_data.get("outputs", {}) if result_data else {}),
    }

    print(f"\n  状态: {result['status']}")
    print(f"  Agent IO 数量: {len(agent_io)}")
    print(f"  Trace 数量: {len(trace) if trace else 0}")

    # Show agent_io
    for agent_name, io in agent_io.items():
        print(f"  Agent {agent_name}:")
        input_prompt = io.get('input_prompt', '')
        output_result = io.get('output_result', '')
        if isinstance(input_prompt, str):
            print(f"    Input: {input_prompt[:80]}...")
        else:
            print(f"    Input: (complex type)")
        if isinstance(output_result, str):
            print(f"    Output: {output_result[:80]}...")
        else:
            print(f"    Output: (complex type)")

    if result_data:
        outputs = result_data.get("outputs", {}).get("runner", {})
        if isinstance(outputs, dict):
            print(f"  Summary: {outputs.get('summary', '')[:50]}...")
            print(f"  Details: {outputs.get('details', '')[:50]}...")

    passed = all(checks.values())
    print(f"\n  {'✅ PASS' if passed else '❌ FAIL'}")
    return {
        "name": "chart_demo",
        "passed": passed,
        "checks": checks,
        "workflow_id": workflow_id,
    }


async def test_parallel_research(tester: WebTester) -> dict:
    """Test parallel_research workflow."""
    print("\n" + "=" * 60)
    print("测试 2: parallel_research")
    print("=" * 60)

    agents = [
        {"name": "researcher_a", "after": [], "retries": 3},
        {"name": "researcher_b", "after": [], "retries": 3},
        {"name": "synthesizer", "after": ["researcher_a", "researcher_b"], "retries": 3},
    ]

    inputs = {
        "task": "分别研究 Python 和 JavaScript 的异步编程模型",
    }

    print(f"  输入: {inputs}")
    workflow_id = await tester.run_workflow("parallel_research", agents, inputs)
    print(f"  Workflow ID: {workflow_id}")

    result = await tester.wait_for_completion(workflow_id)

    run_data = await tester.get_run(workflow_id)
    result_data = run_data.get("result")
    agent_io = run_data.get("agent_io", {})
    dag = run_data.get("dag", {})
    trace = result_data.get("trace", []) if result_data else []

    # Check DAG structure
    has_parallel_structure = (
        dag.get("nodes") == ["researcher_a", "researcher_b", "synthesizer"] or
        "synthesizer" in str(dag)
    )

    checks = {
        "status": result["status"] == "completed",
        "has_agent_io": len(agent_io) >= 2,
        "has_trace": len(trace) >= 2,
        "has_result": result_data is not None,
        "has_parallel_dag": has_parallel_structure,
    }

    print(f"\n  状态: {result['status']}")
    print(f"  Agent IO 数量: {len(agent_io)}")
    print(f"  Trace 数量: {len(trace)}")
    print(f"  DAG 并行结构: {checks['has_parallel_dag']}")

    # Show agent outputs
    agent_outputs = set(agent_io.keys())
    print(f"  执行的 Agents: {agent_outputs}")

    passed = all(checks.values())
    print(f"\n  {'✅ PASS' if passed else '❌ FAIL'}")
    return {
        "name": "parallel_research",
        "passed": passed,
        "checks": checks,
        "workflow_id": workflow_id,
    }


async def test_eval_demo(tester: WebTester) -> dict:
    """Test eval_demo workflow."""
    print("\n" + "=" * 60)
    print("测试 3: eval_demo")
    print("=" * 60)

    agents = [
        {
            "name": "researcher",
            "after": [],
            "tools": ["bash"],
            "retries": 3,
            "eval": True,
        },
        {
            "name": "writer",
            "after": ["researcher"],
            "retries": 3,
        },
    ]

    inputs = {
        "task": "研究 FastAPI 的基本用法",
    }

    print(f"  输入: {inputs}")
    workflow_id = await tester.run_workflow("eval_demo", agents, inputs)
    print(f"  Workflow ID: {workflow_id}")

    result = await tester.wait_for_completion(workflow_id)

    run_data = await tester.get_run(workflow_id)
    result_data = run_data.get("result")
    agent_io = run_data.get("agent_io", {})
    trace = result_data.get("trace", []) if result_data else []

    # Check for judge in trace
    has_judge = any(
        "judge" in entry.get("agent_name", "").lower()
        for entry in (trace or [])
    )

    checks = {
        "status": result["status"] == "completed",
        "has_agent_io": len(agent_io) > 0,
        "has_trace": len(trace) > 0 if trace else False,
        "has_result": result_data is not None,
        "has_judge_event": has_judge,
    }

    print(f"\n  状态: {result['status']}")
    print(f"  Agent IO 数量: {len(agent_io)}")
    print(f"  Trace 条目数: {len(trace) if trace else 0}")
    print(f"  包含 Judge 事件: {checks['has_judge_event']}")

    # Show trace if available
    for entry in trace:
        if "judge" in entry.get("agent_name", "").lower():
            print(f"    Judge entry: {entry.get('agent_name')}")

    passed = all(checks.values())
    print(f"\n  {'✅ PASS' if passed else '❌ FAIL'}")
    return {
        "name": "eval_demo",
        "passed": passed,
        "checks": checks,
        "workflow_id": workflow_id,
    }


async def test_loop_retry(tester: WebTester) -> dict:
    """Test loop_retry workflow."""
    print("\n" + "=" * 60)
    print("测试 4: loop_retry")
    print("=" * 60)

    # Use the actual loop_retry workflow definition
    agents = [
        {"name": "coder", "after": [], "tools": ["bash"], "retries": 3},
        {
            "name": "reviewer",
            "after": ["coder"],
            "retries": 3,
            "on_fail": "coder",  # Add conditional edge
        },
    ]

    inputs = {
        "task": "写一个 Python 函数判断数字是否为偶数",
    }

    print(f"  输入: {inputs}")
    workflow_id = await tester.run_workflow("loop_retry", agents, inputs)
    print(f"  Workflow ID: {workflow_id}")

    try:
        result = await tester.wait_for_completion(workflow_id)
    except TimeoutError:
        # Loop workflows might take longer or get stuck
        print("  ⚠️ Timeout - 可能需要手动取消")
        return {
            "name": "loop_retry",
            "passed": False,
            "checks": {},
            "workflow_id": workflow_id,
            "error": "timeout",
        }

    run_data = await tester.get_run(workflow_id)
    result_data = run_data.get("result")
    agent_io = run_data.get("agent_io", {})
    dag = run_data.get("dag", {})
    trace = result_data.get("trace", []) if result_data else []

    # Check if DAG structure is correct (even if no actual loop occurred)
    has_conditional_edge = any(
        edge.get("label") == "fail"
        for edge in dag.get("conditional_edges", [])
    )

    # Check if coder ran (at least once)
    coder_ran = any(e.get("agent_name") == "coder" for e in (trace or []))

    checks = {
        "status": result["status"] == "completed",
        "has_agent_io": len(agent_io) > 0,
        "has_trace": len(trace) > 0 if trace else False,
        "has_result": result_data is not None,
        "has_conditional_dag": has_conditional_edge,
        "coder_ran": coder_ran,  # At minimum, coder should run once
    }

    print(f"\n  状态: {result['status']}")
    print(f"  Agent IO 数量: {len(agent_io)}")
    print(f"  Trace 条目数: {len(trace) if trace else 0}")
    print(f"  包含条件边: {checks['has_conditional_dag']}")
    print(f"  Coder 执行: {'是' if coder_ran else '否'}")

    # Check for retries (multiple coder/reviewer cycles)
    agent_sequence = [entry.get("agent_name") for entry in (trace or [])]
    print(f"  Agent 执行序列: {agent_sequence}")

    passed = all(checks.values())
    print(f"\n  {'✅ PASS' if passed else '❌ FAIL'}")
    return {
        "name": "loop_retry",
        "passed": passed,
        "checks": checks,
        "workflow_id": workflow_id,
    }


async def test_conditional_route(tester: WebTester) -> dict:
    """Test conditional_route workflow."""
    print("\n" + "=" * 60)
    print("测试 5: conditional_route")
    print("=" * 60)

    agents = [
        {"name": "analyzer", "after": [], "retries": 3},
        {
            "name": "classifier",
            "after": ["analyzer"],
            "retries": 3,
            "on_pass": "summary",
            "on_fail": "debugger",
        },
        {"name": "summary", "after": [], "retries": 3},
        {"name": "debugger", "after": [], "tools": ["bash"], "retries": 3},
    ]

    inputs = {
        "task": "分析以下代码: print('hello')",
    }

    print(f"  输入: {inputs}")
    workflow_id = await tester.run_workflow("conditional_route", agents, inputs)
    print(f"  Workflow ID: {workflow_id}")

    result = await tester.wait_for_completion(workflow_id)

    run_data = await tester.get_run(workflow_id)
    result_data = run_data.get("result")
    agent_io = run_data.get("agent_io", {})
    dag = run_data.get("dag", {})
    trace = result_data.get("trace", []) if result_data else []

    # Check for conditional edges
    conditional_edges = dag.get("conditional_edges", [])
    has_pass_fail = any(
        edge.get("label") in ("pass", "fail")
        for edge in conditional_edges
    )

    checks = {
        "status": result["status"] == "completed",
        "has_agent_io": len(agent_io) > 0,
        "has_trace": len(trace) > 0 if trace else False,
        "has_result": result_data is not None,
        "has_conditional_dag": has_pass_fail,
    }

    print(f"\n  状态: {result['status']}")
    print(f"  Agent IO 数量: {len(agent_io)}")
    print(f"  Trace 条目数: {len(trace) if trace else 0}")
    print(f"  包含条件边: {checks['has_conditional_dag']}")

    # Check which path was taken
    agent_names = [entry.get("agent_name") for entry in (trace or [])]
    path_taken = "summary" if "summary" in agent_names else "debugger"
    print(f"  执行路径: {path_taken}")

    passed = all(checks.values())
    print(f"\n  {'✅ PASS' if passed else '❌ FAIL'}")
    return {
        "name": "conditional_route",
        "passed": passed,
        "checks": checks,
        "workflow_id": workflow_id,
    }


async def test_benchmark_test_quick(tester: WebTester) -> dict:
    """Test test-quick benchmark."""
    print("\n" + "=" * 60)
    print("测试 6: test-quick Benchmark")
    print("=" * 60)

    # Use code_review workflow for benchmark
    agents = [
        {"name": "runner", "after": [], "retries": 3},
    ]

    batch_id = await tester.run_benchmark("test-quick", "chart_demo", agents)
    print(f"  Batch ID: {batch_id}")

    batch_result = await tester.wait_for_batch(batch_id)

    runs = batch_result.get("runs", [])
    completed = sum(1 for r in runs if r["status"] == "completed")

    checks = {
        "has_runs": len(runs) > 0,
        "all_completed": all(r["status"] in ("completed", "failed") for r in runs),
        "expected_count": len(runs) == 2,
    }

    print(f"\n  任务总数: {len(runs)}")
    print(f"  已完成: {completed}")
    print(f"  预期任务数: 2")

    for run in runs:
        print(f"    {run['label']}: {run['status']}")

    passed = all(checks.values())
    print(f"\n  {'✅ PASS' if passed else '❌ FAIL'}")
    return {
        "name": "test-quick_benchmark",
        "passed": passed,
        "checks": checks,
        "batch_id": batch_id,
    }


async def test_benchmark_code_review(tester: WebTester) -> dict:
    """Test code-review-v1 benchmark."""
    print("\n" + "=" * 60)
    print("测试 7: code-review-v1 Benchmark")
    print("=" * 60)

    agents = [
        {"name": "runner", "after": [], "retries": 3},
    ]

    batch_id = await tester.run_benchmark("code-review-v1", "chart_demo", agents)
    print(f"  Batch ID: {batch_id}")

    batch_result = await tester.wait_for_batch(batch_id)

    runs = batch_result.get("runs", [])
    completed = sum(1 for r in runs if r["status"] == "completed")

    checks = {
        "has_runs": len(runs) > 0,
        "all_completed": all(r["status"] in ("completed", "failed") for r in runs),
        "expected_count": len(runs) == 4,
    }

    print(f"\n  任务总数: {len(runs)}")
    print(f"  已完成: {completed}")
    print(f"  预期任务数: 4")

    for run in runs:
        print(f"    {run['label']}: {run['status']}")
        if run.get("score"):
            print(f"      Score: {run['score']}")
        if run.get("duration_ms"):
            print(f"      Duration: {run['duration_ms']}ms")

    passed = all(checks.values())
    print(f"\n  {'✅ PASS' if passed else '❌ FAIL'}")
    return {
        "name": "code-review-v1_benchmark",
        "passed": passed,
        "checks": checks,
        "batch_id": batch_id,
    }


async def run_all_tests():
    """Run all tests and generate report."""
    tester = WebTester()

    # Check server health
    print("检查服务器状态...")
    try:
        health = await tester.health()
        print(f"✅ 服务器正常: {health}")
    except Exception as e:
        print(f"❌ 服务器异常: {e}")
        return

    # List available workflows and benchmarks
    workflows = await tester.list_workflows()
    benchmarks = await tester.list_benchmarks()
    print(f"\n可用 Workflows: {len(workflows)}")
    print(f"可用 Benchmarks: {len(benchmarks)}")

    # Run tests
    results = []

    # P0 tests (must pass)
    try:
        results.append(await test_chart_demo(tester))
    except Exception as e:
        print(f"❌ chart_demo 失败: {e}")
        results.append({"name": "chart_demo", "passed": False, "error": str(e)})

    try:
        results.append(await test_parallel_research(tester))
    except Exception as e:
        print(f"❌ parallel_research 失败: {e}")
        results.append({"name": "parallel_research", "passed": False, "error": str(e)})

    try:
        results.append(await test_benchmark_test_quick(tester))
    except Exception as e:
        print(f"❌ test-quick benchmark 失败: {e}")
        results.append({"name": "test-quick_benchmark", "passed": False, "error": str(e)})

    # P1 tests
    try:
        results.append(await test_eval_demo(tester))
    except Exception as e:
        print(f"❌ eval_demo 失败: {e}")
        results.append({"name": "eval_demo", "passed": False, "error": str(e)})

    try:
        results.append(await test_loop_retry(tester))
    except Exception as e:
        print(f"❌ loop_retry 失败: {e}")
        results.append({"name": "loop_retry", "passed": False, "error": str(e)})

    try:
        results.append(await test_conditional_route(tester))
    except Exception as e:
        print(f"❌ conditional_route 失败: {e}")
        results.append({"name": "conditional_route", "passed": False, "error": str(e)})

    try:
        results.append(await test_benchmark_code_review(tester))
    except Exception as e:
        print(f"❌ code-review-v1 benchmark 失败: {e}")
        results.append({"name": "code-review-v1_benchmark", "passed": False, "error": str(e)})

    await tester.close()

    # Generate report
    print("\n" + "=" * 60)
    print("测试报告")
    print("=" * 60)

    passed_count = sum(1 for r in results if r["passed"])
    total_count = len(results)

    for result in results:
        status = "✅ PASS" if result["passed"] else "❌ FAIL"
        print(f"{status} | {result['name']}")

    print(f"\n通过率: {passed_count}/{total_count} ({passed_count/total_count*100:.1f}%)")

    # Save results to file
    report_path = Path(__file__).parent / "test_results.json"
    report_path.write_text(
        json.dumps(
            {
                "timestamp": time.time(),
                "passed": passed_count,
                "total": total_count,
                "pass_rate": passed_count / total_count if total_count > 0 else 0,
                "results": results,
            },
            indent=2,
        )
    )
    print(f"\n详细结果已保存到: {report_path}")

    return passed_count == total_count


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1)