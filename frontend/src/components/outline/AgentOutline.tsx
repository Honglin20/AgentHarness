"use client";

import React, { useCallback, useEffect, useRef } from "react";
import { useAgentOutline } from "./useAgentOutline";
import { useAutoFollowSelection } from "./useAutoFollowSelection";
import { useWaitingAgentToast } from "./useWaitingAgentToast";
import { useOutlineStore } from "./outlineStore";
import { OutlineItemRow } from "./OutlineItemRow";

/**
 * AgentOutline — left-side list of agents.
 *
 * Performance: each OutlineItemRow is React.memo'd and only re-renders
 * when its specific item object changes (deriveOutlineItems returns the
 * same item reference for unchanged nodes).
 */
export function AgentOutline() {
  const items = useAgentOutline();
  useWaitingAgentToast(items);
  useAutoFollowSelection(items);

  const selectedKey = useOutlineStore((s) => s.selectedKey);
  const select = useOutlineStore((s) => s.select);
  const autoFollow = useOutlineStore((s) => s.autoFollow);
  const setAutoFollow = useOutlineStore((s) => s.setAutoFollow);

  const handleSelect = useCallback((key: string) => select(key, false), [select]);

  // j/k vim-style navigation. Guard against INPUT/TEXTAREA/contentEditable
  // so typing in ChatInput isn't hijacked.
  //
  // Refs hold the latest items/selectedKey/select so the listener binds
  // once on mount. Without refs, every store update (each streamed token)
  // invalidates the `items` array reference and would re-bind the listener.
  const itemsRef = useRef(items);
  itemsRef.current = items;
  const selectedKeyRef = useRef(selectedKey);
  selectedKeyRef.current = selectedKey;
  const selectRef = useRef(select);
  selectRef.current = select;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
        return;
      }
      if (e.key !== "j" && e.key !== "k") return;

      const curItems = itemsRef.current;
      const curSelected = selectedKeyRef.current;
      const idx = curItems.findIndex((i) => i.key === curSelected);
      let nextIdx: number;
      if (e.key === "j") nextIdx = Math.min(curItems.length - 1, (idx < 0 ? -1 : idx) + 1);
      else nextIdx = Math.max(0, (idx < 0 ? curItems.length : idx) - 1);
      if (nextIdx === idx) return;

      e.preventDefault();
      selectRef.current(curItems[nextIdx].key, false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  if (items.length === 0) {
    return (
      <div className="flex h-full items-center justify-center px-4 text-center text-xs text-muted-foreground">
        No agents yet. Start a workflow to see the outline.
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex shrink-0 items-center justify-between border-b border-app-border px-3 py-1.5">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Agents
        </span>
        <button
          type="button"
          onClick={() => setAutoFollow(!autoFollow)}
          className={[
            "rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors",
            autoFollow
              ? "bg-blue-500/10 text-blue-600 hover:bg-blue-500/20"
              : "bg-muted text-muted-foreground hover:bg-muted/70",
          ].join(" ")}
          title={autoFollow ? "Auto-follow ON — click to pin current selection" : "Pinned — click to re-enable auto-follow"}
        >
          {autoFollow ? "Following" : "Pinned"}
        </button>
      </div>

      {/* List — no virtualizer needed; outline is O(agents), usually <20 items */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {items.map((item) => (
          <OutlineItemRow
            key={item.key}
            item={item}
            selected={item.key === selectedKey}
            onSelect={handleSelect}
          />
        ))}
      </div>
    </div>
  );
}
