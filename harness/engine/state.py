import logging
from typing import TypedDict, Annotated

logger = logging.getLogger(__name__)


def merge_dicts(left: dict, right: dict) -> dict:
    """Reducer that merges dicts. Right overwrites left on key conflict."""
    if right:
        conflicts = set(left) & set(right)
        if conflicts:
            logger.warning("merge_dicts: key conflict overwritten: %s", conflicts)
    return {**left, **right}


class HarnessState(TypedDict):
    inputs: dict                                # 工作流初始输入，贯穿所有节点
    outputs: Annotated[dict, merge_dicts]       # {agent_name: result} — reducer 自动合并 fan-out
    errors: Annotated[dict, merge_dicts]        # {agent_name: error_info}
    metadata: Annotated[dict, merge_dicts]      # 可扩展插槽
    iteration_counts: Annotated[dict, merge_dicts]  # {edge_key: count} — 条件边回环计数
    # {node_id: count} — universal invocation counter, incremented every time
    # node_func runs. Used to stamp `iteration` on node.started events and
    # todo steps. Distinct from iteration_counts (which is conditional_edge-
    # specific). Plan F.
    node_invocation_counts: Annotated[dict, merge_dicts]
