"use client";

import React, { useCallback, useEffect, useRef } from "react";
import { useAgentOutline } from "./useAgentOutline";
import { useAutoFollowSelection } from "./useAutoFollowSelection";
import { useWaitingAgentToast } from "./useWaitingAgentToast";
import { useOutlineStore } from "./outlineStore";
import { OutlineGroupRow } from "./OutlineGroupRow";

/**
 * AgentOutline — left-side list of agents (one row per nodeId).
 *
 * Performance: each OutlineGroupRow is React.memo'd and only re-renders
 * when its specific group object changes (groupOutlineByNode returns the
 * same reference for unchanged nodeIds when the underlying items don't
 * change).
 */
export function AgentOutline() {
  const groups = useAgentOutline();
  useWaitingAgentToast(groups);
  useAutoFollowSelection(groups);

  const selectedNodeId = useOutlineStore((s) => s.selectedNodeId);
  const select = useOutlineStore((s) => s.select);
  const autoFollow = useOutlineStore((s) => s.autoFollow);
  const setAutoFollow = useOutlineStore((s) => s.setAutoFollow);

  const handleSelect = useCallback((nodeId: string) => select(nodeId, false), [select]);

  // j/k vim-style navigation. Guard against INPUT/TEXTAREA/contentEditable
  // so typing in ChatInput isn't hijacked.
  //
  // Refs hold the latest groups/selectedNodeId/select so the listener binds
  // once on mount. Without refs, every store update (each streamed token)
  // invalidates the `groups` array reference and would re-bind the listener.
  const groupsRef = useRef(groups);
  groupsRef.current = groups;
  const selectedNodeIdRef = useRef(selectedNodeId);
  selectedNodeIdRef.current = selectedNodeId;
  const selectRef = useRef(select);
  selectRef.current = select;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) {
        return;
      }
      if (e.key !== "j" && e.key !== "k") return;

      const curGroups = groupsRef.current;
      const curSelected = selectedNodeIdRef.current;
      const idx = curGroups.findIndex((g) => g.nodeId === curSelected);
      let nextIdx: number;
      if (e.key === "j") nextIdx = Math.min(curGroups.length - 1, (idx < 0 ? -1 : idx) + 1);
      else nextIdx = Math.max(0, (idx < 0 ? curGroups.length : idx) - 1);
      if (nextIdx === idx) return;

      e.preventDefault();
      selectRef.current(curGroups[nextIdx].nodeId, false);
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  if (groups.length === 0) {
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

      {/* List — no virtualizer needed; outline is O(agents), usually <20 groups */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {groups.map((group) => (
          <OutlineGroupRow
            key={group.nodeId}
            group={group}
            selected={group.nodeId === selectedNodeId}
            onSelect={handleSelect}
          />
        ))}
      </div>
    </div>
  );
}
