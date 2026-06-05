# Phase 3: 教学页（Tutorial Page）实施计划

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 构建教学页——左右分栏，左侧 DAG 章节导航与右侧 Markdown 正文联动，支持 Level 切换和"试一试"启动 workflow。

**Architecture:** 新增后端 API 返回教程完整内容（按章节拆分 markdown），前端用 `DomainTutorialPage` 组件左右分栏渲染。左侧用纯 CSS 绘制 DAG 节点竖线拓扑（非 ReactFlow），右侧复用现有 `MarkdownText` 组件。IntersectionObserver 检测当前阅读章节并同步左侧高亮。`portalStore` 扩展为 `"home" | "workflows" | "tutorial"` 三态。

**Tech Stack:** FastAPI (后端), React + Zustand + Tailwind (前端), react-markdown (MD 渲染)

---

## 核心数据流

```
tutorials/quantization/01_quick_start.md (MD 文件)
  ↓ parse_tutorials.py (后端解析)
  ↓ GET /api/domains/{domain}/tutorials/{id}
  ↓ { sections: [{title, agent, markdown}], workflow: "mxint-analysis", dag: {...} }
  ↓ DomainTutorialPage (前端渲染)
    ├── 左侧: DagChapterNav (CSS 竖线 + 章节节点)
    └── 右侧: MarkdownText × N (每个章节一段 MD)
```

---

## Task 1: 后端 — 扩展解析脚本，提取章节 Markdown 内容

**目标：** `parse_tutorials.py` 的 `_parse_tutorial_md` 增加返回每个章节的 markdown 正文（两个 `##` 之间的内容）。

**Files:**
- Modify: `scripts/parse_tutorials.py:45-96`

**Step 1: 修改 `_parse_tutorial_md` 函数**

在 `_parse_tutorial_md` 中，解析完 sections 后，提取每个章节对应的 markdown 正文。

当前 `sections` 只返回 `{title, agent}`。需要增加 `markdown` 字段：

```python
# 在 _parse_tutorial_md 函数中，替换 sections 提取逻辑为：
    # Split content into per-section markdown chunks
    lines = fm.content.splitlines()
    section_blocks: list[dict] = []
    current_section: dict | None = None
    section_start = 0

    for i, line in enumerate(lines):
        m = _SECTION_RE.match(line)
        if m:
            if current_section is not None:
                current_section["markdown"] = "\n".join(lines[section_start:i]).strip()
                section_blocks.append(current_section)
            current_section = {
                "title": m.group(1).strip(),
                "agent": m.group(2) or None,
            }
            section_start = i + 1

    # Last section: everything after its ## to the end (or to a --- separator)
    if current_section is not None:
        remaining = lines[section_start:]
        # Trim trailing --- separator if present
        if remaining and remaining[-1].strip() == "---":
            remaining = remaining[:-1]
        current_section["markdown"] = "\n".join(remaining).strip()
        section_blocks.append(current_section)

    return {
        "id": tutorial_id,
        "level": level,
        "title": title or tutorial_id,
        "description": description,
        "badge": badge,
        "workflow": workflow,
        "sections": section_blocks,
        "apis": apis,
    }
```

**Step 2: 验证输出**

Run: `cd /Users/mozzie/Desktop/Projects/AgentHarness && python scripts/parse_tutorials.py | python3 -c "import sys,json; d=json.load(sys.stdin); s=d[0]['tutorials'][0]['sections'][0]; print(s['title'], '|', s['agent'], '|', s['markdown'][:80])"`

Expected: `分析项目结构 | analyzer | 第一个 Agent 扫描项目目录，自动找到模型定义、数据集和权重文件。...`

**Step 3: Commit**

```bash
git add scripts/parse_tutorials.py
git commit -m "feat(tutorial): extract per-section markdown content in parse script"
```

---

## Task 2: 后端 — 新增教程详情 API

**目标：** 新增 `GET /api/domains/{domain}/tutorials/{id}` 返回教程完整数据（sections 含 markdown + 关联 workflow 的 DAG）。

**Files:**
- Modify: `server/domain_routes.py`
- Modify: `server/app.py` (确保 lifespan 缓存包含完整数据)

**Step 1: 在 `domain_routes.py` 新增教程详情 API**

