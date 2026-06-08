"""Pydantic schemas for API request/response models."""

import json
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, Field, StrictBool


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
    """Tool information (deprecated — use harness.tools.registry.ToolCatalogEntry)."""
    name: str
    description: str
    source: str = "unknown"
    parameters: dict[str, Any] = {}


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
    chart_groups: dict | None = None  # null — loaded lazily via GET /runs/{id}/charts
    agent_io: dict | None = None  # {agent_name: {input_prompt, system_prompt, output_result}} — for conversation replay
    events: list[dict] | None = None  # null — loaded lazily via GET /runs/{id}/events
    work_dir: str | None = None  # Working directory for MCP reconnection on resume
    batch_id: str | None = None
    user_id: str | None = None
    followup_sessions: dict | None = None  # {agent_name: {model, messages, turn_count, ...}} — persisted follow-up conversations
    _has_charts: bool = False  # True when chart sidecar exists
    _has_events: bool = False  # True when events sidecar exists


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


# --- Domain Portal ---


class TutorialSection(BaseModel):
    title: str
    agent: str | None = None


class TutorialMeta(BaseModel):
    id: str
    level: int
    title: str
    description: str = ""
    badge: str | None = None
    workflow: str | None = None
    sections: list[TutorialSection] = []
    apis: list[str] = []


class ApiDocMeta(BaseModel):
    id: str
    title: str
    file: str


class DomainMeta(BaseModel):
    id: str
    title: str
    description: str = ""
    color: str = "blue"
    icon: str = "Layers"
    status: str = "active"
    tutorials: list[TutorialMeta] = []
    apis: list[ApiDocMeta] = []


# --- User management ---


class CreateUserRequest(BaseModel):
    """POST /users — admin creates a new user."""
    user_id: str
    name: str
    role: Literal["developer", "admin"] = "developer"


# --- Runtime config ---


class SetConfigRequest(BaseModel):
    """POST /config — set API key/model at runtime."""
    api_key: str | None = None
    model: str | None = None
    api_url: str | None = None
    stop_regen_ttl: int | None = None
    thinking: StrictBool | None = None
    persist: StrictBool = True


# --- LLM profiles ---


class SaveProfileRequest(BaseModel):
    """POST /profiles — create or update an LLM profile."""
    name: str
    model: str = ""
    api_key: str = ""
    api_url: str = ""
    proxy: str = ""
    proxy_enabled: StrictBool = False
    ssl_verify: StrictBool = True


class RenameProfileRequest(BaseModel):
    """PUT /profiles/{name}/rename."""
    new_name: str


# --- Agent MD ---


class UpdateAgentMdRequest(BaseModel):
    """PUT /agents/{name}/md — update agent markdown file."""
    md_content: str = ""
    workflow: str
    target: Literal["private", "shared"] = "private"


# --- Chart render (HTTP fallback) ---


class ChartRenderRequest(BaseModel):
    """POST /charts — chart payload from render_chart() HTTP fallback."""
    node_id: str = ""
    chart: dict[str, Any] = Field(default_factory=dict)
    # Workflow ID injected by render_chart() via contextvar when called inside
    # an agent's execution. Lets the server route the event to the correct
    # workflow's Bus instead of guessing by node_id or "last running".
    workflow_id: str | None = None


# --- Runs ---


class BatchDeleteRunsRequest(BaseModel):
    """POST /runs/batch-delete — delete multiple runs."""
    run_ids: list[str]


class UpdateRunConversationRequest(BaseModel):
    """PATCH /runs/{run_id}/conversation — persist conversation messages."""
    conversation: list[dict[str, Any]]


class UpdateRunChartsRequest(BaseModel):
    """PATCH /runs/{run_id}/charts — persist chart_groups snapshot."""
    chart_groups: dict[str, Any] | None = None


class UpdateRunFollowupRequest(BaseModel):
    """PATCH /runs/{run_id}/followup — persist a follow-up session."""
    agent_name: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    model: str | None = None
    turn_count: int = 0
    created_at: str | None = None  # falls back to now() in handler if absent


# --- WebSocket inbound messages ---
#
# Wire format (matches what the frontend actually sends and what
# ws_handler.py reads): every inbound message is a JSON object with a
# top-level `type` discriminator and a nested `payload` object. The
# payload schema differs per message type.
#
# Parsing entry point: `parse_ws_message(raw: str)` — raises
# `WSValidationError` on any failure (malformed JSON, unknown type,
# missing required field, wrong field type). Callers (the WS loop)
# should send the error message back to the client and continue.


class WSChatAnswerPayload(BaseModel):
    """Payload for a `chat.answer` message.

    Two accepted shapes (mirrors ws_handler.parse_chat_answer_payload):
      - new:    {question_id, selected: [...], custom_input: "..."}
      - legacy: {question_id, answer: "..."}

    Note: `selected`, `custom_input`, and `answer` are intentionally
    NOT given defaults. Downstream `parse_chat_answer_payload()` /
    `assemble_answer()` distinguish the two shapes by field *presence*
    (not by emptiness), so we must serialize back with only the keys
    the client actually sent. The handler does this via
    `model_dump(exclude_unset=True)`.
    """
    question_id: str
    selected: list[str] | None = None
    custom_input: str | None = None
    answer: str | None = None


