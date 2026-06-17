"use client";

import { useEffect } from "react";
import { Logo } from "@/components/ui/logo";
import { Skeleton } from "@/components/ui/skeleton";
import { usePortalStore } from "@/stores/portalStore";
import { useAppViewStore } from "@/stores/appView";
import { COLOR_MAP, DEFAULT_COLOR } from "./colors";
import { Layers, Search, Flame, Scissors, ArrowRight, Lock, Terminal } from "lucide-react";
import type { DomainMeta, TutorialMeta } from "@/types/domains";

const ICON_MAP: Record<string, React.ComponentType<{ className?: string }>> = {
  Layers: Layers, Search: Search, Flame: Flame, Scissors: Scissors,
};

const BADGE_STYLES: Record<string, { border: string; bg: string; badgeBg: string; badgeText: string; iconText: string }> = {
  "Quick Start": {
    border: "border-emerald-200 dark:border-emerald-800",
    bg: "bg-emerald-50/50 dark:bg-emerald-950/20",
    badgeBg: "bg-emerald-100 dark:bg-emerald-900/40",
    badgeText: "text-emerald-700 dark:text-emerald-400",
    iconText: "text-emerald-600 dark:text-emerald-400",
  },
};

const DEFAULT_BADGE_STYLE = {
  border: "border-blue-200 dark:border-blue-800",
  bg: "bg-blue-50/50 dark:bg-blue-950/20",
  badgeBg: "bg-blue-100 dark:bg-blue-900/40",
  badgeText: "text-blue-700 dark:text-blue-400",
  iconText: "text-blue-600 dark:text-blue-400",
};

interface Props {
  workflowCountByDomain?: Record<string, number>;
}

function TutorialCard({
  tutorial,
  domain,
  onClick,
}: {
  tutorial: TutorialMeta;
  domain: DomainMeta;
  onClick: () => void;
}) {
  const dc = COLOR_MAP[domain.color] || DEFAULT_COLOR;
  const hasBadge = !!tutorial.badge;
  const bs = hasBadge
    ? (BADGE_STYLES[tutorial.badge!] || DEFAULT_BADGE_STYLE)
    : null;

  const agentCount = tutorial.sections.filter((s) => s.agent).length;
  const subtitle = tutorial.description
    || `${agentCount} agents · Level ${tutorial.level}`;

  const cardBase = hasBadge
    ? `border ${bs!.border} ${bs!.bg}`
    : "border border-app-border bg-background";

  return (
    <button
      onClick={onClick}
      className={`flex flex-col gap-1.5 rounded-lg p-3.5 text-left transition-all hover:shadow-sm ${
        hasBadge
          ? `hover:border-emerald-300 dark:hover:border-emerald-700`
          : `hover:border-gray-300 dark:hover:border-gray-600`
      } ${cardBase}`}
    >
      <div className="flex items-center gap-1.5">
        {tutorial.badge ? (
          <>
            <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${bs!.badgeBg} ${bs!.badgeText}`}>
              {tutorial.badge}
            </span>
            <Terminal className={`h-3 w-3 ${bs!.iconText}`} />
          </>
        ) : (
          <span className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${dc.badge}`}>
            {domain.title}
          </span>
        )}
      </div>
      <span className="text-sm font-medium text-app-text-primary leading-snug">{tutorial.title}</span>
      <span className="text-[11px] text-muted-foreground line-clamp-2">{subtitle}</span>
    </button>
  );
}

function PortalSkeleton() {
  return (
    <div className="flex flex-col gap-5">
      {Array.from({ length: 3 }).map((_, i) => (
        <div key={i}>
          <div className="flex items-center gap-2.5 mb-2.5">
            <Skeleton className="h-3.5 w-3.5" />
            <Skeleton className="h-4 w-24" />
          </div>
          <div className="grid grid-cols-3 gap-3">
            {Array.from({ length: 3 }).map((_, j) => (
              <Skeleton key={j} className="h-24 rounded-lg" />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function DomainPortal({ workflowCountByDomain = {} }: Props) {
  const domains = usePortalStore((s) => s.domains);
  const domainsLoading = usePortalStore((s) => s.domainsLoading);
  const ensureDomains = usePortalStore((s) => s.ensureDomains);

  useEffect(() => {
    ensureDomains();
  }, [ensureDomains]);

  return (
    <div className="flex flex-1 flex-col items-center bg-app-bg-primary px-6 py-8 overflow-y-auto">
      <div className="w-full max-w-4xl">
        <div className="mb-6 flex justify-center">
          <Logo size="lg" className="text-primary" />
        </div>

        {domainsLoading && domains.length === 0 ? (
          <PortalSkeleton />
        ) : (
          domains.map((domain) => {
            const c = COLOR_MAP[domain.color] || DEFAULT_COLOR;
            const Icon = ICON_MAP[domain.icon] || Layers;
            const isComingSoon = domain.status === "coming_soon";

            return (
              <div key={domain.id} className="mb-5">
                <div className={`flex items-center gap-2.5 mb-2.5 border-l-[3px] pl-3 py-0.5 ${c.accent}`}>
                  <Icon className={`h-3.5 w-3.5 ${c.text}`} />
                  <span className="text-sm font-semibold text-app-text-primary">{domain.title}</span>
                  {!isComingSoon && (
                    <button
                      onClick={() =>
                        useAppViewStore.getState().setView({
                          kind: "workflows",
                          domainId: domain.id,
                        })
                      }
                      className="ml-auto flex items-center gap-0.5 text-xs text-muted-foreground hover:text-app-text-primary transition-colors"
                    >
                      Workflows <ArrowRight className="h-3 w-3" />
                    </button>
                  )}
                </div>

                {isComingSoon ? (
                  <div className="flex items-center gap-2 px-4 py-3 rounded-lg border border-dashed border-app-border bg-muted/30">
                    <Lock className="h-3.5 w-3.5 text-muted-foreground" />
                    <span className="text-xs text-muted-foreground">Coming soon</span>
                  </div>
                ) : (
                  <div className="grid grid-cols-3 gap-3">
                    {domain.tutorials.map((tutorial) => (
                      <TutorialCard
                        key={tutorial.id}
                        tutorial={tutorial}
                        domain={domain}
                        onClick={() =>
                          useAppViewStore.getState().setView({
                            kind: "tutorial",
                            domainId: domain.id,
                            tutorialId: tutorial.id,
                          })
                        }
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })
        )}

        {!domainsLoading && domains.length === 0 && (
          <p className="text-center text-xs text-muted-foreground">No tutorials available</p>
        )}
      </div>
    </div>
  );
}