```python
@router.get("/domains/{domain_id}/tutorials/{tutorial_id}")
async def get_tutorial(domain_id: str, tutorial_id: str, request: Request) -> dict:
    """Return full tutorial data including section markdown and DAG topology."""
    cached: list[dict] = getattr(request.app.state, "domain_data", [])
    domain = next((d for d in cached if d["id"] == domain_id), None)
    if not domain:
        raise HTTPException(status_code=404, detail="Domain not found")

    tutorial = next((t for t in domain["tutorials"] if t["id"] == tutorial_id), None)
    if not tutorial:
        raise HTTPException(status=404, detail="Tutorial not found")

    # Load DAG from workflow.json if workflow is referenced
    dag = None
    wf_name = tutorial.get("workflow")
    if wf_name:
        # workflow field may be "workflows/tutorials/mxint-analysis" or just "mxint-analysis"
        wf_stem = wf_name.rsplit("/", 1)[-1]
        wf_path = Path(_WORKFLOWS_DIR) / wf_stem / "workflow.json"
        if not wf_path.exists():
            wf_path = Path(_WORKFLOWS_DIR) / wf_name / "workflow.json"
        if wf_path.exists():
            wf_data = json.loads(wf_path.read_text(encoding="utf-8"))
            dag = wf_data.get("dag")

    return {
        **tutorial,
        "domain_id": domain_id,
        "domain_title": domain["title"],
        "domain_color": domain["color"],
        "dag": dag,
    }
```

需要在文件顶部添加 imports：
```python
import json
from pathlib import Path
from fastapi import HTTPException
from harness.api import _WORKFLOWS_DIR
```

**Step 2: 验证 API**

Run: `curl -s http://localhost:8000/api/domains/quantization/tutorials/quick_start | python3 -c "import sys,json; d=json.load(sys.stdin); print('Sections:', len(d['sections'])); print('DAG nodes:', d.get('dag',{}).get('nodes',[])); print('First section markdown:', d['sections'][0]['markdown'][:60])"`

Expected: 6 sections, DAG nodes 列表, 第一个章节有 markdown 内容。

**Step 3: Commit**

```bash
git add server/domain_routes.py
git commit -m "feat(api): add GET /api/domains/{domain}/tutorials/{id} endpoint"
```

---

## Task 3: 前端 — 扩展 portalStore 支持 tutorial 视图

**目标：** `portalStore` 增加 `"tutorial"` 视图和 tutorial 上下文状态。

**Files:**
- Modify: `frontend/src/stores/portalStore.ts`

**Step 1: 扩展 store**

```typescript
import { create } from "zustand";

export type PortalView = "home" | "workflows" | "tutorial";

interface TutorialContext {
  domainId: string;
  tutorialId: string;
}

interface PortalState {
  portalView: PortalView;
  activeDomain: string | null;
  tutorialContext: TutorialContext | null;
  setPortalView: (view: PortalView) => void;
  showWorkflows: (domainId: string) => void;
  showTutorial: (domainId: string, tutorialId: string) => void;
  goHome: () => void;
}

export const usePortalStore = create<PortalState>((set) => ({
  portalView: "home",
  activeDomain: null,
  tutorialContext: null,
  setPortalView: (view) => set({ portalView: view }),
  showWorkflows: (domainId) => set({ portalView: "workflows", activeDomain: domainId, tutorialContext: null }),
  showTutorial: (domainId, tutorialId) => set({ portalView: "tutorial", activeDomain: domainId, tutorialContext: { domainId, tutorialId } }),
  goHome: () => set({ portalView: "home", activeDomain: null, tutorialContext: null }),
}));
```

**Step 2: Commit**

```bash
git add frontend/src/stores/portalStore.ts
git commit -m "feat(portal): extend portalStore with tutorial view state"
```

---

## Task 4: 前端 — 新增教程详情 TypeScript 类型

**目标：** 为 API 响应增加 TypeScript 接口。

**Files:**
- Modify: `frontend/src/types/domains.ts`

**Step 1: 新增 TutorialDetail 类型**

在 `domains.ts` 底部添加：

