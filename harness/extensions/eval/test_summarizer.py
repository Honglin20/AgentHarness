import hashlib
from pathlib import Path
from harness.extensions.eval.summarizer import summarize_target, _cache_path


def test_cache_path_uses_sha256(tmp_path):
    md = "---\nname: x\n---\nbody"
    h = hashlib.sha256(md.encode()).hexdigest()[:16]
    assert _cache_path(tmp_path, "x", md).name == f"_judge_x_summary.{h}.md"


def test_returns_cached_when_present(tmp_path):
    md = "---\nname: x\n---\nbody"
    p = _cache_path(tmp_path, "x", md)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("cached summary")
    result = summarize_target("x", md, workflow_dir=tmp_path, llm_call=lambda *_: "FRESH")
    assert result == "cached summary"


def test_writes_cache_when_missing(tmp_path):
    md = "---\nname: y\n---\nbody"
    result = summarize_target("y", md, workflow_dir=tmp_path, llm_call=lambda *_: "FRESH")
    assert result == "FRESH"
    p = _cache_path(tmp_path, "y", md)
    assert p.read_text() == "FRESH"


def test_cache_invalidates_on_md_change(tmp_path):
    summarize_target("z", "v1", workflow_dir=tmp_path, llm_call=lambda *_: "S1")
    new = summarize_target("z", "v2", workflow_dir=tmp_path, llm_call=lambda *_: "S2")
    assert new == "S2"
