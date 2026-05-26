# Test Plan - End-to-End Testing

**Date**: 2026-05-26
**Scope**: All examples, benchmark functionality, frontend interfaces

---

## 1. API Endpoints Documentation

### 1.1 Core Endpoints

| Endpoint | Method | Description | Expected Response |
|----------|--------|-------------|-------------------|
| `/health` | GET | Health check | `{"status": "ok"}` |
| `/me` | GET | Get current user info | `{"user_id": "...", "name": "...", "role": "..."}` |
| `/config` | GET | Get current config | API key masked |
| `/config` | POST | Set config (api_key, model, etc.) | `{"status": "ok"}` |

### 1.2 Agent Endpoints

| Endpoint | Method | Description | Expected Response |
|----------|--------|-------------|-------------------|
| `/agents?workflow=<name>` | GET | List all agents for a workflow | `[{name, description, model, retries, tools}, ...]` |
| `/agents/<name>?workflow=<name>` | GET | Get specific agent definition | AgentInfo object |
| `/agents/<name>/md?workflow=<name>` | GET | Get raw Markdown content | `{name, md_content, workflow, source}` |
| `/agents/<name>/md` | PUT | Update agent Markdown | `{status: "ok", name, description, path}` |

### 1.3 Workflow Endpoints

| Endpoint | Method | Description | Expected Response |
|----------|--------|-------------|-------------------|
| `/workflows/definitions` | GET | List saved workflows | `[{name, workflow_dir, scope}, ...]` |
| `/workflows` | POST | Create and start workflow | `CreateWorkflowResponse` |
| `/workflows/<workflow_id>` | GET | Get workflow status | `WorkflowStatusResponse` |
| `/workflows/<workflow_id>/cancel` | POST | Pause/cancel workflow | `{status: "paused"}` |
| `/workflows/<workflow_id>/dag` | GET | Get DAG structure | `{nodes, edges, conditional_edges}` |
| `/workflows/<workflow_id>/trace` | GET | Get execution trace | `{workflow_id, trace: []}` |
| `/workflows/definitions/<name>` | DELETE | Delete workflow definition | `{status: "ok", deleted: <name>}` |

### 1.4 Run/Batch Endpoints

| Endpoint | Method | Description | Expected Response |
|----------|--------|-------------|-------------------|
| `/runs` | GET | List all runs (persisted + live) | `RunDetail[]` |
| `/runs/<run_id>` | GET | Get specific run | `RunDetail` |
| `/runs/<run_id>/conversation` | PATCH | Update conversation messages | `{status: "ok"}` |
| `/runs/<run_id>/charts` | PATCH | Update chart groups snapshot | `{status: "ok"}` |
| `/runs/<run_id>/checkpoints` | GET | List checkpoints | `CheckpointInfo[]` |
| `/runs/<run_id>/resume` | POST | Resume from checkpoint | `{workflow_id, status, resumed_from}` |
| `/runs/<run_id>/rerun` | POST | Re-run with same config | `CreateWorkflowResponse` |
| `/runs/<run_id>` | DELETE | Delete run | `{status: "ok", deleted: run_id}` |
| `/batch` | POST | Create batch of runs | `CreateBatchResponse` |
| `/batch/<batch_id>` | GET | Get batch status | `CreateBatchResponse` |

### 1.5 Benchmark Endpoints

| Endpoint | Method | Description | Expected Response |
|----------|--------|-------------|-------------------|
| `/benchmarks` | GET | List all benchmarks | `[{name, description, tasks}, ...]` |
| `/benchmarks/<name>` | GET | Get benchmark definition | `{name, description, tasks}` |
| `/benchmarks` | POST | Create new benchmark | `{name, path}` |
| `/benchmarks/<name>` | PUT | Update benchmark | `{name, tasks}` |
| `/benchmarks/<name>` | DELETE | Delete benchmark | `{deleted: name}` |
| `/benchmarks/<name>/run` | POST | Run benchmark | `BenchmarkRunSummary` |
| `/benchmarks/<name>/results` | GET | List all results | `BenchmarkResult[]` |
| `/benchmarks/<name>/results/<run_id>` | GET | Get specific result | `BenchmarkResult` |