```typescript
export interface TutorialSectionDetail extends TutorialSection {
  markdown: string;
}

export interface TutorialDetail {
  id: string;
  level: number;
  title: string;
  description: string;
  badge?: string;
  workflow: string | null;
  sections: TutorialSectionDetail[];
  apis: string[];
  domain_id: string;
  domain_title: string;
  domain_color: string;
  dag: { nodes: string[]; edges: [string, string][]; conditional_edges?: { from: string; to: string; label: string }[] } | null;
}
```

**Step 2: Commit**

```bash
git add frontend/src/types/domains.ts
git commit -m "feat(types): add TutorialDetail interface for tutorial page"
```

---

## Task 5: 前端 — DagChapterNav 左侧导航组件

**目标：** 纯 CSS 绘制 DAG 节点竖线导航，支持三种状态（当前/已完成/未到达），点击跳转章节。

**Files:**
- Create: `frontend/src/components/portal/DagChapterNav.tsx`

**Step 1: 实现组件**

这是教学页左侧面板。核心设计：
- 每个节点 = 圆点 + 竖线连接线 + 章节标题 + agent 名
- 三种状态样式：current(蓝)、completed(绿)、upcoming(灰)
- 点击节点 → 调用 `onSectionClick(index)` 让右侧滚动
- 接收 `activeIndex` 高亮当前阅读章节

```tsx
"use client";

interface Section {
  title: string;
  agent: string | null;
}

interface DagChapterNavProps {
  sections: Section[];
  activeIndex: number;
  onSectionClick: (index: number) => void;
}

const STATE_STYLES = {
  current: {
    dot: "bg-blue-500 ring-2 ring-blue-200 dark:ring-blue-800",
    line: "bg-blue-300 dark:bg-blue-700",
    title: "text-app-text-primary font-medium",
    agent: "text-blue-600 dark:text-blue-400",
  },
  completed: {
    dot: "bg-emerald-400",
    line: "bg-emerald-200 dark:bg-emerald-800",
    title: "text-muted-foreground",
    agent: "text-muted-foreground",
  },
  upcoming: {
    dot: "bg-gray-300 dark:bg-gray-600",
    line: "bg-gray-200 dark:bg-gray-700 border-l border-dashed border-gray-300 dark:border-gray-600",
    title: "text-muted-foreground/60",
    agent: "text-muted-foreground/40",
  },
};

export function DagChapterNav({ sections, activeIndex, onSectionClick }: DagChapterNavProps) {
  return (
    <div className="flex flex-col py-2">
      {sections.map((section, i) => {
        const state = i < activeIndex ? "completed" : i === activeIndex ? "current" : "upcoming";
        const s = STATE_STYLES[state];
        const isLast = i === sections.length - 1;
        return (
          <div key={i}>
            <button
              onClick={() => onSectionClick(i)}
              className="flex items-start gap-2.5 w-full text-left px-2 py-1.5 rounded hover:bg-muted/50 transition-colors"
            >
              <div className="flex flex-col items-center pt-1">
                <div className={`h-2.5 w-2.5 rounded-full shrink-0 ${s.dot}`} />
              </div>
              <div className="flex flex-col min-w-0">
                <span className={`text-xs leading-snug ${s.title}`}>{section.title}</span>
                {section.agent && (
                  <span className={`text-[10px] font-mono ${s.agent}`}>{section.agent}</span>
                )}
              </div>
            </button>
            {!isLast && (
              <div className="ml-[1.25rem] h-4 w-px mx-auto">
                <div className={`h-full w-full ${s.line}`} />
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
```

**Step 2: Commit**

```bash
git add frontend/src/components/portal/DagChapterNav.tsx
git commit -m "feat(tutorial): add DagChapterNav left panel component"
```

---

## Task 6: 前端 — DomainTutorialPage 主组件

**目标：** 教学页主组件：左右分栏 + Level tabs + IntersectionObserver 联动 + "试一试"按钮。

**Files:**
- Create: `frontend/src/components/portal/DomainTutorialPage.tsx`

**Step 1: 实现主组件**

核心功能：
1. 挂载时 `fetch /api/domains/{domain}/tutorials/{id}` 获取教程数据
2. 左侧：`DagChapterNav` + "试一试 ▶"按钮
3. 右侧：每个章节渲染为一个 `MarkdownText` block，包裹在 `data-section-index` div 中
4. IntersectionObserver 监测哪个章节可见 → 更新 `activeIndex`
5. 点击左侧节点 → `scrollIntoView` 到对应章节
6. "试一试" → 从 `/api/workflows/definitions` 找到对应 workflow → `setSelectedTemplate` → 退出 portal 进入运行界面

