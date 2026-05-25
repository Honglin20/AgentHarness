"""Lazy summarizer for EvalJudge: read target agent MD -> ask LLM to summarize
its task and red lines -> cache by SHA256 of the MD content under .eval_cache/.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Callable


_CACHE_DIRNAME = ".eval_cache"


def _cache_path(workflow_dir: Path, target_name: str, md_content: str) -> Path:
    h = hashlib.sha256(md_content.encode()).hexdigest()[:16]
    return workflow_dir / _CACHE_DIRNAME / f"_judge_{target_name}_summary.{h}.md"


def _default_llm_call(target_name: str, md_content: str) -> str:
    """Real LLM call. Imports lazily to keep test isolation cheap."""
    from harness.engine.llm import LLMClient

    client = LLMClient()
    agent = client.agent(
        system_prompt=(
            "你的任务:阅读下面的 agent Markdown 定义,用 2-3 段简要总结:\n"
            "1. 这个 agent 的目标和职责\n"
            "2. 它必须遵守的红线/约束(若有)\n"
            "输出纯文本,作为评测员的判断依据。"
        ),
        output_type=str,
    )
    result = agent.run_sync(md_content)
    return str(result.output)


def summarize_target(
    target_name: str,
    md_content: str,
    workflow_dir: Path,
    llm_call: Callable[[str, str], str] | None = None,
) -> str:
    cache = _cache_path(workflow_dir, target_name, md_content)
    if cache.exists():
        return cache.read_text()
    fn = llm_call or _default_llm_call
    summary = fn(target_name, md_content)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(summary)
    return summary