### 1.6 Tool & Chart Endpoints

| Endpoint | Method | Description | Expected Response |
|----------|--------|-------------|-------------------|
| `/tools` | GET | List registered tools | `[{name, description}, ...]` |
| `/charts` | POST | Receive chart payload | `{status: "ok"}` |

---

## 2. Examples Testing Plan

### 2.1 Basic Examples

| Example | Description | Expected Output |
|---------|-------------|-----------------|
| `01_minimal.py` | Single agent workflow | Output from analyzer agent, token usage stats |
| `02_serial_pipeline.py` | 3 agents in series | Output from all 3 agents, trace with execution times |
| `03_parallel.py` | Parallel execution | 2 researchers run concurrently, then synthesizer merges |
| `04_conditional_routing.py` | Conditional routing (on_pass/on_fail) | Workflow routes based on pass/fail conditions |

### 2.2 Advanced Examples

| Example | Description | Expected Output |
|---------|-------------|-----------------|
| `05_loop_retry.py` | Loop and retry mechanism | Retries on failure, loops until condition met |
| `06_sub_agent_loop.py` | Sub-agent within loop | Nested agent execution |
| `07_ask_human.py` | Human-in-the-loop | Workflow pauses, waits for human input |
| `08_eval_judge.py` | Evaluation with scoring | Judge agent scores output, retries if score < threshold |
| `09_charts.py` | Chart generation | Charts rendered and displayed |
| `10_save_load_ui.py` | Save workflow for UI | Workflow saved to disk, available in UI |
| `11_all_extensions.py` | All extensions combined | Multiple hooks/middleware active |
| `12_benchmark.py` | Benchmark creation | Benchmark saved to benchmarks/ directory |
| `13_console_output.py` | Console output hooks | Output displayed in console |

---

## 3. Frontend Interface Testing

### 3.1 Sidebar Components

| Component | Function | Expected Behavior |
|-----------|----------|-------------------|
| **New Workflow** button | Create new workflow | Opens workflow editor modal |
| **Benchmarks section** | List available benchmarks | Shows benchmarks with task counts, clickable to select |
| **History section** | Show run history | Lists recent runs with status badges |
| **Agents section** | Browse agents | Shows agent list with descriptions |
| **Compare Workflows** button | Open comparison dialog | Opens dialog to select runs to compare |

### 3.2 Center Panel Components

| Component | Function | Expected Behavior |
|-----------|----------|-------------------|
| **WorkflowCenterPanel** | Main workflow view | Shows DAG, conversation, results |
| **DAG Preview** | Visualize workflow DAG | Nodes, edges, conditional edges displayed |
| **DAG Status Bar** | Show execution status | Running/completed/failed states with colors |
| **Conversation Tab** | Show agent outputs | Message stream with markdown rendering |
| **Results Tab** | Show final outputs | Agent outputs, charts, scores |
| **Analysis Tab** | Analyze results | Token usage, duration metrics |
| **Diagnostics Panel** | Debug info | Trace, tool calls, errors |

### 3.3 Benchmark Components

| Component | Function | Expected Behavior |
|-----------|----------|-------------------|
| **BenchmarkRunner** | Run benchmark | Workflow selector, run button, progress table |
| **BenchmarkCompare** | Compare results | 4 tabs: scores, charts, workflows, history |
| **BenchmarkEditor** | Create/edit benchmark | Name, description, tasks with add/remove |

### 3.4 Benchmark Compare Tabs

| Tab | Content | Expected Display |
|-----|---------|------------------|
| **Scores** | Task scores table | Bar chart of scores, avg score, task status |
| **Charts** | Generated charts | Charts grouped by title, grid layout |
| **Workflows** | Run comparison | Select runs, grouped bar chart, comparison table |
| **History** | Historical trends | Line chart of avg scores over time, history table |

---

