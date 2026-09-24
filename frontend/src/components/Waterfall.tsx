// 树状瀑布图：每个片段一条横条（长度=耗时），按父子层级缩进；
// 失败片段红色、占位节点斜纹、关键路径加描边；点击片段回调给上层展示详情。
import type { SpanNode } from "../types";

interface WaterfallProps {
  roots: SpanNode[];
  selectedSpanId: string | null;
  onSelect: (span: SpanNode) => void;
}

// 取整棵树的时间范围（含占位节点），让横条位置有共同基准
function timeBounds(roots: SpanNode[]): { min: number; max: number } {
  let min = Number.POSITIVE_INFINITY;
  let max = Number.NEGATIVE_INFINITY;
  const walk = (node: SpanNode) => {
    min = Math.min(min, node.start_ns);
    max = Math.max(max, node.end_ns);
    node.children.forEach(walk);
  };
  roots.forEach(walk);
  return { min, max };
}

function barClass(node: SpanNode): string {
  const classes = ["wf-bar"];
  if (node.placeholder) classes.push("wf-bar-placeholder");
  else if (node.is_error) classes.push("wf-bar-error");
  if (node.on_critical_path) classes.push("wf-bar-critical");
  if (node.awaiting_parent) classes.push("wf-bar-waiting");
  return classes.join(" ");
}

function WaterfallRow({
  node,
  depth,
  bounds,
  selectedSpanId,
  onSelect,
}: {
  node: SpanNode;
  depth: number;
  bounds: { min: number; max: number };
  selectedSpanId: string | null;
  onSelect: (span: SpanNode) => void;
}) {
  const total = Math.max(bounds.max - bounds.min, 1);
  const leftPct = ((node.start_ns - bounds.min) / total) * 100;
  const widthPct = Math.max(((node.end_ns - node.start_ns) / total) * 100, 0.4);

  return (
    <>
      <div
        className={`wf-row${selectedSpanId === node.span_id ? " wf-row-selected" : ""}`}
        onClick={() => onSelect(node)}
      >
        <div className="wf-label" style={{ paddingLeft: 8 + depth * 22 }}>
          <span className="wf-tree-mark">{node.placeholder ? "◆" : depth === 0 ? "●" : "└"}</span>
          <span className="wf-service">{node.placeholder ? node.label : node.service}</span>
          <code className="wf-span-id">{node.placeholder ? "" : node.span_id}</code>
          {node.is_error && !node.placeholder && <span className="badge badge-error">失败 {node.status_code}</span>}
          {node.awaiting_parent && <span className="badge badge-warn">等待父片段</span>}
          {node.parent_missing && <span className="badge badge-error">父缺失</span>}
        </div>
        <div className="wf-track">
          <div
            className={barClass(node)}
            style={{ left: `${leftPct}%`, width: `${widthPct}%` }}
            title={`${node.duration_ms.toFixed(3)} ms`}
          >
            <span className="wf-bar-text">{node.duration_ms.toFixed(1)}ms</span>
          </div>
        </div>
      </div>
      {node.children.map((child) => (
        <WaterfallRow
          key={child.span_id}
          node={child}
          depth={depth + 1}
          bounds={bounds}
          selectedSpanId={selectedSpanId}
          onSelect={onSelect}
        />
      ))}
    </>
  );
}

export function Waterfall({ roots, selectedSpanId, onSelect }: WaterfallProps) {
  const bounds = timeBounds(roots);
  const span = Math.max(bounds.max - bounds.min, 1);
  return (
    <div className="waterfall">
      <div className="wf-header">
        <div className="wf-label">服务 / 片段</div>
        <div className="wf-track wf-ruler">
          <span style={{ left: 0 }}>0ms</span>
          <span style={{ left: "25%" }}>{((span * 0.25) / 1e6).toFixed(1)}</span>
          <span style={{ left: "50%" }}>{((span * 0.5) / 1e6).toFixed(1)}</span>
          <span style={{ left: "75%" }}>{((span * 0.75) / 1e6).toFixed(1)}</span>
          <span style={{ right: 0 }}>{(span / 1e6).toFixed(1)}ms</span>
        </div>
      </div>
      {roots.map((root) => (
        <WaterfallRow
          key={root.span_id}
          node={root}
          depth={0}
          bounds={bounds}
          selectedSpanId={selectedSpanId}
          onSelect={onSelect}
        />
      ))}
    </div>
  );
}
