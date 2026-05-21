from collections import defaultdict


class CycleError(Exception):
    pass


class MissingDependencyError(Exception):
    pass


def build_dag(agents: list) -> list[str]:
    """Build a DAG from agent definitions and return topologically sorted names.

    Conditional edges (on_pass/on_fail) are excluded from topological sort
    since they may form back-loops (e.g., reviewer on_fail -> coder).
    Only static `after` edges are validated for cycles.

    Args:
        agents: List of objects with .name, .after, and optionally .on_pass/.on_fail.

    Returns:
        List of agent names in topological order.

    Raises:
        ValueError: If duplicate agent names are found.
        MissingDependencyError: If a dependency references a non-existent agent.
        CycleError: If a cycle is detected in static dependencies.
    """
    # Check for duplicates
    names = [a.name for a in agents]
    if len(names) != len(set(names)):
        dupes = [n for n in names if names.count(n) > 1]
        raise ValueError(f"Duplicate agent names: {set(dupes)}")

    name_set = set(names)

    # Collect all valid target names (includes conditional edge targets)
    conditional_targets = set()
    for agent in agents:
        if hasattr(agent, 'on_pass') and agent.on_pass:
            conditional_targets.add(agent.on_pass)
        if hasattr(agent, 'on_fail') and agent.on_fail:
            conditional_targets.add(agent.on_fail)

    # Check for missing dependencies (both after and conditional targets)
    for agent in agents:
        for dep in agent.after:
            if dep not in name_set:
                raise MissingDependencyError(
                    f"Agent '{agent.name}' depends on '{dep}', which does not exist"
                )
        for target in conditional_targets:
            if target not in name_set:
                raise MissingDependencyError(
                    f"Agent '{agent.name}' has conditional target '{target}', which does not exist"
                )

    # Build adjacency list using ONLY static `after` edges (not conditional)
    graph = defaultdict(list)
    in_degree = {name: 0 for name in names}

    for agent in agents:
        for dep in agent.after:
            graph[dep].append(agent.name)
            in_degree[agent.name] += 1

    # Kahn's algorithm for topological sort
    queue = [name for name, deg in in_degree.items() if deg == 0]
    result = []

    while queue:
        queue.sort()  # deterministic ordering
        node = queue.pop(0)
        result.append(node)

        for neighbor in graph[node]:
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    if len(result) != len(names):
        raise CycleError("Cycle detected in static agent dependencies (after=[]). "
                         "Conditional edges (on_pass/on_fail) are excluded from this check.")

    return result
