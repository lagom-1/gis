# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 开发环境

- **必须使用 `gdal_env` conda 环境**运行所有 Python 代码（GDAL/rasterio 依赖）
- 后端启动前确保 Redis 已运行（Celery 消息代理），SQLite 无需额外配置

### 启动命令

```bash
# 后端 API（开发模式，端口 8000）
uvicorn api.app:app --reload --host 0.0.0.0 --port 8000

# Celery Worker（异步 GIS 任务执行，当前生产环境用 ThreadPoolExecutor 直连模式）
celery -A api.celery_app worker --loglevel=info -Q gis --concurrency=2

# 前端（开发模式，端口 3000，自动代理 /api → 8000）
cd frontend && npm run dev

# CLI 模式（无需启动后端）
python main.py "找到北京的TIF，做温度反演并制图"
```

## 项目概述

OpenGIS 是一个 AI 驱动的 GIS 遥感分析平台：

1. **`gis/`** — 纯函数 GIS 处理库，每个模块独立，返回 `{"success": bool, "message": str, ...}`
2. **`tools/`** — 基于 `@tool` 装饰器的工具系统，`ToolRegistry` 自动扫描注册（CLI 使用）
3. **`agent/`** — LLM 智能体引擎（含两个引擎实现 + 并发工具系统）
4. **Web 平台** — FastAPI 后端 + React 前端，用户通过 Web UI 提交自然语言 GIS 任务

全局配置集中在 **`config.py`**（路径、默认样式、环境变量）。

## 架构

### Agent 层 — 双引擎 + 双工具系统

存在两套并行的引擎和工具系统：

| | 旧系统（Web 任务） | 新系统（CLI + 多轮对话） |
|---|---|---|
| 引擎 | `agent/core.py` → `GISAgent` | `agent/engine.py` → `AgentLoop` |
| 工具注册 | `agent/tool_registry.py` | `tools/__init__.py` → `ToolRegistry` |
| 运行时 | `agent/tool.py` → `GISRuntime` | `tools/runtime.py` → `GISRuntime` |
| LLM | `agent/llm_client.py`（仅 Tongyi） | `agent/llm.py`（DeepSeek + Tongyi，基于 langchain） |
| 使用者 | `api/tasks_worker.py` | `main.py` + `api/routers/conversations.py` |

共通组件：
- **`agent/guard.py`** — `SafetyGuard`：循环检测、工作流顺序校正、幂等工具防重复
- **`agent/context.py`** — `build_context()`：为 LLM 构建决策上下文
- **`agent/conversational_agent.py`** — 多轮对话支持（SSE 流式响应）
- **`agent/memory.py`** — `MemoryStore` 持久化到 `workspace/memory.json` 和 `workspace/preferences.json`
- **`agent/prompts/system.py`** — LLM 系统提示词
- **`agent/gee_client.py`** — GEE 初始化（认证、重试）

关键设计：
- GIS 函数不共享状态，`GISRuntime` 是唯一状态源
- LLM 是唯一决策路径，无规则回退
- GEE 工作流强制顺序：`resolve_admin_region` → `gee_download_landsat_sca` → `run_lst` → `make_thematic_map`
- 循环检测：同一工具相同参数在同一步中调用两次则强制 final
- `_force_first_step` 防止 LLM 在 GEE 流程中错误选择 `search_local_files`

### Web 平台层

```
React 前端 (Vite + TailwindCSS + Zustand)
  → /api/* 代理 → FastAPI (api/app.py)
    → SQLAlchemy (SQLite) + Celery Worker (Redis)
```

- `api/app.py` — FastAPI 入口，注册路由（auth/tasks/conversations/payments/downloads），挂载 `/outputs` 静态文件，全局异常处理
- `api/models.py` — SQLAlchemy ORM（User、Task、Order、Download）+ Pydantic 模型
- `api/database.py` — 引擎/会话管理，启动自动建表 + 自动添加缺失列（轻量迁移）
- `api/tasks_worker.py` — `run_gis_task` 封装 `GISAgent.run()`，支持 Celery 异步和同步回退
- `api/routers/tasks.py` — 任务 CRUD，当前用 `ThreadPoolExecutor(max_workers=2)` 直连模式，10 分钟超时
- `api/routers/conversations.py` — 多轮对话 SSE 端点，使用 `AgentLoop` + `ToolRegistry`（新系统）
- `api/routers/auth.py` — 用户注册/登录（JWT），当前已移除强制认证，默认用户 ID=1
- `api/routers/payments.py` — Stripe 支付集成
- `api/services/file_service.py` / `payment_service.py` / `conversation_service.py` — 业务逻辑层

前端（React + TypeScript）：
- 状态管理：Zustand（authStore、taskStore、workspaceStore）
- 数据获取：TanStack React Query + axios
- 路由：react-router-dom（/ → Home, /login, /register, /dashboard, /submit, /tasks/:id, /workspace, /profile）
- UI：TailwindCSS + lucide-react 图标 + recharts 图表 + react-hot-toast 通知
- Vite 开发代理：`/api` 和 `/outputs` → `localhost:8000`

### GIS 模块

