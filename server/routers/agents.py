"""Agent definition endpoints (list/get/update agent MD)."""
import logging

from fastapi import APIRouter, HTTPException, Request

from harness.api import _WORKFLOWS_DIR
from harness.compiler.md_parser import (
    AgentNotFoundError,
    _SHARED_AGENTS_DIR,
    parse_agent_md,
    resolve_agent_md,
)
from harness.user_manager import get_current_user
from server._helpers import _validate_workflow_dir
from server.schemas import (
    AgentInfo,
    UpdateAgentMdRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/agents")
async def list_agents(
    workflow: str,
    request: Request,
) -> list[AgentInfo]:
    """List all available agents for a workflow.

    Resolution order:
      1. ``workflows/<workflow>/agents/*.md`` (private)
      2. ``workflows/_shared/agents/*.md`` (shared fallback)
    """
    user = get_current_user(request)
    user_id = user.user_id if user.user_id != "default" else None
    wf_dir = _validate_workflow_dir(workflow, user_id)
    agents: list[AgentInfo] = []
    seen: set[str] = set()

    # Private agents first
    private_dir = wf_dir / "agents"
    if private_dir.exists():
        for md_file in private_dir.glob("*.md"):
            try:
                parsed = parse_agent_md(md_file)
                seen.add(parsed.name)
                agents.append(AgentInfo(
                    name=parsed.name,
                    description=parsed.description,
                    model=parsed.model,
                    retries=parsed.retries,
                    tools=parsed.tools or [],
                ))
            except Exception:
                # Skip malformed agent .md — listing must not fail entirely
                # because one agent file is broken. Log so the user can find it.
                logger.warning(
                    "Failed to parse agent file %s — skipping", md_file, exc_info=True,
                )
                continue

    # Shared agents (not overridden by private)
    if _SHARED_AGENTS_DIR.exists():
        for md_file in _SHARED_AGENTS_DIR.glob("*.md"):
            try:
                parsed = parse_agent_md(md_file)
                if parsed.name not in seen:
                    agents.append(AgentInfo(
                        name=parsed.name,
                        description=parsed.description,
                        model=parsed.model,
                        retries=parsed.retries,
                        tools=parsed.tools or [],
                    ))
            except Exception:
                logger.warning(
                    "Failed to parse shared agent file %s — skipping", md_file, exc_info=True,
                )
                continue

    return agents


@router.get("/agents/{name}")
async def get_agent(
    name: str,
    workflow: str,
    request: Request,
) -> AgentInfo:
    """Get a specific agent's definition."""
    user = get_current_user(request)
    user_id = user.user_id if user.user_id != "default" else None
    wf_dir = _validate_workflow_dir(workflow, user_id)
    try:
        md_path = resolve_agent_md(name, wf_dir)
    except AgentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    try:
        parsed = parse_agent_md(md_path)
        return AgentInfo(
            name=parsed.name,
            description=parsed.description,
            model=parsed.model,
            retries=parsed.retries,
            tools=parsed.tools or [],
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse agent: {e}")


@router.get("/agents/{name}/md")
async def get_agent_md(
    name: str,
    workflow: str,
    request: Request,
) -> dict:
    """Get the raw Markdown content of an agent definition.

    Resolution: ``resolve_agent_md(name, workflows/<workflow>)``
    which falls back to ``workflows/_shared/agents/`` if not found locally.
    """
    user = get_current_user(request)
    user_id = user.user_id if user.user_id != "default" else None
    wf_dir = _validate_workflow_dir(workflow, user_id)
    try:
        md_path = resolve_agent_md(name, wf_dir)
    except AgentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    source = "private" if md_path.parent == wf_dir / "agents" else "shared"
    return {
        "name": name,
        "md_content": md_path.read_text(),
        "workflow": workflow,
        "source": source,
    }


@router.put("/agents/{name}/md")
async def update_agent_md(name: str, body: UpdateAgentMdRequest, request: Request) -> dict:
    """Update an agent's Markdown file.

    Body fields:
      - ``md_content`` (str, required)
      - ``workflow`` (str, required) + ``target`` ("private"|"shared", default
        "private"): write to ``workflows/<workflow>/agents/<name>.md`` or
        ``workflows/_shared/agents/<name>.md``.
    """
    md_content = body.md_content
    workflow = body.workflow
    target = body.target

    if target == "private":
        user = get_current_user(request)
        user_id = user.user_id if user.user_id != "default" else None
        wf_dir = _validate_workflow_dir(workflow, user_id)
        md_path = wf_dir / "agents" / f"{name}.md"
    else:
        md_path = _SHARED_AGENTS_DIR / f"{name}.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)

    # Validate before writing — write to temp file, parse, then rename
    tmp = md_path.with_suffix(".tmp")
    try:
        tmp.write_text(md_content)
        parsed = parse_agent_md(tmp)
        tmp.replace(md_path)
        return {
            "status": "ok",
            "name": parsed.name,
            "description": parsed.description,
            "path": str(md_path),
        }
    except Exception as e:
        tmp.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"Invalid agent MD: {e}")
