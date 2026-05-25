# Agent I/O Viewer — Design

> Date: 2026-05-22

## Problem

During workflow execution, users cannot inspect what input an agent received or what structured output it produced. The agent's input prompt (assembled by `build_node_prompt`) and its structured result (`AgentResult` or custom `result_type`) are never transmitted to the frontend. Only streamed text is visible.

## Design

### §1 Backend — Extend `node.completed` event

Add two fields to the `node.completed` event payload:

```python
event_payload = {
    "workflow_id": builder_self.workflow_id,
    "node_id": agent_def.name,
    "agent_name": agent_def.name,
    "duration_ms": duration_ms,
    "status": "success",
    "input_prompt": context,           # Full build_node_prompt output
    "output_result": output.model_dump() if isinstance(output, BaseModel) else str(output),
}
```

- `input_prompt`: The `context` variable already assembled in `_make_node_func` — includes `## Task`, `## Output from X`, `## Previous judgment`, `## Available scripts`. This is the final version (after `before_node` middleware mutations).
- `output_result`: `AgentResult.model_dump()` or custom `result_type`'s `model_dump()`. Frontend receives a standard JSON object.

Why `node.completed` (not `node.started`): The input prompt may be mutated by `before_node` middleware, which runs after `node.started`. The completed event carries the final, accurate version.

### §2 Frontend — Data storage

New `agentIOStore` (Zustand):

```typescript
// frontend/src/stores/agentIOStore.ts
interface AgentIOState {
  data: Record<string, { inputPrompt: string; outputResult: unknown }>;
  setAgentIO: (nodeId: string, inputPrompt: string, outputResult: unknown) => void;
  reset: () => void;
}
```

Populated from `useWorkflowEvents.ts` `node.completed` handler:

```typescript
case "node.completed": {
  const p = event.payload as unknown as NodeCompletedPayload;
  // ... existing handlers ...
  if (p.input_prompt || p.output_result) {
    useAgentIOStore.getState().setAgentIO(p.node_id, p.input_prompt ?? "", p.output_result);
  }
  break;
}
```

Not stored in `conversationStore` — that's for the conversation message stream. Agent I/O viewing is an independent debug/audit feature.

### §3 Frontend — Agent Header buttons + Sheet

**Buttons on AgentMessage header**: Two small icon buttons (lucide-react) next to the agent name:
- Input button (`FileInput` icon, tooltip "查看输入")
- Output button (`FileOutput` icon, tooltip "查看输出")

Only visible when `status === "done"` (data only available after completion).

**Sheet component**: Uses shadcn/ui `Sheet` (Radix Dialog-based), slides from right:

```typescript
<Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
  <SheetContent side="right" className="w-[500px]">
    <SheetHeader>
      <SheetTitle>{activeTab === "input" ? "输入" : "输出"} — {agentName}</SheetTitle>
    </SheetHeader>
    <div className="p-4">
      {activeTab === "input" ? (
        <pre className="text-sm whitespace-pre-wrap">{inputPrompt}</pre>
      ) : (
        <pre className="text-sm whitespace-pre-wrap">{JSON.stringify(outputResult, null, 2)}</pre>
      )}
    </div>
  </SheetContent>
</Sheet>
```

- Input shown as raw `<pre>` text (markdown prompt, verbatim display is better for debugging)
- Output shown as formatted JSON (`JSON.stringify` with indent=2)
- Sheet state (`sheetOpen`, `activeTab`) managed locally per `AgentMessage` component

## Impact

### Backend changes

| File | Change |
|------|--------|
| `harness/engine/macro_graph.py` | Add `input_prompt` and `output_result` fields to `node.completed` event payload |

### Frontend changes

| File | Change |
|------|--------|
| `frontend/src/stores/agentIOStore.ts` | New store |
| `frontend/src/hooks/useWorkflowEvents.ts` | Write to agentIOStore on `node.completed` |
| `frontend/src/types/events.ts` | Add `input_prompt` and `output_result` to `NodeCompletedPayload` |
| `frontend/src/components/conversation/AgentMessage.tsx` | Add input/output buttons + Sheet |
