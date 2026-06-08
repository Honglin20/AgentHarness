"use client";

import React from "react";
import type { AgentTokenUsage } from "@/types/events";

interface TokenBreakdownProps {
  breakdown: Record<string, AgentTokenUsage>;
}

/**
 * Renders a per-agent token usage table. Sub-agents (keys containing ".sub_agent",
 * matching the backend's f"{parent_name}.sub_agent" key format) are styled as
 * muted. A totals row appears at the bottom.
 */
export const TokenBreakdown = React.memo(function TokenBreakdown({ breakdown }: TokenBreakdownProps) {
  const agents = Object.entries(breakdown);
  if (agents.length === 0) return null;

  const totals = agents.reduce(
    (acc, [, u]) => ({
      input: acc.input + u.input,
      output: acc.output + u.output,
      cache_hit: acc.cache_hit + (u.cache_hit ?? 0),
      reasoning: acc.reasoning + (u.reasoning ?? 0),
    }),
    { input: 0, output: 0, cache_hit: 0, reasoning: 0 },
  );

  return (
    <div className="space-y-2">
      <h4 className="text-sm font-medium">Token Usage Breakdown</h4>
      <table className="w-full text-xs">
        <thead>
          <tr className="text-muted-foreground">
            <th className="text-left">Agent</th>
            <th className="text-right">Input</th>
            <th className="text-right">Output</th>
            <th className="text-right">Cache Hit</th>
            <th className="text-right">Reasoning</th>
            <th className="text-right">Total</th>
          </tr>
        </thead>
        <tbody>
          {agents.map(([name, usage]) => {
            const isSub = name.includes(".sub_agent");
            return (
              <tr key={name} className={isSub ? "text-muted-foreground" : ""}>
                <td className="font-mono">{name}</td>
                <td className="text-right">{usage.input.toLocaleString()}</td>
                <td className="text-right">{usage.output.toLocaleString()}</td>
                <td className="text-right">{(usage.cache_hit ?? 0).toLocaleString()}</td>
                <td className="text-right">{(usage.reasoning ?? 0).toLocaleString()}</td>
                <td className="text-right font-medium">{usage.total.toLocaleString()}</td>
              </tr>
            );
          })}
          <tr className="border-t font-medium">
            <td>Total</td>
            <td className="text-right">{totals.input.toLocaleString()}</td>
            <td className="text-right">{totals.output.toLocaleString()}</td>
            <td className="text-right">{totals.cache_hit.toLocaleString()}</td>
            <td className="text-right">{totals.reasoning.toLocaleString()}</td>
            <td className="text-right">{(totals.input + totals.output).toLocaleString()}</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
});