```tsx
"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { ArrowLeft, Play } from "lucide-react";
import { usePortalStore } from "@/stores/portalStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { fetchWithAuth } from "@/lib/api";
import { MarkdownText } from "@/components/conversation/MarkdownText";
import { DagChapterNav } from "@/components/portal/DagChapterNav";
import type { TutorialDetail } from "@/types/domains";

const COLOR_MAP: Record<string, { accent: string }> = {
  blue:   { accent: "border-b-blue-500" },
  violet: { accent: "border-b-violet-500" },
  amber:  { accent: "border-b-amber-500" },
  rose:   { accent: "border-b-rose-500" },
};

interface WorkflowDef {
  name: string;
  agents: { name: string; description?: string }[];
  dag: { nodes: string[]; edges: [string, string][] };
}

export function DomainTutorialPage() {
  const { tutorialContext, activeDomain, goHome } = usePortalStore();
  const setSelectedTemplate = useWorkflowStore((s) => s.setSelectedTemplate);

  const [tutorial, setTutorial] = useState<TutorialDetail | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const sectionRefs = useRef<(HTMLDivElement | null)[]>([]);
  const rightPanelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!tutorialContext) return;
    fetchWithAuth(`/api/domains/${tutorialContext.domainId}/tutorials/${tutorialContext.tutorialId}`)
      .then((r) => r.json())
      .then((data: TutorialDetail) => setTutorial(data))
      .catch(() => {});
  }, [tutorialContext]);

  // IntersectionObserver to track active section
  useEffect(() => {
    if (!tutorial || !rightPanelRef.current) return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const idx = Number(entry.target.getAttribute("data-section-index"));
            if (!isNaN(idx)) setActiveIndex(idx);
          }
        }
      },
      { root: rightPanelRef.current, rootMargin: "-10% 0px -70% 0px" }
    );

    sectionRefs.current.forEach((el) => {
      if (el) observer.observe(el);
    });

    return () => observer.disconnect();
  }, [tutorial]);

  const handleSectionClick = useCallback((index: number) => {
    const el = sectionRefs.current[index];
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
      setActiveIndex(index);
    }
  }, []);

  const handleTryIt = useCallback(async () => {
    if (!tutorial?.workflow) return;
    const wfName = tutorial.workflow.rsplit("/", 1)[-1] || tutorial.workflow;
    try {
      const r = await fetchWithAuth("/api/workflows/definitions");
      const defs: WorkflowDef[] = await r.json();
      const def = defs.find((w) => w.name === wfName);
      if (def) setSelectedTemplate(def as unknown as Record<string, unknown>);
    } catch (e) {
      console.error("Failed to find workflow definition:", e);
    }
  }, [tutorial, setSelectedTemplate]);

  if (!tutorialContext || !tutorial) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center bg-app-bg-primary">
        <p className="text-sm text-muted-foreground">
          {!tutorialContext ? "教程未找到" : "加载中..."}
        </p>
        <button onClick={goHome} className="mt-2 text-xs text-blue-500 hover:underline">
          返回门户
        </button>
      </div>
    );
  }

  const c = COLOR_MAP[tutorial.domain_color] || COLOR_MAP.blue;

  return (
    <div className="flex flex-1 flex-col bg-app-bg-primary overflow-hidden">
      {/* Header */}
      <div className={`flex items-center gap-3 px-4 py-2 border-b ${c.accent} border-app-border`}>
        <button
          onClick={goHome}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-app-text-primary transition-colors"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> 返回
        </button>
        <span className="text-app-border">|</span>
        <span className="text-xs text-muted-foreground">{tutorial.domain_title}</span>
        <span className="text-app-border">·</span>
        <span className="text-sm font-semibold text-app-text-primary">{tutorial.title}</span>
      </div>

      {/* Body: left nav + right content */}
      <div className="flex flex-1 min-h-0">
        {/* Left panel: DAG chapter nav */}
        <div className="w-56 shrink-0 border-r border-app-border overflow-y-auto px-2">
          <DagChapterNav
            sections={tutorial.sections}
            activeIndex={activeIndex}
            onSectionClick={handleSectionClick}
          />
          {tutorial.workflow && (
            <div className="px-2 py-3 mt-2 border-t border-app-border">
              <button
                onClick={handleTryIt}
                className="flex w-full items-center justify-center gap-1.5 rounded-lg bg-blue-500 px-3 py-2 text-xs font-medium text-white hover:bg-blue-600 transition-colors"
              >
                <Play className="h-3 w-3" /> 试一试
              </button>
            </div>
          )}
        </div>

        {/* Right panel: markdown content */}
        <div ref={rightPanelRef} className="flex-1 overflow-y-auto px-8 py-6">
          {tutorial.sections.map((section, i) => (
            <div
              key={i}
              ref={(el) => { sectionRefs.current[i] = el; }}
              data-section-index={i}
              className="mb-8"
            >
              <h2 className="text-base font-semibold text-app-text-primary mb-3">
                {i + 1}. {section.title}
              </h2>
              {section.agent && (
                <div className="mb-2">
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-mono text-muted-foreground">
                    @{section.agent}
                  </span>
                </div>
              )}
              <div className="prose prose-sm dark:prose-invert max-w-none">
                <MarkdownText>{section.markdown}</MarkdownText>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
```

