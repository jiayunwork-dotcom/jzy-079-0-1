// 服务依赖图页：时间窗口切换（切换即按新窗口全量重算）、环告警、SVG 图渲染
import { useCallback, useEffect, useState } from "react";
import { getDependencyGraph, listWindows } from "../api";
import type { DependencyGraph as Graph } from "../types";
import { GraphView } from "./GraphView";

export function DependencyGraphPage({ refreshTick }: { refreshTick: number }) {
  const [windows, setWindowKeys] = useState<{ key: string; seconds: number }[]>([]);
  const [windowKey, setWindowKey] = useState("1h");
  const [graph, setGraph] = useState<Graph | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // 拉取可用窗口档位
  useEffect(() => {
    listWindows()
      .then((data) => {
        setWindowKeys(data.windows);
        setWindowKey(data.default);
      })
      .catch((e) => setError((e as Error).message));
  }, []);

  const load = useCallback(
    async (win: string) => {
      setLoading(true);
      setError("");
      try {
        // 每次切换都向后端重新请求，后端按新窗口全量聚合，不与旧窗口混
        setGraph(await getDependencyGraph(win));
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  useEffect(() => {
    void load(windowKey);
  }, [windowKey, load, refreshTick]);

  function switchWindow(win: string) {
    if (win !== windowKey) setWindowKey(win);
  }

  return (
    <section className="page">
      <div className="graph-header">
        <h2>服务依赖图</h2>
        <div className="window-switcher" role="tablist">
          {windows.map((w) => (
            <button
              key={w.key}
              role="tab"
              aria-selected={w.key === windowKey}
              className={w.key === windowKey ? "window-btn active" : "window-btn"}
              onClick={() => switchWindow(w.key)}
            >
              最近 {w.key === "1h" ? "一小时" : w.key === "24h" ? "一天" : w.key}
            </button>
          ))}
          {loading && <span className="loading-hint">聚合中…</span>}
        </div>
      </div>

      {error && <div className="error-box">{error}</div>}

      {graph?.has_cycle && (
        <div className="cycle-banner">
          ⚠️ 检测到循环依赖：{graph.cyclic_edges.map((e) => (
            <code key={e}>{e}</code>
          ))}
          ，环上的边已红色高亮，这通常意味着设计上存在问题。
        </div>
      )}

      {graph && graph.edges.length === 0 && (
        <div className="empty-hint">当前时间窗口内还没有调用数据</div>
      )}

      {graph && <GraphView graph={graph} />}

      {graph && graph.edges.length > 0 && (
        <table className="edge-table">
          <thead>
            <tr>
              <th>调用方</th>
              <th>被调用方</th>
              <th>调用次数</th>
              <th>平均耗时</th>
              <th>是否在环上</th>
            </tr>
          </thead>
          <tbody>
            {graph.edges.map((edge) => (
              <tr key={`${edge.caller}->${edge.callee}`}>
                <td><code>{edge.caller}</code></td>
                <td><code>{edge.callee}</code></td>
                <td>{edge.count}</td>
                <td>{edge.avg_duration_ms.toFixed(1)} ms</td>
                <td>
                  {edge.cyclic ? (
                    <span className="badge badge-error">环</span>
                  ) : (
                    <span className="badge badge-ok">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
