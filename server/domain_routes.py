"""Domain portal API routes."""

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from harness.api import _WORKFLOWS_DIR
from harness.compiler.dag_builder import build_dag

router = APIRouter()


@router.get("/domains")
async def list_domains(request: Request) -> list[dict]:
    """Return domain list with tutorials, workflow refs, API docs."""
    cached = getattr(request.app.state, "domain_data", None)
    if cached is not None:
        return cached
    from server.tutorial_parser import parse_tutorials
    return parse_tutorials()


@router.get("/domains/{domain_id}/tutorials/{tutorial_id}")
async def get_tutorial(domain_id: str, tutorial_id: str, request: Request) -> dict:
    """Return full tutorial data including section markdown and DAG topology."""
    cached: list[dict] = getattr(request.app.state, "domain_data", [])
    domain = next((d for d in cached if d["id"] == domain_id), None)
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    tutorial = next((t for t in domain["tutorials"] if t["id"] == tutorial_id), None)
    if not tutorial:
        raise HTTPException(status_code=404, detail="Tutorial not found")

    # Load DAG from workflow.json if workflow is referenced
    dag = None
    wf_name = tutorial.get("workflow")
    if wf_name:
        wf_stem = wf_name.rsplit("/", 1)[-1]
        wf_path = Path(_WORKFLOWS_DIR) / wf_stem / "workflow.json"
        if not wf_path.exists():
            wf_path = Path(_WORKFLOWS_DIR) / wf_name / "workflow.json"
        if wf_path.exists():
            wf_data = json.loads(wf_path.read_text(encoding="utf-8"))
            # workflow.json may not have a dag field — compute from agent deps
            if "dag" in wf_data and wf_data["dag"]:
                dag = wf_data["dag"]
            else:
                agents_raw = wf_data.get("agents", [])
                from types import SimpleNamespace
                agent_objs = [
                    SimpleNamespace(
                        name=a["name"],
                        after=a.get("after", []),
                        on_pass=a.get("on_pass"),
                        on_fail=a.get("on_fail"),
                    )
                    for a in agents_raw
                ]
                node_order = build_dag(agent_objs)
                edges: list[list[str]] = []
                conditional_edges: list[dict] = []
                for a in agent_objs:
                    for dep in a.after or []:
                        edges.append([dep, a.name])
                    if a.on_pass or a.on_fail:
                        if a.on_pass:
                            conditional_edges.append({"from": a.name, "to": a.on_pass, "label": "pass"})
                        if a.on_fail:
                            conditional_edges.append({"from": a.name, "to": a.on_fail, "label": "fail"})
                dag = {"nodes": node_order, "edges": edges, "conditional_edges": conditional_edges}

    return {
        **tutorial,
        "domain_id": domain_id,
        "domain_title": domain["title"],
        "domain_color": domain["color"],
        "dag": dag,
    }


@router.get("/domains/{domain_id}/api/{api_name}")
async def get_api_doc(domain_id: str, api_name: str, request: Request) -> dict:
    """Return API doc markdown + reverse mapping (which tutorial sections reference it)."""
    cached: list[dict] = getattr(request.app.state, "domain_data", [])
    domain = next((d for d in cached if d["id"] == domain_id), None)
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    api_entry = next((a for a in domain.get("apis", []) if a["id"] == api_name), None)
    if not api_entry:
        raise HTTPException(status_code=404, detail="API doc not found")

    # Read the API markdown file
    # Project layer takes precedence over builtin (mirrors parse_tutorials merge).
    from harness.paths import get_builtin_tutorials_dir, get_tutorials_dir
    candidates = [
        get_tutorials_dir() / domain_id / "api" / f"{api_name}.md",
        get_builtin_tutorials_dir() / domain_id / "api" / f"{api_name}.md",
    ]
    api_path = next((p for p in candidates if p.exists()), None)
    if api_path is None:
        raise HTTPException(status_code=404, detail="API file not found")

    markdown_content = api_path.read_text(encoding="utf-8")

    # Other APIs in the same domain
    other_apis = [
        {"id": a["id"], "title": a["title"]}
        for a in domain.get("apis", [])
        if a["id"] != api_name
    ]

    return {
        "id": api_name,
        "title": api_entry["title"],
        "description": api_entry.get("description", ""),
        "markdown": markdown_content,
        "domain_id": domain_id,
        "domain_title": domain["title"],
        "domain_color": domain["color"],
        "referenced_by": api_entry.get("referenced_by", []),
        "other_apis": other_apis,
    }


@router.post("/domains/refresh")
async def refresh_domains(request: Request) -> dict:
    """Force re-parse of tutorials directory."""
    from server.tutorial_parser import parse_tutorials
    data = parse_tutorials()
    request.app.state.domain_data = data
    return {"status": "ok", "count": len(data)}
