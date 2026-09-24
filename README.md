# 分布式链路追踪看板（TraceBoard）

轻量级分布式链路追踪：各服务上报调用片段（span），后端按追踪编号聚拢、
按父子编号拼成调用树（支持乱序到达、重复去重、父缺失占位），算关键路径与
服务耗时占比；并持续从已拼好的树里提取服务调用边，按时间窗口聚合成带环检测
的全局依赖图。浏览器两页看板：请求检索 + 树状瀑布图、服务依赖图。新片段和
图更新通过 WebSocket 实时推送。

## 一键启动

```bash
docker compose up --build
# 浏览器打开 http://localhost:8080
```

- 后端：`python:3.12-slim` + FastAPI + Uvicorn，SQLite 数据落在 `trace-data` 卷
- 前端：`node:20-alpine` 构建静态资源，`nginx:alpine` 提供页面并反代 `/api`、`/ws`

灌入演示数据（正常链路 / 失败片段 / 环 / 延迟父片段 / 缺失父片段）：

```bash
docker compose exec backend python scripts/seed_demo.py
# 或对本地 8000 端口： python backend/scripts/seed_demo.py
```

## 关键配置（后端环境变量）

| 变量 | 默认 | 说明 |
| --- | --- | --- |
| `TRACE_DB_PATH` | `/data/traces.db` | SQLite 文件 |
| `ORPHAN_MAX_WAIT_SECONDS` | `30` | 子片段等父片段的最长时间，超时归入占位节点 |
| `DEPENDENCY_WINDOW_1H` / `DEPENDENCY_WINDOW_24H` | `3600` / `86400` | 依赖图窗口档位（秒） |
| `GRAPH_REFRESH_INTERVAL_SECONDS` | `30` | 后台孤儿超时扫描间隔 |

## HTTP 接口

| 方法 路径 | 说明 |
| --- | --- |
| `POST /api/spans` | 批量上报片段，任一片段非法则整批 422，返回结构化错误 |
| `GET /api/traces?trace_id=&service=` | 请求检索列表 |
| `GET /api/traces/{trace_id}` | 完整调用树 + 关键路径 + 服务耗时占比 |
| `GET /api/dependencies?window=1h\|24h` | 按窗口全量重算的依赖图（节点/边/环标记） |
| `GET /api/windows` | 可用窗口档位 |
| `WS  /ws/events` | 实时事件：`spans.ingested` / `spans.timeout` / `graph.updated` |

上报片段示例：

```json
{
  "spans": [
    {"trace_id": "t1", "span_id": "root", "parent_span_id": null,
     "service": "gateway", "start_time": "2026-09-24T10:00:00Z",
     "end_time": "2026-09-24T10:00:00.320Z", "status_code": 200}
  ]
}
```

时间支持带时区的 ISO 8601 字符串，或数值时间戳（自动识别秒/毫秒/微秒/纳秒）。
返回字段含 `accepted / duplicates / resolved_waits / timed_out`。

## 三种麻烦情况的处理

1. **父片段后到**：子片段先进 `orphans` 等待（`waiting`），瀑布图挂在占位节点
   下并标「等待父片段」；父片段在 `ORPHAN_MAX_WAIT_SECONDS` 内到达则立即归位，
   调用边此时才写入；超时则置 `timeout` 永久归占位（不可逆）。
2. **重复上报**：`(trace_id, span_id)` 主键 + `INSERT OR IGNORE`，只认最早一份。
3. **父编号指向不存在片段**：拼树不失败，该片段归「父片段缺失」占位节点。

依赖边只在片段真正挂到父片段下时记录；等父超时归占位的片段不产生调用边。

环检测用 Tarjan 强连通分量（自调用也算环），环上的边 `cyclic=true`，
前端红色虚线高亮。窗口切换是按桶下界全量重算，不缓存、不串窗。

## 目录结构（按职责拆模块）

```
backend/
  app/
    config.py            # 配置
    errors.py            # 结构化业务错误
    timeutil.py          # 时间解析/归一化（纳秒时间戳）
    schemas.py           # 片段上报模型与边界校验
    assembler.py         # 调用树拼接：乱序等待/去重/占位/关键路径
    dependencies.py      # 依赖图窗口聚合 + Tarjan 环检测
    service.py           # 业务编排
    events.py            # WebSocket 推送枢纽（跨线程）
    main.py              # FastAPI 装配/生命周期/错误处理
    routes/
      http.py            # HTTP 路由
      websocket.py       # 推送路由
    repositories/
      db.py              # SQLite 连接与表结构
      spans.py orphans.py dependencies.py
  tests/                 # 32 个自动化测试
frontend/src/
  components/
    SearchPage.tsx       # 请求检索列表
    TraceDetail.tsx      # 详情页（关键路径/服务占比）
    Waterfall.tsx        # 树状瀑布图
    SpanDetail.tsx       # 片段完整信息
    DependencyGraph.tsx # 依赖图页（窗口切换/环告警/边表）
    GraphView.tsx        # SVG 图渲染（节点频次/环边高亮）
  api.ts types.ts useEventSocket.ts App.tsx
```

## 本地开发与测试

```bash
# 后端
cd backend
python -m venv .venv && . .venv/bin/pip install -r requirements.txt
.venv/bin/pytest                  # 32 个测试

# 前端
cd frontend
npm install && npm run dev        # http://localhost:5173 ，自动代理到 :8000
npm run build                     # 类型检查 + 产出 dist/
```

## 测试锁住的判据

- 父片段延后到达：等待期挂占位并标 `awaiting_parent`，父到即归位；超时后才永久
  归占位，超时后父再到也不改挂
- 同一片段编号重复上报（跨批次/同批次）：树中只出现一次，且保留最早数据
- 父编号不存在：整批不报错，其它片段正常入树
- 4! 种上报顺序全排列，树结构完全一致
- 环检测：A↔B、A→B→C→A（含环外分支不误标）、自调用；纯 DAG 不误标
- 窗口切换：1h 只有新边，24h 含旧边，再切回 1h 不串窗
- 非法片段（缺时间/结束早于开始/编号为空/时间不可解析）422 + 结构化错误，整批拒绝
