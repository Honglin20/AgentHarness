"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { WSEvent } from "@/types/events";
import { getApiKey, getUserId, getUserFromApiKey } from "@/lib/api";

function getWsBaseUrl(): string {
  if (typeof window === "undefined") return "";
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}`;
}

const MAX_BACKOFF_MS = 30_000;

export interface UseBatchWebSocketOptions {
  batchId: string | null;
  onEvent?: (event: WSEvent) => void;
  autoReconnect?: boolean;
  reconnectDelay?: number;
}

export interface UseBatchWebSocketReturn {
  isConnected: boolean;
  connect: () => void;
  disconnect: () => void;
  send: (data: unknown) => void;
}

export function useBatchWebSocket({
  batchId,
  onEvent,
  autoReconnect = true,
  reconnectDelay = 3000,
}: UseBatchWebSocketOptions): UseBatchWebSocketReturn {
  const [isConnected, setIsConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const attemptRef = useRef(0);
  const onEventRef = useRef(onEvent);
  const cancelledRef = useRef(false);
  const batchIdRef = useRef(batchId);
  batchIdRef.current = batchId;

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
    if (!batchId) return;
    disconnect();
    cancelledRef.current = false;

    // Get user_id from API Key for WebSocket isolation
    let userId = getUserId();
    const apiKey = getApiKey();
    if (!userId && apiKey) {
      userId = getUserFromApiKey(apiKey);
    }
    if (!userId) {
      userId = "default";
    }

    const base = getWsBaseUrl();
    const url = `${base}/ws/batch/${batchId}?user_id=${userId}`;
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
      if (autoReconnect && !cancelledRef.current && batchIdRef.current) {
        const delay = Math.min(
          reconnectDelay * Math.pow(2, attemptRef.current),
          MAX_BACKOFF_MS,
        );
        attemptRef.current++;
        setTimeout(connect, delay);
      }
    };

    ws.onerror = () => {
      ws.close();
    };
  }, [batchId, autoReconnect, reconnectDelay, disconnect]);

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