| 模块 | 功能 |
|------|------|
| `gis/sca_runner.py` | 单通道算法 LST 温度反演 |
| `gis/inspect.py` | 栅格元数据检查 + 产品类型推断 |
| `gis/file_discovery.py` | 本地文件模糊搜索 |
| `gis/cartographic_map.py` | 专题图（图例、比例尺、指北针） |
| `gis/classify.py` | 栅格分类（自然断点、等间隔、分位数） |
| `gis/statistics.py` | 单波段统计 + 直方图 |
| `gis/enhance.py` | 图像增强（高斯、中值、CLAHE、锐化） |
| `gis/threshold.py` | 阈值高亮 |
| `gis/compare.py` | 并排/差异对比 |
| `gis/profile.py` | 剖面线分析 |
| `gis/view3d.py` | 3D 渲染（表面/线框/等高线） |
| `gis/transform.py` | 翻转/旋转 |
| `gis/export.py` | 格式转换（PNG/JPG/PDF/TIFF） |
| `gis/report.py` | HTML 实验报告 |
| `gis/web_map.py` | Leaflet 交互地图 |
| `gis/admin_region.py` | 中国行政区 GeoJSON 解析 |
| `gis/gee_tools.py` | GEE Landsat 数据下载 |
| `gis/gee_timelapse.py` | 多年时间序列（GIF、分屏、趋势图） |
| `gis/gee_charts.py` | GEE 图表生成 |
| `gis/dynamic_world.py` | Dynamic World 土地覆盖 |
| `gis/time_slider.py` | 时间滑块可视化 |
| `gis/ee_classification.py` | Earth Engine 分类 |
| `gis/zonal_stats.py` | 分区统计 |
| `gis/timeseries_extract.py` | 时间序列提取 |
| `gis/timeseries_inspector.py` | 时间序列检查 |

### tools/ 包（新工具系统，CLI + 多轮对话用）

基于 `@tool` 装饰器，`ToolRegistry` 自动扫描子模块注册：

| 模块 | 功能 |
|------|------|
| `tools/data.py` | 数据搜索、检查 |
| `tools/analysis.py` | 分析（分类、统计、剖面等） |
| `tools/visualization.py` | 可视化（专题图、3D、Web 地图） |
| `tools/export.py` | 导出 |
| `tools/gee_lst.py` | GEE LST 温度反演 |
| `tools/gee_timelapse.py` | GEE 时间序列 |
| `tools/gee_analysis.py` | GEE 分析 |
| `tools/lst_local.py` | 本地 LST |
| `tools/system.py` | 系统工具 |

## 环境变量

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `LLM_PROVIDER` | LLM 提供商：`deepseek` 或 `tongyi` | `tongyi` |
| `DASHSCOPE_API_KEY` | 阿里云 DashScope API Key（tongyi 必填） | - |
| `DEEPSEEK_API_KEY` | DeepSeek API Key（deepseek 必填） | - |
| `DEEPSEEK_MODEL` | DeepSeek 模型名 | `deepseek-chat` |
| `QWEN_MODEL` | Qwen 模型名称 | `qwen-plus` |
| `LLM_TEMPERATURE` | LLM 温度 | `0.1` |
| `SECRET_KEY` | JWT 签名密钥 | 开发默认值 |
| `DATABASE_URL` | 数据库连接 | `sqlite:///workspace/opengis.db` |
| `REDIS_URL` | Redis 连接 | `redis://localhost:6379/0` |
| `CELERY_RESULT_BACKEND` | Celery 结果后端 | `redis://localhost:6379/1` |
| `CORS_ORIGINS` | 允许的跨域来源 | `http://localhost:3000,...` |
| `DEBUG` | 调试模式（返回详细错误） | `false` |
| `EARTHENGINE_PROJECT` / `EE_PROJECT` | GEE 项目 ID | - |
| `GEE_DRIVE_FOLDER` | GEE Google Drive 导出目录 | `GEE_Exports` |
| `GDRIVE_SYNC_DIR` | Google Drive 本地同步路径 | `G:\我的云端硬盘\GEE_Exports` |
| `STRIPE_SECRET_KEY` | Stripe 密钥 | - |
| `STRIPE_WEBHOOK_SECRET` | Stripe Webhook 密钥 | - |
| `FRONTEND_URL` | 前端地址（支付回调） | `http://localhost:3000` |

## 关键设计模式

- 所有 GIS 函数返回 dict：`success`（bool）+ `message`（str），成功时附加 `output_png`、`output_tif`
- `GISRuntime` 是会话状态的唯一来源，工具通过读写 `runtime.current_dataset`、`runtime.last_output`、`runtime.map_style` 传递状态
- 中国行政区名称（如"温江区"）在 GEE 操作前必须先通过 `resolve_admin_region` 解析为 GeoJSON 边界
- 任务状态流：pending → running → completed/failed/cancelled
- 当前任务执行用 `ThreadPoolExecutor` 直连模式（非 Celery），Celery worker 可用于独立部署
- `agent/tool.py`（88KB）是旧工具系统的集中定义文件，新工具在 `tools/` 下各模块分散定义
