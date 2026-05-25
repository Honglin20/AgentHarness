"""Pydantic schemas for API request/response models."""

from typing import Any

from pydantic import BaseModel, Field


class AgentDef(BaseModel):
    """Agent definition for workflow creation."""
    name: str
    after: list[str] = Field(default_factory=list)
    on_pass: str | None = None
    on_fail: str | None = None
    eval: bool = False


class CreateWorkflowRequest(BaseModel):
    """Request to create and start a workflow."""
    name: str
    agents: list[AgentDef]
    workflow: str
    inputs: dict = Field(default_factory=dict)


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
    after: list[str] = []
    md_content: str = ""
    tools: list[str] | None = None
    model: str | None = None
    retries: int = 3


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


class CheckpointInfo(BaseModel):
    """A single checkpoint within a workflow run."""
    checkpoint_id: str
    thread_id: str
    next_nodes: list[str] = []
    values: dict[str, Any] = {}


class ResumeRequest(BaseModel):
    """Request to resume a workflow from a checkpoint."""
    checkpoint_id: str | None = None  # None = latest non-final checkpoint


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

class BenchmarkTask(BaseModel):
    """A single task in a benchmark."""
    id: str = ""
    label: str
    inputs: dict = Field(default_factory=dict)


class BenchmarkDef(BaseModel):
    """Benchmark definition."""
    name: str
    description: str = ""
    tasks: list[BenchmarkTask] = []


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
