#!/usr/bin/env python
"""init_session.py — NAS session 路径初始化（绝对路径，LLM 不参与路径决策）.

用法:
    python init_session.py --working-dir <abs path>

输出 JSON 到 stdout:
    {
      "session_id": "20260613_103045_project_x",
      "session_dir": "<abs path>",
      "workflow_dir": "<abs path>",
      "helpers_dir": "<abs path>",
      "working_dir": "<abs path>",
      "meta_path": "<abs path to runs/<id>/.session_meta.json>",
      "created_at": "20260613_103045"
    }

副作用:
    - 创建 <workflow_dir>/runs/<session_id>/ 目录
    - 初始化空文件：candidates.json=[], signatures.idx, HISTORY.md, direction.md, tier_state.json
    - 写 <workflow_dir>/runs/<session_id>/.session_meta.json（session 元信息，
      供 agent 反向发现 session_dir）。**不写入用户的 working dir**——保持用户
      项目目录干净；resume 通过 --session-id 复用已有目录。
      见 docs/guides/workflow-development-guide.md §10。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path


def main() -> None:
    p = argparse.ArgumentParser(description="Initialize NAS session paths")
    p.add_argument("--working-dir", required=True, help="Absolute path to target project")
    p.add_argument("--workflow-name", default="nas")
    p.add_argument("--session-id", default=None,
                   help="Override auto-generated session_id (for resume)")
    args = p.parse_args()

    working_dir = Path(args.working_dir).resolve()
    if not working_dir.exists():
        print(json.dumps({"error": f"working_dir does not exist: {working_dir}"}))
        sys.exit(1)

    # workflow_dir via harness API (absolute)
    import harness.workflow as w
    workflows_root = w._get_workflows_dir()
    workflow_dir = workflows_root / args.workflow_name
    helpers_dir = workflow_dir / "helpers"

    # Generate session_id
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    proj_name = working_dir.name
    session_id = args.session_id or f"{ts}_{proj_name}"

    # session_dir
    session_dir = workflow_dir / "runs" / session_id
    session_dir.mkdir(parents=True, exist_ok=True)

    # Init empty files (idempotent — only write if absent)
    _init_if_absent(session_dir / "candidates.json", "[]")
    _init_if_absent(session_dir / "signatures.idx", "")
    _init_if_absent(session_dir / "HISTORY.md", "# NAS Search History\n\n")
    _init_if_absent(session_dir / "direction.md", "# Directions Explored\n\n")
    _init_if_absent(session_dir / "tier_state.json",
                    json.dumps({"current_tier": 0}, indent=2))

    # Session meta lives INSIDE the workflow session dir — never write into the
    # user's working dir (keeps their project tree clean; resume discovers the
    # session via --session-id instead of a pointer in their repo).
    # See docs/guides/workflow-development-guide.md §10.
    meta_path = session_dir / ".session_meta.json"
    session_data = {
        "session_id": session_id,
        "session_dir": str(session_dir),
        "workflow_dir": str(workflow_dir),
        "helpers_dir": str(helpers_dir),
        "working_dir": str(working_dir),
        "created_at": ts,
    }
    _atomic_write(meta_path, json.dumps(session_data, indent=2))

    # Output for scout to read
    result = {**session_data, "meta_path": str(meta_path)}
    print(json.dumps(result, indent=2))


def _init_if_absent(path: Path, content: str) -> None:
    if not path.exists() or path.stat().st_size == 0:
        _atomic_write(path, content)


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content)
    os.replace(tmp, path)


if __name__ == "__main__":
    main()
