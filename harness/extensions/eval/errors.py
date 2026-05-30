from __future__ import annotations


class EvalNotCompiledError(RuntimeError):
    """Raised when ``Workflow.save()`` is called on a workflow that still has
    ``Agent(eval=True)`` agents. The user must call ``Workflow.compile()`` first
    so EvalJudge can materialize judge nodes into ``workflow.json``.
    """


class EvalCompileError(RuntimeError):
    """Raised when ``EvalJudge.persist()`` cannot summarize a target agent
    (e.g. LLM unreachable, summarizer timeout). Aborts compile and prevents save.
    """
