"""Verify no silent `except: pass`-style patterns remain in production code.

Silent failure modes hide bugs. Every exception should be logged at minimum.

Patterns caught (single-line and two-line variants):
  - except ...: pass
  - except ...: continue
  - except ...: return None
  - except ...: return "" / return ''

Each pattern matches both bare `except:` and typed `except SomeError:` /
`except SomeError as e:` forms.

A site is considered intentional if it (or the swallow body line) carries the
inline comment marker `# intentional silent fallback`. These are excluded
via `_has_intention_marker`.
"""
import re
from pathlib import Path


# Match the "except ...:" prefix (bare or typed, optional `as e`).
_EXCEPT_CLAUSE = r"except\s+(?:[\w.]+(?:\s+as\s+\w+)?)?\s*:"

# Inline-comment marker that whitelists a swallow as intentional.
INTENTION_MARKER = "intentional silent fallback"

# Allowed swallow bodies (the right-hand side of `except ...:`).
# `[ \t]*` matches horizontal whitespace only — never the newline, so
# the single-line patterns don't accidentally span into the two-line form.
_SILENT_BODY = r"[ \t]*(?:pass|continue|return[ \t]+None|return[ \t]+\"\"|return[ \t]+'')[ \t]*$"

# Single-line patterns: `except ...: <silent-body>` on one physical line.
SILENT_PATTERNS = [
    re.compile(rf"{_EXCEPT_CLAUSE}{_SILENT_BODY}", re.MULTILINE),
]

# Two-line variant: `except ...:\n    <silent-body>`
TWO_LINE_SILENT = re.compile(
    rf"{_EXCEPT_CLAUSE}[ \t]*\n[ \t]*(?:pass|continue|return[ \t]+None|return[ \t]+\"\"|return[ \t]+'')[ \t]*$",
    re.MULTILINE,
)

PRODUCTION_DIRS = ["harness", "server"]


def _is_test_file(path: Path) -> bool:
    return "test_" in path.name or "/tests/" in str(path) or "\\tests\\" in str(path)


def _has_intention_marker(match: re.Match) -> bool:
    """Return True if the swallow block carries the `# intentional silent fallback`
    comment marker anywhere within the matched text."""
    return INTENTION_MARKER in match.group(0)


def test_no_silent_exception_swallowing():
    """Production code should not silently swallow exceptions."""
    violations = []

    for d in PRODUCTION_DIRS:
        root = Path(__file__).resolve().parent.parent.parent / d
        for path in root.rglob("*.py"):
            if _is_test_file(path):
                continue
            text = path.read_text()

            for pattern in SILENT_PATTERNS + [TWO_LINE_SILENT]:
                for match in pattern.finditer(text):
                    if _has_intention_marker(match):
                        continue
                    line_no = text[:match.start()].count("\n") + 1
                    violations.append(
                        f"{path.relative_to(Path(__file__).resolve().parent.parent.parent)}:{line_no}: {match.group().strip()!r}"
                    )

    assert not violations, (
        f"Silent except:<swallow> found at {len(violations)} sites:\n"
        + "\n".join(violations)
    )
