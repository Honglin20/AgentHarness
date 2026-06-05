"use client";

import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { Play } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { usePortalStore } from "@/stores/portalStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { fetchWithAuth } from "@/lib/api";
import { MarkdownText } from "@/components/conversation/MarkdownText";
import { DagChapterNav } from "@/components/portal/DagChapterNav";
import { MiniDag } from "@/components/portal/MiniDag";
import { Breadcrumb } from "@/components/portal/Breadcrumb";
import type { TutorialDetail } from "@/types/domains";

export function DomainTutorialPage() {
  const { tutorialContext, goHome } = usePortalStore();
  const domains = usePortalStore((s) => s.domains);
  const ensureDomains = usePortalStore((s) => s.ensureDomains);
  const workflowDefs = usePortalStore((s) => s.workflowDefs);
  const ensureWorkflowDefs = usePortalStore((s) => s.ensureWorkflowDefs);
  const setSelectedTemplate = useWorkflowStore((s) => s.setSelectedTemplate);
  const previewTemplate = useWorkflowStore((s) => s.previewTemplate);

  const [tutorial, setTutorial] = useState<TutorialDetail | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);

  const sectionRefs = useRef<(HTMLDivElement | null)[]>([]);
  const rightPanelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    ensureDomains();
    ensureWorkflowDefs();
  }, [ensureDomains, ensureWorkflowDefs]);

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

  // IntersectionObserver
  useEffect(() => {
    if (!tutorial || !rightPanelRef.current) return;

    const observer = new IntersectionObserver(
      (entries) => {
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

  // Not found state
  if (!tutorialContext) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center bg-app-bg-primary">
        <p className="text-sm text-muted-foreground">Tutorial not found</p>
        <button onClick={goHome} className="mt-2 text-xs text-blue-500 hover:underline">Back to portal</button>
      </div>
    );
  }

  // Loading state
  if (!tutorial) {
    return (
      <div className="flex flex-1 flex-col bg-app-bg-primary overflow-hidden">
        <div className="flex items-center gap-3 border-b border-app-border px-4 py-2.5">
          <Skeleton className="h-4 w-48" />
          <div className="ml-auto flex gap-1.5">
            <Skeleton className="h-6 w-6 rounded-full" />
            <Skeleton className="h-6 w-6 rounded-full" />
          </div>
        </div>
        <div className="flex flex-1 overflow-hidden">
          <div className="w-56 shrink-0 border-r border-app-border p-4">
            <Skeleton className="h-4 w-32 mb-3" />
            <Skeleton className="h-3 w-24 mb-2" />
            <Skeleton className="h-3 w-28 mb-2" />
            <Skeleton className="h-3 w-20" />
          </div>
          <div className="flex-1 p-8">
            <Skeleton className="h-6 w-48 mb-4" />
            <Skeleton className="h-4 w-full mb-2" />
            <Skeleton className="h-4 w-3/4 mb-2" />
            <Skeleton className="h-4 w-5/6" />
          </div>
        </div>
      </div>
    );
  }

  const domain = domains.find((d) => d.id === tutorialContext.domainId);
  const domainTutorials = domain?.tutorials ?? [];

  // Determine active agent node for MiniDag
  const activeSection = tutorial.sections[activeIndex];
  const activeAgent = activeSection?.agent ?? null;

  return (
    <div className="flex flex-1 flex-col bg-app-bg-primary overflow-hidden">
      {/* Header with breadcrumb, level tabs, and Try it */}
      <div className="flex items-center gap-3 border-b border-app-border px-4 py-2.5">
        <Breadcrumb
          items={[
            { label: "Portal", onClick: goHome },
            { label: tutorial.domain_title },
            { label: tutorial.title },
          ]}
        />

        {/* Level tabs + Try it */}
        <div className="ml-auto flex items-center gap-1.5 shrink-0">
          {domainTutorials.length > 1 && domainTutorials.map((t) => {
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
          {tutorial.workflow && (
            <button
              onClick={handleTryIt}
              className="flex items-center gap-1.5 rounded-md bg-blue-500 px-3 py-1 text-xs font-medium text-white hover:bg-blue-600 transition-colors"
            >
              <Play className="h-3 w-3" /> Try it
            </button>
          )}
        </div>
      </div>

      {/* Body: 2 columns (sidebar + content) */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left: MiniDag + chapter nav */}
        <div className="w-56 shrink-0 border-r border-app-border overflow-y-auto flex flex-col">
          {/* MiniDag — shows workflow topology */}
          {tutorial.dag && (
            <div className="border-b border-app-border px-4 pt-4 pb-3">
              <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-2">
                Workflow
              </p>
              <MiniDag
                nodes={tutorial.dag.nodes}
                edges={tutorial.dag.edges}
                activeNode={activeAgent}
              />
            </div>
          )}
          <div className="px-4 pt-3 pb-2">
            <DagChapterNav
              sections={tutorial.sections}
              activeIndex={activeIndex}
              onSectionClick={handleSectionClick}
            />
          </div>
        </div>

        {/* Right: reading area */}
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
      </div>
    </div>
  );
}
