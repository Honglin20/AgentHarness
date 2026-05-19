"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { WSEvent } from "@/types/events";

const WS_BASE_URL =
  typeof window !== "undefined"
    ? (window as unknown as Record<string, string>).__WS_BASE_URL__ ??
      "ws://localhost:8001"
    : "ws://localhost:8001";

const MAX_BACKOFF_MS = 30_000;

export interface UseWebSocketOptions {
  workflowId: string | null;
  onEvent?: (event: WSEvent) => void;
  autoReconnect?: boolean;
  reconnectDelay?: number;
}

export interface UseWebSocketReturn {
  isConnected: boolean;
  connect: () => void;
  disconnect: () => void;
  send: (data: unknown) => void;
}

export function useWebSocket({
  workflowId,
  onEvent,
  autoReconnect = true,
  reconnectDelay = 3000,
}: UseWebSocketOptions): UseWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const attemptRef = useRef(0);
  const onEventRef = useRef(onEvent);
  const [isConnected, setIsConnected] = useState(false);

  // Keep onEvent ref current without re-running the effect
  useEffect(() => {
    onEventRef.current = onEvent;
  }, [onEvent]);

  const clearReconnectTimer = useCallback(() => {
    if (reconnectTimerRef.current !== null) {
      clearTimeout(reconnectTimerRef.current);
      reconnectTimerRef.current = null;
    }
  }, []);

  const disconnect = useCallback(() => {
    clearReconnectTimer();
    attemptRef.current = 0;
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsConnected(false);
  }, [clearReconnectTimer]);

  const connect = useCallback(() => {
    if (!workflowId) return;

    // Close existing connection if any
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }

    const url = `${WS_BASE_URL}/ws/workflows/${workflowId}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      attemptRef.current = 0;
      setIsConnected(true);
    };

    ws.onmessage = (event: MessageEvent) => {
      try {
        const parsed = JSON.parse(event.data as string) as WSEvent;
        onEventRef.current?.(parsed);
      } catch {
        // Ignore malformed messages
      }
    };

    ws.onclose = () => {
      setIsConnected(false);
      wsRef.current = null;

      if (autoReconnect) {
        const backoff = Math.min(
          reconnectDelay * Math.pow(2, attemptRef.current),
          MAX_BACKOFF_MS,
        );
        attemptRef.current += 1;
        reconnectTimerRef.current = setTimeout(connect, backoff);
      }
    };

    ws.onerror = () => {
      // Let onclose handle reconnection; onclose fires after onerror
    };
  }, [workflowId, autoReconnect, reconnectDelay]);

  const send = useCallback((data: unknown) => {
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  // Connect when workflowId changes, disconnect on cleanup
  useEffect(() => {
    if (workflowId) {
      connect();
    }
    return () => {
      disconnect();
    };
  }, [workflowId, connect, disconnect]);

  return { isConnected, connect, disconnect, send };
}
