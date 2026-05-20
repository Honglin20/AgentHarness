from pydantic import BaseModel


class AgentDeps(BaseModel):
    """通过 RunContext.deps 传递给工具的运行时上下文"""
    workdir: str = "."
    agent_name: str = ""
    depth: int = 0

    model_config = {"extra": "allow"}
