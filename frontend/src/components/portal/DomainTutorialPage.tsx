"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { ArrowLeft, Play } from "lucide-react";
import { usePortalStore } from "@/stores/portalStore";
import type { ApiDocMeta } from "@/types/domains";
import { useWorkflowStore } from "@/stores/workflowStore";
import { fetchWithAuth } from "@/lib/api";
import { MarkdownText } from "@/components/conversation/MarkdownText";
import { DagChapterNav } from "@/components/portal/DagChapterNav";
import type { TutorialDetail, DomainMeta } from "@/types/domains";

interface WorkflowDef {
  name: string;
  agents: { name: string; description?: string }[];
  dag: { nodes: string[]; edges: [string, string][] };
}

export function DomainTutorialPage() {
  const { tutorialContext, goHome } = usePortalStore();
  const showApiDoc = usePortalStore((s) => s.showApiDoc);
  const setSelectedTemplate = useWorkflowStore((s) => s.setSelectedTemplate);
  const previewTemplate = useWorkflowStore((s) => s.previewTemplate);

  const [tutorial, setTutorial] = useState<TutorialDetail | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [domains, setDomains] = useState<DomainMeta[]>([]);
  const [workflowDefs, setWorkflowDefs] = useState<WorkflowDef[]>([]);

  // Build API lookup from domains (stable across activeIndex changes)
  const apiMap = useMemo(() => {
    const domain = domains.find((d) => d.id === tutorialContext?.domainId);
    return new Map<string, ApiDocMeta>((domain?.apis ?? []).map((a) => [a.id, a]));
  }, [domains, tutorialContext?.domainId]);

  const sectionRefs = useRef<(HTMLDivElement | null)[]>([]);
  const rightPanelRef = useRef<HTMLDivElement>(null);

  // Fetch tutorial detail
  useEffect(() => {
    if (!tutorialContext) return;
    setTutorial(null);
    setActiveIndex(0);
    fetchWithAuth(
      `/api/domains/${tutorialContext.domainId}/tutorials/${tutorialContext.tutorialId}`
    )
      .then((r) => r.json())
      .then((data: TutorialDetail) => setTutorial(data))
      .catch(() => {});
  }, [tutorialContext]);

  // Fetch domains + workflow definitions
  useEffect(() => {
    fetchWithAuth("/api/domains")
      .then((r) => r.json())
      .then((data: DomainMeta[]) => setDomains(data))
      .catch(() => {});
    fetchWithAuth("/api/workflows/definitions")
      .then((r) => r.json())
      .then((data: WorkflowDef[]) => setWorkflowDefs(data))
      .catch(() => {});
  }, []);

  // IntersectionObserver
  useEffect(() => {
    if (!tutorial || !rightPanelRef.current) return;

    const observer = new IntersectionObserver(
      (entries) => {
        // Collect all currently visible sections, pick the one closest to top
        let topIdx = -1;
        let topY = Infinity;
        for (const entry of entries) {
          if (entry.isIntersecting) {
            const idx = Number((entry.target as HTMLElement).dataset.sectionIndex);
            const rect = entry.boundingClientRect;
            if (!isNaN(idx) && rect.top < topY) {
              topIdx = idx;
              topY = rect.top;
            }
          }
        }
        if (topIdx >= 0) setActiveIndex(topIdx);
      },
      { root: rightPanelRef.current, rootMargin: "0px 0px -60% 0px" }
    );

    const raf = requestAnimationFrame(() => {
      sectionRefs.current.forEach((el) => {
        if (el) observer.observe(el);
      });
    });

    return () => {
      cancelAnimationFrame(raf);
      observer.disconnect();
    };
  }, [tutorial]);

  const handleSectionClick = useCallback((index: number) => {
    const el = sectionRefs.current[index];
    const container = rightPanelRef.current;
    if (el && container) {
      const containerRect = container.getBoundingClientRect();
      const elRect = el.getBoundingClientRect();
      container.scrollTo({
        top: container.scrollTop + elRect.top - containerRect.top - 16,
        behavior: "smooth",
      });
      setActiveIndex(index);
    }
  }, []);

  const handleTryIt = useCallback(() => {
    if (!tutorial?.workflow) return;
    const wfName = tutorial.workflow.split("/").pop() || tutorial.workflow;
    const def = workflowDefs.find((w) => w.name === wfName);
    if (def) {
      setSelectedTemplate(def as unknown as Record<string, unknown>);
      previewTemplate(def as unknown as Record<string, unknown>);
    }
  }, [tutorial, workflowDefs, setSelectedTemplate, previewTemplate]);

  // Loading states
  if (!tutorialContext) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center bg-app-bg-primary">
        <p className="text-sm text-muted-foreground">教程未找到</p>
        <button onClick={goHome} className="mt-2 flex items-center gap-1 text-xs text-blue-500 hover:underline">
          <ArrowLeft className="h-3 w-3" /> 返回
        </button>
      </div>
    );
  }

  if (!tutorial) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center bg-app-bg-primary">
        <p className="text-sm text-muted-foreground">加载中...</p>
      </div>
    );
  }

  const domain = domains.find((d) => d.id === tutorialContext.domainId);
  const domainTutorials = domain?.tutorials ?? [];
  const domainApis = domain?.apis ?? [];

  // Current section's API refs (plain computation, no hooks)
  const activeSection = tutorial.sections[activeIndex];
  const activeApiRefs = activeSection?.api_refs ?? [];

  return (
    <div className="flex flex-1 flex-col bg-app-bg-primary overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-app-border px-4 py-2.5">
        <button
          onClick={goHome}
          className="flex items-center gap-1 text-xs text-muted-foreground hover:text-app-text-primary transition-colors shrink-0"
        >
          <ArrowLeft className="h-3.5 w-3.5" /> 返回
        </button>
        <span className="text-muted-foreground/40">/</span>
        <span className="text-xs text-muted-foreground">{tutorial.domain_title}</span>
        <span className="text-muted-foreground/40">/</span>
        <span className="text-sm font-medium text-app-text-primary truncate">
          {tutorial.title}
        </span>

        {/* Level tabs */}
        {domainTutorials.length > 1 && (
          <div className="ml-auto flex items-center gap-1.5 shrink-0">
            {domainTutorials.map((t) => {
              const isActive = t.id === tutorialContext.tutorialId;
              return (
                <button
                  key={t.id}
                  onClick={() => usePortalStore.getState().showTutorial(tutorialContext.domainId, t.id)}
                  className={`rounded-full px-2.5 py-0.5 text-[11px] font-medium transition-colors ${
                    isActive
                      ? "bg-foreground text-background"
                      : "text-muted-foreground hover:text-app-text-primary hover:bg-muted"
                  }`}
                >
                  {t.level}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* Body: 3 columns */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: chapter nav (with DAG dots) + try-it */}
        <div className="w-56 shrink-0 border-r border-app-border overflow-y-auto flex flex-col">
          <div className="px-4 pt-4 pb-2">
            <DagChapterNav
              sections={tutorial.sections}
              activeIndex={activeIndex}
              onSectionClick={handleSectionClick}
            />
          </div>

          {/* Try it button */}
          {tutorial.workflow && (
            <div className="mt-auto border-t border-app-border p-3">
              <button
                onClick={handleTryIt}
                className="flex w-full items-center justify-center gap-1.5 rounded-md bg-blue-500 px-3 py-2 text-xs font-medium text-white hover:bg-blue-600 transition-colors"
              >
                <Play className="h-3 w-3" /> 试一试
              </button>
            </div>
          )}
        </div>

        {/* Center: reading area */}
        <div ref={rightPanelRef} className="flex-1 overflow-y-auto">
          <div className="mx-auto px-8 py-8" style={{ maxWidth: 780 }}>
            {tutorial.sections.map((section, i) => (
              <div
                key={i}
                ref={(el) => { sectionRefs.current[i] = el; }}
                data-section-index={i}
                className={i > 0 ? "mt-10" : ""}
              >
                <h2 className="text-lg font-semibold text-app-text-primary mb-1">
                  {section.title}
                </h2>
                {section.agent && (
                  <p className="text-[11px] font-mono text-muted-foreground mb-4">
                    @{section.agent}
                  </p>
                )}
                <div className="prose prose-sm dark:prose-invert max-w-none text-app-text-secondary leading-relaxed">
                  <MarkdownText>{section.markdown}</MarkdownText>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Right: API reference — always show all, highlight active */}
        <div className="w-52 shrink-0 border-l border-app-border overflow-y-auto">
          {domainApis.length > 0 && (
            <div className="p-3">
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-2">
                API 参考
              </p>
              <div className="flex flex-col gap-2">
                {domainApis.map((api) => {
                  const isActive = activeApiRefs.includes(api.id);
                  return (
                    <button
                      key={api.id}
                      onClick={() => showApiDoc(tutorialContext.domainId, api.id)}
                      className={`flex flex-col gap-0.5 rounded-md border p-2.5 text-left transition-all hover:shadow-sm ${
                        isActive
                          ? "border-blue-300 bg-blue-50/50 dark:border-blue-700 dark:bg-blue-950/20"
                          : "border-app-border bg-background hover:border-gray-300 dark:hover:border-gray-600"
                      }`}
                    >
                      <span className={`text-xs font-medium ${isActive ? "text-blue-600 dark:text-blue-400" : "text-app-text-primary"}`}>
                        {api.title}
                      </span>
                      {api.description && (
                        <span className="text-[10px] text-muted-foreground line-clamp-2">{api.description}</span>
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
