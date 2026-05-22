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
    # New (preferred): workflow directory name (under workflows/). If omitted, derived from `name`.
    workflow: str | None = None
    # Legacy: kept for back-compat with old clients. Deprecated.
    agents_dir: str = "agents"
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
