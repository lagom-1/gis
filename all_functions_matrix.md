# OpenGIS 全量功能矩阵

> 生成时间: 2026-05-23 | 工具总数: 35 | 状态: Agent 可调用

---

## 一、数据获取层

| # | 功能 | 后端工具/函数 | API/路由 | 独立运行 |
|---|------|-------------|----------|:---:|
| 1 | 本地文件模糊搜索 | `tools/data.py` → `search_local_files` → `gis/file_discovery.py:find_local_files()` | Agent Tool | ✅ |
| 2 | 栅格元数据检查 | `tools/data.py` → `inspect_raster` → `gis/inspect.py:inspect_raster()` | Agent Tool | ✅ |
| 3 | 设置当前工作数据集 | `tools/data.py` → `set_current_dataset` | Agent Tool | ✅ |
| 4 | 中国行政区边界解析 | `tools/data.py` → `resolve_admin_region` → `gis/admin_region.py:resolve_admin_region()` | Agent Tool | ✅ |
| 5 | GEE 认证初始化 | `tools/gee_auth.py` → `gee_init` | Agent Tool | ✅ |
| 6 | GEE 单月 LST 下载 | `tools/gee_lst.py` → `gee_compute_lst` → `gis/gee_tools.py` | Agent Tool | ✅ |
| 7 | GEE Landsat SCA 下载 | `tools/gee_lst.py` → `gee_download_landsat_sca` → `gis/gee_tools.py` | Agent Tool | ✅ |
| 8 | GEE 月度 LST 合成 | `tools/gee_lst.py` → `gee_download_monthly_lst` → `gis/gee_tools.py` | Agent Tool | ✅ |
| 9 | GEE 全年月度 LST 批量 | `tools/gee_lst.py` → `gee_download_yearly_lst` → `gis/gee_tools.py` | Agent Tool | ✅ |
| 10 | GEE 跨多年单月 LST | `tools/gee_lst.py` → `gee_download_multi_year_lst` → `gis/gee_tools.py` | Agent Tool | ✅ |

## 二、空间分析与算法层

| # | 功能 | 后端工具/函数 | 核心算法 | 独立运行 |
|---|------|-------------|----------|:---:|
| 11 | 本地 LST 温度反演(SCA) | `tools/lst_local.py` → `run_lst` → `gis/sca_runner.py` | 单通道算法(SCA) | ✅ |
| 12 | 栅格统计分析+直方图 | `tools/analysis.py` → `statistics` → `gis/statistics.py:analyze_raster()` | 均值/方差/百分位 | ✅ |
| 13 | 栅格自动分类(3种方法) | `tools/analysis.py` → `classify_map` → `gis/classify.py:classify_raster()` | 自然断点/等间隔/分位数 | ✅ |
| 14 | 阈值高亮 | `tools/analysis.py` → `threshold_highlight` → `gis/threshold.py` | 区间过滤 | ✅ |
| 15 | 栅格增强/去噪 | `tools/analysis.py` → `enhance_raster` → `gis/enhance.py:enhance_raster()` | 高斯/中值/CLAHE/锐化 | ✅ |
| 16 | 剖面线分析 | `tools/analysis.py` → `profile_analysis` → `gis/profile.py` | 沿线段采样 | ✅ |
| 17 | GEE Dynamic World 地覆 | `tools/gee_analysis.py` → `dynamic_world_landcover` → `gis/dynamic_world.py` | 9类地覆分类 | ✅ |
| 18 | GEE 无监督分类 | `tools/gee_analysis.py` → `ee_unsupervised_classify` → `gis/ee_classification.py` | K-Means 聚类 | ✅ |
| 19 | GEE 点时序提取 | `tools/gee_analysis.py` → `extract_timeseries_to_point` → `gis/timeseries_extract.py` | 时间序列CSV+折线图 | ✅ |
| 20 | GEE 分区统计 | `tools/gee_analysis.py` → `gee_zonal_statistics` → `gis/zonal_stats.py` | mean/min/max/std/sum | ✅ |

## 三、制图与可视化层

| # | 功能 | 后端工具/函数 | 核心库 | 独立运行 |
|---|------|-------------|--------|:---:|
| 21 | 标准专题图(图例/比例尺/指北针) | `tools/visualization.py` → `make_thematic_map` → `gis/cartographic_map.py:generate_cartographic_map()` | Matplotlib | ✅ |
| 22 | 地图样式设置(配色/标题/图例位置) | `tools/system.py` → `set_map_style` | — | ✅ |
| 23 | 3D 可视化 | `tools/visualization.py` → `view_3d` → `gis/view3d.py:render_3d()` | Matplotlib 3D | ✅ |
| 24 | 交互式 Web 地图 | `tools/visualization.py` → `generate_web_map` → `gis/web_map.py` | Leaflet HTML | ✅ |
| 25 | 时间滑块地图 | `tools/gee_analysis.py` → `generate_timeslider_map` → `gis/time_slider.py` | Leaflet + 时间轴 | ✅ |
| 26 | 多年 LST GIF 动画(GEE) | `tools/gee_timelapse.py` → `gee_lst_timelapse` | GEE + GIF合成 | ✅ |
| 27 | 多年 LST GIF 动画(本地) | `tools/gee_timelapse.py` → `gee_lst_timelapse_local` | 下载→反演→GIF | ✅ |
| 28 | 两年分屏对比 | `tools/gee_timelapse.py` → `gee_lst_split_panel` → `gis/gee_timelapse.py` | HTML 对比 | ✅ |
| 29 | 多年温度趋势图 | `tools/gee_timelapse.py` → `gee_lst_trend_chart` → `gis/gee_charts.py` | Matplotlib 折线图 | ✅ |
| 30 | 翻转/旋转 | `tools/visualization.py` → `transform_raster` → `gis/transform.py` | GDAL/rasterio | ✅ |

