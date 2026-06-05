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

export function DagChapterNav({
  sections,
  activeIndex,
  onSectionClick,
}: DagChapterNavProps) {
  // Only show sections with agents (DAG nodes)
  const navItems = sections
    .map((s, i) => ({ ...s, originalIndex: i }))
    .filter((s) => s.agent !== null);

  if (navItems.length === 0) return null;

  // Map activeIndex to dag-index
  const dagToOriginal = navItems.map((item) => item.originalIndex);
  const activeDagIdx = dagToOriginal.indexOf(activeIndex);

  return (
    <nav className="flex flex-col">
      {navItems.map((item, dagIdx) => {
        const isActive = dagIdx === activeDagIdx;
        const isPast = dagIdx < activeDagIdx;
        const isLast = dagIdx === navItems.length - 1;

        return (
          <div key={item.originalIndex}>
            <button
              onClick={() => onSectionClick(item.originalIndex)}
              className="flex items-start gap-2.5 w-full text-left py-1"
            >
              {/* Dot */}
              <div className="flex flex-col items-center pt-1">
                <div
                  className={`h-2 w-2 rounded-full shrink-0 transition-colors ${
                    isActive
                      ? "bg-blue-500"
                      : isPast
                        ? "bg-emerald-400"
                        : "bg-gray-300 dark:bg-gray-600"
                  }`}
                />
              </div>
              {/* Title + agent */}
              <div className="flex flex-col min-w-0">
                <span
                  className={`text-[13px] leading-tight transition-colors ${
                    isActive
                      ? "text-blue-600 dark:text-blue-400 font-medium"
                      : isPast
                        ? "text-muted-foreground"
                        : "text-muted-foreground/50"
                  }`}
                >
                  {item.title}
                </span>
                {item.agent && (
                  <span
                    className={`text-[10px] font-mono leading-tight transition-colors ${
                      isActive
                        ? "text-blue-500/70 dark:text-blue-400/60"
                        : "text-muted-foreground/40"
                    }`}
                  >
                    {item.agent}
                  </span>
                )}
              </div>
            </button>
            {/* Connecting line */}
            {!isLast && (
              <div className="ml-[3.5px] h-4">
                <div
                  className={`w-px h-full ${
                    dagIdx < activeDagIdx
                      ? "bg-emerald-300 dark:bg-emerald-700"
                      : "bg-gray-200 dark:bg-gray-700"
                  }`}
                />
              </div>
            )}
          </div>
        );
      })}
    </nav>
  );
}
