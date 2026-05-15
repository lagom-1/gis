# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 开发环境

- **必须使用 `gdal_env` conda 环境**运行所有 Python 代码（GDAL/rasterio 依赖）
- 后端启动前确保 Redis 已运行（Celery 消息代理），SQLite 无需额外配置

### 启动命令

```bash
# 后端 API（开发模式，端口 8000）
uvicorn api.app:app --reload --host 0.0.0.0 --port 8000

# Celery Worker（异步 GIS 任务执行）
celery -A api.celery_app worker --loglevel=info -Q gis --concurrency=2

# 前端（开发模式，端口 3000，自动代理 /api → 8000）
cd frontend && npm run dev

# CLI 模式（无需启动后端）
python main.py "找到北京的TIF，做温度反演并制图"
```

## 项目概述

OpenGIS 是一个 AI 驱动的 GIS 遥感分析平台，包含三层：

1. **`gis/`** — 纯函数 GIS 处理库，每个模块返回 `{"success": bool, "message": str, ...}`
2. **`agent/`** — LLM 驱动的智能体引擎，`GISAgent`（`agent/core.py`）为入口，使用 Qwen/Tongyi 做决策，通过 `ToolRegistry` 调用工具
3. **Web 平台** — FastAPI 后端 + React 前端，用户通过 Web UI 提交自然语言 GIS 任务，后台异步执行，结果下载

## 架构

### Agent 层

```
用户输入 → LLM 决策 (prompts.py) → Tool 执行 (tool_registry.py)
  → 状态更新 (memory.py: MemoryStore) → 循环或 final 响应
```

- `agent/core.py` — `GISAgent` 主引擎，含决策验证、循环检测、timelapse 流程校正
- `agent/gee_client.py` — GEE 初始化（认证、重试），独立于 gis 层
- `agent/llm_client.py` — `LLMClient` 封装 ChatTongyi，JSON 解析、重试
- `agent/tool_registry.py` — `ToolRegistry` 管理 25+ 工具
- `agent/tool.py` — `GISRuntime` 持有会话状态（current_dataset、map_style 等）
- `agent/memory.py` — `MemoryStore` 持久化到 `workspace/memory.json` 和 `workspace/preferences.json`

关键设计：
- GIS 函数不共享状态，`GISRuntime` 是唯一状态源
- LLM 是唯一决策路径，无规则回退
- 循环检测：`set_map_style`/`make_thematic_map` 同轮调用两次则强制 final
- GEE 工作流强制顺序：`resolve_admin_region` → `gee_download_landsat_sca` → `run_lst` → `make_thematic_map`
- 第一步前置拦截（`_force_first_step`）防止 LLM 错误选择 `search_local_files` 而非 GEE 流程

### Web 平台层

```
React 前端 (Vite + TailwindCSS + Zustand)
  → /api/* 代理 → FastAPI (api/app.py)
    → SQLAlchemy (SQLite) + Celery Worker (Redis)
```

- `api/app.py` — FastAPI 应用入口，注册 auth/tasks/payments/downloads 路由，挂载 `/outputs` 静态文件
- `api/models.py` — SQLAlchemy ORM（User、Task、Order、Download）+ Pydantic 请求/响应模型
- `api/database.py` — 引擎/会话管理，启动时自动创建表 + 自动添加缺失列（轻量迁移）
- `api/celery_app.py` — Celery 配置（Redis broker，30 分钟超时，每 worker 处理 10 个任务后重启）
- `api/tasks_worker.py` — `run_gis_task` 封装 `GISAgent.run()`，支持 Celery 异步和同步回退两种模式
- `api/routers/tasks.py` — 任务 CRUD，当前使用 `ThreadPoolExecutor(max_workers=2)` 直连模式（非 Celery），10 分钟超时
- `api/routers/auth.py` — 用户注册/登录（JWT），但当前已移除认证，默认用户 ID=1
- `api/routers/payments.py` — Stripe 支付集成
- `api/services/file_service.py` / `payment_service.py` — 业务逻辑层

前端（React + TypeScript）：
- 状态管理：Zustand（authStore、taskStore、workspaceStore）
- 数据获取：TanStack React Query（useTasks、useAuth、usePayments hooks）
- 路由：react-router-dom（/ → Home, /login, /register, /dashboard, /submit, /tasks/:id, /workspace, /profile）
- Vite 开发代理：`/api` 和 `/outputs` → `localhost:8000`

### GIS 模块（完整列表）

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

## 环境变量

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `DASHSCOPE_API_KEY` | 阿里云 DashScope API Key（必填，否则 agent 无法启动） | - |
| `QWEN_MODEL` | Qwen 模型名称 | `qwen-plus` |
| `QWEN_TEMPERATURE` | LLM 温度 | `0.1` |
| `SECRET_KEY` | JWT 签名密钥 | 开发默认值 |
| `DATABASE_URL` | 数据库连接 | `sqlite:///workspace/opengis.db` |
| `REDIS_URL` | Redis 连接 | `redis://localhost:6379/0` |
| `CORS_ORIGINS` | 允许的跨域来源 | `http://localhost:3000,...` |
| `GEE_DRIVE_FOLDER` | GEE Google Drive 导出目录 | `GEE_Exports` |
| `GDRIVE_SYNC_DIR` | Google Drive 本地同步路径 | `G:\我的云端硬盘\GEE_Exports` |
| `STRIPE_SECRET_KEY` | Stripe 密钥 | - |
| `FRONTEND_URL` | 前端地址（支付回调） | `http://localhost:3000` |

## 关键设计模式

- 所有 GIS 函数返回 dict：`success`（bool）+ `message`（str），成功时附加 `output_png`、`output_tif`
- `GISRuntime` 是会话状态的唯一来源，工具通过读写 `runtime.current_dataset`、`runtime.last_output`、`runtime.map_style` 传递状态
- 中国行政区名称（如"温江区"）在 GEE 操作前必须先通过 `resolve_admin_region` 解析为 GeoJSON 边界
- 任务状态流：pending → running → completed/failed/cancelled
- 当前不使用 Celery 异步模式（任务路由直接用 ThreadPoolExecutor），Celery worker 可用于独立部署场景
