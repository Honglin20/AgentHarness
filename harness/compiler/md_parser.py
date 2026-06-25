from pathlib import Path
from pydantic import BaseModel
import frontmatter
import yaml


from harness.paths import get_shared_agents_dir

_SHARED_AGENTS_DIR = get_shared_agents_dir()


class AgentNotFoundError(FileNotFoundError):
    """Raised when an agent MD cannot be found in the workflow or shared pool."""

    def __init__(self, name: str, searched: list[str]):
        self.name = name
        self.searched = searched
        super().__init__(
            f"Agent '{name}' not found. Searched:\n  - " + "\n  - ".join(searched)
        )


def resolve_agent_md(agent_name: str, workflow_dir: Path) -> Path:
    """Locate an agent MD file: workflow-private first, then shared pool.

    Returns the resolved Path. Raises AgentNotFoundError(name, searched=[...])
    if neither location has the file.
    """
    local = workflow_dir / "agents" / f"{agent_name}.md"
    if local.exists():
        return local
    shared = _SHARED_AGENTS_DIR / f"{agent_name}.md"
    if shared.exists():
        return shared
    raise AgentNotFoundError(agent_name, searched=[str(local), str(shared)])


class ParsedAgent(BaseModel):
    name: str
    prompt: str
    tools: list[str] = []
    model: str | None = None
    retries: int = 3
    description: str | None = None
    on_pass: str | None = None
    on_fail: str | None = None
    eval: bool = False
    # 默认值与 harness.core.agent.DEFAULT_EXECUTOR 字面值保持一致；
    # 白名单由 parse_agent_md 内部 import 校验，避免顶层循环依赖。
    executor: str = "pydantic-ai"


def parse_agent_md(path: Path) -> ParsedAgent:
    """Parse an agent Markdown file with YAML frontmatter.

    Raises:
        ValueError: If frontmatter is missing or 'name' field is absent,
                    or if ``executor`` is not in the whitelist.
        FileNotFoundError: If the file doesn't exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Agent file not found: {path}")

    # 局部 import 避免顶层循环：harness.core.agent 顶层依赖本模块的 resolve_agent_md。
    from harness.core.agent import DEFAULT_EXECUTOR, VALID_EXECUTORS

    post = frontmatter.load(str(path))

    if not post.metadata:
        raise ValueError(f"Missing YAML frontmatter in {path}")

    name = post.metadata.get("name")
    if not name:
        raise ValueError(f"Missing required 'name' field in frontmatter of {path}")

    executor = post.metadata.get("executor", DEFAULT_EXECUTOR)
    if executor not in VALID_EXECUTORS:
        raise ValueError(
            f"executor must be one of {sorted(VALID_EXECUTORS)}, got {executor!r} "
            f"in {path}"
        )

    prompt = post.content.strip()

    # Extract description from first non-empty line of prompt
    description = None
    for line in prompt.splitlines():
        stripped = line.strip()
        if stripped:
            description = stripped
            break

    return ParsedAgent(
        name=name,
        prompt=prompt,
        tools=post.metadata.get("tools", []) or [],
        model=post.metadata.get("model"),
        retries=post.metadata.get("retries", 3),
        description=description,
        on_pass=post.metadata.get("on_pass"),
        on_fail=post.metadata.get("on_fail"),
        eval=bool(post.metadata.get("eval", False)),
        executor=executor,
    )


def write_agent_md(
    path: Path,
    name: str,
    prompt: str,
    tools: list[str] | None = None,
    model: str | None = None,
    retries: int = 3,
    on_pass: str | None = None,
    on_fail: str | None = None,
    executor: str | None = None,
) -> None:
    """Write an agent Markdown file with YAML frontmatter.

    ``executor`` is only written when explicitly provided AND non-default
    (i.e. not ``"pydantic-ai"``) to keep generated MD diffs minimal.
    """
    metadata: dict = {"name": name, "retries": retries}
    if tools:
        metadata["tools"] = tools
    if model:
        metadata["model"] = model
    if on_pass is not None:
        metadata["on_pass"] = on_pass
    if on_fail is not None:
        metadata["on_fail"] = on_fail
    if executor is not None and executor != "pydantic-ai":
        metadata["executor"] = executor

    frontmatter_str = yaml.dump(metadata, default_flow_style=False, allow_unicode=True).strip()
    content = f"---\n{frontmatter_str}\n---\n\n{prompt.strip()}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
