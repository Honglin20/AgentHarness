"""Pydantic schemas for API request/response models."""

from typing import Any

from pydantic import BaseModel, Field


class AgentDef(BaseModel):
    """Agent definition for workflow creation."""
    name: str
    after: list[str] = Field(default_factory=list)
    on_pass: str | None = None
    on_fail: str | None = None


class CreateWorkflowRequest(BaseModel):
    """Request to create and start a workflow."""
    name: str
    agents: list[AgentDef]
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
