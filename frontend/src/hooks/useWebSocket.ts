"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { WSEvent } from "@/types/events";

function getWsBaseUrl(): string {
  if (typeof window === "undefined") return "";
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}`;
}

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
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const attemptRef = useRef(0);
  const onEventRef = useRef(onEvent);
  const cancelledRef = useRef(false);
  // Keep workflowId in a ref so the onclose handler reads the latest value
  const workflowIdRef = useRef(workflowId);
  workflowIdRef.current = workflowId;

  onEventRef.current = onEvent;

  const disconnect = useCallback(() => {
    attemptRef.current = 0;
    cancelledRef.current = true;
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    setIsConnected(false);
  }, []);

  const connect = useCallback(() => {
    if (!workflowId) return;
    disconnect();
    cancelledRef.current = false;

    const base = getWsBaseUrl();
    const url = `${base}/ws/workflows/${workflowId}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      setIsConnected(true);
      attemptRef.current = 0;
    };

    ws.onmessage = (e) => {
      try {
        const event: WSEvent = JSON.parse(e.data);
        onEventRef.current?.(event);
      } catch {}
    };

    ws.onclose = () => {
      setIsConnected(false);
      wsRef.current = null;
      // Read latest workflowId from ref + check cancellation flag
      if (autoReconnect && !cancelledRef.current && workflowIdRef.current) {
        const delay = Math.min(
          reconnectDelay * Math.pow(2, attemptRef.current),
          MAX_BACKOFF_MS
        );
        attemptRef.current++;
        setTimeout(connect, delay);
      }
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [workflowId, autoReconnect, reconnectDelay, disconnect]);

  useEffect(() => {
    connect();
    return () => disconnect();
  }, [connect, disconnect]);

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  return { isConnected, connect, disconnect, send };
}
