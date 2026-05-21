from pathlib import Path
from pydantic import BaseModel
import frontmatter


class ParsedAgent(BaseModel):
    name: str
    prompt: str
    tools: list[str] = []
    model: str | None = None
    retries: int = 3
    description: str | None = None
    on_pass: str | None = None
    on_fail: str | None = None


def parse_agent_md(path: Path) -> ParsedAgent:
    """Parse an agent Markdown file with YAML frontmatter.

    Raises:
        ValueError: If frontmatter is missing or 'name' field is absent.
        FileNotFoundError: If the file doesn't exist.
    """
    if not path.exists():
        raise FileNotFoundError(f"Agent file not found: {path}")

    post = frontmatter.load(str(path))

    if not post.metadata:
        raise ValueError(f"Missing YAML frontmatter in {path}")

    name = post.metadata.get("name")
    if not name:
        raise ValueError(f"Missing required 'name' field in frontmatter of {path}")

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
    )
