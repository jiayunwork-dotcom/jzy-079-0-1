// 依赖图的纯渲染层（SVG）：分层布局，节点大小随调用频次，
// 环上的边红色虚线高亮 + 箭头，边上标注调用次数/平均耗时。
import { useMemo } from "react";
import type { DependencyGraph } from "../types";

interface Positioned {
  x: number;
  y: number;
  r: number;
}

const WIDTH = 960;
const COLUMN_W = 190;
const ROW_H = 110;
const MARGIN_X = 110;
const MARGIN_Y = 70;

// 用强连通分量做分层布局：缩点 DAG 按拓扑层级分列，环内节点排在同一列附近
function layout(graph: DependencyGraph): Map<string, Positioned> {
  const nodes = graph.nodes.map((n) => n.service);
  const adj = new Map<string, string[]>();
  const indeg = new Map<string, number>();
  nodes.forEach((n) => {
    adj.set(n, []);
    indeg.set(n, 0);
  });
  graph.edges.forEach((e) => {
    adj.get(e.caller)?.push(e.callee);
    indeg.set(e.callee, (indeg.get(e.callee) ?? 0) + 1);
  });

  // Kahn 分层；有环时残余节点按名字插入，保证布局不失败
  const level = new Map<string, number>();
  const queue = nodes.filter((n) => (indeg.get(n) ?? 0) === 0);
  const remaining = new Set(nodes);
  while (queue.length) {
    const cur = queue.shift()!;
    if (!remaining.has(cur)) continue;
    let lvl = 0;
    graph.edges.forEach((e) => {
      if (e.callee === cur && level.has(e.caller)) {
        lvl = Math.max(lvl, (level.get(e.caller) ?? 0) + 1);
      }
    });
    level.set(cur, lvl);
    remaining.delete(cur);
    adj.get(cur)?.forEach((next) => {
      const d = (indeg.get(next) ?? 1) - 1;
      indeg.set(next, d);
      if (d <= 0) queue.push(next);
    });
  }
  // 环内剩余节点：放到其环邻居所在层级
  remaining.forEach((n) => {
    let lvl = 0;
    graph.edges.forEach((e) => {
      if (e.callee === n && level.has(e.caller)) {
        lvl = Math.max(lvl, (level.get(e.caller) ?? 0) + 1);
      }
    });
    level.set(n, lvl);
  });

  const columns = new Map<number, string[]>();
  level.forEach((lvl, name) => {
    if (!columns.has(lvl)) columns.set(lvl, []);
    columns.get(lvl)!.push(name);
  });

  const maxCount = Math.max(1, ...graph.nodes.map((n) => n.total_calls));
  const positions = new Map<string, Positioned>();
  const columnKeys = [...columns.keys()].sort((a, b) => a - b);
  columnKeys.forEach((lvl, colIndex) => {
    const members = columns.get(lvl)!.sort();
    members.forEach((name, rowIndex) => {
      const node = graph.nodes.find((n) => n.service === name)!;
      positions.set(name, {
        x: MARGIN_X + colIndex * COLUMN_W,
        y: MARGIN_Y + rowIndex * ROW_H + members.length * 10,
        r: 16 + (node.total_calls / maxCount) * 16,
      });
    });
  });
  return positions;
}

export function GraphView({ graph }: { graph: DependencyGraph }) {
  const positions = useMemo(() => layout(graph), [graph]);
  const height = Math.max(
    360,
    ...[...positions.values()].map((p) => p.y + p.r + 40),
  );

  return (
    <svg className="dependency-svg" viewBox={`0 0 ${WIDTH} ${height}`} role="img">
      <defs>
        <marker
          id="arrow"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#6b7a90" />
        </marker>
        <marker
          id="arrow-cyclic"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#e5484d" />
        </marker>
      </defs>

      {/* 边 */}
      {graph.edges.map((edge) => {
        const from = positions.get(edge.caller);
        const to = positions.get(edge.callee);
        if (!from || !to) return null;
        const isSelf = edge.caller === edge.callee;
        const label = `${edge.count} 次 / 均 ${edge.avg_duration_ms.toFixed(1)}ms`;
        if (isSelf) {
          return (
            <g key={`${edge.caller}->${edge.callee}`} className="edge-group">
              <path
                d={`M ${from.x + from.r} ${from.y - 6}
                    C ${from.x + from.r + 46} ${from.y - 60},
                      ${from.x - from.r} ${from.y - 60},
                      ${from.x - 4} ${from.y - from.r}`}
                fill="none"
                className={edge.cyclic ? "edge edge-cyclic" : "edge"}
                markerEnd="url(#arrow-cyclic)"
              />
              <text x={from.x + from.r + 8} y={from.y - 42} className="edge-label">
                自调用 {label}
              </text>
            </g>
          );
        }

        // 同一对节点之间（有环时）双向都存在：向两侧弯曲避免重叠
        const reverseExists = graph.edges.some(
          (e) => e.caller === edge.callee && e.callee === edge.caller,
        );
        const bend = reverseExists ? 40 : 0;
        const mx = (from.x + to.x) / 2;
        const my = (from.y + to.y) / 2;
        const path = bend
          ? `M ${from.x + from.r} ${from.y}
             Q ${mx + bend} ${my - bend} ${to.x - to.r} ${to.y}`
          : `M ${from.x + from.r} ${from.y} L ${to.x - to.r} ${to.y}`;
        return (
          <g key={`${edge.caller}->${edge.callee}`}>
            <path
              d={path}
              fill="none"
              className={edge.cyclic ? "edge edge-cyclic" : "edge"}
              markerEnd={edge.cyclic ? "url(#arrow-cyclic)" : "url(#arrow)"}
            />
            <text
              x={mx + (bend ? bend / 2 : 0)}
              y={my - 6 + (bend ? -bend / 2 : 0)}
              className={edge.cyclic ? "edge-label edge-label-cyclic" : "edge-label"}
            >
              {label}
            </text>
          </g>
        );
      })}

      {/* 节点 */}
      {graph.nodes.map((node) => {
        const p = positions.get(node.service)!;
        const inCycle = graph.edges.some(
          (e) => e.cyclic && (e.caller === node.service || e.callee === node.service),
        );
        return (
          <g key={node.service} transform={`translate(${p.x},${p.y})`}>
            <circle r={p.r} className={inCycle ? "node node-cyclic" : "node"} />
            <text y={4} textAnchor="middle" className="node-label">
              {node.service}
            </text>
            <text y={p.r + 16} textAnchor="middle" className="node-count">
              总参与 {node.total_calls} 次
            </text>
          </g>
        );
      })}
    </svg>
  );
}
