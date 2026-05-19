"use client";

import AgentStatusBar from "@/components/output/AgentStatusBar";
import StreamingText from "@/components/output/StreamingText";

export function CenterPanel() {
  return (
    <div className="flex flex-1 flex-col bg-app-bg-primary">
      <AgentStatusBar />
      <StreamingText />
    </div>
  );
}
