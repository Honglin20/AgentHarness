"""Verify no silent `except: pass` patterns remain in production code.

Silent failure modes hide bugs. Every exception should be logged at minimum.
"""
import re
from pathlib import Path


# Patterns that indicate silent swallowing
SILENT_PATTERNS = [
    # except Exception: pass  (same line)
    re.compile(r"except\s+Exception\s*:\s*pass\s*$", re.MULTILINE),
    re.compile(r"except\s+BaseException\s*:\s*pass\s*$", re.MULTILINE),
    re.compile(r"except\s*:\s*pass\s*$", re.MULTILINE),
]

# Two-line pattern: `except ...:` then `pass` on next line
TWO_LINE_SILENT = re.compile(
    r"except\s+(?:Exception|BaseException)?\s*(?:\w+)?\s*:\s*\n\s*pass\s*$",
    re.MULTILINE,
)

PRODUCTION_DIRS = ["harness", "server"]


def _is_test_file(path: Path) -> bool:
    return "test_" in path.name or "/tests/" in str(path) or "\\tests\\" in str(path)


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
                    line_no = text[:match.start()].count("\n") + 1
                    violations.append(
                        f"{path.relative_to(Path(__file__).resolve().parent.parent.parent)}:{line_no}: {match.group().strip()!r}"
                    )

    assert not violations, (
        f"Silent except:pass found at {len(violations)} sites:\n"
        + "\n".join(violations)
    )