## 四、对比与导出层

| # | 功能 | 后端工具/函数 | 输出格式 | 独立运行 |
|---|------|-------------|----------|:---:|
| 31 | 并排/差异对比 | `tools/visualization.py` → `compare_views` → `gis/compare.py` | PNG | ✅ |
| 32 | 格式导出 | `tools/export.py` → `export_result` → `gis/export.py` | PNG/JPG/PDF/TIF | ✅ |
| 33 | HTML 实验报告 | `tools/export.py` → `generate_report` → `gis/report.py` | HTML | ✅ |

## 五、系统管理

| # | 功能 | 后端工具/函数 | 用途 | 独立运行 |
|---|------|-------------|------|:---:|
| 34 | 上下文摘要 | `tools/system.py` → `summarize_context` | 获取当前会话状态 | ✅ |
| 35 | 用户偏好设置 | `tools/system.py` → `update_preferences` | 默认格式/配色 | ✅ |

## 六、前端交互能力

| # | 功能 | 前端组件 | 技术 |
|---|------|---------|------|
| 1 | 多轮对话 | `ChatPanel` + `MessageList` + `ChatInput` | React + SSE |
| 2 | 画布预览 | `CanvasPanel` + `ViewerRouter` | React |
| 3 | 图片缩放查看 | `ImageViewer` | React |
| 4 | GIF 播放控制 | `GifPlayer` | React |
| 5 | HTML 嵌入预览 | `HtmlPreview` | iframe |
| 6 | 时序图表 | `TimeSeriesChart` | Recharts |
| 7 | **卷帘对比(手动选择)** | `CanvasPanel` + `CompareSlider` + 双下拉 `<select>` | React |
| 8 | 全屏灯箱 | `CanvasPanel` lightbox | React |
| 9 | 文件下载 | `DownloadButton` | React |
| 10 | 成果画廊 | `Gallery` 页面 | React |

## 七、Agent 引擎能力

| # | 能力 | 位置 | 说明 |
|---|------|------|------|
| 1 | LLM 决策循环 (max 25步) | `agent/engine.py` → `AgentLoop.run()` | DeepSeek/Tongyi 驱动 |
| 2 | 循环卡死检测 | `agent/guard.py` → `SafetyGuard.check()` | 连续调用/交替循环/OOM防御 |
| 3 | GEE 工作流强制校正 | `agent/engine.py` → `AgentLoop._correct_decision()` | GEE工具必须先解析行政区 |
| 4 | 批量文件自动处理 | `agent/engine.py` → `AgentLoop._get_next_unmapped_file()` | 下载N个文件→逐个制图 |
| 5 | 错误分类返回 | `agent/engine.py` → `classify_error()` | RETRYABLE/AUTH/FILE/OOM/UNKNOWN |
| 6 | UI 渲染协议 | `agent/engine.py` → `get_ui_action()` | RENDER_IMAGE/CHART/MAP/ANIMATION/COMPARISON |
| 7 | 上下文阶段推断 | `agent/context.py` → `build_context()` + `stage_hint` | idle→has_region→has_data→ready_to_map→has_output |
| 8 | SSE 流式推送 | `api/routers/conversations.py` → SSE endpoint | 心跳15s + ThreadPoolExecutor |
| 9 | 会话持久化 | `api/services/conversation_service.py` | SQLite + runtime.to_dict() |
| 10 | 对话自动创建(404自愈) | `api/routers/conversations.py` | 旧convId不存在→自动建新会话 |

## 八、API 端点总览

| 方法 | 路径 | 功能 |
|------|------|------|
| POST | `/api/conversations` | 创建新会话 |
| GET | `/api/conversations` | 列出会话 |
| GET | `/api/conversations/{id}` | 获取会话详情 |
| DELETE | `/api/conversations/{id}` | 删除会话 |
| POST | `/api/conversations/{id}/messages` | 发送消息(同步) |
| GET | `/api/conversations/{id}/messages` | 获取历史消息 |
| POST | `/api/conversations/{id}/messages/stream` | SSE 流式 Agent 执行 |
| POST | `/api/tasks` | 提交 GIS 任务 |
| GET | `/api/tasks` | 列出任务 |
| GET | `/api/tasks/{id}` | 获取任务详情 |
| DELETE | `/api/tasks/{id}` | 取消任务 |
| GET | `/outputs/{filename}` | 静态文件(预览/下载) |
| GET | `/health` | 健康检查 |
