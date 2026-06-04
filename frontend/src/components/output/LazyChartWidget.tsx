"use client";

import { useRef, useState, useEffect } from "react";
import type { ChartPayload } from "@/types/events";
import ChartWidget from "./ChartWidget";

/**
 * Lazily mounts ChartWidget only when it scrolls into viewport.
 * Shows a 300px skeleton placeholder while off-screen.
 * Once visible, permanently mounts the chart (no unmount on scroll-away).
 */
export default function LazyChartWidget({ chart }: { chart: ChartPayload }) {
  const ref = useRef<HTMLDivElement>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setVisible(true);
          observer.disconnect();
        }
      },
      { rootMargin: "200px" }
    );

    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  if (visible) {
    return <ChartWidget chart={chart} />;
  }

  return (
    <div
      ref={ref}
      className="flex h-[300px] items-center justify-center rounded bg-muted/50 animate-pulse"
    >
      <span className="text-xs text-muted-foreground">{chart.title || chart.chart_type}</span>
    </div>
  );
}
