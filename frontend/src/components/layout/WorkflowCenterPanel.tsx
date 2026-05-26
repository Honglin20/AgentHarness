/**
 * WorkflowCenterPanel - Context 架构集成包装器
 *
 * 此组件作为 Context 隔离架构的入口点，负责：
 * 1. 从现有状态获取 workflowId
 * 2. 使用 WorkflowScope 包装 ScopedCenterPanel
 * 3. 在 live 和 replay 模式下都能正确工作
 *
 * 这是渐进式迁移策略的一部分，保持与现有代码兼容
 */

"use client";

import { useViewStore } from "@/stores/viewStore";
import { useWorkflowStore } from "@/stores/workflowStore";
import { useBatchStore } from "@/stores/batchStore";
import { WorkflowScope } from "@/contexts/workflow-context";
import { ScopedCenterPanel } from "./ScopedCenterPanel";

interface WorkflowCenterPanelProps {
  activeBenchmark?: string | null;
}

/**
 * useActiveWorkflowId
 *
 * Hook: 获取当前活跃的 workflow ID
 *
 * 从不同的状态源获取 workflowId：
 * - live 模式：从 workflowStore
 * - replay 模式：从 activeView.run (用于展示历史数据)
 * - batch 模式：从 batchStore.selectedRunId
 */
function useActiveWorkflowId(): string | null {
  const activeView = useViewStore((s) => s.activeView);
  const workflowId = useWorkflowStore((s) => s.workflowId);
  const selectedRunId = useBatchStore((s) => s.selectedRunId);

  if (activeView.type === "replay") {
    // Replay 模式下，返回 run.run_id（用于从后端加载历史数据）
    return activeView.run.run_id;
  }

  if (selectedRunId) {
    // Batch 模式下，返回选中的 run ID
    return selectedRunId;
  }

  // Live 模式下，返回当前 workflow ID
  return workflowId;
}

/**
 * useShouldUseContext
 *
 * Hook: 判断是否应该使用 Context 隔离架构
 *
 * 条件：
 * - 有活跃的 workflow ID
 * - 不是 replay 模式（replay 模式下数据来自后端 API）
 */
function useShouldUseContextStores(): { workflowId: string | null; useContext: boolean } {
  const workflowId = useActiveWorkflowId();
  const activeView = useViewStore((s) => s.activeView);
  const activeBatchId = useBatchStore((s) => s.activeBatchId);

  // Replay 模式暂时不使用 Context（数据来自后端 API）
  if (activeView.type === "replay") {
    return { workflowId: activeView.run.run_id, useContext: false };
  }

  if (!workflowId) {
    return { workflowId: null, useContext: false };
  }

  return { workflowId, useContext: true };
}

export function WorkflowCenterPanel({ activeBenchmark }: WorkflowCenterPanelProps) {
  const { workflowId, useContext } = useShouldUseContextStores();
  const activeBatchId = useBatchStore((s) => s.activeBatchId);

  // 如果不应该使用 Context 架构，回退到原始 CenterPanel
  // 这包括：
  // 1. replay 模式（数据来自后端 API）
  // 2. 无 workflowId
  if (!useContext) {
    // 动态导入避免循环依赖
    const CenterPanel = require("./CenterPanel").CenterPanel;
    return <CenterPanel activeBenchmark={activeBenchmark} />;
  }

  // 使用 Context 架构
  return (
    <WorkflowScope
      workflowId={workflowId}
      batchId={activeBatchId}
    >
      <ScopedCenterPanel activeBenchmark={activeBenchmark} />
    </WorkflowScope>
  );
}