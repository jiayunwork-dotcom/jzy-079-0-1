// 请求检索列表：按追踪编号或服务名查询，点击进入瀑布图
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { searchTraces } from "../api";
import type { TraceSummary } from "../types";

export function SearchPage({ refreshTick }: { refreshTick: number }) {
  const [traceId, setTraceId] = useState("");
  const [service, setService] = useState("");
  const [traces, setTraces] = useState<TraceSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      setTraces(
        await searchTraces({
          trace_id: traceId.trim() || undefined,
          service: service.trim() || undefined,
          limit: 50,
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  // 首次加载 + 实时事件触发刷新
  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [refreshTick]);

  return (
    <section className="page">
      <h2>请求检索</h2>
      <form
        className="search-bar"
        onSubmit={(e) => {
          e.preventDefault();
          void load();
        }}
      >
        <input
          placeholder="追踪编号 trace_id"
          value={traceId}
          onChange={(e) => setTraceId(e.target.value)}
        />
        <input
          placeholder="服务名 service"
          value={service}
          onChange={(e) => setService(e.target.value)}
        />
        <button type="submit" disabled={loading}>
          {loading ? "查询中…" : "查询"}
        </button>
      </form>

      {error && <div className="error-box">{error}</div>}

      <table className="trace-table">
        <thead>
          <tr>
            <th>追踪编号</th>
            <th>片段数</th>
            <th>涉及服务</th>
            <th>开始时间</th>
            <th>总耗时</th>
            <th>失败片段</th>
          </tr>
        </thead>
        <tbody>
          {traces.map((trace) => (
            <tr key={trace.trace_id}>
              <td>
                <Link to={`/traces/${encodeURIComponent(trace.trace_id)}`}>
                  {trace.trace_id}
                </Link>
              </td>
              <td>{trace.span_count}</td>
              <td>{trace.services.join(" → ")}</td>
              <td>{new Date(trace.start_time).toLocaleTimeString()}</td>
              <td>{trace.duration_ms.toFixed(1)} ms</td>
              <td>
                {trace.error_count > 0 ? (
                  <span className="badge badge-error">{trace.error_count}</span>
                ) : (
                  <span className="badge badge-ok">0</span>
                )}
              </td>
            </tr>
          ))}
          {!loading && traces.length === 0 && (
            <tr>
              <td colSpan={6} className="empty-hint">
                没有匹配的请求
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </section>
  );
}