注意：`workflow.rsplit` 不存在于 JS string，需要改为：

```typescript
const wfName = tutorial.workflow.split("/").pop() || tutorial.workflow;
```

**Step 2: Commit**

```bash
git add frontend/src/components/portal/DomainTutorialPage.tsx
git commit -m "feat(tutorial): add DomainTutorialPage with DAG nav + markdown content"
```

---

## Task 7: 前端 — 接入导航：DomainPortal 教程卡片 + CenterPanel 视图切换

**目标：** 教程卡片点击进入教学页，CenterPanel 处理 `"tutorial"` 视图。

**Files:**
- Modify: `frontend/src/components/portal/DomainPortal.tsx:108-110`
- Modify: `frontend/src/components/layout/CenterPanel.tsx:17-19` (imports)
- Modify: `frontend/src/components/layout/CenterPanel.tsx:319-334` (portal rendering)

**Step 1: DomainPortal — 接入 showTutorial**

替换 `handleTutorialClick` 的 console.log：

```typescript
  const showWorkflows = usePortalStore((s) => s.showWorkflows);
  const showTutorial = usePortalStore((s) => s.showTutorial);

  const handleTutorialClick = (domainId: string, tutorialId: string) => {
    showTutorial(domainId, tutorialId);
  };
```

**Step 2: CenterPanel — 增加 tutorial 视图分支**

在 imports 添加 `DomainTutorialPage`：

```typescript
import { DomainWorkflowsPage } from "@/components/portal/DomainWorkflowsPage";
import { DomainTutorialPage } from "@/components/portal/DomainTutorialPage";
```

在落地页条件块中，增加 tutorial 分支：

```typescript
  // Landing page — Domain Portal
  if (isIdle && !selectedTemplate) {
    if (portalView === "workflows") {
      return <DomainWorkflowsPage />;
    }
    if (portalView === "tutorial") {
      return <DomainTutorialPage />;
    }
    return (
      <>
        <DomainPortal />
        ...
      </>
    );
  }
```

**Step 3: Commit**

```bash
git add frontend/src/components/portal/DomainPortal.tsx frontend/src/components/layout/CenterPanel.tsx
git commit -m "feat(portal): wire tutorial card click to DomainTutorialPage"
```

---

## Task 8: 前端 — Level tabs 切换（多教程支持）

**目标：** 如果一个领域有多个教程（Level 1/2/3），在教学页顶部显示 Level tabs，点击切换。

**Files:**
- Modify: `frontend/src/components/portal/DomainTutorialPage.tsx`

**Step 1: 在 Header 区域添加 Level tabs**

在 `DomainTutorialPage` 中，从 `/api/domains` 获取当前领域的所有 tutorials，在 header 中渲染 tab 按钮：

