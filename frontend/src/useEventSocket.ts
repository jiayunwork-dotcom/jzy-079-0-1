// WebSocket 连接管理：断线自动重连，收到事件回调通知
import { useEffect, useRef, useState } from "react";
import type { WsEvent } from "./types";

export type ConnectionState = "connecting" | "open" | "closed";

export function useEventSocket(onEvent: (event: WsEvent) => void): ConnectionState {
  const [state, setState] = useState<ConnectionState>("connecting");
  const callbackRef = useRef(onEvent);
  callbackRef.current = onEvent;

  useEffect(() => {
    let socket: WebSocket | null = null;
    let retryTimer: ReturnType<typeof setTimeout> | null = null;
    let disposed = false;

    const connect = () => {
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${protocol}://${window.location.host}/ws/events`);
      setState("connecting");

      socket.onopen = () => setState("open");

      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data as string) as WsEvent;
          callbackRef.current(event);
        } catch {
          // 忽略无法解析的消息
        }
      };

      socket.onclose = () => {
        if (disposed) return;
        setState("closed");
        // 3 秒后自动重连
        retryTimer = setTimeout(connect, 3000);
      };

      socket.onerror = () => socket?.close();
    };

    connect();
    return () => {
      disposed = true;
      if (retryTimer) clearTimeout(retryTimer);
      socket?.close();
    };
  }, []);

  return state;
}
