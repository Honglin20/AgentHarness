# Framework Overview HTML Redesign — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace `framework-overview.html` with a clean, investor-facing static SVG showing how Hook/Middleware/GraphMutator progressively modify the Agent lifecycle.

**Architecture:** Single HTML file with inline SVG. Built in layers: shell → baseline → three extension cards → full overview pipeline → bottom bar. Each task adds one SVG section.

**Tech Stack:** Pure HTML + SVG, no dependencies.

**Design doc:** `docs/plans/2026-06-01-framework-overview-redesign-design.md`

---

## Color Palette (used throughout)

| Role | Color | Hex |
|------|-------|-----|
| Main line / baseline | Purple | `#6366f1` |
| Middleware | Orange | `#d97706` |
| Hook | Amber/Yellow | `#f59e0b` |
| GraphMutator | Red/Rose | `#e11d48` |
| Observability | Blue | `#3b82f6` |
| Grey baseline | Slate | `#94a3b8` |
| Text primary | Dark | `#0f172a` |
| Text secondary | Muted | `#64748b` |
| Implemented badge | Green | `#16a34a` bg `#dcfce7` |
| Planned badge | Amber | `#d97706` bg `#fef3c7` |

---

## Task 1: HTML Shell + SVG Defs + Title

**Files:**
- Rewrite: `framework-overview.html`

**Step 1: Write the HTML shell with defs and title section**

