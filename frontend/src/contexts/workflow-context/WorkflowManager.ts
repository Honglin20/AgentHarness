/**
 * WorkflowManager - Workflow 生命周期管理
 *
 * 核心职责：
 * - 创建和管理 WorkflowStores 实例
 * - 管理 WebSocket 连接
 * - 清理空闲 workflow
 */

import type {
  WorkflowStores,
  WorkflowLifecycleState,
  ConnectionType,
  ConnectionInfo,
  WorkflowManagerConfig,
} from "./types";
import { createWorkflowStores } from "./workflowStores";
import { cleanupSeqTracker } from "./routeEvent";
import { resetAllStores } from "./routeEvent";

/**
 * Workflow Entry - 管理 workflow 的状态和资源
 */
interface WorkflowEntry {
  id: string;
  lifecycle: WorkflowLifecycleState;
  status: "idle" | "running" | "completed" | "failed" | "paused";
  stores: WorkflowStores;
  connection: ConnectionInfo;
  lastActiveAt: number;
  createdAt: number;
}

/**
 * WorkflowManager - 单例类
 *
 * 管理所有 workflow 的生命周期
 */
class WorkflowManager {
  private static instance: WorkflowManager | null = null;

  private workflows: Map<string, WorkflowEntry> = new Map();
  private activeWorkflowId: string | null = null;
  private config: Required<WorkflowManagerConfig>;

  // 默认配置
  private readonly defaultConfig: Required<WorkflowManagerConfig> = {
    idleCleanupThreshold: 5 * 60 * 1000, // 5 分钟
    maxWorkflows: 50,
    maxEventCacheSize: 500,
  };

  private constructor(config?: WorkflowManagerConfig) {
    this.config = config
      ? { ...this.defaultConfig, ...config }
      : this.defaultConfig;

    // 启动清理定时器
    this.startCleanupTimer();
  }

  /**
   * 获取单例实例
   */
  static getInstance(config?: WorkflowManagerConfig): WorkflowManager {
    if (!WorkflowManager.instance) {
      WorkflowManager.instance = new WorkflowManager(config);
    }
    return WorkflowManager.instance;
  }

  /**
   * 创建或获取 workflow
   */
  getOrCreate(workflowId: string): WorkflowEntry {
    const existing = this.workflows.get(workflowId);
    if (existing) {
      existing.lastActiveAt = Date.now();
      return existing;
    }

    const stores = createWorkflowStores(workflowId);
    const entry: WorkflowEntry = {
      id: workflowId,
      lifecycle: "created",
      status: "idle",
      stores,
      connection: { type: "single", ws: null, batchId: null },
      lastActiveAt: Date.now(),
      createdAt: Date.now(),
    };

    this.workflows.set(workflowId, entry);
    return entry;
  }

  /**
   * 设置活跃 workflow
   */
  setActiveWorkflowId(id: string | null): void {
    // 清理上一个 workflow
    if (this.activeWorkflowId && this.activeWorkflowId !== id) {
      const prev = this.workflows.get(this.activeWorkflowId);
      if (prev && prev.status === "running") {
        prev.lifecycle = "background";
      } else if (prev && (prev.status === "completed" || prev.status === "failed")) {
        prev.lifecycle = "completed";
      }
    }

    this.activeWorkflowId = id;

    // 激活新 workflow
    if (id) {
      const current = this.workflows.get(id);
      if (current) {
        current.lastActiveAt = Date.now();
        if (current.status === "running") {
          current.lifecycle = "running";
        } else {
          current.lifecycle = "idle";
        }
      }
    }
  }

  /**
   * 获取活跃 workflow
   */
  getActiveWorkflow(): WorkflowEntry | null {
    return this.activeWorkflowId ? this.workflows.get(this.activeWorkflowId) ?? null : null;
  }

  /**
   * 设置 workflow 状态
   */
  setWorkflowStatus(workflowId: string, status: WorkflowEntry["status"]): void {
    const entry = this.workflows.get(workflowId);
    if (!entry) return;

    entry.status = status;

    if (status === "running") {
      entry.lifecycle = entry.id === this.activeWorkflowId ? "running" : "background";
    } else if (status === "completed" || status === "failed") {
      entry.lifecycle = "completed";
    }
  }