```tsx
// 在组件内，tutorial 加载成功后：
const [domainTutorials, setDomainTutorials] = useState<{id: string; level: number; title: string}[]>([]);

useEffect(() => {
  if (!tutorialContext) return;
  fetchWithAuth("/api/domains")
    .then((r) => r.json())
    .then((domains: DomainMeta[]) => {
      const d = domains.find((d) => d.id === tutorialContext.domainId);
      if (d) setDomainTutorials(d.tutorials.map((t) => ({ id: t.id, level: t.level, title: t.title })));
    })
    .catch(() => {});
}, [tutorialContext]);
```

在 Header 中：

```tsx
{/* Level tabs */}
{domainTutorials.length > 1 && (
  <div className="flex items-center gap-1 ml-auto">
    {domainTutorials
      .sort((a, b) => a.level - b.level)
      .map((t) => (
        <button
          key={t.id}
          onClick={() => t.id !== tutorialContext?.tutorialId && usePortalStore.getState().showTutorial(tutorialContext.domainId, t.id)}
          className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium transition-colors ${
            t.id === tutorialContext?.tutorialId
              ? "bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-400"
              : "text-muted-foreground hover:text-app-text-primary hover:bg-muted"
          }`}
        >
          {t.level}. {t.title}
        </button>
      ))}
  </div>
)}
```

**Step 2: Commit**

```bash
git add frontend/src/components/portal/DomainTutorialPage.tsx
git commit -m "feat(tutorial): add Level tabs for multi-tutorial domains"
```

---

## Task 9: 构建 + 端到端验证

**Step 1: 前端构建**

Run: `cd frontend && npm run build`
Expected: Build 成功，无类型错误。

**Step 2: 重启服务器**

Run: `kill $(lsof -ti:8000) 2>/dev/null; sleep 1; cd /Users/mozzie/Desktop/Projects/AgentHarness && python -m uvicorn server.app:app --host 0.0.0.0 --port 8000 &`

**Step 3: 验证 API**

Run: `curl -s http://localhost:8000/api/domains/quantization/tutorials/quick_start | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK - sections:', len(d['sections']), 'dag:', d.get('dag',{}).get('nodes',[])); [print(f'  {i}: {s[\"title\"]} ({len(s[\"markdown\"])} chars)') for i,s in enumerate(d['sections'])]"`

Expected: 6 sections, 每个 section 有 markdown 内容，dag.nodes 列表。

**Step 4: 浏览器验证**

1. 打开 http://localhost:8000
2. 点击"基础量化"教程卡片 → 进入教学页
3. 验证：左侧 DAG 导航 + 右侧 Markdown 内容
4. 滚动右侧 → 左侧高亮跟随
5. 点击左侧节点 → 右侧滚动到对应章节
6. 点击"试一试" → 进入 DAG 预览 + ChatInput
7. 点击"返回" → 回到门户首页

**Step 5: 提交构建产物**

```bash
git add frontend/out/
git commit -m "build: frontend build with tutorial page"
```

---

## 文件清单

| 操作 | 文件 |
|------|------|
| Modify | `scripts/parse_tutorials.py` |
| Modify | `server/domain_routes.py` |
| Modify | `frontend/src/stores/portalStore.ts` |
| Modify | `frontend/src/types/domains.ts` |
| Create | `frontend/src/components/portal/DagChapterNav.tsx` |
| Create | `frontend/src/components/portal/DomainTutorialPage.tsx` |
| Modify | `frontend/src/components/portal/DomainPortal.tsx` |
| Modify | `frontend/src/components/layout/CenterPanel.tsx` |

---

## 风险与注意事项

1. **教程 MD 没有 `__init__.py` 问题**：`scripts/` 不可作为 Python 包导入，但服务器启动时通过 `sys.path` 加载。如果 import 失败，改用 `runpy.run_path`。
2. **IntersectionObserver 性能**：章节数量少（5-10），不需要 throttle。
3. **workflow field 格式**：MD frontmatter 中 `workflow: workflows/tutorials/mxint-analysis`，API 需要从路径提取名称匹配 `workflow.json` 所在目录。
4. **DAG 复杂度**：当前只有串行 DAG（mxint-analysis），分叉 DAG 的竖线绘制在后续迭代中支持。当前 `DagChapterNav` 用简单竖线拓扑，足够覆盖串行场景。
