"use client";

import { useState, useEffect } from "react";
import { BookOpen } from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { usePortalStore } from "@/stores/portalStore";
import { fetchWithAuth } from "@/lib/api";
import { MarkdownText } from "@/components/conversation/MarkdownText";
import { COLOR_DOT, COLOR_TEXT } from "./colors";
import { Breadcrumb } from "./Breadcrumb";

interface ApiRefMeta {
  tutorial_id: string;
  tutorial_title: string;
  section_index: number;
  section_title: string;
}

interface ApiDocData {
  id: string;
  title: string;
  markdown: string;
  domain_id: string;
  domain_title: string;
  domain_color: string;
  referenced_by: ApiRefMeta[];
  other_apis: { id: string; title: string }[];
}

export function ApiDocPage() {
  const { apiDocContext, goHome } = usePortalStore();
  const showApiDoc = usePortalStore((s) => s.showApiDoc);
  const showTutorial = usePortalStore((s) => s.showTutorial);

  const [data, setData] = useState<ApiDocData | null>(null);

  useEffect(() => {
    if (!apiDocContext) return;
    setData(null);
    fetchWithAuth(`/api/domains/${apiDocContext.domainId}/api/${apiDocContext.apiName}`)
      .then((r) => r.json())
      .then((d: ApiDocData) => setData(d))
      .catch(() => {});
  }, [apiDocContext]);

  if (!apiDocContext) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center bg-app-bg-primary">
        <p className="text-sm text-muted-foreground">API doc not found</p>
        <button onClick={goHome} className="mt-2 text-xs text-blue-500 hover:underline">Back to portal</button>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex flex-1 flex-col bg-app-bg-primary overflow-hidden">
        <div className="flex items-center gap-3 border-b border-app-border px-4 py-2.5">
          <Skeleton className="h-4 w-64" />
        </div>
        <div className="flex flex-1 overflow-hidden">
          <div className="w-56 shrink-0 border-r border-app-border p-4">
            <Skeleton className="h-3 w-20 mb-3" />
            <Skeleton className="h-7 w-32 mb-2" />
            <Skeleton className="h-7 w-28 mb-2" />
            <Skeleton className="h-7 w-24" />
          </div>
          <div className="flex-1 p-8">
            <Skeleton className="h-6 w-48 mb-4" />
            <Skeleton className="h-4 w-full mb-2" />
            <Skeleton className="h-4 w-3/4 mb-2" />
            <Skeleton className="h-4 w-5/6 mb-2" />
            <Skeleton className="h-4 w-2/3" />
          </div>
        </div>
      </div>
    );
  }

  const dot = COLOR_DOT[data.domain_color] || "bg-blue-500";
  const accent = COLOR_TEXT[data.domain_color] || "text-blue-600 dark:text-blue-400";

  return (
    <div className="flex flex-1 flex-col bg-app-bg-primary overflow-hidden">
      {/* Header with breadcrumb */}
      <div className="flex items-center gap-3 border-b border-app-border px-4 py-2.5">
        <Breadcrumb
          items={[
            { label: "Portal", onClick: goHome },
            { label: data.domain_title },
            { label: data.title },
          ]}
        />
      </div>

      {/* Body: sidebar + content */}
      <div className="flex flex-1 overflow-hidden">
        {/* Left sidebar */}
        <div className="w-56 shrink-0 border-r border-app-border overflow-y-auto">
          {/* API list */}
          <div className="border-b border-app-border p-4">
            <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-2.5">
              API Reference
            </p>
            <div className="flex flex-col gap-0.5">
              {/* Current API */}
              <div className={`flex items-center gap-2 rounded-md px-2 py-1.5 ${accent} bg-muted/50`}>
                <span className={`h-1.5 w-1.5 rounded-full shrink-0 ${dot}`} />
                <span className="text-xs font-medium">{data.title}</span>
              </div>
              {/* Other APIs */}
              {data.other_apis.map((api) => (
                <button
                  key={api.id}
                  onClick={() => showApiDoc(data.domain_id, api.id)}
                  className="flex items-center gap-2 rounded-md px-2 py-1.5 text-xs text-muted-foreground hover:text-app-text-primary hover:bg-muted/30 transition-colors"
                >
                  {api.title}
                </button>
              ))}
            </div>
          </div>

          {/* Related tutorials */}
          {data.referenced_by.length > 0 && (
            <div className="p-4">
              <div className="flex items-center gap-1.5 mb-2.5">
                <BookOpen className="h-3 w-3 text-muted-foreground" />
                <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">
                  Related Tutorials
                </p>
              </div>
              <div className="flex flex-col gap-1.5">
                {data.referenced_by.map((ref, i) => (
                  <button
                    key={i}
                    onClick={() => showTutorial(data.domain_id, ref.tutorial_id)}
                    className="flex flex-col text-left rounded-md px-2 py-1.5 hover:bg-muted/30 transition-colors group"
                  >
                    <span className={`text-xs font-medium ${accent} group-hover:underline`}>
                      {ref.tutorial_title}
                    </span>
                    <span className="text-[10px] text-muted-foreground">
                      {ref.section_title}
                    </span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Content area */}
        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto px-10 py-8" style={{ maxWidth: 820 }}>
            <div className="prose prose-sm dark:prose-invert max-w-none text-app-text-secondary leading-relaxed">
              <MarkdownText>{data.markdown}</MarkdownText>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
