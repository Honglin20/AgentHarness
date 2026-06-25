"""PROMPT assembly layer.

Centralizes how an agent's final system prompt is built from layered sources.
See docs/plans/2026-06-23-prompt-system-refactor-plan.md for the design.

Layering (outer = first seen by the model):
  [base]    harness/prompts/base.md   — cross-agent working norms   (TASK 3)
  [agent]   agents/<name>.md body     — domain logic (caller-supplied)
  [output]  ## Output Format + schema — derived from result_type      (TASK 1)

Layers are assembled at agent-construction time into a single static string
and fed to pydantic-ai. A dynamic runtime-status layer is registered
separately via @agent.system_prompt(dynamic=True) in TASK 4.

Centralization policy (see plan §1):
  - base.md, runtime.py, feedback.py, assembler.py live HERE (shared ≥2 units)
  - agent.md bodies stay in workflows/ (domain-coupled)
  - tool descriptions stay in tools/*.py (behavior-coupled)
"""
from harness.prompts.assembler import assemble_static_prompt

__all__ = ["assemble_static_prompt"]
