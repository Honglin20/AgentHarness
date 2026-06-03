"""Pydantic schemas for API request/response models."""

from typing import Any

from pydantic import BaseModel, Field


class AgentDef(BaseModel):
    """Agent definition for workflow creation."""
    name: str
    after: list[str] | None = Field(default_factory=list)
    on_pass: str | None = None
    on_fail: str | None = None
    eval: bool = False
    result_type_name: str | None = None
    result_type_schema: dict[str, Any] | None = None


class CreateWorkflowRequest(BaseModel):
    """Request to create and start a workflow."""
    name: str
    agents: list[AgentDef]
    workflow: str
    inputs: dict = Field(default_factory=dict)
    work_dir: str | None = None  # Working directory to execute in


class CreateWorkflowResponse(BaseModel):
    """Response to workflow creation."""
    workflow_id: str
    status: str = "running"
    dag: dict | None = None  # {nodes: [...], edges: [...]} for frontend


class WorkflowStatusResponse(BaseModel):
    """Response to workflow status query."""
    workflow_id: str
    name: str
    status: str
    result: dict[str, Any] | None = None


class AgentInfo(BaseModel):
    """Agent information."""
    name: str
    description: str | None = None
    model: str | None = None
    retries: int = 3
    tools: list[str] = Field(default_factory=list)


class ToolInfo(BaseModel):
    """Tool information."""
    name: str
    description: str


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "ok"


class AgentSnapshot(BaseModel):
    """Snapshot of an agent definition at run time."""
    name: str
    after: list[str] | None = []
    md_content: str = ""
    tools: list[str] | None = None
    model: str | None = None
    retries: int = 3
    on_pass: str | None = None
    on_fail: str | None = None
    eval: bool = False
    result_type_name: str | None = None
    result_type_schema: dict[str, Any] | None = None


class RunDetail(BaseModel):
    """Full persisted workflow run record."""
    run_id: str
    workflow_name: str
    agents_snapshot: list[AgentSnapshot] = []
    status: str
    inputs: dict = {}
    result: dict[str, Any] | None = None
    conversation: list[dict] = []
    created_at: str
    dag: dict | None = None  # {nodes, edges, conditional_edges} — needed so replay view can render the DAG identically to live view
    chart_groups: dict | None = None  # {groups: {label: ChartGroup}, groupOrder: [labels]} — snapshot of frontend chartStore so Results tab replays
    agent_io: dict | None = None  # {agent_name: {input_prompt, system_prompt, output_result}} — for conversation replay
    events: list[dict] | None = None  # Raw event buffer for full replay fidelity (IO, tools, thinking, etc.)
    work_dir: str | None = None  # Working directory for MCP reconnection on resume
    batch_id: str | None = None
    user_id: str | None = None


class RunSummary(BaseModel):
    """Lightweight run record for list views — excludes heavy fields."""
    run_id: str
    workflow_name: str
    status: str
    inputs: dict = {}
    created_at: str
    batch_id: str | None = None
    user_id: str | None = None


class CheckpointInfo(BaseModel):
    """A single checkpoint within a workflow run."""
    checkpoint_id: str
    thread_id: str
    next_nodes: list[str] = []
    values: dict[str, Any] = {}


class ResumeRequest(BaseModel):
    """Request to resume a workflow from a checkpoint."""
    checkpoint_id: str | None = None  # None = latest non-final checkpoint
    guidance: str | None = None  # User guidance for interrupt resume


# --- Batch execution ---

class BatchRunItem(BaseModel):
    """A single item in a batch run."""
    label: str
    inputs: dict = Field(default_factory=dict)


class CreateBatchRequest(BaseModel):
    """Request to create a batch of workflow runs."""
    name: str
    agents: list[AgentDef]
    workflow: str
    items: list[BatchRunItem]
    work_dir: str | None = None


class BatchRunSummary(BaseModel):
    """Summary of a single run within a batch."""
    workflow_id: str
    label: str
    status: str = "pending"  # pending | running | completed | failed
    score: float | None = None
    error: str | None = None


class CreateBatchResponse(BaseModel):
    """Response to batch creation."""
    batch_id: str
    runs: list[BatchRunSummary] = []


# --- Benchmark ---


class BenchmarkPrep(BaseModel):
    """Prep phase for a benchmark run. Executes once before all tasks."""
    type: str = "script"  # "script" or "agent"
    # For script type: shell command to execute
    command: str | None = None
    # For agent type: agent MD name (resolved via resolve_agent_md)
    agent: str | None = None
    # Working directory for prep execution (optional)
    work_dir: str | None = None


class BenchmarkTask(BaseModel):
    """A single task in a benchmark."""
    id: str = ""
    label: str
    inputs: dict = Field(default_factory=dict)


class LLMJudgeConfig(BaseModel):
    """LLM-as-Judge configuration."""
    enabled: bool = False
    model: str | None = None   # Override model, falls back to HARNESS_MODEL
    rubric: str | None = None  # Custom rubric, uses default if None


class ScoringConfig(BaseModel):
    """Scoring configuration for benchmark evaluation."""
    mode: str = "efficiency"  # "efficiency" | "llm_judge" | "hybrid"
    weights: dict[str, float] = {"success": 0.4, "duration": 0.3, "tokens": 0.3}
    thresholds: dict[str, dict[str, int]] = {}  # task_id -> {max_duration_ms, max_tokens}
    llm_judge: LLMJudgeConfig | None = None


class BenchmarkDef(BaseModel):
    """Benchmark definition."""
    name: str
    description: str = ""
    prep: BenchmarkPrep | None = None
    tasks: list[BenchmarkTask] = []
    scoring: ScoringConfig | None = None


class RunBenchmarkRequest(BaseModel):
    """Request to run a benchmark with a specific workflow."""
    workflow: str


class BenchmarkTaskResult(BaseModel):
    """Result of a single task within a benchmark run."""
    task_id: str
    label: str
    status: str = "pending"
    score: float | None = None
    duration_ms: int = 0
    token_usage: dict | None = None
    charts: list[dict] = []
    error: str | None = None


class BenchmarkRunSummary(BaseModel):
    """Summary of a full benchmark run."""
    run_id: str
    benchmark_name: str
    workflow_name: str
    status: str = "running"
    created_at: str = ""
    task_results: list[BenchmarkTaskResult] = []
    avg_score: float | None = None
