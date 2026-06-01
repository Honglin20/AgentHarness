# Framework Overview HTML Redesign

Date: 2026-06-01
Status: Design Approved

## Goal

Replace the current `framework-overview.html` with a clean, investor-facing static SVG that communicates the core value proposition: **Agent is no longer a black box — full lifecycle control through three extension types**.

## Audience

Potential users / investors. The diagram must be understandable without reading code. Technical accuracy matters, but narrative clarity matters more.

## File

`framework-overview.html` — single file, inline SVG, no external dependencies.

---

## Overall Layout

viewBox: `1500 × 1050`

Four vertical sections, top to bottom:

| Section | Y range | Visual weight | Purpose |
|---------|---------|---------------|---------|
| Title | 0–55 | Low | Name + one-liner |
| Baseline | 60–150 | Low (grey) | Establish the "vanilla" flow |
| Three Extensions | 160–370 | Medium (3 columns) | Teach the three mechanisms |
| **Full Overview** | 380–880 | **High (50% of canvas)** | All modifications combined |
| Bottom Bar | 890–950 | Low | System-level capabilities |

---

## Section 1: Title (y: 0–55)

```
AgentHarness — Agent 全生命周期框架
三层扩展机制，让 Agent 从黑盒变成可控工程
```

## Section 2: Baseline (y: 60–150)

Grey tones, dashed lines, small font. Purpose: show what "without harness" looks like.

```
Prompt ─ ─ ─ ─ ─ ─ ─ ─ → [ Agent 黑盒 ] ─ ─ ─ ─ ─ ─ ─ ─ → Result
(用户指令)                                              (原始输出)

标注: 不可控 · 不可观测 · 不可信赖
```

- Grey dashed lines for connections
- Agent box is a solid grey rectangle with "黑盒" label
- Height: ~90px, compact

## Section 3: Three Extensions — Compact 3-Column Comparison (y: 160–370)

Three cards side by side. Each card shows the extension type's **effect on the baseline**.

### Column 1: Middleware (orange `#d97706`)

**What it does:** Modifies data flow, doesn't change graph structure.

```
Prompt →[Memory/Compact]→ Agent →[Guardrail/Budget]→ Result
          enrich ↑                   filter ↑

Runtime · Sequential · Can reject/retry
```

- Show a small inline mini-flow: Prompt branches into Memory box, enriched prompt feeds back to Agent
- Output side: Agent output branches into Guardrail, filtered output feeds to Result
- Orange solid lines for branches

### Column 2: Hook (blue `#3b82f6`, semi-transparent)

**What it does:** Observes only, never modifies.

```
Prompt ─→ Agent ─→ Result
  ↓ trace   ↓ trace   ↓ trace

Concurrent · Non-blocking · Read-only
```

- Main line unchanged (solid)
- Dotted blue lines dropping down to observation points (Trace, Console, Chart, Persist)
- Semi-transparent visual weight to convey "presence without interference"

### Column 3: GraphMutator (red `#e11d48`)

**What it does:** Rewrites DAG structure at compile time.

```
Before: A ────→ B

After:  A → [EvalJudge] → B
              ↩ fail → retry

Compile-time · Structural change · Inserts nodes
```

- "Before" dimmed, "After" highlighted
- EvalJudge box inserted between A and B
- Red loop arrow for retry

### Layout Notes

- Each card: ~450px wide, ~200px tall
- Cards separated by ~20px gaps
- Each card has a colored header bar with the extension type name
- Bottom of each card: one-line summary of its nature (runtime vs compile-time, modifies vs observes)

## Section 4: Full Overview — All Modifications Combined (y: 380–880)

**This is the most important section. It occupies ~50% of the canvas.**

The design must make it visually obvious **where and how each extension type modifies the baseline flow**. Use color coding consistently from Section 3.

### Structure

One horizontal main line from left to right with extension points branching off and rejoining:

```
Prompt ──→ [Memory] ──→ [Compact] ──→ ┌─────────────────────┐ ──→ [Validate] ──→ [EvalJudge] ──→ Result
           │  Middleware │  Middleware  │       Agent         │      │Middleware│     │GraphMutator│
           │  输入增强    │  上下文压缩   │                     │      │类型校验   │     │ 自动评审    │
           └──────┬──────┘──────────────│  ┌───────────────┐  │      └─────┬────┘     └──────┬─────┘
                  │                     │  │  Tool Call    │  │            │                 │ ↩ retry
                  │                     │  │ ┌Pre┐→┌Exec┐→┌Post┐ │            │                 ↓
                  │                     │  │ │Hook│ │    │ │Hook│ │            ↓              Scored
                  │                     │  │ └───┘ └───┘ └───┘ │       Structured           Output
                  ↓                     │  └───────────────┘  │       Output
            Enriched Prompt             └──────────┬──────────┘
                                                      │
 ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ Hook 观测层（虚线，贯穿全流程）─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
  │Trace     │Log       │Console   │Chart      │Persist     │Budget
  ▼          ▼          ▼          ▼           ▼            ▼
```

### Visual Layering (top to bottom within the section)

1. **Main line** (purple `#6366f1`, thick solid): Prompt → Result backbone, always visible
2. **Middleware branches** (orange `#d97706`, solid): Branch off main line, process data, rejoin main line
   - Input side: Memory (cross-turn persistent context) + Compact (context compression)
   - Output side: Validate (Pydantic type-safe output) + Guardrail (content filtering)
3. **Agent internals** (the Agent node is expanded to show):
   - Pre-hook → Tool Execute → Post-hook (yellow `#d97706` Hook markers)
   - This shows Hooks wrapping tool calls inside the agent
4. **GraphMutator** (red `#e11d48`): EvalJudge node inserted after output validation
   - Pass path → Result
   - Fail loop → retry back to Agent
5. **Hook observation layer** (blue dashed `#3b82f6`, semi-transparent): A horizontal dashed line running beneath the entire flow with observation points dropping down at each node

### Color Legend (top-right corner of this section)

```
● 紫色 主线 (Prompt → Result)
● 橙色 Middleware (改数据流)
● 黄色 Hook (过程管控)
● 红色 GraphMutator (改图结构)
● 蓝色虚线 Observability (只读观测)
```

### Key Design Requirements

- Each extension's contribution must be **color-coded and visually traceable** — the viewer should be able to follow orange to understand Middleware, red for GraphMutator, blue dashed for Hooks
- The baseline grey path from Section 2 should be **ghosted behind** the full overview, so the viewer sees the "before" underneath the "after"
- Branch points where Middleware diverts from the main line should have clear **fork + rejoin** visual markers
- EvalJudge's retry loop should be the most eye-catching element (red loop arrow) — it's the "aha" moment of the framework
- Status badges on each module: 🟢 已实现 / 🟡 规划中

### Module → Status Mapping

| Module | Type | Status |
|--------|------|--------|
| Memory | Middleware | 🟡 规划中 |
| Compact | Middleware | 🟢 已实现 |
| Guardrail | Middleware | 🟢 已实现 |
| Validate (Pydantic) | Middleware | 🟢 已实现 |
| EvalJudge | GraphMutator | 🟢 已实现 |
| Pre/Post Hook | Hook | 🟢 已实现 |
| Trace/Console/Chart/Persist | Hook | 🟢 已实现 |
| Budget Monitor | Hook | 🟡 规划中 |

## Section 5: Bottom Bar (y: 890–950)

Single horizontal bar with system-level capabilities:

```
Multi-Agent DAG · Serial · Parallel (fan-in/out) · Conditional Routing · Checkpoint · Streaming · Cost Tracking · Benchmark
```

Light background, subtle border, one line of text.

---

## Technical Constraints

- Pure SVG embedded in HTML, no external CSS/JS
- All text in Chinese (with English technical terms where appropriate)
- Responsive: `width: 100%; height: auto` on the SVG
- Max width: 1500px wrapper
- Font: system-ui stack
- Must render correctly in Chrome, Safari, Firefox

## Design Principles

1. **Narrative over comprehensiveness** — tell the story of "baseline → enhanced"
2. **Color as narrative** — each extension type has its own color, consistent throughout
3. **Total overview gets 50% of space** — it's the takeaway image
4. **Status badges ground the story** — show what's real vs planned
5. **No animation** — static, embeddable, lightweight