## 4. Benchmark End-to-End Test Flow

### 4.1 Create Benchmark
1. Open sidebar
2. Click "Benchmarks" (should show `code-review-v1` if exists)
3. Create new benchmark or use existing
4. Verify tasks are displayed correctly

### 4.2 Run Benchmark
1. Select benchmark from sidebar
2. Choose workflow from dropdown
3. Click "Run Benchmark"
4. Verify:
   - Loading state displayed
   - Batch runs created
   - Progress table shows running status
   - WebSocket connection indicator shows green

### 4.3 Monitor Progress
1. Watch runs change status (running → completed/failed)
2. Click on individual runs to view details
3. Verify DAG, conversation, results display correctly

### 4.4 Compare Results
1. Switch to "Compare" tab
2. Verify 4 tabs available
3. Check "Scores" tab:
   - Bar chart displays
   - Avg score shown
   - Table with task scores, duration, status
4. Check "Charts" tab (if charts generated)
5. Check "Workflows" tab:
   - Run selector buttons
   - Comparison chart
   - Comparison table
6. Check "History" tab:
   - Trend line chart
   - History table

---

## 5. Test Execution Checklist

### 5.1 Prerequisites
- [ ] Backend server running (uvicorn server.app:app --host 0.0.0.0 --port 8001)
- [ ] Frontend dev server running (cd frontend && npm run dev)
- [ ] API key configured (optional, can use mock for testing)
- [ ] Browser open to http://localhost:3000

### 5.2 API Health Check
- [ ] `GET /health` returns 200 OK
- [ ] `GET /me` returns user info
- [ ] `GET /config` returns config

### 5.3 Example Tests
- [ ] Run `01_minimal.py` - verify single agent output
- [ ] Run `02_serial_pipeline.py` - verify serial execution
- [ ] Run `03_parallel.py` - verify parallel execution
- [ ] Run `04_conditional_routing.py` - verify conditional logic
- [ ] Run `08_eval_judge.py` - verify scoring
- [ ] Run `09_charts.py` - verify chart generation
- [ ] Run `12_benchmark.py` - verify benchmark creation

### 5.4 Frontend UI Tests
- [ ] Sidebar loads and shows benchmarks
- [ ] Click benchmark to select it
- [ ] Workflow center panel shows correctly
- [ ] DAG visualization renders
- [ ] Conversation tab displays messages
- [ ] Results tab shows outputs
- [ ] Diagnostics panel shows traces

### 5.5 Benchmark End-to-End Tests
- [ ] Benchmark list loads in sidebar
- [ ] Clicking benchmark shows runner
- [ ] Workflow dropdown populates
- [ ] "Run Benchmark" button creates batch
- [ ] Progress table shows all tasks
- [ ] Individual runs can be clicked
- [ ] Compare tab loads after completion
- [ ] Scores tab shows bar chart
- [ ] Workflows tab allows comparison
- [ ] History tab shows trends

### 5.6 Data Flow Verification
- [ ] WebSocket events received by frontend
- [ ] Stores updated correctly (workflowStore, batchStore, etc.)
- [ ] UI components re-render on state changes
- [ ] Chart data flows to chart widgets
- [ ] Conversation messages display correctly

### 5.7 Error Handling
- [ ] Invalid workflow name shows error
- [ ] Empty benchmark cannot be saved
- [ ] Cancel workflow works
- [ ] Failed runs show error state
- [ ] Network errors handled gracefully

---

## 6. Test Results

### 6.1 API Tests
| Endpoint | Status | Notes |
|----------|--------|-------|

### 6.2 Example Tests
| Example | Status | Notes |
|---------|--------|-------|

### 6.3 Frontend Tests
| Component | Status | Notes |
|-----------|--------|-------|

### 6.4 Benchmark Tests
| Test Case | Status | Notes |
|-----------|--------|-------|

---

## 7. Issues Found

| ID | Description | Severity | Status |
|----|-------------|----------|--------|

---

## 8. Recommendations

| # | Recommendation |
|---|----------------|