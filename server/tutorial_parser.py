"""Parse tutorials/ directory into domain metadata for the portal API.

Usage:
    python -m server.tutorial_parser          # print JSON to stdout
    python -c "from server.tutorial_parser import parse_tutorials; ..."
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import frontmatter


_SECTION_RE = re.compile(r"^##\s+(.+?)(?:\s+@(\w+))?\s*$")
_H1_RE = re.compile(r"^#\s+(.+)$")
_LEVEL_RE = re.compile(r"^(\d+)")
_API_LINK_RE = re.compile(r"\[.*?\]\(api/(\w+)\.md\)")


def _parse_index(index_path: Path) -> dict:
    """Parse _index.md frontmatter + body for domain metadata."""
    fm = frontmatter.load(str(index_path))
    title = ""
    description = ""
    for line in fm.content.splitlines():
        stripped = line.strip()
        m = _H1_RE.match(stripped)
        if m:
            title = m.group(1).strip()
            continue
        if title and stripped and not stripped.startswith("#"):
            description = stripped
            break
        workflows_raw = fm.metadata.get("workflows", []) or []
        workflows = [
            {"name": w["name"], "description": w.get("description", "")}
            for w in workflows_raw
            if isinstance(w, dict) and w.get("name")
        ]
    return {
        "title": title or fm.metadata.get("title", index_path.parent.name),
        "description": description,
        "order": fm.metadata.get("order", 99),
        "color": fm.metadata.get("color", "blue"),
        "icon": fm.metadata.get("icon", "Layers"),
        "status": fm.metadata.get("status", "active"),
        "workflows": workflows,
    }


def _parse_tutorial_md(path: Path) -> dict:
    """Parse a single tutorial MD file."""
    fm = frontmatter.load(str(path))
    title = fm.metadata.get("title", "")
    workflow = fm.metadata.get("workflow")
    apis = fm.metadata.get("apis", [])
    badge = fm.metadata.get("badge")

    # Extract title from H1 if not in frontmatter
    if not title:
        for line in fm.content.splitlines():
            m = _H1_RE.match(line.strip())
            if m:
                title = m.group(1).strip()
                break

    # Extract description: first non-empty paragraph after H1
    description = ""
    past_h1 = False
    for line in fm.content.splitlines():
        stripped = line.strip()
        if _H1_RE.match(stripped):
            past_h1 = True
            continue
        if past_h1 and stripped and not stripped.startswith("#"):
            description = stripped
            break

    stem = path.stem
    level_match = _LEVEL_RE.match(stem)
    level = int(level_match.group(1)) if level_match else 0
    tutorial_id = _LEVEL_RE.sub("", stem).lstrip("_- ") or stem

    sections: list[dict] = []
    lines = fm.content.splitlines()

    # Find all H2 section boundaries: (line_index, title, agent)
    section_starts: list[tuple[int, str, str | None]] = []
    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if m:
            section_starts.append((i, m.group(1).strip(), m.group(2) or None))

    # Build sections with markdown content between consecutive H2 headers
    for idx, (start_i, sec_title, sec_agent) in enumerate(section_starts):
        # Content starts on the line after the ## header
        content_start = start_i + 1
        # Content ends at the next ## header (or end of file)
        if idx + 1 < len(section_starts):
            content_end = section_starts[idx + 1][0]
        else:
            content_end = len(lines)

        # Collect lines for this section
        section_lines = lines[content_start:content_end]

        # For the last section: strip trailing --- separator
        if idx == len(section_starts) - 1 and section_lines:
            last_nonempty = len(section_lines) - 1
            while last_nonempty >= 0 and section_lines[last_nonempty].strip() == "":
                last_nonempty -= 1
            if last_nonempty >= 0 and section_lines[last_nonempty].strip() == "---":
                # Remove the --- and any trailing blank lines after it
                section_lines = section_lines[:last_nonempty]

        section_md = "\n".join(section_lines).strip()
        api_refs = list(dict.fromkeys(_API_LINK_RE.findall(section_md)))

        sections.append({
            "title": sec_title,
            "agent": sec_agent,
            "markdown": section_md,
            "api_refs": api_refs,
        })

    # Aggregate all api_refs across sections
    all_api_refs = list(dict.fromkeys(
        ref for sec in sections for ref in sec["api_refs"]
    ))
    # Merge frontmatter apis with inline refs
    combined_apis = list(dict.fromkeys(apis + all_api_refs))

    return {
        "id": tutorial_id,
        "level": level,
        "title": title or tutorial_id,
        "description": description,
        "badge": badge,
        "workflow": workflow,
        "sections": sections,
        "apis": combined_apis,
    }


def _parse_api_md(path: Path, tutorials_dir: Path) -> dict:
    """Parse an API doc MD file for title + description."""
    content = path.read_text(encoding="utf-8")
    title = ""
    description = ""
    for line in content.splitlines():
        stripped = line.strip()
        m = _H1_RE.match(stripped)
        if m:
            title = m.group(1).strip()
            continue
        if title and stripped and not stripped.startswith("#"):
            description = stripped
            break
    rel = path.relative_to(tutorials_dir)
    return {
        "id": path.stem,
        "title": title or path.stem,
        "description": description,
        "file": str(rel),
    }


def _scan_single_dir(tutorials_dir: Path) -> list[dict]:
    """Scan a single tutorials directory and return list of domain dicts.

    ``tutorials_dir`` is used both as the scan root and as the base for
    API file relative paths (see ``_parse_api_md``), so it must be the
    directory actually being scanned — not a merged/parent root.
    """
    if not tutorials_dir.is_dir():
        return []

    domains: list[dict] = []
    for child in sorted(tutorials_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith("_") or child.name == "__pycache__":
            continue

        index_path = child / "_index.md"
        if not index_path.exists():
            continue

        meta = _parse_index(index_path)

        tutorials: list[dict] = []
        for md_file in sorted(child.glob("*.md")):
            if md_file.name == "_index.md":
                continue
            tutorials.append(_parse_tutorial_md(md_file))

        apis: list[dict] = []
        api_dir = child / "api"
        if api_dir.is_dir():
            for api_file in sorted(api_dir.glob("*.md")):
                apis.append(_parse_api_md(api_file, tutorials_dir))

        domains.append({
            "id": child.name,
            **meta,
            "tutorials": tutorials,
            "apis": apis,
            "workflows": meta.pop("workflows", []),
        })

    return domains


def parse_tutorials(tutorials_dir: Path | None = None) -> list[dict]:
    """Scan tutorials and return a list of domain dicts.

    Two-layer merge (mirrors ``harness.registry``: project overrides
    builtin, keyed by domain ``id``):

      1. Builtin — ``harness/builtin/tutorials`` (shipped with the pip
         package; always present after install).
      2. Project — ``<project_root>/tutorials`` (developer-authored; a
         same-named domain here wholly replaces the builtin one).

    An explicit ``tutorials_dir`` short-circuits the merge and scans only
    that single directory (kept for backward compatibility and tests).

    Returns domains sorted by the ``order`` frontmatter field (default 99),
    with a reverse ``referenced_by`` map attached to each API entry.
    """
    # Explicit single-dir mode — backward-compatible escape hatch.
    if tutorials_dir is not None:
        domains = _scan_single_dir(tutorials_dir)
    else:
        from harness.paths import get_builtin_tutorials_dir, get_tutorials_dir
        # Builtin first, then project overrides by id.
        merged: dict[str, dict] = {}
        for d in _scan_single_dir(get_builtin_tutorials_dir()):
            merged[d["id"]] = d
        for d in _scan_single_dir(get_tutorials_dir()):
            merged[d["id"]] = d
        domains = list(merged.values())

    # Build reverse mapping: api_id → [{tutorial_id, section_index, section_title}]
    for domain in domains:
        reverse: dict[str, list[dict]] = {}
        for tut in domain["tutorials"]:
            for idx, sec in enumerate(tut["sections"]):
                for ref in sec.get("api_refs", []):
                    reverse.setdefault(ref, []).append({
                        "tutorial_id": tut["id"],
                        "tutorial_title": tut["title"],
                        "section_index": idx,
                        "section_title": sec["title"],
                    })
        # Attach reverse mapping to each API entry
        for api in domain["apis"]:
            api["referenced_by"] = reverse.get(api["id"], [])

    # Synthetic domains — only in merged mode (explicit-dir mode has no
    # workflows context). Appended after the referenced_by loop so synthetic
    # domains (which carry empty tutorials/apis) are never touched by it.
    if tutorials_dir is None:
        _append_synthetic_domains(domains)

    # Sort by order field (default 99 for missing)
    domains.sort(key=lambda d: d.get("order", 99))

    return domains


# ── synthetic domains ───────────────────────────────────────────────
#
# Synthetic domains are auto-generated from project resources rather than
# authored in ``_index.md``. The canonical example is the ``project``
# domain, which aggregates every workflow under ``workflows/`` that no
# authored domain has claimed — so a workflow dropped into the workflows
# folder shows up in the Portal without a manual ``_index.md`` entry.
#
# Extension point: add a builder to ``_SYNTHETIC_BUILDERS`` and
# ``parse_tutorials`` picks it up unchanged (open/closed). Each builder
# shares the signature ``(candidates, claimed) -> dict | None`` and may
# return ``None`` (e.g. nothing to aggregate) to emit no domain.

# Metadata for the synthetic project domain. ``order: 99`` is the
# missing-frontmatter default, so it always sorts last behind authored
# domains (which currently use 1-5).
_PROJECT_DOMAIN_META = {
    "id": "project",
    "title": "Project Workflows",
    "description": "本地 workflows/ 下未被任何领域认领的工作流。",
    "color": "amber",
    "icon": "Layers",
    "status": "active",
    "order": 99,
}


def _collect_claimed_workflows(domains: list[dict]) -> set[str]:
    """Workflow names already claimed by authored domains.

    A workflow is "claimed" when it appears in either:
      - a domain ``_index.md`` ``workflows:`` declaration, or
      - a tutorial frontmatter ``workflow:`` field (the Try-it reference).
    Claimed workflows never enter the synthetic project domain. The
    ``rsplit`` tolerates ``"domain/name"`` path-style references.
    """
    claimed: set[str] = set()
    for d in domains:
        for w in d.get("workflows", []) or []:
            if w.get("name"):
                claimed.add(w["name"])
        for t in d.get("tutorials", []) or []:
            wf = t.get("workflow")
            if wf:
                claimed.add(wf.rsplit("/", 1)[-1])
    return claimed


def _build_project_domain(candidates, claimed: set[str]) -> dict | None:
    """Aggregate unclaimed project-layer workflows into a synthetic domain.

    ``candidates`` comes from ``registry.list_workflows(scope="project")``
    — the workflows dir rooted at the project (CWD), shared with
    ``/api/workflows/definitions`` so the two never drift apart. Returns
    ``None`` when nothing is unclaimed, so no empty domain card renders.
    """
    workflows = [
        {"name": m.name, "description": m.description}
        for m in candidates
        if m.name not in claimed
    ]
    if not workflows:
        return None
    return {
        **_PROJECT_DOMAIN_META,
        "tutorials": [],
        "apis": [],
        "workflows": workflows,
    }


# Builder list — the open/closed extension point. New synthetic domains
# append a builder here; parse_tutorials stays untouched.
_SYNTHETIC_BUILDERS = [_build_project_domain]


def _append_synthetic_domains(domains: list[dict]) -> None:
    """Append synthetic domains in place (merged mode only)."""
    from harness.registry import get_registry

    claimed = _collect_claimed_workflows(domains)
    project_candidates = get_registry().list_workflows(scope="project")
    for builder in _SYNTHETIC_BUILDERS:
        synth = builder(project_candidates, claimed)
        if synth:
            domains.append(synth)


if __name__ == "__main__":
    data = parse_tutorials()
    json.dump(data, sys.stdout, indent=2, ensure_ascii=False)
    print()
