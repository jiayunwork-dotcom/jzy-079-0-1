// 单个片段详情面板：点击瀑布图横条后展开完整信息
import type { ReactNode } from "react";
import type { SpanNode } from "../types";

function Row({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div className="detail-row">
      <span className="detail-label">{label}</span>
      <span className="detail-value">{value}</span>
    </div>
  );
}

export function SpanDetail({ span }: { span: SpanNode | null }) {
  if (!span) {
    return (
      <div className="span-detail span-detail-empty">
        点击左侧瀑布图中的片段查看完整信息
      </div>
    );
  }
  return (
    <div className="span-detail">
      <h3>
        {span.placeholder ? "⚠️ 占位节点：" : "片段详情："}
        {span.placeholder ? span.label : span.span_id}
      </h3>
      {!span.placeholder && (
        <>
          <Row label="片段编号" value={<code>{span.span_id}</code>} />
          <Row
            label="父片段编号"
            value={span.parent_span_id ? <code>{span.parent_span_id}</code> : "（根片段）"}
          />
        </>
      )}
      <Row label="服务" value={<code>{span.service}</code>} />
      <Row label="开始时间" value={span.start_time} />
      <Row label="结束时间" value={span.end_time} />
      <Row label="自身耗时" value={`${span.duration_ms.toFixed(3)} ms`} />
      {!span.placeholder && (
        <Row
          label="状态码"
          value={
            <span className={span.is_error ? "status-error" : "status-ok"}>
              {span.status_code}
            </span>
          }
        />
      )}
      {span.awaiting_parent && (
        <Row label="状态" value={<span className="badge badge-warn">等待父片段到达中</span>} />
      )}
      {span.parent_missing && (
        <Row label="状态" value={<span className="badge badge-error">父片段缺失（等待超时）</span>} />
      )}
      {span.on_critical_path && (
        <Row label="关键路径" value={<span className="badge badge-critical">在关键路径上</span>} />
      )}
    </div>
  );
}