  /**
   * 更新 workflow 连接信息
   */
  setConnection(workflowId: string, connection: ConnectionInfo): void {
    const entry = this.workflows.get(workflowId);
    if (!entry) return;

    entry.connection = connection;
  }

  /**
   * 获取 workflow 的 stores
   */
  getStores(workflowId: string): WorkflowStores | null {
    const entry = this.workflows.get(workflowId);
    return entry?.stores ?? null;
  }

  /**
   * 销毁 workflow
   */
  destroy(workflowId: string): void {
    const entry = this.workflows.get(workflowId);
    if (!entry) return;

    // Clean up seq dedup tracker
    cleanupSeqTracker(workflowId);

    // Reset all scoped stores to free memory
    try {
      resetAllStores(entry.stores);
    } catch {
      // Best-effort cleanup
    }

    // 关闭连接
    if (entry.connection.ws) {
      entry.connection.ws.close();
    }

    // 从 map 中移除
    this.workflows.delete(workflowId);

    // 如果是活跃 workflow，清空
    if (this.activeWorkflowId === workflowId) {
      this.activeWorkflowId = null;
    }
  }

  /**
   * 清理空闲 workflow
   */
  private cleanupIdleWorkflows(): void {
    const now = Date.now();
    const toDestroy: string[] = [];

    for (const [id, entry] of Array.from(this.workflows.entries())) {
      // 不清理活跃 workflow
      if (id === this.activeWorkflowId) continue;

      // 不清理正在运行的 workflow
      if (entry.status === "running") continue;

      // 检查空闲时间
      const idleTime = now - entry.lastActiveAt;
      if (idleTime > this.config.idleCleanupThreshold) {
        toDestroy.push(id);
      }
    }

    // 超过最大数量时，清理最旧的
    if (this.workflows.size > this.config.maxWorkflows) {
      const sorted = Array.from(this.workflows.entries())
        .filter(([id]) => id !== this.activeWorkflowId && this.workflows.get(id)?.status !== "running")
        .sort(([, a], [, b]) => a.lastActiveAt - b.lastActiveAt);

      const extra = sorted.length - (this.config.maxWorkflows - (this.workflows.size - sorted.length));
      for (let i = 0; i < extra && i < sorted.length; i++) {
        if (!toDestroy.includes(sorted[i][0])) {
          toDestroy.push(sorted[i][0]);
        }
      }
    }

    // 销毁
    for (const id of toDestroy) {
      this.destroy(id);
    }
  }

  /**
   * 启动清理定时器
   */
  private cleanupTimer: number | null = null;
  private startCleanupTimer(): void {
    if (typeof window === "undefined") return;
    this.cleanupTimer = window.setInterval(() => {
      this.cleanupIdleWorkflows();
    }, 60 * 1000);
  }

  /**
   * 停止清理定时器
   */
  private stopCleanupTimer(): void {
    if (this.cleanupTimer) {
      clearInterval(this.cleanupTimer);
      this.cleanupTimer = null;
    }
  }

  /**
   * 获取所有 workflow 信息
   */
  getWorkflowInfo(): Array<{
    id: string;
    lifecycle: WorkflowLifecycleState;
    status: WorkflowEntry["status"];
    lastActiveAt: number;
    isActive: boolean;
  }> {
    return Array.from(this.workflows).map(([id, entry]) => ({
      id,
      lifecycle: entry.lifecycle,
      status: entry.status,
      lastActiveAt: entry.lastActiveAt,
      isActive: id === this.activeWorkflowId,
    }));
  }

  /**
   * 重置（测试用）
   */
  reset(): void {
    for (const id of Array.from(this.workflows.keys())) {
      this.destroy(id);
    }
    this.activeWorkflowId = null;
    this.stopCleanupTimer();
    WorkflowManager.instance = null;
  }
}

/**
 * 导出单例获取函数
 */
export function getWorkflowManager(config?: WorkflowManagerConfig): WorkflowManager {
  return WorkflowManager.getInstance(config);
}

export type { WorkflowEntry };