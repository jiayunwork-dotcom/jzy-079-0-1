// 请求详情页：瀑布图 + 关键路径 + 服务耗时占比 + 片段详情面板
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getTrace } from "../api";
import type { SpanNode, TraceTree } from "../types";
import { Waterfall } from "./Waterfall";
import { SpanDetail } from "./SpanDetail";

export function TraceDetail({ refreshTick }: { refreshTick: number }) {
  const { traceId = "" } = useParams();
  const [tree, setTree] = useState<TraceTree | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<SpanNode | null>(null);

  useEffect(() => {
    let cancelled = false;
    getTrace(traceId)
      .then((data) => {
        if (!cancelled) {
          setTree(data);
          setSelected(data.roots[0] ?? null);
        }
      })
      .catch((e) => !cancelled && setError((e as Error).message));
    return () => {
      cancelled = true;
    };
  }, [traceId, refreshTick]);

  if (error) return <div className="error-box">{error}</div>;
  if (!tree) return <div className="loading">加载中…</div>;

  return (
    <section className="page">
      <p className="breadcrumb">
        <Link to="/">← 返回请求列表</Link>
      </p>
      <h2>
        调用树 <code>{tree.trace_id}</code>
      </h2>

      {tree.has_missing_parent && (
        <div className="warn-box">
          本次请求存在父片段缺失的片段（等待超时或父编号不存在），已归入占位节点。
        </div>
      )}

      <div className="summary-grid">
        <div className="summary-card">
          <h4>关键路径</h4>
          <p className="critical-path">
            {tree.critical_path.span_ids.map((id) => (
              <code key={id}>{id}</code>
            ))}
          </p>
          <p>累计耗时 {tree.critical_path.total_duration_ms.toFixed(1)} ms</p>
        </div>
        <div className="summary-card">
          <h4>服务耗时占比</h4>
          {tree.service_share.map((item) => (
            <div key={item.service} className="share-row">
              <code>{item.service}</code>
              <div className="share-bar-track">
                <div className="share-bar" style={{ width: `${item.share * 100}%` }} />
              </div>
              <span>
                {(item.share * 100).toFixed(1)}%（{item.duration_ms.toFixed(1)}ms）
              </span>
            </div>
          ))}
        </div>
      </div>

      <div className="detail-layout">
        <Waterfall
          roots={tree.roots}
          selectedSpanId={selected?.span_id ?? null}
          onSelect={setSelected}
        />
        <SpanDetail span={selected} />
      </div>
    </section>
  );
}
