// 看板外壳：两页路由（请求检索 / 服务依赖图）+ 全局实时事件订阅
import { useCallback, useState } from "react";
import { HashRouter, NavLink, Navigate, Route, Routes } from "react-router-dom";
import { DependencyGraphPage } from "./components/DependencyGraph";
import { SearchPage } from "./components/SearchPage";
import { TraceDetail } from "./components/TraceDetail";
import type { WsEvent } from "./types";
import { useEventSocket } from "./useEventSocket";

const STATE_TEXT: Record<string, string> = {
  connecting: "连接中…",
  open: "实时连接已建立",
  closed: "连接断开，正在重连…",
};

export default function App() {
  // 每次后端推送数据变动事件就 +1，驱动两页重新拉取
  const [refreshTick, setRefreshTick] = useState(0);
  const [lastEvent, setLastEvent] = useState<string>("");

  const onEvent = useCallback((event: WsEvent) => {
    if (event.type === "spans.ingested") {
      setLastEvent(
        `新到片段 ${event.data.accepted} 个（重复忽略 ${event.data.duplicates}，等待归位 ${event.data.resolved_waits}）`,
      );
      setRefreshTick((n) => n + 1);
    } else if (event.type === "graph.updated") {
      setRefreshTick((n) => n + 1);
    } else if (event.type === "spans.timeout") {
      setLastEvent(`${event.data.timed_out} 个片段等待父片段超时，已归入占位节点`);
      setRefreshTick((n) => n + 1);
    }
  }, []);

  const connection = useEventSocket(onEvent);

  return (
    <HashRouter>
      <header className="topbar">
        <h1>分布式链路追踪看板</h1>
        <nav>
          <NavLink to="/traces" className={({ isActive }) => (isActive ? "active" : "")}>
            请求检索
          </NavLink>
          <NavLink to="/dependencies" className={({ isActive }) => (isActive ? "active" : "")}>
            服务依赖图
          </NavLink>
        </nav>
        <div className={`conn-state conn-${connection}`}>
          <span className="conn-dot" />
          {STATE_TEXT[connection]}
          {lastEvent && <em className="last-event">{lastEvent}</em>}
        </div>
      </header>

      <main>
        <Routes>
          <Route path="/" element={<Navigate to="/traces" replace />} />
          <Route path="/traces" element={<SearchPage refreshTick={refreshTick} />} />
          <Route path="/traces/:traceId" element={<TraceDetail refreshTick={refreshTick} />} />
          <Route path="/dependencies" element={<DependencyGraphPage refreshTick={refreshTick} />} />
        </Routes>
      </main>
    </HashRouter>
  );
}