Replace entire file content with:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AgentHarness — Agent 全生命周期框架</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{background:#fff;display:flex;justify-content:center;align-items:flex-start;min-height:100vh;padding:1.5rem;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',system-ui,sans-serif}
.wrap{width:100%;max-width:1500px}
svg{width:100%;height:auto;display:block}
</style>
</head>
<body>
<div class="wrap">
<svg viewBox="0 0 1500 1050" xmlns="http://www.w3.org/2000/svg">
<defs>
  <!-- Arrow markers -->
  <marker id="a" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0,8 3,0 6" fill="#94a3b8"/></marker>
  <marker id="ap" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0,8 3,0 6" fill="#6366f1"/></marker>
  <marker id="ao" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0,8 3,0 6" fill="#d97706"/></marker>
  <marker id="ah" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0,8 3,0 6" fill="#f59e0b"/></marker>
  <marker id="ar" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0,8 3,0 6" fill="#e11d48"/></marker>
  <marker id="ab" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0,8 3,0 6" fill="#3b82f6"/></marker>
  <filter id="sh"><feDropShadow dx="0" dy="1" stdDeviation="2" flood-opacity="0.06"/></filter>
</defs>

<!-- ═══════════════════════════════════════════════════ -->
<!-- TITLE                                             -->
<!-- ═══════════════════════════════════════════════════ -->
<text x="750" y="30" text-anchor="middle" font-size="24" font-weight="700" fill="#0f172a" letter-spacing="-0.5">AgentHarness — Agent 全生命周期框架</text>
<text x="750" y="50" text-anchor="middle" font-size="12" fill="#64748b">三层扩展机制，让 Agent 从黑盒变成可控工程</text>

<!-- === PLACEHOLDERS FOR NEXT TASKS === -->

</svg>
</div>
</body>
</html>
```

**Step 2: Open in browser to verify title renders**

Run: `open framework-overview.html`
Expected: White page with centered title and subtitle text.

**Step 3: Commit**

```bash
git add framework-overview.html
git commit -m "wip: framework overview redesign — shell + title"
```

---

## Task 2: Baseline Section (y: 60–150)

**Files:**
- Modify: `framework-overview.html` — replace `<!-- === PLACEHOLDERS === -->`

**Step 1: Add baseline SVG section**

Insert after the title, before the closing `</svg>`:

```svg
<!-- ═══════════════════════════════════════════════════ -->
<!-- BASELINE — 原始流程 (grey)                         -->
<!-- ═══════════════════════════════════════════════════ -->

<!-- Section background -->
<rect x="30" y="62" width="1440" height="90" rx="10" fill="#f8fafc" stroke="#e2e8f0" stroke-width="1"/>

<!-- Section label -->
<text x="60" y="82" font-size="10" font-weight="700" fill="#94a3b8">BASELINE — 原始流程</text>

<!-- Prompt box -->
<rect x="70" y="98" width="120" height="42" rx="10" fill="#f1f5f9" stroke="#cbd5e1" stroke-width="1.5" filter="url(#sh)"/>
<text x="130" y="124" text-anchor="middle" font-size="14" font-weight="600" fill="#94a3b8">Prompt</text>

<!-- Dashed arrow Prompt → Agent -->
<line x1="190" y1="119" x2="645" y2="119" stroke="#cbd5e1" stroke-width="1.5" stroke-dasharray="6 4"/>
<text x="420" y="112" text-anchor="middle" font-size="8" fill="#cbd5e1">不可控</text>

<!-- Agent box (black box) -->
<rect x="650" y="92" width="200" height="54" rx="14" fill="#94a3b8" filter="url(#sh)"/>
<text x="750" y="125" text-anchor="middle" font-size="16" font-weight="700" fill="#fff">Agent 黑盒</text>

<!-- Dashed arrow Agent → Result -->
<line x1="850" y1="119" x2="1310" y2="119" stroke="#cbd5e1" stroke-width="1.5" stroke-dasharray="6 4"/>
<text x="1080" y="112" text-anchor="middle" font-size="8" fill="#cbd5e1">不可观测</text>

<!-- Result box -->
<rect x="1315" y="98" width="120" height="42" rx="10" fill="#f1f5f9" stroke="#cbd5e1" stroke-width="1.5" filter="url(#sh)"/>
<text x="1375" y="124" text-anchor="middle" font-size="14" font-weight="600" fill="#94a3b8">Result</text>

<!-- Callout -->
<text x="750" y="148" text-anchor="middle" font-size="9" fill="#94a3b8">不可控 · 不可观测 · 不可信赖</text>
```

**Step 2: Open in browser**

Run: `open framework-overview.html`
Expected: Grey baseline flow visible under title.

**Step 3: Commit**

```bash
git add framework-overview.html
git commit -m "wip: add baseline section to framework overview"
```

---

## Task 3: Three Extension Cards (y: 160–370)

**Files:**
- Modify: `framework-overview.html` — insert after baseline section

**Step 1: Add three extension cards**

Three cards side by side, each ~450px wide with 20px gaps.

Card layout:
- Card 1 (Middleware): x:30–490, orange `#d97706`
- Card 2 (Hook): x:510–990, amber `#f59e0b`
- Card 3 (GraphMutator): x:1010–1470, red `#e11d48`

Each card contains:
1. Colored header bar with type name
2. Small inline mini-flow showing **how it modifies the baseline**
3. One-line nature summary at bottom

**Card 1 — Middleware (orange):**
```svg
<!-- ═══════════════════════════════════════════════════ -->
<!-- THREE EXTENSIONS — 3 columns                       -->
<!-- ═══════════════════════════════════════════════════ -->

<!-- Card 1: Middleware (orange) -->
<rect x="30" y="165" width="460" height="210" rx="12" fill="#fffbeb" stroke="#d97706" stroke-width="1.2" stroke-dasharray="6 3"/>
<!-- Header -->
<rect x="30" y="165" width="460" height="28" rx="12" fill="#d97706"/>
<rect x="30" y="180" width="460" height="13" fill="#d97706"/>
<text x="260" y="184" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">Middleware — 改数据流，不改结构</text>

<!-- Mini-flow: input side -->
<text x="55" y="220" font-size="9" font-weight="600" fill="#92400e">输入侧:</text>
<rect x="55" y="228" width="70" height="26" rx="6" fill="#eef2ff" stroke="#c7d2fe" stroke-width="1"/>
<text x="90" y="245" text-anchor="middle" font-size="9" fill="#6366f1">Prompt</text>
<line x1="125" y1="241" x2="150" y2="241" stroke="#d97706" stroke-width="1.2" marker-end="url(#ao)"/>
<rect x="155" y="228" width="80" height="26" rx="6" fill="#d97706" filter="url(#sh)"/>
<text x="195" y="245" text-anchor="middle" font-size="9" font-weight="700" fill="#fff">Memory</text>
<line x1="235" y1="241" x2="260" y2="241" stroke="#d97706" stroke-width="1.2" marker-end="url(#ao)"/>
<rect x="265" y="228" width="90" height="26" rx="6" fill="#fef3c7" stroke="#d97706" stroke-width="1"/>
<text x="310" y="245" text-anchor="middle" font-size="8" font-weight="600" fill="#92400e">丰富指令</text>

<!-- Mini-flow: output side -->
<text x="55" y="275" font-size="9" font-weight="600" fill="#92400e">输出侧:</text>
<rect x="55" y="283" width="70" height="26" rx="6" fill="#eef2ff" stroke="#c7d2fe" stroke-width="1"/>
<text x="90" y="300" text-anchor="middle" font-size="9" fill="#6366f1">Output</text>
<line x1="125" y1="296" x2="150" y2="296" stroke="#d97706" stroke-width="1.2" marker-end="url(#ao)"/>
<rect x="155" y="283" width="80" height="26" rx="6" fill="#d97706" filter="url(#sh)"/>
<text x="195" y="300" text-anchor="middle" font-size="9" font-weight="700" fill="#fff">Validate</text>
<line x1="235" y1="296" x2="260" y2="296" stroke="#d97706" stroke-width="1.2" marker-end="url(#ao)"/>
<rect x="265" y="283" width="90" height="26" rx="6" fill="#fef3c7" stroke="#d97706" stroke-width="1"/>
<text x="310" y="300" text-anchor="middle" font-size="8" font-weight="600" fill="#92400e">结构化输出</text>

<!-- Compact + Guardrail mentioned -->
<text x="55" y="335" font-size="8" fill="#78716c">Compact · Guardrail · Budget — 运行时顺序执行</text>
<rect x="380" y="325" width="56" height="14" rx="3" fill="#fef3c7"/>
<text x="408" y="336" text-anchor="middle" font-size="8" font-weight="600" fill="#d97706">Middleware</text>

<!-- Key insight -->
<text x="55" y="358" font-size="9" font-weight="600" fill="#92400e">运行时 · 拦截数据流 · 可 reject/retry</text>
```

**Card 2 — Hook (amber):**
```svg
<!-- Card 2: Hook (amber) -->
<rect x="510" y="165" width="460" height="210" rx="12" fill="#fffbeb" stroke="#f59e0b" stroke-width="1.2" stroke-dasharray="6 3"/>
<rect x="510" y="165" width="460" height="28" rx="12" fill="#f59e0b"/>
<rect x="510" y="180" width="460" height="13" fill="#f59e0b"/>
<text x="740" y="184" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">Hook — 只观察，不改任何数据</text>

<!-- Main flow (unchanged) -->
<rect x="535" y="228" width="70" height="26" rx="6" fill="#eef2ff" stroke="#c7d2fe" stroke-width="1"/>
<text x="570" y="245" text-anchor="middle" font-size="9" fill="#6366f1">Prompt</text>
<line x1="605" y1="241" x2="640" y2="241" stroke="#94a3b8" stroke-width="1" marker-end="url(#a)"/>
<rect x="645" y="228" width="70" height="26" rx="6" fill="#6366f1" filter="url(#sh)"/>
<text x="680" y="245" text-anchor="middle" font-size="9" font-weight="700" fill="#fff">Agent</text>
<line x1="715" y1="241" x2="750" y2="241" stroke="#94a3b8" stroke-width="1" marker-end="url(#a)"/>
<rect x="755" y="228" width="70" height="26" rx="6" fill="#eef2ff" stroke="#c7d2fe" stroke-width="1"/>
<text x="790" y="245" text-anchor="middle" font-size="9" fill="#6366f1">Result</text>

<!-- Observation points dropping down (dotted blue) -->
<line x1="570" y1="254" x2="570" y2="280" stroke="#3b82f6" stroke-width="1" stroke-dasharray="3 2"/>
<text x="570" y="292" text-anchor="middle" font-size="8" fill="#3b82f6">Trace</text>
<line x1="680" y1="254" x2="680" y2="280" stroke="#3b82f6" stroke-width="1" stroke-dasharray="3 2"/>
<text x="680" y="292" text-anchor="middle" font-size="8" fill="#3b82f6">Console</text>
<line x1="790" y1="254" x2="790" y2="280" stroke="#3b82f6" stroke-width="1" stroke-dasharray="3 2"/>
<text x="790" y="292" text-anchor="middle" font-size="8" fill="#3b82f6">Chart</text>

<!-- Additional hooks listed -->
<text x="535" y="315" font-size="8" fill="#78716c">Persist · Diagnostics · Budget — 并发执行，永不阻塞</text>

<!-- Key insight -->
<text x="535" y="358" font-size="9" font-weight="600" fill="#92400e">并发 · 只读观测 · 永不阻塞主线</text>
```

**Card 3 — GraphMutator (red):**
```svg
<!-- Card 3: GraphMutator (red) -->
<rect x="990" y="165" width="480" height="210" rx="12" fill="#fff1f2" stroke="#e11d48" stroke-width="1.2" stroke-dasharray="6 3"/>
<rect x="990" y="165" width="480" height="28" rx="12" fill="#e11d48"/>
<rect x="990" y="180" width="480" height="13" fill="#e11d48"/>
<text x="1230" y="184" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">GraphMutator — 改写 DAG 结构，插入节点</text>

<!-- Before -->
<text x="1015" y="220" font-size="9" font-weight="600" fill="#9f1239">Before:</text>
<rect x="1070" y="208" width="70" height="24" rx="6" fill="#eef2ff" stroke="#c7d2fe" stroke-width="1"/>
<text x="1105" y="224" text-anchor="middle" font-size="9" fill="#6366f1">Agent A</text>
<line x1="1140" y1="220" x2="1180" y2="220" stroke="#94a3b8" stroke-width="1" stroke-dasharray="4 3"/>
<rect x="1185" y="208" width="70" height="24" rx="6" fill="#eef2ff" stroke="#c7d2fe" stroke-width="1"/>
<text x="1220" y="224" text-anchor="middle" font-size="9" fill="#6366f1">Agent B</text>

<!-- Arrow down to After -->
<path d="M1220 232 L1220 248" stroke="#e11d48" stroke-width="1" marker-end="url(#ar)"/>
<text x="1240" y="244" font-size="7" fill="#e11d48">mutate</text>

<!-- After -->
<text x="1015" y="272" font-size="9" font-weight="600" fill="#9f1239">After:</text>
<rect x="1070" y="258" width="70" height="24" rx="6" fill="#eef2ff" stroke="#c7d2fe" stroke-width="1"/>
<text x="1105" y="274" text-anchor="middle" font-size="9" fill="#6366f1">Agent A</text>
<line x1="1140" y1="270" x2="1170" y2="270" stroke="#e11d48" stroke-width="1.5" marker-end="url(#ar)"/>

<!-- EvalJudge inserted -->
<rect x="1175" y="255" width="90" height="30" rx="8" fill="#e11d48" filter="url(#sh)"/>
<text x="1220" y="275" text-anchor="middle" font-size="9" font-weight="700" fill="#fff">EvalJudge</text>
<line x1="1265" y1="270" x2="1295" y2="270" stroke="#10b981" stroke-width="1.5" marker-end="url(#a)"/>
<text x="1280" y="264" font-size="7" fill="#10b981">pass</text>
<rect x="1300" y="258" width="70" height="24" rx="6" fill="#dcfce7" stroke="#10b981" stroke-width="1"/>
<text x="1335" y="274" text-anchor="middle" font-size="9" fill="#065f46">Agent B</text>

<!-- Retry loop -->
<path d="M1220 285 L1220 305 L1105 305 L1105 282" stroke="#ef4444" stroke-width="1" stroke-dasharray="3 2" marker-end="url(#a)" fill="none"/>
<text x="1162" y="318" text-anchor="middle" font-size="8" fill="#ef4444">fail → retry</text>

<!-- Key insight -->
<text x="1015" y="358" font-size="9" font-weight="600" fill="#9f1239">编译时 · 改写图结构 · 插入新节点</text>
```

**Step 2: Open in browser**

Run: `open framework-overview.html`
Expected: Three colored cards side by side below baseline.

**Step 3: Commit**

```bash
git add framework-overview.html
git commit -m "wip: add three extension cards to framework overview"
```

---

## Task 4: Full Overview — Section Header + Main Line (y: 385–530)

This is the core of the diagram. The main pipeline with Prompt → Result and the expanded Agent node.

**Files:**
- Modify: `framework-overview.html` — insert after the three cards section

**Step 1: Add full overview header, color legend, and main line**

The main flow runs at y=500 (center of the overview section).

X coordinates for main nodes:
- Prompt: x:50-160
- Memory: x:215-325
- Compact: x:360-470
- Agent: x:530-760
- Validate: x:820-930
- EvalJudge: x:980-1120
- Result: x:1200-1370

```svg
<!-- ═══════════════════════════════════════════════════ -->
<!-- FULL OVERVIEW — 全部改造叠加                       -->
<!-- ═══════════════════════════════════════════════════ -->

<!-- Section background -->
<rect x="30" y="390" width="1440" height="510" rx="12" fill="#fafafa" stroke="#e2e8f0" stroke-width="1"/>

<!-- Section header -->
<text x="60" y="415" font-size="14" font-weight="700" fill="#0f172a">全部改造叠加 — 完整 Agent 生命周期</text>
<text x="60" y="430" font-size="9" fill="#64748b">主线 (紫色) + Middleware (橙色) + Hook (黄色) + GraphMutator (红色) + Observability (蓝色虚线)</text>

<!-- Color legend (top-right) -->
<rect x="1120" y="398" width="340" height="40" rx="6" fill="#fff" stroke="#e2e8f0" stroke-width="1"/>
<circle cx="1140" cy="412" r="4" fill="#6366f1"/><text x="1150" y="416" font-size="8" fill="#475569">主线</text>
<circle cx="1190" cy="412" r="4" fill="#d97706"/><text x="1200" y="416" font-size="8" fill="#475569">Middleware</text>
<circle cx="1280" cy="412" r="4" fill="#f59e0b"/><text x="1290" y="416" font-size="8" fill="#475569">Hook</text>
<circle cx="1340" cy="412" r="4" fill="#e11d48"/><text x="1350" y="416" font-size="8" fill="#475569">GraphMutator</text>
<circle cx="1140" cy="430" r="4" fill="#3b82f6"/><text x="1150" y="434" font-size="8" fill="#475569">Observability (虚线)</text>

<!-- ── Ghost baseline (dimmed grey behind everything) ── -->
<line x1="160" y1="500" x2="530" y2="500" stroke="#e2e8f0" stroke-width="2" stroke-dasharray="6 4"/>
<line x1="760" y1="500" x2="1200" y2="500" stroke="#e2e8f0" stroke-width="2" stroke-dasharray="6 4"/>
<text x="345" y="494" text-anchor="middle" font-size="7" fill="#e2e8f0">原始路径</text>
<text x="980" y="494" text-anchor="middle" font-size="7" fill="#e2e8f0">原始路径</text>

<!-- ══ MAIN LINE (purple) ══ -->

<!-- Prompt -->
<rect x="50" y="480" width="110" height="40" rx="10" fill="#eef2ff" stroke="#6366f1" stroke-width="2" filter="url(#sh)"/>
<text x="105" y="505" text-anchor="middle" font-size="14" font-weight="700" fill="#4f46e5">Prompt</text>

<!-- Arrow Prompt → Memory (purple, main flow passes through Memory) -->
<line x1="160" y1="500" x2="215" y2="500" stroke="#6366f1" stroke-width="2" marker-end="url(#ap)"/>

<!-- Agent (expanded node) -->
<rect x="530" y="450" width="230" height="100" rx="16" fill="#6366f1" filter="url(#sh)"/>
<text x="645" y="478" text-anchor="middle" font-size="18" font-weight="800" fill="#fff">Agent</text>

<!-- Hook sub-flow inside Agent -->
<rect x="550" y="490" width="55" height="22" rx="5" fill="#fffbeb" stroke="#f59e0b" stroke-width="1.5"/>
<text x="577" y="505" text-anchor="middle" font-size="8" font-weight="600" fill="#92400e">⚡ Pre</text>
<line x1="605" y1="501" x2="620" y2="501" stroke="#f59e0b" stroke-width="1" marker-end="url(#ah)"/>
<rect x="625" y="490" width="55" height="22" rx="5" fill="#dbeafe" stroke="#3b82f6" stroke-width="1.5"/>
<text x="652" y="505" text-anchor="middle" font-size="8" font-weight="600" fill="#1e40af">Tool</text>
<line x1="680" y1="501" x2="695" y2="501" stroke="#f59e0b" stroke-width="1" marker-end="url(#ah)"/>
<rect x="700" y="490" width="55" height="22" rx="5" fill="#fffbeb" stroke="#f59e0b" stroke-width="1.5"/>
<text x="727" y="505" text-anchor="middle" font-size="8" font-weight="600" fill="#92400e">🔍 Post</text>

<!-- Hook bracket above the three boxes -->
<path d="M550 487 L550 483 L755 483 L755 487" stroke="#f59e0b" stroke-width="1" fill="none"/>
<text x="652" y="481" text-anchor="middle" font-size="7" font-weight="600" fill="#f59e0b">Hooks — 过程管控</text>

<!-- Status badge for hooks -->
<rect x="550" y="530" width="56" height="14" rx="3" fill="#dcfce7"/>
<text x="578" y="541" text-anchor="middle" font-size="8" font-weight="600" fill="#16a34a">已实现</text>

<!-- Result -->
<rect x="1200" y="480" width="110" height="40" rx="10" fill="#eef2ff" stroke="#6366f1" stroke-width="2" filter="url(#sh)"/>
<text x="1255" y="505" text-anchor="middle" font-size="14" font-weight="700" fill="#4f46e5">Result</text>
```

**Step 2: Open in browser**

Run: `open framework-overview.html`
Expected: Full overview section with background, legend, ghost baseline, and main nodes (Prompt, Agent with hooks inside, Result).

**Step 3: Commit**

```bash
git add framework-overview.html
git commit -m "wip: full overview — header, legend, main line, agent with hooks"
```

---

## Task 5: Full Overview — Middleware Branches (Input + Output)

The Middleware branches fork off the main line and rejoin it. Orange color.

**Files:**
- Modify: `framework-overview.html` — insert inside the full overview section, between Prompt and Agent

**Step 1: Add Middleware input branches (Memory + Compact)**

These sit between Prompt and Agent. The main line forks down into Memory → Compact, then enriched prompt rejoins into Agent.

```svg
<!-- ══ MIDDLEWARE — Input side (orange) ══ -->

<!-- Memory box -->
<rect x="215" y="484" width="110" height="32" rx="8" fill="#d97706" filter="url(#sh)"/>
<text x="270" y="505" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">Memory</text>

<!-- Arrow Memory → Compact -->
<line x1="325" y1="500" x2="360" y2="500" stroke="#d97706" stroke-width="1.5" marker-end="url(#ao)"/>

<!-- Compact box -->
<rect x="365" y="484" width="110" height="32" rx="8" fill="#d97706" filter="url(#sh)"/>
<text x="420" y="505" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">Compact</text>

<!-- Arrow Compact → Agent (main line continues) -->
<line x1="475" y1="500" x2="530" y2="500" stroke="#6366f1" stroke-width="2" marker-end="url(#ap)"/>

<!-- Middleware input label -->
<text x="270" y="530" text-anchor="middle" font-size="8" fill="#d97706" font-weight="600">输入增强</text>
<text x="420" y="530" text-anchor="middle" font-size="8" fill="#d97706" font-weight="600">上下文压缩</text>

<!-- Status badges -->
<rect x="240" y="538" width="56" height="13" rx="3" fill="#fef3c7"/>
<text x="268" y="548" text-anchor="middle" font-size="7" font-weight="600" fill="#d97706">规划中</text>
<rect x="395" y="538" width="56" height="13" rx="3" fill="#dcfce7"/>
<text x="423" y="548" text-anchor="middle" font-size="7" font-weight="600" fill="#16a34a">已实现</text>

<!-- "Enriched Prompt" annotation -->
<path d="M420 484 L420 468 L490 468" stroke="#d97706" stroke-width="1" fill="none"/>
<text x="495" y="472" font-size="8" font-weight="600" fill="#d97706">丰富指令 →</text>
```

**Step 2: Add Middleware output branches (Validate + Guardrail)**

These sit between Agent and EvalJudge. Main line forks into Validate, then continues.

```svg
<!-- ══ MIDDLEWARE — Output side (orange) ══ -->

<!-- Arrow Agent → Validate -->
<line x1="760" y1="500" x2="820" y2="500" stroke="#d97706" stroke-width="2" marker-end="url(#ao)"/>

<!-- Validate box -->
<rect x="825" y="484" width="105" height="32" rx="8" fill="#d97706" filter="url(#sh)"/>
<text x="877" y="505" text-anchor="middle" font-size="11" font-weight="700" fill="#fff">Validate</text>

<!-- Arrow Validate → EvalJudge -->
<line x1="930" y1="500" x2="980" y2="500" stroke="#6366f1" stroke-width="2" marker-end="url(#ap)"/>

<!-- Middleware output label -->
<text x="877" y="530" text-anchor="middle" font-size="8" fill="#d97706" font-weight="600">Pydantic 类型校验</text>

<!-- Status badge -->
<rect x="852" y="538" width="56" height="13" rx="3" fill="#dcfce7"/>
<text x="880" y="548" text-anchor="middle" font-size="7" font-weight="600" fill="#16a34a">已实现</text>

<!-- "Structured Output" annotation -->
<path d="M877 484 L877 468 L940 468" stroke="#d97706" stroke-width="1" fill="none"/>
<text x="945" y="472" font-size="8" font-weight="600" fill="#d97706">结构化输出 →</text>
```

**Step 3: Open in browser**

Run: `open framework-overview.html`
Expected: Orange Middleware boxes (Memory, Compact, Validate) inline on the main flow between Prompt → Agent → Result.

**Step 4: Commit**

```bash
git add framework-overview.html
git commit -m "wip: full overview — middleware branches (input + output)"
```

---

## Task 6: Full Overview — GraphMutator (EvalJudge + Retry Loop)

The most visually striking element. EvalJudge node with a red retry loop.

**Files:**
- Modify: `framework-overview.html` — insert between Validate and Result

**Step 1: Add EvalJudge node and retry loop**

```svg
<!-- ══ GRAPH MUTATOR — EvalJudge (red) ══ -->

<!-- EvalJudge box -->
<rect x="985" y="475" width="130" height="50" rx="12" fill="#e11d48" filter="url(#sh)"/>
<text x="1050" y="498" text-anchor="middle" font-size="12" font-weight="700" fill="#fff">EvalJudge</text>
<text x="1050" y="514" text-anchor="middle" font-size="8" fill="#fecdd3">自动评审</text>

<!-- Arrow EvalJudge → Result (pass path) -->
<line x1="1115" y1="500" x2="1200" y2="500" stroke="#6366f1" stroke-width="2" marker-end="url(#ap)"/>
<text x="1155" y="494" text-anchor="middle" font-size="7" font-weight="600" fill="#10b981">pass ✓</text>

<!-- Retry loop — large red arc going down and back to Agent -->
<path d="M1050 525 L1050 580 L645 580 L645 550" stroke="#ef4444" stroke-width="2" stroke-dasharray="5 3" marker-end="url(#ar)" fill="none"/>
<text x="850" y="595" text-anchor="middle" font-size="9" font-weight="700" fill="#ef4444">fail → retry (max_iterations)</text>

<!-- Status badge -->
<rect x="1005" y="558" width="56" height="13" rx="3" fill="#dcfce7"/>
<text x="1033" y="568" text-anchor="middle" font-size="7" font-weight="600" fill="#16a34a">已实现</text>

<!-- GraphMutator type label -->
<text x="1050" y="610" text-anchor="middle" font-size="8" font-weight="600" fill="#e11d48">编译时插入节点</text>
```

**Step 2: Open in browser**

Run: `open framework-overview.html`
Expected: Red EvalJudge box between Validate and Result, with a dashed red retry loop going back to Agent.

**Step 3: Commit**

```bash
git add framework-overview.html
git commit -m "wip: full overview — EvalJudge with retry loop"
```

---

## Task 7: Full Overview — Hook Observation Layer

Blue dashed horizontal line running beneath the entire flow with observation points.

**Files:**
- Modify: `framework-overview.html` — insert below the retry loop area

**Step 1: Add observability layer**

```svg
<!-- ══ HOOK OBSERVATION LAYER (blue dashed) ══ -->

<!-- Horizontal dashed line spanning the flow -->
<line x1="105" y1="640" x2="1255" y2="640" stroke="#3b82f6" stroke-width="1.5" stroke-dasharray="6 4"/>

<!-- Observation point connectors -->
<line x1="105" y1="520" x2="105" y2="635" stroke="#3b82f6" stroke-width="0.8" stroke-dasharray="3 2"/>
<line x1="270" y1="555" x2="270" y2="635" stroke="#3b82f6" stroke-width="0.8" stroke-dasharray="3 2"/>
<line x1="645" y1="550" x2="645" y2="635" stroke="#3b82f6" stroke-width="0.8" stroke-dasharray="3 2"/>
<line x1="877" y1="555" x2="877" y2="635" stroke="#3b82f6" stroke-width="0.8" stroke-dasharray="3 2"/>
<line x1="1050" y1="615" x2="1050" y2="635" stroke="#3b82f6" stroke-width="0.8" stroke-dasharray="3 2"/>
<line x1="1255" y1="520" x2="1255" y2="635" stroke="#3b82f6" stroke-width="0.8" stroke-dasharray="3 2"/>

<!-- Observation point labels -->
<rect x="75" y="646" width="60" height="18" rx="4" fill="#eff6ff" stroke="#93c5fd" stroke-width="0.8"/>
<text x="105" y="659" text-anchor="middle" font-size="8" font-weight="600" fill="#2563eb">Trace</text>

<rect x="235" y="646" width="70" height="18" rx="4" fill="#eff6ff" stroke="#93c5fd" stroke-width="0.8"/>
<text x="270" y="659" text-anchor="middle" font-size="8" font-weight="600" fill="#2563eb">Logging</text>

<rect x="605" y="646" width="80" height="18" rx="4" fill="#eff6ff" stroke="#93c5fd" stroke-width="0.8"/>
<text x="645" y="659" text-anchor="middle" font-size="8" font-weight="600" fill="#2563eb">Console</text>

<rect x="845" y="646" width="65" height="18" rx="4" fill="#eff6ff" stroke="#93c5fd" stroke-width="0.8"/>
<text x="877" y="659" text-anchor="middle" font-size="8" font-weight="600" fill="#2563eb">Chart</text>

<rect x="1010" y="646" width="80" height="18" rx="4" fill="#eff6ff" stroke="#93c5fd" stroke-width="0.8"/>
<text x="1050" y="659" text-anchor="middle" font-size="8" font-weight="600" fill="#2563eb">Persist</text>

<rect x="1210" y="646" width="90" height="18" rx="4" fill="#fef3c7" stroke="#fbbf24" stroke-width="0.8"/>
<text x="1255" y="659" text-anchor="middle" font-size="8" font-weight="600" fill="#d97706">Budget</text>

<!-- Layer label -->
<text x="750" y="636" text-anchor="middle" font-size="9" font-weight="600" fill="#3b82f6">Observability Layer — 只读观测，不影响主线</text>
```

**Step 2: Open in browser**

Run: `open framework-overview.html`
Expected: Blue dashed observation line beneath the flow with labeled observation points.

**Step 3: Commit**

```bash
git add framework-overview.html
git commit -m "wip: full overview — hook observation layer"
```

---

## Task 8: Bottom Bar + Summary Annotations

**Files:**
- Modify: `framework-overview.html` — insert after observability layer

**Step 1: Add bottom bar and summary flow annotation**

```svg
<!-- ═══════════════════════════════════════════════════ -->
<!-- BOTTOM BAR — System-level capabilities            -->
<!-- ═══════════════════════════════════════════════════ -->
<rect x="30" y="920" width="1440" height="48" rx="10" fill="#f5f3ff" stroke="#7c3aed" stroke-width="1" stroke-dasharray="6 3"/>
<text x="750" y="941" text-anchor="middle" font-size="10" font-weight="600" fill="#6d28d9">Multi-Agent DAG — 每个 DAG 节点 = 一个完整的 Agent 生命周期</text>
<text x="750" y="958" text-anchor="middle" font-size="9" fill="#94a3b8">Serial · Parallel (fan-in/out) · Conditional Routing · Checkpoint · Streaming · Cost Tracking · Benchmark</text>

<!-- ═══════════════════════════════════════════════════ -->
<!-- SUMMARY FLOW — condensed one-liner below overview  -->
<!-- ═══════════════════════════════════════════════════ -->
<text x="750" y="690" text-anchor="middle" font-size="10" font-weight="600" fill="#475569">
  Prompt ──→ [Memory] ──→ [Compact] ──→ Agent (Pre→Tool→Post) ──→ [Validate] ──→ [EvalJudge] ──→ Result
</text>
<text x="750" y="705" text-anchor="middle" font-size="8" fill="#94a3b8">
  输入增强(Middleware)    上下文压缩(Middleware)    过程管控(Hook)    类型校验(Middleware)    自动评审(GraphMutator)
</text>

<!-- Three extension type labels as a summary -->
<rect x="340" y="720" width="140" height="22" rx="6" fill="#fffbeb" stroke="#d97706" stroke-width="1"/>
<text x="410" y="735" text-anchor="middle" font-size="9" font-weight="600" fill="#d97706">Middleware 改数据流</text>

<rect x="530" y="720" width="140" height="22" rx="6" fill="#fffbeb" stroke="#f59e0b" stroke-width="1"/>
<text x="600" y="735" text-anchor="middle" font-size="9" font-weight="600" fill="#f59e0b">Hook 过程管控</text>

<rect x="720" y="720" width="160" height="22" rx="6" fill="#fff1f2" stroke="#e11d48" stroke-width="1"/>
<text x="800" y="735" text-anchor="middle" font-size="9" font-weight="600" fill="#e11d48">GraphMutator 改图结构</text>

<rect x="940" y="720" width="140" height="22" rx="6" fill="#eff6ff" stroke="#3b82f6" stroke-width="1"/>
<text x="1010" y="735" text-anchor="middle" font-size="9" font-weight="600" fill="#3b82f6">Observability 观测</text>
```

**Step 2: Open in browser**

Run: `open framework-overview.html`
Expected: Bottom bar visible, summary annotations below the full overview.

**Step 3: Commit**

```bash
git add framework-overview.html
git commit -m "wip: bottom bar and summary annotations"
```

---

## Task 9: Visual Polish — Alignment, Spacing, Cross-Review

This task is for fine-tuning coordinates, fixing overlaps, and ensuring visual consistency.

**Step 1: Open in browser and check**

Run: `open framework-overview.html`

Check each section for:
1. Title is centered and readable
2. Baseline grey flow is visible but subdued
3. Three cards are aligned, same height, evenly spaced
4. Full overview main line flows left to right without gaps
5. Middleware boxes (Memory, Compact, Validate) are visually distinct from main line
6. Agent node is large enough to contain the Hook sub-flow
7. EvalJudge retry loop is eye-catching but doesn't overlap
8. Observability layer is clearly beneath the main flow
9. Bottom bar doesn't overlap with full overview
10. Status badges are readable
11. Color legend is accurate
12. No text overlaps with boxes or arrows

**Step 2: Fix any alignment issues**

Adjust x/y coordinates as needed. Common adjustments:
- If Agent box is too narrow for Hook sub-flow, widen it
- If EvalJudge retry loop overlaps with observability layer, move observability down
- If three cards aren't aligned at the bottom, adjust heights
- If text is too small to read, increase font-size

**Step 3: Final commit**

```bash
git add framework-overview.html
git commit -m "feat: redesign framework overview — lifecycle-focused SVG"
```

---

## Summary

| Task | Section | Key deliverable |
|------|---------|-----------------|
| 1 | Shell + Title | HTML wrapper, SVG defs, title text |
| 2 | Baseline | Grey Prompt → Agent → Result |
| 3 | Three Cards | Middleware / Hook / GraphMutator comparison |
| 4 | Full Overview — Main | Section header, legend, Prompt, Agent (with hooks), Result |
| 5 | Full Overview — Middleware | Memory, Compact, Validate on the main line |
| 6 | Full Overview — GraphMutator | EvalJudge node + retry loop |
| 7 | Full Overview — Hooks | Blue observation layer |
| 8 | Bottom Bar | System capabilities bar + summary annotations |
| 9 | Polish | Alignment, spacing, visual consistency |
