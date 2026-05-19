from typing import TypedDict, Annotated


def merge_dicts(left: dict, right: dict) -> dict:
    """Reducer that merges dicts. Right overwrites left on key conflict."""
    return {**left, **right}


class HarnessState(TypedDict):
    inputs: dict                                # 工作流初始输入，贯穿所有节点
    outputs: Annotated[dict, merge_dicts]       # {agent_name: result} — reducer 自动合并 fan-out
    errors: Annotated[dict, merge_dicts]        # {agent_name: error_info}
    metadata: Annotated[dict, merge_dicts]      # 可扩展插槽