class WSStopAndRegeneratePayload(BaseModel):
    """Payload for an `agent.stop_and_regenerate` message."""
    agent_name: str
    partial_output: str = ""
    user_guidance: str = ""


class WSProvideGuidancePayload(BaseModel):
    """Payload for an `agent.provide_guidance` message (post-stop guidance)."""
    guidance: str


class WSChatFollowupPayload(BaseModel):
    """Payload for a `chat.followup` message (post-workflow follow-up)."""
    agent_name: str
    question: str


class WSChatAnswer(BaseModel):
    """`chat.answer` — answer an ask_user question."""
    type: Literal["chat.answer"] = "chat.answer"
    payload: WSChatAnswerPayload


class WSStopAndRegenerate(BaseModel):
    """`agent.stop_and_regenerate` — interrupt current agent + regenerate."""
    type: Literal["agent.stop_and_regenerate"] = "agent.stop_and_regenerate"
    payload: WSStopAndRegeneratePayload


class WSProvideGuidance(BaseModel):
    """`agent.provide_guidance` — provide guidance after a stop."""
    type: Literal["agent.provide_guidance"] = "agent.provide_guidance"
    payload: WSProvideGuidancePayload


class WSChatFollowup(BaseModel):
    """`chat.followup` — post-workflow follow-up question to an agent."""
    type: Literal["chat.followup"] = "chat.followup"
    payload: WSChatFollowupPayload


# All recognized inbound message types. Kept as a list (not derived from
# the union) so unknown-type errors can name them in a stable order.
WS_KNOWN_TYPES: tuple[str, ...] = (
    "chat.answer",
    "agent.stop_and_regenerate",
    "agent.provide_guidance",
    "chat.followup",
)

# Map from message type → model. Manual dispatch (instead of relying on
# Pydantic's discriminated-union error) so unknown-type failures get a
# friendly "Unknown message type 'X'. Known: [...]" message instead of
# Pydantic's generic discriminator error.
_WS_TYPE_TO_MODEL: dict[str, type[BaseModel]] = {
    "chat.answer": WSChatAnswer,
    "agent.stop_and_regenerate": WSStopAndRegenerate,
    "agent.provide_guidance": WSProvideGuidance,
    "chat.followup": WSChatFollowup,
}

# Discriminated union — exported for callers that want isinstance-based
# narrowing. Pydantic v2 picks the right variant on the `type` field.
WSMessage = Annotated[
    Union[WSChatAnswer, WSStopAndRegenerate, WSProvideGuidance, WSChatFollowup],
    Field(discriminator="type"),
]


class WSValidationError(Exception):
    """Raised when an inbound WS message fails validation.

    Message text is safe to forward verbatim to the client.
    """


def parse_ws_message(raw: str) -> BaseModel:
    """Parse + validate a raw WS text frame.

    Returns the validated model instance (one of the WS* classes above),
    or raises `WSValidationError` with a client-safe message.

    Replaces raw `json.loads()` + `msg.get("type")` dispatch in
    `ws_handler.py`. Unknown types, malformed JSON, missing `type`,
    missing `payload`, and per-message field errors all surface here as
    `WSValidationError` instead of being silently ignored or surfacing
    as opaque 500s / handler-level KeyErrors.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise WSValidationError(f"Invalid JSON: {e.msg}") from e

    if not isinstance(data, dict):
        raise WSValidationError(
            f"Message must be a JSON object, got {type(data).__name__}"
        )

    msg_type = data.get("type")
    if msg_type is None:
        raise WSValidationError("Message missing 'type' field")
    if not isinstance(msg_type, str):
        raise WSValidationError(
            f"'type' must be a string, got {type(msg_type).__name__}"
        )

    if msg_type not in _WS_TYPE_TO_MODEL:
        raise WSValidationError(
            f"Unknown message type '{msg_type}'. "
            f"Known: {list(WS_KNOWN_TYPES)}"
        )

    model = _WS_TYPE_TO_MODEL[msg_type]
    try:
        return model.model_validate(data)
    except Exception as e:  # noqa: BLE001 — surface Pydantic errors verbatim-ish
        # Pydantic v2 raises ValidationError. Flatten the first error into
        # a one-line message — clients get a precise, actionable reason
        # ("payload.question_id: field required") instead of a stack trace.
        errors = getattr(e, "errors", None)
        if callable(errors):
            errors = errors()
        if errors:
            first = errors[0]
            loc = ".".join(str(x) for x in first.get("loc", ()) if x != "__root__")
            raise WSValidationError(
                f"Field '{loc}': {first.get('msg', 'invalid')}"
            ) from e
        raise WSValidationError(str(e)) from e
