"""NAS workflow registration package.

Source of truth for the NAS workflow definition. Run ``register.py`` to
regenerate ``workflows/nas/workflow.json`` with embedded Pydantic schemas.

Layout:
  schemas.py    — all Pydantic result_types (agent outputs + sub_agent file formats)
  register.py   — Agent + Workflow definition; call ``python register.py`` to save
"""
