"use client";

import { ArrowLeft } from "lucide-react";

interface Crumb {
  label: string;
  onClick?: () => void;
}

interface BreadcrumbProps {
  items: Crumb[];
}

export function Breadcrumb({ items }: BreadcrumbProps) {
  return (
    <div className="flex items-center gap-2 shrink-0">
      {items.map((item, i) => {
        const isLast = i === items.length - 1;
        return (
          <span key={i} className="flex items-center gap-2">
            {i === 0 && (
              <ArrowLeft className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            )}
            {item.onClick ? (
              <button
                onClick={item.onClick}
                className="text-xs text-muted-foreground hover:text-app-text-primary transition-colors"
              >
                {item.label}
              </button>
            ) : isLast ? (
              <span className="text-sm font-medium text-app-text-primary truncate">
                {item.label}
              </span>
            ) : (
              <span className="text-xs text-muted-foreground">{item.label}</span>
            )}
            {!isLast && (
              <span className="text-muted-foreground/40">/</span>
            )}
          </span>
        );
      })}
    </div>
  );
}
