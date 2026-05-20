from abc import ABC, abstractmethod

from pydantic_ai import Tool as PydanticAITool


class ToolNotFoundError(Exception):
    pass


class ToolFactory(ABC):
    """Abstract tool factory — subclasses must implement create()."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def create(self) -> PydanticAITool: ...


class ToolRegistry:
    """工具名 → ToolFactory 的注册表"""

    def __init__(self):
        self._factories: dict[str, ToolFactory] = {}

    def register(self, name: str, factory: ToolFactory) -> None:
        self._factories[name] = factory

    def resolve(
        self,
        tool_names: list[str] | None = None,
        exclude: list[str] | None = None,
    ) -> list[PydanticAITool]:
        exclude_set = set(exclude or [])

        if tool_names is None:
            names = [n for n in self._factories if n not in exclude_set]
        else:
            for name in tool_names:
                if name not in self._factories:
                    raise ToolNotFoundError(f"Tool '{name}' not registered")
            names = [n for n in tool_names if n not in exclude_set]

        return [self._factories[n].create() for n in names]

    def list_tools(self) -> list[str]:
        return list(self._factories.keys())
