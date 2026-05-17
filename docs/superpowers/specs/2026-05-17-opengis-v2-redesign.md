# OpenGIS V2 重构设计文档

## 核心原则

1. **1 个页面** — 不跳转，所有操作在 Workspace 完成
2. **对话为主** — 连续交互，LLM 记住上下文（当前数据集、地图样式、操作历史）
3. **画布自适应** — 根据输出文件类型自动切换查看器
4. **函数原子化** — 每个 GIS 函数独立、可测试、无副作用
5. **工具语义化** — LLM 只看到 5-7 个语义清晰的工具，不纠结选哪个 download 函数
6. **代码最小化** — 删除所有重复逻辑，文件平均 150 行

## 一、后端架构

### 目录结构

```
opengis/
├── config.py                   # 配置
├── main.py                     # CLI 入口
│
├── gis/                        # GIS 层 — 纯函数，LLM 不可见
│   ├── __init__.py
│   │
│   ├── gee/                    # GEE 相关（新增目录）
│   │   ├── __init__.py
│   │   ├── client.py           # 初始化 + 认证（从 gee_client.py 移入）
│   │   ├── collection.py       # 筛选影像 + QA_PIXEL 云掩膜
│   │   ├── lst.py              # NDVI→Pv→ε→LST 单通道反演
│   │   └── download.py         # HTTP/Drive 下载 + 进度条
│   │
│   ├── raster/                 # 栅格处理（重组现有文件）
│   │   ├── __init__.py
│   │   ├── inspect.py          # 元数据检查（合并 load.py display.py）
│   │   ├── classify.py         # 分类
│   │   ├── statistics.py       # 统计 + 直方图
│   │   ├── enhance.py          # 增强
│   │   ├── threshold.py        # 阈值高亮
│   │   ├── transform.py        # 翻转/旋转
│   │   ├── compare.py          # 对比
│   │   ├── profile.py          # 剖面线
│   │   └── zonal.py            # 分区统计
│   │
│   ├── map/                    # 制图可视化（重组现有文件）
│   │   ├── __init__.py
│   │   ├── thematic.py         # 专题图（原 cartographic_map.py）
│   │   ├── webmap.py           # Leaflet 交互地图
│   │   ├── timelapse.py        # 时间序列 GIF/分屏/趋势图
│   │   ├── timeseries.py       # 时间序列提取 + 检查（合并两个文件）
│   │   ├── charts.py           # GEE 图表（原 gee_charts.py）
│   │   ├── classification.py   # EE 分类（原 ee_classification.py）
│   │   ├── dynamic_world.py    # Dynamic World 土地覆盖
│   │   ├── time_slider.py      # 时间滑块
│   │   └── view3d.py           # 3D 渲染
│   │
│   ├── io/                     # 输入输出
│   │   ├── __init__.py
│   │   ├── discovery.py        # 本地文件搜索（原 file_discovery.py）
│   │   ├── export.py           # 格式转换
│   │   └── report.py           # HTML 报告
│   │
│   └── region/                 # 行政区域
│       ├── __init__.py
│       └── admin.py            # 中国行政区解析
│
├── agent/                      # Agent 层
│   ├── __init__.py
│   ├── core.py                 # GISAgent（精简到 ~250 行）
│   ├── llm.py                  # LLM 客户端（原 llm_client.py）
│   ├── memory.py               # 记忆存储
│   │
│   ├── tools/                  # 工具目录（每个工具一个文件 ~50 行）
│   │   ├── __init__.py
│   │   ├── registry.py         # ToolRegistry + 注册所有工具
│   │   ├── runtime.py          # GISRuntime（原 tool.py 前半）
│   │   ├── discovery.py        # 本地文件搜索 + 元数据检查
│   │   ├── gee_download.py     # GEE 下载 LST（单时相）
│   │   ├── gee_timelapse.py    # GEE 时间序列（多年动画）
│   │   ├── classify.py         # 分类工具
│   │   ├── map.py              # 专题图 + set_map_style
│   │   ├── statistics.py       # 统计 + 直方图
│   │   ├── export.py           # 导出
│   │   └── compare.py          # 对比
│   │
│   └── prompts/
│       ├── __init__.py
│       └── system.py           # 系统 prompt（~80 行，精简自 497 行）
│
├── api/                        # Web API 层（保持结构，精简内容）
│   ├── app.py
│   ├── models.py
│   ├── database.py
│   ├── tasks_worker.py
│   └── routers/
│       ├── tasks.py
│       ├── downloads.py
│       └── payments.py
```

