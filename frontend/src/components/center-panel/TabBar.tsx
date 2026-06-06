"use client";

import React from "react";

export interface TabDef<T extends string = string> {
  key: T;
  label: string;
}

interface TabBarProps<T extends string> {
  tabs: TabDef<T>[];
  activeTab: T;
  setActiveTab: (tab: T) => void;
  /** Optional trailing element rendered after all tabs (e.g. badge, status pill) */
  trailing?: React.ReactNode;
}

/**
 * Generic horizontal tab bar with active underline indicator.
 */
export function TabBar<T extends string>({ tabs, activeTab, setActiveTab, trailing }: TabBarProps<T>) {
  return (
    <div className="flex shrink-0 items-center gap-1 border-b border-app-border px-2 pt-1">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          onClick={() => setActiveTab(tab.key)}
          className={`rounded-t px-3 py-1.5 text-xs font-medium transition-colors ${
            activeTab === tab.key
              ? "bg-app-bg-primary text-app-text-primary border-b-2 border-blue-500"
              : "text-muted-foreground hover:text-app-text-primary"
          }`}
        >
          {tab.label}
        </button>
      ))}
      {trailing}
    </div>
  );
}
