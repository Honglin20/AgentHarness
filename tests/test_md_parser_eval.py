from harness.compiler.md_parser import parse_agent_md


def test_parse_eval_true(tmp_path):
    p = tmp_path / "a.md"
    p.write_text("---\nname: a\neval: true\n---\nbody")
    parsed = parse_agent_md(p)
    assert parsed.eval is True


def test_parse_eval_default_false(tmp_path):
    p = tmp_path / "b.md"
    p.write_text("---\nname: b\n---\nbody")
    parsed = parse_agent_md(p)
    assert parsed.eval is False
