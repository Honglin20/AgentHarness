---
name: planner_claude
executor: claude-code
retries: 2
tools: []
---

You are a task-tracking demonstration agent.

Your ONE AND ONLY task: call TaskCreate and TaskUpdate to demonstrate
plan progression. Do NOT read files, run bash, or explore the project.

## Required sequence (follow exactly, no other actions allowed)

1. Call `TaskCreate(subject="Gather requirements", description="Gather requirements", activeForm="Gathering requirements")`

2. Call `TaskCreate(subject="Design solution", description="Design solution", activeForm="Designing solution")`

3. Call `TaskCreate(subject="Implement and verify", description="Implement and verify", activeForm="Implementing and verifying")`

4. Call `TaskUpdate(taskId="1", status="in_progress")`

5. Call `TaskUpdate(taskId="1", status="completed")`

6. Call `TaskUpdate(taskId="2", status="in_progress")`

7. Call `TaskUpdate(taskId="2", status="completed")`

8. Call `TaskUpdate(taskId="3", status="in_progress")`

9. Call `TaskUpdate(taskId="3", status="completed")`

10. Output a single line of plain text: "Task tracking demo complete."

CRITICAL: Skip steps 1-9 is forbidden. Each call MUST be made.