### 删除的文件

- `gis/gee_tools.py`（1804行）→ 拆分为 `gis/gee/` 4 个文件
- `gis/gee_timelapse.py`（679行）→ 合并到 `gis/map/timelapse.py`
- `gis/gee_charts.py` → 合并到 `gis/map/charts.py`
- `gis/ee_classification.py` → 移入 `gis/map/classification.py`
- `gis/dynamic_world.py` → 移入 `gis/map/dynamic_world.py`
- `gis/time_slider.py` → 移入 `gis/map/time_slider.py`
- `gis/timeseries_extract.py` + `gis/timeseries_inspector.py` → 合并为 `gis/map/timeseries.py`
- `gis/display.py` + `gis/load.py` → 移到 `gis/raster/inspect.py`
- `agent/tool.py`（1787行）→ 拆分为 `agent/tools/` 9 个文件
- `agent/prompts.py`（497行）→ 精简为 `agent/prompts/system.py`（~80行）
- `agent/gee_client.py` → 移入 `gis/gee/client.py`

### GEE 管线 API

```python
# gis/gee/collection.py
def filter_collection(geom, start, end, cloud_pct=30) -> ee.ImageCollection
def mask_clouds(image) -> ee.Image
def reduce_collection(col, method="median") -> ee.Image

# gis/gee/lst.py
def compute_lst(image) -> ee.Image  # 输入 L2 影像，输出 LST (°C) 单波段

# gis/gee/download.py
def download_tif(image, geom, output_path, scale=30) -> dict  # HTTP下载

# Agent 工具：组装上面的函数
# agent/tools/gee_download.py
def gee_lst_single(args) -> dict:
    col = filter_collection(geom, start, end, cloud)
    col = col.map(mask_clouds)
    img = reduce_collection(col, "median")
    lst = compute_lst(img)
    result = download_tif(lst, geom, output_path, scale)
    return result
```

## 二、前端架构

### 目录结构

```
frontend/src/
├── App.tsx                     # 路由 + 全局 Provider
├── main.tsx
│
├── pages/
│   ├── Workspace.tsx           # 唯一主页面（~350行）
│   └── Settings.tsx            # 设置（可选）
│
├── components/
│   ├── layout/
│   │   └── AppShell.tsx        # 顶栏 + 全局布局
│   │
│   ├── chat/
│   │   ├── ChatPanel.tsx       # 对话面板（可收缩为侧边条）
│   │   ├── MessageBubble.tsx   # 消息气泡（含 Markdown 渲染）
│   │   ├── TaskInput.tsx       # 输入框（textarea 自适应）
│   │   ├── HistoryPanel.tsx    # 历史任务面板
│   │   └── ProgressBar.tsx     # 执行进度
│   │
│   ├── canvas/
│   │   ├── CanvasArea.tsx      # 画布区域
│   │   ├── CanvasToolbar.tsx   # 工具栏
│   │   ├── FileThumbnails.tsx  # 缩略图条（按类型分组）
│   │   └── EmptyState.tsx      # 空状态提示
│   │
│   ├── viewers/
│   │   ├── ImageViewer.tsx     # 图片缩放拖拽
│   │   ├── GifPlayer.tsx       # GIF 播放控制
│   │   ├── ChartViewer.tsx     # recharts 图表
│   │   ├── HtmlPreview.tsx     # iframe 内嵌
│   │   ├── CompareSlider.tsx   # 对比滑块
│   │   └── ViewerRouter.tsx    # 根据文件类型路由
│   │
│   └── ui/
│       ├── Button.tsx
│       ├── IconButton.tsx
│       ├── Modal.tsx
│       └── LoadingSpinner.tsx
│
├── stores/
│   └── appStore.ts             # 单一 Zustand Store
│
├── services/
│   ├── api.ts                  # axios 实例
│   └── tasks.ts                # 任务 API
│
└── types/
    └── index.ts                # 所有 TypeScript 类型
```

