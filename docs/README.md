# OpenGIS — AI 驱动的 GIS 遥感分析平台

> 用自然语言描述需求，AI 自动规划并执行 GIS 工作流

---

## 目录

- [项目简介](#项目简介)
- [核心特性](#核心特性)
- [系统架构](#系统架构)
- [快速开始](#快速开始)
- [功能模块详解](#功能模块详解)
- [工具系统](#工具系统)
- [Agent 智能体](#agent-智能体)
- [API 接口](#api-接口)
- [前端界面](#前端界面)
- [配置说明](#配置说明)
- [技术栈](#技术栈)
- [开发指南](#开发指南)

---

## 项目简介

OpenGIS 是一个 **AI 驱动的地理信息系统（GIS）遥感分析平台**。用户只需用自然语言描述需求（如"找到北京市的 Landsat 数据，做地表温度反演，生成专题图"），系统会自动：

1. **理解意图** — LLM 解析用户需求，规划执行步骤
2. **调用工具** — 自动选择并执行 GIS 工具（数据下载、处理、分析、可视化）
3. **返回结果** — 生成图片、地图、图表、报告等多种格式输出

### 设计理念

- **纯 LLM 决策**：所有决策由 LLM 完成，无规则回退，保证灵活性
- **工具即函数**：GIS 功能封装为独立工具，LLM 按需调用
- **状态隔离**：`GISRuntime` 是唯一状态源，工具间通过 runtime 传递数据
- **流式交互**：SSE 实时推送执行进度，用户可随时介入

---

## 核心特性

### 🛰️ 遥感数据获取

- **Google Earth Engine 云端处理**：直接在 GEE 云端完成 Landsat 数据筛选、LST 反演，仅下载结果
- **分级降级选景**：5 级质量策略（A+ 到 C），自动处理云量不足场景
- **批量下载**：支持月度、年度、跨多年批量下载

### 🌡️ 地表温度反演

- **SCA 单通道算法**：基于 Red/NIR/BT 三波段，经亮温转换 → NDVI → 植被覆盖度 → 比辐射率 → LST
- **云端/本地双模式**：GEE 云端反演（推荐）或本地处理

### 💧 地表蒸散发反演

- **SEBAL 模型**：基于地表能量平衡算法，计算净辐射 → 土壤热通量 → 感热通量 → 潜热通量 → 蒸散发
- **GEE 云端计算**：结合 Landsat 8/9 影像和 ERA5-Land 再分析数据，无需地面气象站
- **冷热点自动标定**：自动选取干湿极端像元，建立温度差线性关系
- **输出**：瞬时 ET (mm/h)、日 ET (mm/d)、蒸发比

### 📊 数据分析

- **统计分析**：均值、标准差、直方图
- **栅格分类**：自然断点、等间隔、分位数
- **阈值高亮**：支持 >、<、between、outside 操作符
- **剖面线分析**：沿指定路径提取数值变化
- **分区统计**：按区域计算 mean/min/max/std/sum

### 🗺️ 专业制图

- **出版级专题图**：图例（4 方向）、比例尺（自动单位）、指北针（4 种风格）、标题、注记
- **17 种配色方案**：coolwarm、viridis、terrain、RdYlBu 等
- **交互式 Web 地图**：Leaflet 地图，支持坐标查看、图层切换、热力图
- **时间滑块**：多时相数据交互式浏览

### 🎬 时间序列

- **GIF 动画**：多年变化动画
- **分屏对比**：两年同期数据并排对比
- **趋势折线图**：多年变化趋势分析
- **点位提取**：指定坐标的时间序列 CSV + 图表

### 🖼️ 多格式可视化

| 格式 | 说明 |
|------|------|
| PNG/JPG | 静态图片 |
| GIF | 动画 |
| HTML | 交互式地图、图表、报告 |
| TIFF | 栅格数据 |
| CSV | 时间序列数据 |
| PDF | 实验报告 |

---

## 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                      用户界面层                              │
│  React + TypeScript + TailwindCSS + Zustand                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │ ChatPanel │  │  Canvas  │  │  Gallery │                  │
│  └────┬─────┘  └────┬─────┘  └──────────┘                  │
│       │ SSE 流式     │ 文件预览                              │
└───────┼─────────────┼───────────────────────────────────────┘
        │             │
┌───────┼─────────────┼───────────────────────────────────────┐
│       ▼             ▼          API 层                       │
│  FastAPI + SQLAlchemy + Celery                               │
│  ┌──────────────────────────────────────────┐               │
│  │ /api/conversations/{id}/messages/stream  │ ← SSE 端点    │
│  └──────────────────┬───────────────────────┘               │
└─────────────────────┼───────────────────────────────────────┘
                      │
┌─────────────────────┼───────────────────────────────────────┐
│                     ▼          Agent 层                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │ AgentLoop│  │  LLMClient│  │SafetyGuard│                 │
│  └────┬─────┘  └──────────┘  └──────────┘                  │
│       │ 工具调用                                              │
│  ┌────▼─────────────────────────────────────┐               │
│  │         ToolRegistry (25 个工具)          │               │
│  └────┬─────────────────────────────────────┘               │
└───────┼─────────────────────────────────────────────────────┘
        │
┌───────┼─────────────────────────────────────────────────────┐
│       ▼          GIS 处理层                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │ gis/     │  │gee_tools │  │cartograph│                  │
│  │ 核心算法  │  │GEE 下载   │  │ 专题制图  │                  │
│  └──────────┘  └──────────┘  └──────────┘                  │
│       │                                                      │
│       ▼                                                      │
│  rasterio / numpy / matplotlib / Google Earth Engine         │
└──────────────────────────────────────────────────────────────┘
```

### 分层架构

| 层 | 职责 | 技术 |
|---|---|---|
| **前端** | 用户交互、结果展示 | React, TypeScript, Vite, TailwindCSS |
| **API** | 请求路由、任务管理、认证 | FastAPI, SQLAlchemy, JWT |
| **Agent** | LLM 决策、工具调度、流程控制 | LangChain, DeepSeek/Tongyi |
| **Tools** | 工具注册、状态管理 | @tool 装饰器, ToolRegistry |
| **GIS** | 纯函数处理库 | rasterio, numpy, matplotlib, GEE |

---

## 快速开始

### 环境要求

- Python 3.10+（需 `gdal_env` conda 环境）
- Node.js 18+
- Redis（可选，Celery 消息代理）
- Google Earth Engine 账号（GEE 功能需要）

### 安装

```bash
# 1. 克隆仓库
git clone <repository-url>
cd opengis

# 2. 创建 conda 环境
conda create -n gdal_env python=3.10
conda activate gdal_env
conda install -c conda-forge gdal rasterio

# 3. 安装 Python 依赖
pip install -r requirements.txt

# 4. 安装前端依赖
cd frontend && npm install && cd ..

# 5. 配置环境变量
cp .env.example .env
# 编辑 .env 填入 API Key
```

### 配置环境变量

```bash
# LLM 配置（二选一）
LLM_PROVIDER=deepseek          # 或 tongyi
DEEPSEEK_API_KEY=sk-xxx        # DeepSeek API Key
DASHSCOPE_API_KEY=sk-xxx       # 通义千问 API Key

# GEE 配置（可选）
EARTHENGINE_PROJECT=your-project-id

# 数据库（默认 SQLite，无需配置）
DATABASE_URL=sqlite:///workspace/opengis.db
```

### 启动

```bash
# 方式一：一键启动
start.bat

# 方式二：分别启动
# 终端 1 - 后端
uvicorn api.app:app --reload --host 0.0.0.0 --port 8000

# 终端 2 - 前端
cd frontend && npm run dev

# 方式三：CLI 模式（无需启动后端）
python main.py "找到北京的TIF，做温度反演并制图"
```

### 访问

- **前端**：http://localhost:3000
- **API 文档**：http://localhost:8000/docs
- **健康检查**：http://localhost:8000/health

---

## 功能模块详解

### GIS 核心处理 (`gis/`)

GIS 层是纯函数库，每个模块独立，返回统一格式：

```python
{
    "success": True,           # 是否成功
    "message": "处理完成",     # 结果描述
    "output_png": "path.png",  # 输出图片（可选）
    "output_tif": "path.tif",  # 输出栅格（可选）
    "output_html": "path.html" # 输出 HTML（可选）
}
```

#### 核心模块列表

| 模块 | 功能 | 关键函数 |
|------|------|----------|
| `sca_runner.py` | SCA 单通道 LST 反演 | `run_sca()` |
| `sebal.py` | SEBAL 蒸散发反演 | `calc_sebal()` |
| `gee_tools.py` | GEE 云端数据下载 | `gee_compute_lst()`, `gee_compute_et()` |
| `cartographic_map.py` | 出版级专题图 | `generate_cartographic_map()` |
| `classify.py` | 栅格分类 | `classify_raster()` |
| `statistics.py` | 统计分析 | `analyze_raster()` |
| `enhance.py` | 图像增强 | `enhance_raster()` |
| `threshold.py` | 阈值高亮 | `threshold_highlight()` |
| `profile.py` | 剖面线分析 | `profile_analysis()` |
| `view3d.py` | 3D 渲染 | `render_3d()` |
| `web_map.py` | Leaflet 交互地图 | `generate_web_map()` |
| `report.py` | HTML 报告 | `generate_html_report()` |
| `export.py` | 格式转换 | `export_image()` |

#### GEE 高级功能

| 模块 | 功能 |
|------|------|
| `gee_timelapse.py` | 时间序列：GIF 动画、分屏对比、趋势图 |
| `dynamic_world.py` | Dynamic World 10m 土地覆盖分类 |
| `ee_classification.py` | GEE 无监督分类（K-Means） |
| `timeseries_extract.py` | 点位时间序列提取 |
| `zonal_stats.py` | 分区统计 |
| `time_slider.py` | 时间滑块可视化 |

---

## 工具系统

### 注册机制

工具基于 `@tool` 装饰器自动注册：

```python
from tools.base import tool, BaseTool

@tool(
    name="my_tool",
    description="工具描述",
    parameters={
        "param1": {"type": "string", "description": "参数说明"}
    }
)
class MyTool(BaseTool):
    def execute(self, **kwargs) -> dict:
        # 实现逻辑
        return {"success": True, "message": "完成"}
```

### 工具清单（25 个）

#### 数据工具

| 工具 | 功能 |
|------|------|
| `search_local_files` | 本地文件模糊搜索 |
| `set_current_dataset` | 设置当前工作数据集 |
| `inspect_raster` | 栅格元数据检查 |
| `resolve_admin_region` | 中国行政区边界解析 |

#### 分析工具

| 工具 | 功能 |
|------|------|
| `statistics` | 统计分析 + 直方图 |
| `classify_map` | 自动分类出图 |
| `threshold_highlight` | 阈值高亮 |
| `enhance_raster` | 图像增强/去噪 |
| `profile_analysis` | 剖面线分析 |

#### 可视化工具

| 工具 | 功能 |
|------|------|
| `make_thematic_map` | 标准专题图（图例、比例尺、指北针） |
| `generate_web_map` | Leaflet 交互式 Web 地图 |
| `view_3d` | 3D 可视化 |
| `compare_views` | 对比视图 |
| `transform_raster` | 翻转/旋转 |

#### 导出工具

| 工具 | 功能 |
|------|------|
| `export_result` | 格式转换（PNG/JPG/PDF/TIFF） |
| `generate_report` | HTML/PDF 实验报告 |

#### GEE LST 工具

| 工具 | 功能 |
|------|------|
| `gee_compute_lst` | GEE 云端 LST 反演（推荐） |
| `gee_download_landsat_sca` | GEE 下载 Landsat SCA 数据 |
| `gee_download_monthly_lst` | 月度 LST 智能合成 |
| `gee_download_yearly_lst` | 全年 12 月批量下载 |
| `gee_download_multi_year_lst` | 跨多年单月批量 |

#### GEE ET 工具（SEBAL 模型）

| 工具 | 功能 |
|------|------|
| `gee_compute_et` | GEE 云端 SEBAL 蒸散发反演（推荐） |
| `gee_download_monthly_et` | 月度 ET 智能合成 |
| `gee_download_yearly_et` | 全年 12 月批量下载 |

#### GEE 时间序列工具

| 工具 | 功能 |
|------|------|
| `gee_lst_timelapse` | GEE 端 GIF 动画 |
| `gee_lst_split_panel` | 两年分屏对比 HTML |
| `gee_lst_trend_chart` | 多年趋势折线图 |
| `gee_lst_timelapse_local` | 本地 LST 反演 + GIF（推荐） |

#### GEE 高级分析工具

| 工具 | 功能 |
|------|------|
| `extract_timeseries_to_point` | 点位时间序列提取 |
| `dynamic_world_landcover` | Dynamic World 土地覆盖 |
| `ee_unsupervised_classify` | GEE 无监督分类 |
| `generate_timeslider_map` | 时间滑块地图 |
| `gee_zonal_statistics` | 分区统计 |

#### 系统工具

| 工具 | 功能 |
|------|------|
| `set_map_style` | 更新地图样式参数 |
| `update_preferences` | 更新用户偏好 |
| `summarize_context` | 返回当前会话上下文摘要 |

---

## Agent 智能体

### 架构设计

Agent 层采用 **"纯 LLM 决策 → 工具执行"** 循环架构：

```
┌─────────────────────────────────────────────────────────┐
│                    AgentLoop 主循环                      │
│                                                         │
│  for step in 1..max_steps:                              │
│    ┌─────────────────────────────────────────────┐      │
│    │ 1. SafetyGuard.check() — 下载次数检查        │      │
│    │ 2. build_context() — 构建 LLM 上下文        │      │
│    │ 3. llm.invoke_json() — LLM 返回决策         │      │
│    │ 4. _correct_decision() — 安全校正           │      │
│    │ 5. 根据 decision.type 分支：                │      │
│    │    - "final" → 返回最终答案                  │      │
│    │    - "ask_user" → 返回用户提问              │      │
│    │    - "tool_call" → 执行工具 → 继续循环      │      │
│    └─────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────┘
```

### 核心组件

#### AgentLoop (`agent/engine.py`)

主循环引擎，负责：
- 调用 LLM 获取决策
- 执行工具调用
- 错误处理和重试
- SSE 事件推送

#### LLMClient (`agent/llm.py`)

LLM 统一适配层：
- 支持 DeepSeek 和通义千问
- 5 级 JSON 解析容错
- 3 次指数退避重试
- "白卷拦截"机制

```python
# JSON 解析容错策略
1. 直接解析
2. 代码块提取（```json ... ```）
3. 平衡括号提取
4. 截断补括号
5. 尾逗号修复
```

#### SafetyGuard (`agent/guard.py`)

安全守卫：
- 下载次数上限检查（默认 10 次）
- 防止 GEE 配额耗尽

#### build_context (`agent/context.py`)

上下文构建器，为 LLM 提供决策信息：
- 用户输入、当前步骤
- 工具清单（名称、描述、参数 schema）
- 运行时状态（当前数据集、输出文件）
- 执行阶段推断（idle → has_region → has_data → ready_to_map → has_output）
- 复合任务 DAG 指令
- 对话历史（最多 30 条）

### 关键设计

#### GEE 工具链强制顺序

```
resolve_admin_region → gee_download_landsat_sca → run_lst → make_thematic_map
```

系统会自动校正 LLM 的决策，确保 GEE 工作流按正确顺序执行。

#### UI 渲染协议

工具执行结果自动映射到前端渲染类型：

| 渲染类型 | 触发工具 |
|----------|----------|
| `RENDER_IMAGE` | make_thematic_map, statistics, classify_map 等 |
| `RENDER_ANIMATION` | gee_lst_timelapse, gee_lst_timelapse_local |
| `RENDER_MAP` | generate_web_map, generate_timeslider_map |
| `RENDER_HTML` | generate_report, gee_lst_split_panel |
| `RENDER_CHART` | gee_lst_trend_chart, extract_timeseries_to_point |

#### 复合指令解析

系统能从自然语言提取多步任务：

```python
# 用户输入："下载北京2023年数据，做温度反演，生成专题图"
# 解析为子任务：
[
    ("download", "gee_download_landsat_sca"),
    ("lst", "run_lst"),
    ("map", "make_thematic_map")
]
```

---

## API 接口

### 认证

```bash
# 注册（赠送 1000 积分）
POST /api/auth/register
{
    "username": "user1",
    "email": "user@example.com",
    "password": "password123"
}

# 登录（返回 JWT）
POST /api/auth/login
{
    "username": "user1",
    "password": "password123"
}

# 开发模式：无 token 时自动使用默认用户 ID=1
```

### 会话（核心端点）

```bash
# 创建会话
POST /api/conversations
Response: {"id": "conv_xxx", "title": "新会话"}

# 发送消息（SSE 流式响应）
POST /api/conversations/{id}/messages/stream
Request: {"content": "找到北京的TIF，做温度反演"}

# SSE 事件类型
event: step_start      # 步骤开始
event: tool_start      # 工具开始执行
event: tool_result     # 工具执行结果
event: ask_user        # 向用户提问
event: final_answer    # 最终答案
event: error           # 错误
event: done            # 完成
event: heartbeat       # 心跳保活
```

### 任务

```bash
# 提交任务（异步执行）
POST /api/tasks
{"input_text": "找到北京的TIF，做温度反演"}

# 查询任务状态
GET /api/tasks/{id}

# 列出任务
GET /api/tasks?status=completed&page=1&size=10
```

### 下载

```bash
# 免费预览（缩略图）
GET /api/downloads/{task_id}/preview/{filename}

# 付费下载
GET /api/downloads/{task_id}/{filename}
Authorization: Bearer <token>

# 文件信息
GET /api/downloads/{task_id}/info
```

### 支付

```bash
# 创建支付订单
POST /api/payments/create
{
    "task_id": "task_xxx",
    "filename": "output.png",
    "tier_id": "basic"
}

# 查询订单状态
GET /api/payments/{order_id}

# 获取定价层级
GET /api/payments/tiers
```

---

## 前端界面

### 页面结构

| 路径 | 页面 | 功能 |
|------|------|------|
| `/` | 首页 | 功能介绍、使用示例 |
| `/login` | 登录 | 用户登录 |
| `/register` | 注册 | 用户注册 |
| `/conversations` | 会话 | 三栏布局：会话列表 + 对话 + 画布 |
| `/submit` | 提交 | 任务提交 |
| `/tasks/:id` | 任务详情 | 任务状态和结果 |
| `/gallery` | 画廊 | 历史产出浏览 |

### 三栏布局（会话页面）

```
┌──────────┬─────────────────────┬─────────────────────┐
│          │                     │                     │
│  会话列表 │     ChatPanel       │    CanvasPanel      │
│          │                     │                     │
│  - 历史  │  - 消息列表          │  - 文件标签栏        │
│  - 搜索  │  - 工具调用卡片      │  - 图片/GIF/HTML    │
│  - 新建  │  - 状态指示器        │  - 卷帘对比         │
│          │  - 输入框            │  - 全屏灯箱         │
│          │                     │  - 下载按钮         │
└──────────┴─────────────────────┴─────────────────────┘
```

### 核心组件

| 组件 | 功能 |
|------|------|
| `ChatPanel` | 对话面板，消息列表 + 输入框 |
| `CanvasPanel` | 画布面板，文件预览 + 对比 |
| `CompareSlider` | 卷帘对比滑块 |
| `GifPlayer` | GIF 动画播放器 |
| `HtmlPreview` | HTML 预览（iframe） |
| `TimeSeriesChart` | 时间序列图表 |
| `ToolCallCard` | 工具调用进度卡片 |
| `PaymentModal` | 支付弹窗 |
| `ViewerRouter` | 文件类型路由到对应查看器 |

### 状态管理

使用 Zustand 管理全局状态：
- 用户认证信息
- 对话消息列表
- 流式状态（分析中/执行中/等待输入/完成）
- 输出文件列表
- 会话列表

支持 `persist` 中间件持久化到 localStorage。

### SSE 客户端

```typescript
// 基于 fetch + ReadableStream
connectSSE(url, {
    onMessage: (event) => { /* 处理事件 */ },
    onError: (error) => { /* 错误处理 */ },
    signal: abortController.signal  // 取消信号
})

// 自动重连：指数退避（2s → 4s → 8s），最多 3 次
```

---

## 配置说明

### 环境变量

| 变量 | 用途 | 默认值 |
|------|------|--------|
| `LLM_PROVIDER` | LLM 提供商 | `tongyi` |
| `DEEPSEEK_API_KEY` | DeepSeek API Key | - |
| `DASHSCOPE_API_KEY` | 通义千问 API Key | - |
| `DEEPSEEK_MODEL` | DeepSeek 模型名 | `deepseek-chat` |
| `QWEN_MODEL` | Qwen 模型名 | `qwen-plus` |
| `LLM_TEMPERATURE` | LLM 温度 | `0.1` |
| `SECRET_KEY` | JWT 签名密钥 | 开发默认值 |
| `DATABASE_URL` | 数据库连接 | `sqlite:///workspace/opengis.db` |
| `REDIS_URL` | Redis 连接 | `redis://localhost:6379/0` |
| `EARTHENGINE_PROJECT` | GEE 项目 ID | - |
| `GEE_DRIVE_FOLDER` | GEE Drive 导出目录 | `GEE_Exports` |
| `GDRIVE_SYNC_DIR` | Google Drive 本地同步路径 | `G:\我的云端硬盘\GEE_Exports` |
| `STRIPE_SECRET_KEY` | Stripe 密钥 | - |
| `FRONTEND_URL` | 前端地址（支付回调） | `http://localhost:3000` |

### 配置文件 (`config.py`)

```python
# 路径配置
PROJECT_ROOT = "D:/opengis"
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
OUTPUTS_DIR = WORKSPACE_DIR / "outputs"

# 默认地图样式
DEFAULT_MAP_STYLE = {
    "colormap": "RdYlBu_r",
    "title": "",
    "show_legend": True,
    "show_scalebar": True,
    "show_north": True,
    "dpi": 150,
    "legend_position": "right",
    # ... 22 个参数
}

# 用户偏好
DEFAULT_PREFERENCES = {
    "export_format": "png",
    "colormap": "RdYlBu_r",
    "classification_method": "natural_breaks",
    "n_classes": 5
}
```

---

## 技术栈

### 后端

| 技术 | 用途 |
|------|------|
| Python 3.10+ | 主语言 |
| FastAPI | Web 框架 |
| SQLAlchemy | ORM |
| SQLite | 数据库 |
| Celery + Redis | 异步任务（可选） |
| python-jose | JWT 认证 |
| passlib | 密码哈希 |

### GIS

| 技术 | 用途 |
|------|------|
| rasterio | 栅格读写 |
| numpy | 数值计算 |
| matplotlib | 可视化 |
| Pillow | 图像处理 |
| scipy | 科学计算 |
| shapely | 几何计算 |
| Google Earth Engine | 云端遥感 |
| geemap | GEE 可视化 |

### LLM

| 技术 | 用途 |
|------|------|
| langchain-openai | LLM 调用 |
| langchain-community | 模型集成 |
| DeepSeek | LLM 提供商 |
| 通义千问 | LLM 提供商 |

### 前端

| 技术 | 用途 |
|------|------|
| React 18 | UI 框架 |
| TypeScript | 类型安全 |
| Vite | 构建工具 |
| TailwindCSS | 样式 |
| Zustand | 状态管理 |
| axios | HTTP 客户端 |
| react-router-dom | 路由 |
| recharts | 图表 |
| lucide-react | 图标 |

---

## 开发指南

### 项目结构

```
opengis/
├── agent/              # LLM 智能体引擎
│   ├── engine.py       # AgentLoop 主循环
│   ├── llm.py          # LLM 客户端
│   ├── guard.py        # 安全守卫
│   ├── context.py      # 上下文构建
│   └── prompts/        # 系统提示词
├── api/                # FastAPI 后端
│   ├── app.py          # 应用入口
│   ├── models.py       # 数据模型
│   ├── routers/        # 路由模块
│   └── services/       # 业务逻辑
├── gis/                # GIS 处理库
│   ├── sca_runner.py   # LST 反演
│   ├── sebal.py        # SEBAL 蒸散发反演
│   ├── gee_tools.py    # GEE 工具
│   ├── cartographic_map.py  # 专题图
│   └── ...             # 其他模块
├── tools/              # 工具系统
│   ├── base.py         # 基类和装饰器
│   ├── runtime.py      # 运行时状态
│   ├── __init__.py     # 工具注册表
│   ├── data.py         # 数据工具
│   ├── analysis.py     # 分析工具
│   ├── visualization.py # 可视化工具
│   ├── export.py       # 导出工具
│   ├── gee_lst.py      # GEE LST 工具
│   ├── gee_et.py       # GEE ET 工具（SEBAL）
│   └── ...             # 其他工具
├── frontend/           # React 前端
│   └── src/
│       ├── components/ # 组件
│       ├── pages/      # 页面
│       ├── services/   # API 客户端
│       └── stores/     # 状态管理
├── config.py           # 全局配置
├── main.py             # CLI 入口
└── workspace/          # 运行时输出
```

### 添加新工具

1. 在 `tools/` 下创建模块文件
2. 使用 `@tool` 装饰器定义工具类
3. 实现 `execute(**kwargs) -> dict` 方法
4. 工具会自动注册到 `ToolRegistry`

```python
# tools/my_tool.py
from tools.base import tool, BaseTool

@tool(
    name="my_new_tool",
    description="我的新工具",
    parameters={
        "input_path": {"type": "string", "description": "输入文件路径"}
    }
)
class MyNewTool(BaseTool):
    def execute(self, **kwargs) -> dict:
        input_path = kwargs.get("input_path")
        # 实现逻辑...
        return {
            "success": True,
            "message": "处理完成",
            "output_png": "path/to/output.png"
        }
```

### 添加新 GIS 模块

1. 在 `gis/` 下创建模块文件
2. 实现纯函数，返回统一格式 dict
3. 在 `tools/` 中创建对应工具调用

```python
# gis/my_processor.py
def process_raster(input_tif, output_tif):
    """处理栅格数据"""
    try:
        # 使用 rasterio 读写
        with rasterio.open(input_tif) as src:
            data = src.read(1)
            # 处理逻辑...
            
        # 写入结果
        with rasterio.open(output_tif, 'w', **profile) as dst:
            dst.write(result, 1)
        
        return {
            "success": True,
            "message": "处理完成",
            "output_tif": output_tif
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"处理失败: {str(e)}"
        }
```

### 运行测试

```bash
# 激活环境
conda activate gdal_env

# 运行测试
python -m pytest tests/

# 运行特定测试
python -m pytest tests/test_gis.py
```

---

## 常见问题

### Q: GEE 认证失败怎么办？

```bash
# 1. 确保已安装 earthengine-api
pip install earthengine-api

# 2. 初始化 GEE
earthengine authenticate

# 3. 设置项目 ID
export EARTHENGINE_PROJECT=your-project-id
```

### Q: 如何切换 LLM 提供商？

```bash
# 使用 DeepSeek
export LLM_PROVIDER=deepseek
export DEEPSEEK_API_KEY=sk-xxx

# 使用通义千问
export LLM_PROVIDER=tongyi
export DASHSCOPE_API_KEY=sk-xxx
```

### Q: 前端无法连接后端？

1. 确保后端已启动：`uvicorn api.app:app --port 8000`
2. 检查端口是否被占用：`netstat -ano | findstr 8000`
3. 检查 CORS 配置：`config.py` 中的 `CORS_ORIGINS`

### Q: 如何查看执行日志？

```bash
# 后端日志
uvicorn api.app:app --log-level debug

# Celery Worker 日志
celery -A api.celery_app worker --loglevel=debug
```

---

## 许可证

[待定]

---

## 贡献

欢迎提交 Issue 和 Pull Request！

---

## 联系方式

[待定]