### 页面布局

```
┌─────────────────────────────────────────────────────────┐
│  [☰] OpenGIS  [Workspace]                    [设置 ⚙] │
├──────────┬──────────────────────────────────────────────┤
│ [对话|历史]│                                              │
│          │             画布（主区域）                     │
│ ▼可收缩  │                                              │
│          │    ┌─────────────────────────────────┐       │
│ 消息列表  │    │  根据文件类型自动切换查看器      │       │
│          │    │  · 图片 → 缩放拖拽              │       │
│ 输入框   │    │  · GIF  → 播放调速              │       │
│          │    │  · CSV  → 折线图                │       │
│ [示例]   │    │  · HTML → iframe                │       │
│          │    │  · 对比 → 滑块分割              │       │
│          │    └─────────────────────────────────┘       │
│          │    ┌─────────────────────────────────┐       │
│          │    │  缩略图条 [分组: 图片|GIF|其他]   │       │
│          │    └─────────────────────────────────┘       │
├──────────┴──────────────────────────────────────────────┤
│ 状态栏: 文件名 | 大小 | [对比上次] [全屏] [下载]         │
└─────────────────────────────────────────────────────────┘
```

### 单一 Store 设计

```typescript
interface AppState {
  // 对话
  messages: Message[]
  isProcessing: boolean
  activeTaskId: number | null
  executionStep: number
  executionTool: string

  // 输出
  currentOutput: OutputFile[]
  previousOutput: OutputFile[]
  previewFile: OutputFile | null
  showComparison: boolean
  fullscreenPreview: boolean

  // 面板
  sidebarCollapsed: boolean
  activeTab: 'chat' | 'history'

  // 用户（合并 authStore）
  user: User | null
  token: string | null

  // 历史任务
  recentTasks: Task[]

  // Actions
  addMessage: (msg) => void
  setProcessing: (val, taskId?) => void
  setPreviewFile: (file) => void
  fetchRecentTasks: () => Promise<void>
  login: (data) => Promise<boolean>
  logout: () => void
  // ...
}
```

## 三、工具清单（LLM 可见）

```
resolve_admin_region  解析中国行政区边界
search_local_files    搜索本地栅格文件
inspect_raster        查看栅格元数据
gee_download_lst      从 GEE 下载 LST 温度数据（云端反演，单波段）
gee_lst_timelapse     生成多年 LST 时间序列（GIF+数据）
classify              对当前结果分类
set_map_style         调整地图样式（配色/图例/指北针）
make_thematic_map     生成标准专题图
export_result         导出为指定格式
compare_views         对比当前和上次结果
statistics            波段统计+直方图
```

**11 个工具，LLM 在任意上下文中只需选 1 个。**

## 四、实施顺序

1. **Phase 1: GIS 层** — 创建 `gis/gee/` 目录，提取核心函数
2. **Phase 2: Agent 层** — 拆分 `agent/tool.py` → `agent/tools/`
3. **Phase 3: 清理** — 删除旧文件，更新所有 import
4. **Phase 4: Prompt** — 重写系统 prompt（80 行）
5. **Phase 5: 前端** — 单一 Store + Workspace 重构
6. **Phase 6: 测试** — 端到端验证
