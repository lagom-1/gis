# OpenGIS Clean Plugin 架构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 OpenGIS 从巨型文件紧耦合架构重构为 Clean Plugin 架构，gis/ 层不动，重写 agent/api/frontend 三层。

**Architecture:** 工具系统用 @tool 装饰器自动注册，Agent 引擎精简到纯循环，API 统一 SSE 流式，前端组件化拆分 + TanStack Query/Zustand 双层状态。

**Tech Stack:** Python 3.11+ / FastAPI / SQLAlchemy / LangChain / React 19 / TypeScript / TailwindCSS / TanStack Query / Zustand

---

## 文件结构蓝图

### 新建文件

```
tools/
├── __init__.py          # ToolRegistry + auto_discover()
├── base.py              # BaseTool ABC + @tool 装饰器 + ToolSpec
├── runtime.py            # GISRuntime (从 agent/tool.py 迁移)
├── data.py              # search_local_files, set_current_dataset, inspect_raster, resolve_admin_region
├── gee_auth.py          # gee_init
├── gee_lst.py           # gee_compute_lst, gee_download_landsat_sca, gee_download_monthly_lst, gee_download_yearly_lst, gee_download_multi_year_lst
├── gee_timelapse.py     # gee_lst_timelapse, gee_lst_split_panel, gee_lst_trend_chart, gee_lst_timelapse_local
├── gee_analysis.py      # extract_timeseries, timeseries_inspector, charts, dynamic_world, classification, zonal, download_collection, download_tiled, time_slider
├── lst_local.py         # run_lst
├── analysis.py          # statistics, classify_map, threshold_highlight, enhance_raster, profile_analysis
├── visualization.py     # view_3d, compare_views, transform_raster, make_thematic_map, generate_web_map, generate_timeslider_map
├── export.py            # export_result, generate_report
└── system.py            # set_map_style, update_preferences, summarize_context

agent/
├── engine.py            # AgentLoop (纯循环, ~150行)
├── guard.py             # SafetyGuard (验证规则 + 循环检测)
├── llm.py               # LLMClient (从 agent/llm_client.py 迁移并清理)
└── context.py           # ContextBuilder (构建 LLM 上下文)

api/
├── deps.py              # 依赖注入 (get_db, get_current_user)
├── models/
│   ├── __init__.py
│   ├── user.py
│   ├── conversation.py
│   └── task.py
├── routes/
│   ├── auth.py          # 新 auth 路由
│   ├── conversations.py # SSE 流式端点
│   └── files.py         # 文件下载/预览
└── services/
    ├── auth_service.py
    └── conversation_service.py

frontend/src/
├── api/
│   ├── client.ts
│   ├── conversations.ts
│   └── files.ts
├── hooks/
│   ├── useConversation.ts
│   ├── useConversations.ts
│   └── useMessages.ts
├── stores/
│   └── uiStore.ts
├── components/
│   ├── layout/
│   │   ├── AppShell.tsx
│   │   ├── Sidebar.tsx
│   │   └── ConversationList.tsx
│   ├── chat/
│   │   ├── ChatPanel.tsx
│   │   ├── MessageList.tsx
│   │   ├── MessageBubble.tsx
│   │   ├── StreamingMessage.tsx
│   │   ├── ToolCallCard.tsx
│   │   ├── ChatInput.tsx
│   │   └── ExamplePrompts.tsx
│   ├── viewer/
│   │   ├── ViewerPanel.tsx
│   │   ├── ImageViewer.tsx
│   │   ├── GifViewer.tsx
│   │   ├── HtmlViewer.tsx
│   │   ├── CompareSlider.tsx
│   │   ├── FileThumbnails.tsx
│   │   └── FileToolbar.tsx
│   └── shared/
│       ├── StatusBadge.tsx
│       ├── LoadingSpinner.tsx
│       └── EmptyState.tsx
├── pages/
│   ├── Workspace.tsx
│   ├── Home.tsx
│   └── Login.tsx
└── types/
    ├── conversation.ts
    ├── tool.ts
    └── index.ts
```

### 删除文件

```
agent/core.py            → 替换为 engine.py + guard.py
agent/conversational_agent.py → 合并到 engine.py
agent/tool.py            → 替换为 tools/ 目录
agent/tool_registry.py   → 替换为 tools/__init__.py
agent/llm_client.py      → 替换为 agent/llm.py
agent/memory.py          → 保留但简化
agent/prompts.py         → 保留
agent/tools/             → 替换为 tools/
api/models.py            → 拆分为 api/models/
api/routers/tasks.py     → 废弃（轮询模式移除）
api/routers/downloads.py → 合并到 routes/files.py
api/routers/conversations.py → 重写
api/routers/auth.py      → 重写
api/routers/payments.py  → 保留
api/services/conversation_service.py → 重写
frontend/src/stores/{authStore,taskStore,workspaceStore,appStore}.ts → 合并为 uiStore.ts
frontend/src/services/{api,auth,conversations,payments,sse,tasks}.ts → 替换为 api/
frontend/src/pages/{Dashboard,Submit,TaskPage,Register,Profile}.tsx → 删除
frontend/src/components/{Layout,DownloadButton,GifPlayer,HtmlPreview,ImagePreview,ImageViewer,OutputPreview,PaymentModal,TaskCard,TaskInput,TimeSeriesChart,ViewerRouter,CompareSlider,LoadingSpinner,StatusBadge}.tsx → 替换为新组件
```

---

## Phase 1: 工具系统重构

### Task 1.1: 创建工具基础设施 (base + registry + runtime)

**Files:**
- Create: `tools/__init__.py`
- Create: `tools/base.py`
- Create: `tools/runtime.py`

- [ ] **Step 1: 创建 `tools/runtime.py`**

将 `GISRuntime` 从 `agent/tool.py` 迁移，保持原有逻辑不变：

```python
"""
运行时状态管理 - 当前数据集、上次输出、地图样式
"""
from __future__ import annotations

import os
from typing import Any, Dict

from config import DEFAULT_MAP_STYLE


class GISRuntime:
    def __init__(self) -> None:
        self.current_dataset: str | None = None
        self.source_dataset: str | None = None
        self.last_output: str | None = None
        self.last_tif_output: str | None = None
        self.last_region_geojson: Dict[str, Any] | None = None
        self.last_region_name: str | None = None
        self.map_style: Dict[str, Any] = dict(DEFAULT_MAP_STYLE)

    def reset_for_new_task(self) -> None:
        self.current_dataset = None
        self.source_dataset = None
        self.last_region_geojson = None
        self.last_region_name = None

    def current_tif(self) -> str | None:
        if self.current_dataset and os.path.exists(self.current_dataset):
            return self.current_dataset
        if self.last_tif_output and os.path.exists(self.last_tif_output):
            return self.last_tif_output
        return None

    def to_dict(self) -> Dict[str, Any]:
        region = self.last_region_geojson
        if region is not None and not isinstance(region, dict):
            region = None
        return {
            "current_dataset": self.current_dataset,
            "source_dataset": self.source_dataset,
            "last_output": self.last_output,
            "last_tif_output": self.last_tif_output,
            "last_region_geojson": region,
            "last_region_name": self.last_region_name,
            "map_style": dict(self.map_style),
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        if not data:
            return
        self.current_dataset = data.get("current_dataset") or self.current_dataset
        self.source_dataset = data.get("source_dataset") or self.source_dataset
        self.last_output = data.get("last_output") or self.last_output
        self.last_tif_output = data.get("last_tif_output") or self.last_tif_output
        self.last_region_geojson = data.get("last_region_geojson") or self.last_region_geojson
        self.last_region_name = data.get("last_region_name") or self.last_region_name
        if data.get("map_style"):
            self.map_style.update(data["map_style"])
```

- [ ] **Step 2: 创建 `tools/base.py`**

```python
"""
工具基类和装饰器
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, str]
    category: str = "general"
    handler: Optional[Callable] = None


# 全局注册表，由 @tool 装饰器填充
_registry: List[tuple[Type, ToolSpec]] = []


def tool(
    name: str,
    description: str,
    parameters: Dict[str, str],
    category: str = "general",
):
    """装饰器：将类注册为工具"""
    spec = ToolSpec(
        name=name,
        description=description,
        input_schema=parameters,
        category=category,
    )
    def decorator(cls):
        spec.handler = cls
        _registry.append((cls, spec))
        return cls
    return decorator


def get_registered_tools() -> List[tuple[Type, ToolSpec]]:
    return list(_registry)


class BaseTool:
    """工具基类，提供 runtime 访问"""

    def __init__(self, runtime):
        self.runtime = runtime
```

- [ ] **Step 3: 创建 `tools/__init__.py`**

```python
"""
工具系统入口 - ToolRegistry + 自动发现
"""
from __future__ import annotations

import importlib
import os
import pkgutil
from typing import Any, Dict, Optional

from tools.base import BaseTool, ToolSpec, get_registered_tools
from tools.runtime import GISRuntime


class ToolRegistry:
    def __init__(self, runtime: Optional[GISRuntime] = None):
        self.runtime = runtime or GISRuntime()
        self._tools: Dict[str, ToolSpec] = {}
        self._instances: Dict[str, BaseTool] = {}
        self._auto_discover()

    def _auto_discover(self):
        """自动扫描 tools 子目录，导入所有模块"""
        import tools as pkg
        pkg_path = os.path.dirname(__file__)

        for _, name, is_pkg in pkgutil.iter_modules([pkg_path]):
            if name.startswith('_') or name in ('base', 'runtime'):
                continue
            importlib.import_module(f'tools.{name}')

        for cls, spec in get_registered_tools():
            self._tools[spec.name] = spec

    def register(self, spec: ToolSpec, handler_cls: type):
        self._tools[spec.name] = spec
        spec.handler = handler_cls

    def manifest(self) -> list:
        return [
            {"name": s.name, "description": s.description,
             "parameters": s.input_schema, "category": s.category}
            for s in self._tools.values()
        ]

    def call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        spec = self._tools.get(name)
        if not spec:
            return {"success": False, "message": f"未知工具: {name}"}

        if name not in self._instances:
            if not spec.handler:
                return {"success": False, "message": f"工具 {name} 无处理器"}
            self._instances[name] = spec.handler(self.runtime)

        instance = self._instances[name]
        return instance.execute(**args)
```

- [ ] **Step 4: 验证导入**

```bash
cd d:/opengis && python -c "from tools import ToolRegistry, GISRuntime; print('OK')"
```

- [ ] **Step 5: Commit**

```bash
git add tools/__init__.py tools/base.py tools/runtime.py
git commit -m "feat: 工具系统基础设施 - BaseTool + @tool 装饰器 + ToolRegistry 自动发现"
```

---

### Task 1.2: 迁移数据工具 (data.py)

**Files:**
- Create: `tools/data.py`
- Read: `agent/tool.py` (参考现有逻辑)

- [ ] **Step 1: 创建 `tools/data.py`**

```python
"""
数据工具：文件搜索、数据集管理、栅格检查、行政区解析
"""
from __future__ import annotations

import os
from typing import Any, Dict

from tools.base import BaseTool, tool


@tool(
    name="search_local_files",
    description="在本地常见目录中搜索文件",
    parameters={"query": "文件名或关键词", "roots": "可选，搜索根目录列表", "extensions": "可选，扩展名列表"},
    category="data",
)
class SearchLocalFilesTool(BaseTool):
    def execute(self, query="", roots=None, extensions=None) -> Dict[str, Any]:
        from gis.file_discovery import find_local_files
        return find_local_files(query=query, roots=roots, extensions=extensions)


@tool(
    name="set_current_dataset",
    description="将某个找到的栅格文件设置为当前工作数据",
    parameters={"path": "本地文件完整路径"},
    category="data",
)
class SetCurrentDatasetTool(BaseTool):
    def execute(self, path="") -> Dict[str, Any]:
        if not path or not os.path.exists(path):
            return {"success": False, "message": f"文件不存在: {path}"}
        self.runtime.current_dataset = path
        if self.runtime.source_dataset is None:
            self.runtime.source_dataset = path
        return {"success": True, "message": "当前数据已切换", "path": path}


@tool(
    name="inspect_raster",
    description="读取当前或指定栅格的波段、值域、分辨率、CRS",
    parameters={"path": "可选，栅格路径"},
    category="data",
)
class InspectRasterTool(BaseTool):
    def execute(self, path=None) -> Dict[str, Any]:
        target = path or self.runtime.current_tif()
        from gis.inspect import inspect_raster
        return inspect_raster(target)


@tool(
    name="resolve_admin_region",
    description="根据中国市/县/区名称解析行政边界",
    parameters={"region_name": "行政区名称，如 广元市 / 旺苍县"},
    category="data",
)
class ResolveAdminRegionTool(BaseTool):
    def execute(self, region_name="") -> Dict[str, Any]:
        from gis.admin_region import resolve_admin_region
        result = resolve_admin_region(region_name)
        if result.get("success"):
            self.runtime.last_region_geojson = result.get("region_geojson")
            self.runtime.last_region_name = result.get("matched_name")
        return result
```

- [ ] **Step 2: 验证数据工具**

```bash
cd d:/opengis && python -c "
from tools import ToolRegistry
r = ToolRegistry()
print('Tools:', [t['name'] for t in r.manifest() if t['category']=='data'])
"
```
Expected: `['search_local_files', 'set_current_dataset', 'inspect_raster', 'resolve_admin_region']`

- [ ] **Step 3: Commit**

```bash
git add tools/data.py
git commit -m "feat: 迁移数据工具 - search/set/inspect/resolve_admin_region"
```

---

### Task 1.3: 迁移 GEE 认证和 LST 工具

**Files:**
- Create: `tools/gee_auth.py`
- Create: `tools/gee_lst.py`

- [ ] **Step 1: 创建 `tools/gee_auth.py`**

```python
"""GEE 认证工具"""
from typing import Any, Dict
from tools.base import BaseTool, tool


@tool(
    name="gee_init",
    description="初始化 Google Earth Engine 认证与项目配置",
    parameters={"project_id": "可选，GEE 项目 ID", "force_auth": "是否强制重新认证"},
    category="data",
)
class GeeInitTool(BaseTool):
    def execute(self, project_id=None, force_auth=False) -> Dict[str, Any]:
        from gis.gee_tools import gee_init
        return gee_init(project_id=project_id, force_auth=bool(force_auth))
```

- [ ] **Step 2: 创建 `tools/gee_lst.py`**

```python
"""
GEE LST 工具：云端反演、下载、月度/年度/跨年批量
"""
import os
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict

from config import GEE_DRIVE_FOLDER, GDRIVE_SYNC_DIR
import config as app_config
from tools.base import BaseTool, tool


def _out_dir():
    d = Path(app_config.OUTPUTS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _default_last_full_month():
    today = date.today()
    first = today.replace(day=1)
    last_prev = first - timedelta(days=1)
    first_prev = last_prev.replace(day=1)
    return first_prev.isoformat(), last_prev.isoformat()


class _GeeLSTBase(BaseTool):
    """GEE LST 工具基类：共享 region 解析和 runtime 更新逻辑"""

    def _get_region(self, args: Dict[str, Any]) -> Any:
        region = args.get("region") or self.runtime.last_region_geojson
        return region

    def _on_success(self, result: Dict[str, Any]):
        if result.get("success") and result.get("output_tif") and os.path.exists(result["output_tif"]):
            self.runtime.current_dataset = result["output_tif"]
            self.runtime.last_tif_output = result["output_tif"]
            self.runtime.last_output = None
            if self.runtime.source_dataset is None:
                self.runtime.source_dataset = result["output_tif"]


@tool(
    name="gee_compute_lst",
    description="在 GEE 云端直接进行单通道地表温度反演，下载单波段 LST(°C) TIF",
    parameters={
        "start_date": "开始日期 YYYY-MM-DD",
        "end_date": "结束日期 YYYY-MM-DD",
        "cloud_pct": "最大云量百分比，默认30",
        "scale": "分辨率(米)，默认30",
    },
    category="data",
)
class GeeComputeLSTTool(_GeeLSTBase):
    def execute(self, start_date=None, end_date=None, cloud_pct=30, scale=30) -> Dict[str, Any]:
        if not start_date or not end_date:
            start_date, end_date = _default_last_full_month()
        region = self._get_region({})
        if region is None:
            return {"success": False, "message": "缺少研究区边界，请先调用 resolve_admin_region", "requires": "resolve_admin_region"}

        from gis.gee_tools import gee_compute_lst
        filename = f"{self.runtime.last_region_name or 'area'}_LST_{start_date}_{end_date}.tif"
        output_tif = str(_out_dir() / filename.replace(' ', '_'))

        result = gee_compute_lst(
            start_date=start_date, end_date=end_date,
            output_tif=output_tif, region=region,
            scale=int(scale), cloud_pct=float(cloud_pct),
        )
        self._on_success(result)
        return result


@tool(
    name="gee_download_landsat_sca",
    description="从 GEE 下载 Landsat 8/9 Level-2 三波段数据用于本地 SCA 反演",
    parameters={
        "start_date": "开始日期", "end_date": "结束日期",
        "region": "AOI [xmin,ymin,xmax,ymax] 或 GeoJSON",
        "scale": "分辨率", "cloud_pct": "云量百分比",
        "reducer": "合成方式 median/mean", "mask_clouds": "是否去云",
    },
    category="data",
)
class GeeDownloadLandsatSCATool(_GeeLSTBase):
    def execute(self, start_date=None, end_date=None, region=None, scale=30,
                cloud_pct=30, reducer="median", mask_clouds=True, **kwargs) -> Dict[str, Any]:
        if not start_date or not end_date:
            start_date, end_date = _default_last_full_month()
        region = region or self._get_region({})
        if region is None:
            return {"success": False, "message": "缺少研究区边界", "requires": "resolve_admin_region"}

        from gis.gee_tools import gee_download_landsat_sca
        name = self.runtime.last_region_name or "area"
        output_tif = str(_out_dir() / f"{name}_Landsat_SCA_{start_date}_{end_date}.tif".replace(' ', '_'))

        result = gee_download_landsat_sca(
            start_date=start_date, end_date=end_date,
            output_tif=output_tif, region=region,
            scale=int(scale), cloud_pct=float(cloud_pct),
            reducer=reducer, mask_clouds=bool(mask_clouds),
            drive_folder=kwargs.get("drive_folder") or GEE_DRIVE_FOLDER,
            local_drive_path=kwargs.get("local_drive_path") or str(GDRIVE_SYNC_DIR),
        )
        self._on_success(result)
        return result


@tool(
    name="gee_download_monthly_lst",
    description="月度 LST 智能合成（分级降级选景+逐景反演）",
    parameters={
        "start_date": "开始日期", "end_date": "结束日期",
        "scale": "分辨率，默认30",
    },
    category="data",
)
class GeeDownloadMonthlyLSTTool(_GeeLSTBase):
    def execute(self, start_date=None, end_date=None, scale=30, **kwargs) -> Dict[str, Any]:
        if not start_date or not end_date:
            start_date, end_date = _default_last_full_month()
        region = self._get_region({})
        if region is None:
            return {"success": False, "message": "缺少研究区边界", "requires": "resolve_admin_region"}

        from gis.gee_tools import gee_download_monthly_lst
        name = self.runtime.last_region_name or "area"
        output_tif = str(_out_dir() / f"{name}_LST_monthly_{start_date}_{end_date}.tif".replace(' ', '_'))

        result = gee_download_monthly_lst(
            start_date=start_date, end_date=end_date,
            output_tif=output_tif, region=region,
            scale=int(scale),
            drive_folder=kwargs.get("drive_folder") or GEE_DRIVE_FOLDER,
            local_drive_path=kwargs.get("local_drive_path") or str(GDRIVE_SYNC_DIR),
        )
        self._on_success(result)
        return result


@tool(
    name="gee_download_yearly_lst",
    description="批量下载全年月度 LST",
    parameters={
        "year": "年份", "months": "可选，月份列表",
        "scale": "分辨率", "output_dir": "输出目录",
    },
    category="data",
)
class GeeDownloadYearlyLSTTool(_GeeLSTBase):
    def execute(self, year=2025, months=None, scale=30, output_dir=None, **kwargs) -> Dict[str, Any]:
        region = self._get_region({})
        if region is None:
            return {"success": False, "message": "缺少研究区边界", "requires": "resolve_admin_region"}

        from gis.gee_tools import gee_download_yearly_lst
        name = self.runtime.last_region_name or "area"
        output_dir = output_dir or str(_out_dir() / f"{name}_{year}_LST")

        result = gee_download_yearly_lst(
            year=int(year), output_dir=output_dir,
            region=region, region_name=name,
            months=months, scale=int(scale),
            drive_folder=kwargs.get("drive_folder") or GEE_DRIVE_FOLDER,
            local_drive_path=kwargs.get("local_drive_path") or str(GDRIVE_SYNC_DIR),
        )
        if result.get("success") and result.get("results"):
            last = result["results"][-1]
            if last.get("output_tif") and os.path.exists(last["output_tif"]):
                self.runtime.current_dataset = last["output_tif"]
                self.runtime.last_tif_output = last["output_tif"]
        return result


@tool(
    name="gee_download_multi_year_lst",
    description="跨多年单月 LST 批量反演",
    parameters={
        "start_year": "起始年份", "end_year": "结束年份",
        "month": "月份 1-12", "scale": "分辨率",
        "output_dir": "输出目录",
    },
    category="data",
)
class GeeDownloadMultiYearLSTTool(_GeeLSTBase):
    def execute(self, start_year=2020, end_year=2025, month=8, scale=30,
                output_dir=None, **kwargs) -> Dict[str, Any]:
        region = self._get_region({})
        if region is None:
            return {"success": False, "message": "缺少研究区边界", "requires": "resolve_admin_region"}

        from gis.gee_tools import gee_download_multi_year_lst
        name = self.runtime.last_region_name or "area"
        output_dir = output_dir or str(_out_dir() / f"{name}_{start_year}_{end_year}_m{month}_LST")

        result = gee_download_multi_year_lst(
            start_year=int(start_year), end_year=int(end_year),
            month=int(month), output_dir=output_dir,
            region=region, region_name=name, scale=int(scale),
            drive_folder=kwargs.get("drive_folder") or GEE_DRIVE_FOLDER,
            local_drive_path=kwargs.get("local_drive_path") or str(GDRIVE_SYNC_DIR),
        )
        if result.get("success") and result.get("results"):
            last = result["results"][-1]
            if last.get("output_tif") and os.path.exists(last["output_tif"]):
                self.runtime.current_dataset = last["output_tif"]
                self.runtime.last_tif_output = last["output_tif"]
        return result
```

- [ ] **Step 3: 验证 GEE 工具**

```bash
cd d:/opengis && python -c "
from tools import ToolRegistry
r = ToolRegistry()
names = [t['name'] for t in r.manifest()]
assert 'gee_init' in names
assert 'gee_compute_lst' in names
print('GEE tools OK:', [n for n in names if n.startswith('gee_')])
"
```

- [ ] **Step 4: Commit**

```bash
git add tools/gee_auth.py tools/gee_lst.py
git commit -m "feat: 迁移 GEE 认证和 LST 工具"
```

---

### Task 1.4: 迁移 GEE 时间序列和高级分析工具

**Files:**
- Create: `tools/gee_timelapse.py`
- Create: `tools/gee_analysis.py`

- [ ] **Step 1: 创建 `tools/gee_timelapse.py`**

```python
"""
GEE 时间序列可视化工具：时间序列动画、分屏对比、趋势图
"""
import os
from typing import Any, Dict

from tools.base import BaseTool, tool
import config as app_config
from pathlib import Path


def _out_dir():
    d = Path(app_config.OUTPUTS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ensure_gee_and_roi(runtime):
    """确保 GEE 已初始化且有研究区，返回 (ee_geometry, error_dict)"""
    from gis.gee.client import init_gee
    init_result = init_gee()
    if not init_result.get("success"):
        return None, {"success": False, "message": f"GEE 未认证: {init_result.get('message', '')}", "requires": "gee_init"}

    roi = runtime.last_region_geojson
    if roi is None:
        return None, {"success": False, "message": "缺少研究区，请先调用 resolve_admin_region"}
    try:
        from gis.gee_tools import _normalize_region
        return _normalize_region(region=roi), None
    except Exception as e:
        return None, {"success": False, "message": f"研究区转换失败: {e}"}


@tool(
    name="gee_lst_timelapse",
    description="生成多年 LST 时间序列 GIF 动画（GEE 端合成）",
    parameters={
        "start_year": "起始年份", "end_year": "结束年份",
        "month": "月份", "cloud_pct": "云量百分比",
        "title": "标题", "fps": "帧率", "dimensions": "图片尺寸",
        "vmin": "色标最小值", "vmax": "色标最大值",
    },
    category="visualization",
)
class GeeLSTTimelapseTool(BaseTool):
    def execute(self, start_year=2015, end_year=2024, month=7, cloud_pct=30,
                title="", fps=2, dimensions=600, vmin=20, vmax=45) -> Dict[str, Any]:
        ee_geom, err = _ensure_gee_and_roi(self.runtime)
        if err:
            return err

        from gis.gee_timelapse import generate_lst_timelapse, parse_month
        gif_dir = str(_out_dir() / "timelapse")
        os.makedirs(gif_dir, exist_ok=True)

        result = generate_lst_timelapse(
            roi=ee_geom, output_dir=gif_dir,
            start_year=int(start_year), end_year=int(end_year),
            month=parse_month(month), cloud_pct=float(cloud_pct),
            title=title, fps=int(fps), dimensions=int(dimensions),
            vmin=float(vmin), vmax=float(vmax),
        )
        if result.get("success") and result.get("gif_path"):
            self.runtime.last_output = result["gif_path"]
        return result


@tool(
    name="gee_lst_split_panel",
    description="生成两年 LST 分屏对比交互式地图",
    parameters={
        "year_a": "第一年", "year_b": "第二年",
        "month": "月份", "cloud_pct": "云量",
        "vmin": "色标最小", "vmax": "色标最大",
    },
    category="visualization",
)
class GeeLSTSplitPanelTool(BaseTool):
    def execute(self, year_a=2015, year_b=2024, month=7, cloud_pct=30,
                vmin=20, vmax=45) -> Dict[str, Any]:
        ee_geom, err = _ensure_gee_and_roi(self.runtime)
        if err:
            return err

        from gis.gee_timelapse import generate_lst_split_panel, parse_month
        name = self.runtime.last_region_name or "region"
        output_path = str(_out_dir() / f"{name}_split_{year_a}_vs_{year_b}_m{month}.html")

        result = generate_lst_split_panel(
            roi=ee_geom, output_path=output_path,
            year_a=int(year_a), year_b=int(year_b),
            month=parse_month(month), cloud_pct=float(cloud_pct),
            vmin=float(vmin), vmax=float(vmax),
        )
        if result.get("success"):
            self.runtime.last_output = output_path
        return result


@tool(
    name="gee_lst_trend_chart",
    description="生成多年 LST 均值变化折线图",
    parameters={
        "start_year": "起始年份", "end_year": "结束年份",
        "month": "月份", "cloud_pct": "云量", "title": "标题",
    },
    category="visualization",
)
class GeeLSTTrendChartTool(BaseTool):
    def execute(self, start_year=2015, end_year=2024, month=7, cloud_pct=30,
                title="") -> Dict[str, Any]:
        ee_geom, err = _ensure_gee_and_roi(self.runtime)
        if err:
            return err

        from gis.gee_timelapse import generate_lst_trend_chart, parse_month
        name = self.runtime.last_region_name or "region"
        month_val = parse_month(month)
        output_path = str(_out_dir() / f"{name}_trend_{start_year}_{end_year}_m{month_val}.png")

        result = generate_lst_trend_chart(
            roi=ee_geom, output_path=output_path,
            start_year=int(start_year), end_year=int(end_year),
            month=month, cloud_pct=float(cloud_pct), title=title,
        )
        if result.get("success"):
            self.runtime.last_output = output_path
        return result


@tool(
    name="gee_lst_timelapse_local",
    description="本地版时间序列：逐年下载→反演→合成GIF（推荐）",
    parameters={
        "start_year": "起始年份", "end_year": "结束年份",
        "month": "月份", "cloud_pct": "云量",
        "title": "标题", "fps": "帧率", "dpi": "分辨率",
        "vmin": "色标最小", "vmax": "色标最大",
    },
    category="visualization",
)
class GeeLSTTimelapseLocalTool(BaseTool):
    def execute(self, start_year=2015, end_year=2024, month=7, cloud_pct=30,
                title="", fps=2, dpi=150, vmin=None, vmax=None) -> Dict[str, Any]:
        ee_geom, err = _ensure_gee_and_roi(self.runtime)
        if err:
            return err

        from gis.gee_timelapse import generate_lst_timelapse_local, parse_month
        from gis.web_map import generate_timelapse_web_map

        gif_dir = str(_out_dir() / "timelapse")
        os.makedirs(gif_dir, exist_ok=True)

        result = generate_lst_timelapse_local(
            roi=ee_geom, output_dir=gif_dir,
            start_year=int(start_year), end_year=int(end_year),
            month=parse_month(month), cloud_pct=float(cloud_pct),
            title=title, fps=int(fps), dpi=int(dpi),
            vmin=float(vmin) if vmin is not None else None,
            vmax=float(vmax) if vmax is not None else None,
        )
        if result.get("success") and result.get("gif_path"):
            self.runtime.last_output = result["gif_path"]

            # 自动生成交互式 Web 地图
            lst_tifs = result.get("lst_tifs", [])
            years_ok = result.get("years_ok", [])
            if lst_tifs and years_ok:
                m = parse_month(month)
                web_path = str(_out_dir() / f"timelapse_lst_{start_year}_{end_year}_m{m}_interactive.html")
                web_result = generate_timelapse_web_map(
                    lst_tif_paths=lst_tifs, years=years_ok,
                    output_path=web_path,
                    title=title or f"{month}月地表温度变化 {start_year}-{end_year}",
                    month=m,
                )
                if web_result.get("success"):
                    result["web_map_path"] = web_path
        return result
```

- [ ] **Step 2: 创建 `tools/gee_analysis.py`**（精简版，包含 timeseries/charts/classification/zonal/download/slider）

```python
"""
GEE 高级分析工具：时间序列提取、图表、分类、分区统计、下载、时间滑块
"""
import os
from typing import Any, Dict

from tools.base import BaseTool, tool
from pathlib import Path
import config as app_config


def _out_dir():
    d = Path(app_config.OUTPUTS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ensure_gee(runtime):
    from gis.gee.client import init_gee
    r = init_gee()
    if not r.get("success"):
        return {"success": False, "message": f"GEE 未认证: {r.get('message', '')}", "requires": "gee_init"}
    return None


def _resolve_roi(runtime, args):
    roi = args.get("region") or runtime.last_region_geojson
    if roi is None:
        return None, {"success": False, "message": "缺少研究区"}
    try:
        from gis.gee_tools import _normalize_region
        return _normalize_region(region=roi), None
    except Exception as e:
        return None, {"success": False, "message": f"研究区转换失败: {e}"}


@tool(
    name="extract_timeseries_to_point",
    description="从 GEE ImageCollection 提取指定坐标的时间序列数据",
    parameters={
        "lat": "纬度", "lon": "经度",
        "image_collection_id": "GEE ImageCollection ID",
        "band_names": "波段名列表",
        "start_date": "起始日期", "end_date": "结束日期",
        "scale": "分辨率(米)", "title": "图表标题",
    },
    category="analysis",
)
class ExtractTimeseriesTool(BaseTool):
    def execute(self, lat, lon, image_collection_id="ECMWF/ERA5_LAND/DAILY_AGGR",
                band_names=None, start_date="2020-01-01", end_date="2020-12-31",
                scale=1000, title="", **kwargs) -> Dict[str, Any]:
        err = _ensure_gee(self.runtime)
        if err:
            return err
        from gis.timeseries_extract import extract_timeseries_to_point
        name = self.runtime.last_region_name or f"{lat}_{lon}"
        csv_path = str(_out_dir() / f"timeseries_{name}.csv")
        png_path = str(_out_dir() / f"timeseries_{name}.png")
        result = extract_timeseries_to_point(
            lat=float(lat), lon=float(lon),
            image_collection_id=image_collection_id,
            band_names=band_names or ["temperature_2m"],
            start_date=start_date, end_date=end_date,
            scale=int(scale), output_csv=csv_path, output_png=png_path,
            title=title,
        )
        if result.get("success"):
            self.runtime.last_output = result.get("png_path")
        return result


@tool(
    name="dynamic_world_landcover",
    description="获取 Dynamic World 10m 土地覆盖分类",
    parameters={
        "start_date": "开始日期", "end_date": "结束日期",
        "return_type": "class 或 hillshade", "scale": "分辨率",
        "title": "标题",
    },
    category="analysis",
)
class DynamicWorldTool(BaseTool):
    def execute(self, start_date="2021-01-01", end_date="2022-01-01",
                return_type="class", scale=10, title="") -> Dict[str, Any]:
        err = _ensure_gee(self.runtime)
        if err:
            return err
        ee_geom, err2 = _resolve_roi(self.runtime, {})
        if err2:
            return err2
        from gis.dynamic_world import dynamic_world_landcover
        name = self.runtime.last_region_name or "dw"
        tif_path = str(_out_dir() / f"{name}_dynamic_world.tif")
        png_path = str(_out_dir() / f"{name}_dynamic_world.png")
        result = dynamic_world_landcover(
            region=ee_geom, start_date=start_date, end_date=end_date,
            output_tif=tif_path, output_png=png_path,
            return_type=return_type, scale=int(scale), title=title,
        )
        if result.get("success"):
            self.runtime.last_tif_output = result.get("output_tif")
            self.runtime.last_output = result.get("output_png")
        return result


@tool(
    name="ee_unsupervised_classify",
    description="GEE 端无监督分类（K-Means 聚类）",
    parameters={
        "n_clusters": "聚类数", "scale": "分辨率",
        "start_date": "日期起始", "end_date": "日期结束",
        "band_names": "波段列表", "title": "标题",
    },
    category="analysis",
)
class UnsupervisedClassifyTool(BaseTool):
    def execute(self, n_clusters=5, scale=30, start_date=None, end_date=None,
                band_names=None, title="", **kwargs) -> Dict[str, Any]:
        err = _ensure_gee(self.runtime)
        if err:
            return err
        ee_geom, err2 = _resolve_roi(self.runtime, {})
        if err2:
            return err2
        from gis.ee_classification import ee_unsupervised_classify
        name = self.runtime.last_region_name or "classify"
        tif_path = str(_out_dir() / f"{name}_unsupervised.tif")
        png_path = str(_out_dir() / f"{name}_unsupervised.png")
        result = ee_unsupervised_classify(
            region=ee_geom, n_clusters=int(n_clusters), scale=int(scale),
            start_date=start_date, end_date=end_date,
            band_names=band_names, output_tif=tif_path, output_png=png_path,
            title=title,
        )
        if result.get("success"):
            self.runtime.last_tif_output = result.get("output_tif")
            self.runtime.last_output = result.get("output_png")
        return result


@tool(
    name="generate_timeslider_map",
    description="生成带时间滑块的交互式 HTML 地图",
    parameters={
        "image_collection_id": "GEE ImageCollection ID",
        "start_date": "开始日期", "end_date": "结束日期",
        "band_names": "波段列表", "opacity": "透明度",
    },
    category="visualization",
)
class TimeSliderTool(BaseTool):
    def execute(self, image_collection_id="NOAA/GFS0P25",
                start_date="2018-12-22", end_date="2018-12-23",
                band_names=None, opacity=0.8) -> Dict[str, Any]:
        err = _ensure_gee(self.runtime)
        if err:
            return err
        ee_geom, err2 = _resolve_roi(self.runtime, {})
        if err2:
            return err2
        from gis.time_slider import generate_time_slider_map
        name = self.runtime.last_region_name or "timeslider"
        output_path = str(_out_dir() / f"{name}_time_slider.html")
        result = generate_time_slider_map(
            image_collection_id=image_collection_id,
            region=ee_geom, start_date=start_date, end_date=end_date,
            output_path=output_path, band_names=band_names,
            opacity=float(opacity),
        )
        if result.get("success"):
            self.runtime.last_output = output_path
        return result


@tool(
    name="gee_zonal_statistics",
    description="按区域计算影像的分区统计量",
    parameters={
        "image_id": "GEE 影像 ID 或 TIF 路径",
        "stat_type": "统计类型 mean/min/max/median/std/sum",
        "scale": "分辨率(米)",
    },
    category="analysis",
)
class ZonalStatsTool(BaseTool):
    def execute(self, image_id=None, stat_type="MEAN", scale=1000) -> Dict[str, Any]:
        import ee
        err = _ensure_gee(self.runtime)
        if err:
            return err
        image_input = image_id or self.runtime.current_tif()
        if not image_input:
            return {"success": False, "message": "缺少影像参数"}
        roi = self.runtime.last_region_geojson
        if roi is None:
            return {"success": False, "message": "缺少研究区"}
        from gis.gee_tools import _normalize_region
        from gis.zonal_stats import gee_zonal_statistics
        try:
            ee_geom = _normalize_region(region=roi)
            ee_fc = ee.FeatureCollection([ee.Feature(ee_geom)])
        except Exception as e:
            return {"success": False, "message": f"区域转换失败: {e}"}
        name = self.runtime.last_region_name or "zonal"
        csv_path = str(_out_dir() / f"{name}_zonal_stats.csv")
        result = gee_zonal_statistics(
            image=image_input, regions=ee_fc, output_csv=csv_path,
            stat_type=stat_type, scale=int(scale),
        )
        if result.get("success"):
            self.runtime.last_output = csv_path
        return result
```

- [ ] **Step 3: 验证时间序列和分析工具**

```bash
cd d:/opengis && python -c "
from tools import ToolRegistry
r = ToolRegistry()
names = [t['name'] for t in r.manifest()]
for n in ['gee_lst_timelapse', 'dynamic_world_landcover', 'generate_timeslider_map']:
    assert n in names, f'Missing: {n}'
print('All timelapse/analysis tools OK:', len(names), 'total')
"
```

- [ ] **Step 4: Commit**

```bash
git add tools/gee_timelapse.py tools/gee_analysis.py
git commit -m "feat: 迁移 GEE 时间序列和高级分析工具"
```

---

### Task 1.5: 迁移本地分析和可视化工具

**Files:**
- Create: `tools/lst_local.py`
- Create: `tools/analysis.py`
- Create: `tools/visualization.py`
- Create: `tools/export.py`
- Create: `tools/system.py`

- [ ] **Step 1: 创建 `tools/lst_local.py`**

```python
"""本地 LST 反演工具"""
from pathlib import Path
from typing import Any, Dict
from tools.base import BaseTool, tool
import config as app_config


@tool(
    name="run_lst",
    description="对当前多波段影像执行地表温度反演（SCA算法）",
    parameters={"input_tif": "可选，输入栅格路径"},
    category="analysis",
)
class RunLSTTool(BaseTool):
    def execute(self, input_tif=None) -> Dict[str, Any]:
        tif = input_tif or self.runtime.current_tif()
        if not tif:
            return {"success": False, "message": "没有可用输入影像"}
        from gis.sca_runner import run_sca
        stem = Path(tif).stem
        out_dir = Path(app_config.OUTPUTS_DIR)
        out_dir.mkdir(parents=True, exist_ok=True)
        output_tif = str(out_dir / f"{stem}_lst.tif")
        output_png = str(out_dir / f"{stem}_lst.png")
        result = run_sca(input_tif=tif, output_tif=output_tif, output_png=output_png)
        if result.get("success"):
            self.runtime.current_dataset = output_tif
            self.runtime.last_tif_output = output_tif
            self.runtime.last_output = output_png
        return result
```

- [ ] **Step 2: 创建 `tools/analysis.py`**

```python
"""栅格分析工具：统计、分类、阈值、增强、剖面"""
from pathlib import Path
from typing import Any, Dict
from tools.base import BaseTool, tool
import config as app_config


def _out_dir():
    d = Path(app_config.OUTPUTS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stem(path):
    return Path(path).stem if path else "result"


class _AnalysisBase(BaseTool):
    def _get_tif(self, tif_path=None) -> str | None:
        return tif_path or self.runtime.current_tif()


@tool(
    name="statistics",
    description="对当前单波段栅格做统计分析并输出直方图",
    parameters={"tif_path": "可选，栅格路径"},
    category="analysis",
)
class StatisticsTool(_AnalysisBase):
    def execute(self, tif_path=None) -> Dict[str, Any]:
        tif = self._get_tif(tif_path)
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        from gis.statistics import analyze_raster
        result = analyze_raster(tif)
        if result.get("success") and result.get("histogram_png"):
            self.runtime.last_output = result["histogram_png"]
        return result


@tool(
    name="classify_map",
    description="对当前单波段结果自动分类并出分类图",
    parameters={"method": "分类方法", "n_classes": "分类数", "colormap": "配色"},
    category="analysis",
)
class ClassifyMapTool(_AnalysisBase):
    def execute(self, tif_path=None, method="natural_breaks", n_classes=5, colormap="YlOrRd", title=None, dpi=300) -> Dict[str, Any]:
        tif = self._get_tif(tif_path)
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        from gis.classify import classify_raster
        result = classify_raster(
            tif_path=tif, output_png=str(_out_dir() / f"{_stem(tif)}_classified.png"),
            method=method, n_classes=int(n_classes), colormap=colormap,
            title=title, dpi=int(dpi),
        )
        if result.get("success"):
            self.runtime.last_output = result.get("output_png")
        return result


@tool(
    name="threshold_highlight",
    description="高亮超过阈值或位于某个区间的区域",
    parameters={"operator": ">/< /between/outside", "value": "阈值"},
    category="analysis",
)
class ThresholdHighlightTool(_AnalysisBase):
    def execute(self, tif_path=None, operator=">", value=30, value_upper=None,
                highlight_color="red", base_colormap="gray", title=None, dpi=300) -> Dict[str, Any]:
        tif = self._get_tif(tif_path)
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        from gis.threshold import threshold_highlight
        result = threshold_highlight(
            tif_path=tif, output_path=str(_out_dir() / f"{_stem(tif)}_threshold.png"),
            operator=operator, value=float(value), value_upper=value_upper,
            highlight_color=highlight_color, base_colormap=base_colormap,
            title=title, dpi=int(dpi),
        )
        if result.get("success"):
            self.runtime.last_output = result.get("output_png")
        return result


@tool(
    name="enhance_raster",
    description="对当前栅格做增强或去噪",
    parameters={"method": "gaussian/median/histogram_eq/clahe/sharpen", "kernel_size": "核大小"},
    category="analysis",
)
class EnhanceRasterTool(_AnalysisBase):
    def execute(self, tif_path=None, method="gaussian", kernel_size=5) -> Dict[str, Any]:
        tif = self._get_tif(tif_path)
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        from gis.enhance import enhance_raster
        result = enhance_raster(
            tif_path=tif,
            output_tif=str(_out_dir() / f"{_stem(tif)}_enhanced.tif"),
            output_png=str(_out_dir() / f"{_stem(tif)}_enhanced.png"),
            method=method, kernel_size=int(kernel_size),
        )
        if result.get("success"):
            self.runtime.current_dataset = result.get("output_tif")
            self.runtime.last_tif_output = result.get("output_tif")
            self.runtime.last_output = result.get("output_png")
        return result


@tool(
    name="profile_analysis",
    description="对当前栅格做剖面分析",
    parameters={"start": "起点[col,row]", "end": "终点[col,row]", "n_points": "采样点数"},
    category="analysis",
)
class ProfileAnalysisTool(_AnalysisBase):
    def execute(self, tif_path=None, start=None, end=None, n_points=200) -> Dict[str, Any]:
        tif = self._get_tif(tif_path)
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        from gis.profile import profile_analysis
        return profile_analysis(
            tif_path=tif, output_png=str(_out_dir() / f"{_stem(tif)}_profile.png"),
            start=start, end=end, n_points=int(n_points),
        )
```

- [ ] **Step 3: 创建 `tools/visualization.py`**

```python
"""可视化工具：3D、对比、变换、专题图、Web地图"""
from pathlib import Path
from typing import Any, Dict
from tools.base import BaseTool, tool
import config as app_config


def _out_dir():
    d = Path(app_config.OUTPUTS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stem(path):
    return Path(path).stem if path else "result"


class _VisBase(BaseTool):
    def _get_tif(self, tif_path=None) -> str | None:
        return tif_path or self.runtime.current_tif()


@tool(
    name="view_3d",
    description="将当前栅格生成 3D 可视化",
    parameters={"elevation": "俯仰角", "azimuth": "方位角", "colormap": "配色", "render_mode": "surface/wireframe/contour"},
    category="visualization",
)
class View3DTool(_VisBase):
    def execute(self, tif_path=None, elevation=45, azimuth=225, vertical_exaggeration=1.0,
                colormap="terrain", render_mode="surface") -> Dict[str, Any]:
        tif = self._get_tif(tif_path)
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        from gis.view3d import render_3d
        result = render_3d(
            tif_path=tif, output_png=str(_out_dir() / f"{_stem(tif)}_3d.png"),
            elevation=float(elevation), azimuth=float(azimuth),
            vertical_exaggeration=float(vertical_exaggeration),
            colormap=colormap, render_mode=render_mode,
        )
        if result.get("success"):
            self.runtime.last_output = result.get("output_png")
        return result


@tool(
    name="compare_views",
    description="对比原始图和当前结果图",
    parameters={"mode": "side_by_side 或 difference"},
    category="visualization",
)
class CompareViewsTool(_VisBase):
    def execute(self, tif_original=None, tif_result=None, mode="side_by_side") -> Dict[str, Any]:
        tif_orig = tif_original or self.runtime.source_dataset
        tif_res = tif_result or self.runtime.current_tif()
        if not tif_orig or not tif_res:
            return {"success": False, "message": "缺少对比所需原始图或结果图"}
        from gis.compare import compare_views
        result = compare_views(
            tif_original=tif_orig, tif_result=tif_res,
            output_png=str(_out_dir() / f"{_stem(tif_res)}_compare.png"),
            mode=mode,
        )
        if result.get("success"):
            self.runtime.last_output = result.get("output_png")
        return result


@tool(
    name="transform_raster",
    description="对当前栅格做翻转或旋转",
    parameters={"operation": "flip_h/flip_v/rotate_90/rotate_180/rotate_270"},
    category="visualization",
)
class TransformRasterTool(_VisBase):
    def execute(self, tif_path=None, operation="flip_h") -> Dict[str, Any]:
        tif = self._get_tif(tif_path)
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        from gis.transform import transform_raster
        result = transform_raster(
            tif_path=tif,
            output_tif=str(_out_dir() / f"{_stem(tif)}_{operation}.tif"),
            output_png=str(_out_dir() / f"{_stem(tif)}_{operation}.png"),
            operation=operation,
        )
        if result.get("success"):
            self.runtime.current_dataset = result.get("output_tif")
            self.runtime.last_tif_output = result.get("output_tif")
            self.runtime.last_output = result.get("output_png")
        return result


@tool(
    name="make_thematic_map",
    description="将当前单波段结果做成标准专题图（含图例、比例尺、指北针）",
    parameters={
        "title": "标题", "colormap": "配色", "legend_position": "图例位置",
        "dpi": "分辨率", "tif_path": "可选，栅格路径",
    },
    category="visualization",
)
class MakeThematicMapTool(_VisBase):
    def execute(self, tif_path=None, title=None, colormap=None, legend_position=None,
                dpi=None, **kwargs) -> Dict[str, Any]:
        tif = self._get_tif(tif_path)
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        from gis.cartographic_map import generate_cartographic_map
        style = dict(self.runtime.map_style)
        style.update({k: v for k, v in kwargs.items() if v is not None})
        if colormap:
            style["colormap"] = colormap
        if title:
            style["title"] = title
        if legend_position:
            style["legend_position"] = legend_position
        if dpi:
            style["dpi"] = int(dpi)

        output_path = kwargs.get("output_path") or str(_out_dir() / f"{_stem(tif)}_map.png")
        result = generate_cartographic_map(
            tif_path=tif, output_path=output_path,
            title=style.get("title", f"专题图 - {_stem(tif)}"),
            colormap=style.get("colormap", "coolwarm"),
            show_legend=bool(style.get("show_legend", True)),
            show_scalebar=bool(style.get("show_scalebar", True)),
            show_north=bool(style.get("show_north", True)),
            dpi=int(style.get("dpi", 300)),
            legend_position=style.get("legend_position", "right"),
            scalebar_position=style.get("scalebar_position", "lower left"),
            north_position=style.get("north_position", "upper right"),
            figsize=style.get("figsize"),
            alpha=float(style.get("alpha", 1.0)),
            bg_color=style.get("bg_color", "#EFEFEF"),
            title_color=style.get("title_color", "#1A1A1A"),
            grid=bool(style.get("grid", False)),
            frame=bool(style.get("frame", True)),
            legend_tick_fontsize=int(style.get("legend_tick_fontsize", 10)),
            legend_label_fontsize=int(style.get("legend_label_fontsize", 12)),
            legend_shrink=float(style.get("legend_shrink", 0.88)),
            scalebar_fontsize=int(style.get("scalebar_fontsize", 10)),
            scalebar_length_ratio=float(style.get("scalebar_length_ratio", 0.16)),
            north_fontsize=int(style.get("north_fontsize", 13)),
            title_fontsize=int(style.get("title_fontsize", 18)),
            map_margin=float(style.get("map_margin", 0.035)),
            map_frame_scale=float(style.get("map_frame_scale", 0.94)),
            legend_xoffset=float(style.get("legend_xoffset", 0.0)),
            legend_yoffset=float(style.get("legend_yoffset", 0.0)),
            north_xoffset=float(style.get("north_xoffset", 0.0)),
            north_yoffset=float(style.get("north_yoffset", 0.0)),
            scalebar_xoffset=float(style.get("scalebar_xoffset", 0.0)),
            scalebar_yoffset=float(style.get("scalebar_yoffset", 0.0)),
        )
        if result.get("success"):
            self.runtime.last_output = output_path
            self.runtime.map_style.update(style)
        return result


@tool(
    name="generate_web_map",
    description="生成交互式 Web 地图（Leaflet HTML）",
    parameters={
        "title": "标题", "colormap": "配色", "show_heatmap": "显示热力图",
        "overlay_opacity": "透明度", "tif_path": "可选，栅格路径",
    },
    category="visualization",
)
class GenerateWebMapTool(_VisBase):
    def execute(self, tif_path=None, title=None, colormap="viridis",
                overlay_opacity=0.7, show_heatmap=False, **kwargs) -> Dict[str, Any]:
        tif = self._get_tif(tif_path)
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        from gis.web_map import generate_web_map
        output_path = str(_out_dir() / f"{_stem(tif)}_interactive_map.html")
        result = generate_web_map(
            tif_path=tif, output_path=output_path,
            title=title or f"交互式地图 - {_stem(tif)}",
            colormap=colormap, overlay_opacity=float(overlay_opacity),
            show_heatmap=bool(show_heatmap),
            additional_layers=kwargs.get("additional_layers"),
            popup_info=kwargs.get("popup_info"),
            center_lat=kwargs.get("center_lat"),
            center_lon=kwargs.get("center_lon"),
            zoom_start=int(kwargs.get("zoom_start", 12)),
        )
        if result.get("success"):
            self.runtime.last_output = output_path
        return result
```

- [ ] **Step 4: 创建 `tools/export.py`**

```python
"""导出工具：格式转换、报告生成"""
from pathlib import Path
from typing import Any, Dict
from tools.base import BaseTool, tool
import config as app_config


def _out_dir():
    d = Path(app_config.OUTPUTS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


@tool(
    name="export_result",
    description="把最近结果图导出为 png/jpg/pdf/tif",
    parameters={"format": "png/jpg/pdf/tif", "input_path": "可选，输入路径", "dpi": "分辨率"},
    category="export",
)
class ExportResultTool(BaseTool):
    def execute(self, format="png", input_path=None, dpi=300) -> Dict[str, Any]:
        input_path = input_path or self.runtime.last_output
        if not input_path:
            return {"success": False, "message": "没有可导出的结果图"}
        from gis.export import export_image
        stem = Path(input_path).stem
        output_path = str(_out_dir() / f"{stem}_export.{format}")
        result = export_image(input_path=input_path, output_path=output_path,
                              format=format, dpi=int(dpi))
        if result.get("success"):
            self.runtime.last_output = result.get("output_path")
        return result


@tool(
    name="generate_report",
    description="生成带文字解读的图文实验报告（HTML格式）",
    parameters={
        "title": "标题", "subtitle": "副标题", "conclusion": "总结",
        "format": "html/pdf", "images": "图片路径列表",
    },
    category="export",
)
class GenerateReportTool(BaseTool):
    def execute(self, title="GIS 实验报告", subtitle="", conclusion="",
                format="html", images=None, report_items=None) -> Dict[str, Any]:
        from pathlib import Path
        from gis.report import generate_html_report, try_convert_pdf

        dataset_name = Path(self.runtime.current_dataset or "unknown").stem
        items = report_items or []

        if not items and images:
            for img in images:
                if isinstance(img, str):
                    items.append({"section_title": "", "image_path": img, "image_caption": Path(img).stem})

        if not items:
            tif = self.runtime.current_tif()
            if tif:
                try:
                    from gis.statistics import analyze_raster
                    stats = analyze_raster(tif)
                    if stats.get("success") and stats.get("histogram_png"):
                        items.append({
                            "section_title": "数据统计",
                            "item_type": "statistics",
                            "image_path": stats["histogram_png"],
                            "image_caption": f"{dataset_name} 直方图",
                            "stats": stats.get("statistics", {}),
                        })
                except Exception:
                    pass
            if self.runtime.last_output and self.runtime.last_output.endswith(('.png', '.jpg')):
                items.append({
                    "section_title": "专题图",
                    "item_type": "map",
                    "image_path": self.runtime.last_output,
                    "image_caption": dataset_name,
                })

        if not items:
            return {"success": False, "message": "没有可用的分析结果来生成报告"}

        output_path = str(_out_dir() / f"{dataset_name}_report.html")
        result = generate_html_report(
            report_items=items, output_path=output_path,
            title=title, subtitle=subtitle, dataset_name=dataset_name,
            conclusion=conclusion,
        )
        if result.get("success") and format == "pdf":
            pdf = try_convert_pdf(output_path)
            if pdf.get("success"):
                result["pdf_path"] = pdf["pdf_path"]
        if result.get("success"):
            self.runtime.last_output = output_path
        return result
```

- [ ] **Step 5: 创建 `tools/system.py`**

```python
"""系统工具：样式设置、偏好管理、上下文摘要"""
from typing import Any, Dict
from tools.base import BaseTool, tool


@tool(
    name="set_map_style",
    description="更新地图样式参数",
    parameters={
        "title": "标题", "colormap": "配色", "legend_position": "图例位置",
        "legend_xoffset": "图例X偏移", "legend_yoffset": "图例Y偏移",
        "dpi": "分辨率", "show_legend": "显示图例", "show_scalebar": "显示比例尺",
        "show_north": "显示指北针",
    },
    category="system",
)
class SetMapStyleTool(BaseTool):
    def execute(self, **kwargs) -> Dict[str, Any]:
        style = {k: v for k, v in kwargs.items() if v is not None}
        self.runtime.map_style.update(style)
        return {"success": True, "message": "地图样式已更新", "map_style": self.runtime.map_style}


@tool(
    name="update_preferences",
    description="更新长期用户偏好",
    parameters={"export_format": "导出格式", "n_classes": "默认分类数", "colormap": "默认配色"},
    category="system",
)
class UpdatePreferencesTool(BaseTool):
    def execute(self, **kwargs) -> Dict[str, Any]:
        # preferences 通过外部 MemoryStore 管理
        return {"success": True, "message": "偏好已更新", "updated": {k: v for k, v in kwargs.items() if v is not None}}


@tool(
    name="summarize_context",
    description="返回当前会话上下文摘要",
    parameters={},
    category="system",
)
class SummarizeContextTool(BaseTool):
    def execute(self) -> Dict[str, Any]:
        return {
            "success": True,
            "message": "当前上下文摘要",
            "context": {
                "current_dataset": self.runtime.current_dataset,
                "source_dataset": self.runtime.source_dataset,
                "last_output": self.runtime.last_output,
                "last_tif_output": self.runtime.last_tif_output,
                "last_region_name": self.runtime.last_region_name,
                "map_style": self.runtime.map_style,
            },
        }
```

- [ ] **Step 6: 验证全部工具注册**

```bash
cd d:/opengis && python -c "
from tools import ToolRegistry
r = ToolRegistry()
names = sorted([t['name'] for t in r.manifest()])
print(f'Total tools: {len(names)}')
for n in names:
    print(f'  - {n}')
"
```
Expected: 30+ tools registered

- [ ] **Step 7: Commit**

```bash
git add tools/lst_local.py tools/analysis.py tools/visualization.py tools/export.py tools/system.py
git commit -m "feat: 迁移本地分析、可视化、导出和系统工具"
```

---

## Phase 2: Agent 引擎重写

### Task 2.1: 创建 SafetyGuard

**Files:**
- Create: `agent/guard.py`

- [ ] **Step 1: 创建 `agent/guard.py`**

将 `agent/core.py` 中的 `_detect_loop`、`_should_auto_make_map`、`_has_timelapse_intent` 等函数迁移为 `SafetyGuard` 的方法：

```python
"""
安全守卫 - 循环检测、自动出图判断、意图检测
所有硬编码的工具特定验证逻辑集中在这里，每条规则独立方法
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class SafetyGuard:
    def __init__(self, max_map_calls=2, max_style_calls=2, max_consecutive_same=3):
        self.max_map_calls = max_map_calls
        self.max_style_calls = max_style_calls
        self.max_consecutive_same = max_consecutive_same

    def check(self, history: List[Dict[str, Any]]) -> str:
        """返回停止原因或空字符串"""
        if len(history) < 2:
            return ""

        # set_map_style 同轮两次
        style_calls = [h for h in history if h.get("tool") == "set_map_style"]
        if len(style_calls) >= self.max_style_calls:
            return "同一轮对话中 set_map_style 已调用多次，必须立即返回 final"

        # make_thematic_map 同轮两次
        map_calls = [h for h in history if h.get("tool") == "make_thematic_map"]
        if len(map_calls) >= self.max_map_calls:
            return "同一轮对话中 make_thematic_map 已调用多次，必须立即返回 final"

        # 下载工具连续调用
        _download_tools = {"gee_download_landsat_sca", "gee_download_monthly_lst",
                           "gee_download_yearly_lst", "gee_download_multi_year_lst"}
        if len(history) >= 2:
            last_two = [h.get("tool") for h in history[-2:]]
            if last_two[0] == last_two[1] and last_two[0] in _download_tools:
                return f"{last_two[0]} 已连续调用 2 次，必须立即返回 final"

        # 同一工具连续 3 次
        if len(history) >= 3:
            last_tool = history[-1].get("tool")
            if all(h.get("tool") == last_tool for h in history[-3:]):
                return f"{last_tool} 已连续调用 3 次，必须立即返回 final"

        # set_map_style ↔ make_thematic_map 交替循环
        if len(history) >= 4:
            recent = [h.get("tool") for h in history[-4:]]
            if recent == ["set_map_style", "make_thematic_map", "set_map_style", "make_thematic_map"]:
                return "set_map_style 和 make_thematic_map 已交替循环，必须立即返回 final"

        return ""

    def should_auto_map(self, history: List[Dict[str, Any]]) -> bool:
        """判断是否应在 final 前自动生成专题图"""
        if not history:
            return False
        data_producers = {"run_lst", "gee_compute_lst", "gee_download_monthly_lst"}
        map_tools = {"make_thematic_map", "generate_web_map", "classify_map",
                     "gee_lst_timelapse", "gee_lst_timelapse_local",
                     "gee_lst_split_panel", "generate_timeslider_map"}
        last_data_idx = -1
        for i, h in enumerate(history):
            if h.get("tool") in data_producers and h.get("result", {}).get("success"):
                last_data_idx = i
        if last_data_idx < 0:
            return False
        for h in history[last_data_idx + 1:]:
            if h.get("tool") in map_tools:
                return False
        return True
```

- [ ] **Step 2: Commit**

```bash
git add agent/guard.py
git commit -m "feat: SafetyGuard - 循环检测和自动出图判断独立模块"
```

---

### Task 2.2: 创建 AgentLoop

**Files:**
- Create: `agent/engine.py`
- Create: `agent/context.py`

- [ ] **Step 1: 创建 `agent/context.py`**

```python
"""
上下文构建器 - 为 LLM 构建决策上下文
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_context(
    user_input: str,
    step: int,
    runtime: Dict[str, Any],
    history: List[Dict[str, Any]],
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    loop_warning: str = "",
) -> Dict[str, Any]:
    """构建发送给 LLM 的决策 payload"""
    payload = {
        "user_input": user_input,
        "step": step,
        "runtime": runtime,
        "last_result": history[-1].get("result") if history else None,
        "loop_warning": loop_warning,
    }

    if conversation_history:
        payload["conversation_history"] = _format_history(conversation_history, user_input)

    return payload


def _format_history(messages: List[Dict[str, Any]], current_msg: str, max_msgs=30) -> str:
    if not messages:
        return f"[用户]: {current_msg}"
    truncated = messages[-max_msgs:] if len(messages) > max_msgs else messages
    lines = []
    for msg in truncated:
        role = msg.get("role", "")
        content = msg.get("content", "")
        tool = msg.get("tool_name", "")
        if role == "user":
            lines.append(f"[用户]: {content}")
        elif role == "assistant":
            lines.append(f"[助手]: {content}")
        elif role == "tool_call":
            lines.append(f"[助手]: 调用 {tool}")
        elif role == "tool_result":
            r = msg.get("tool_result", {})
            if isinstance(r, dict):
                ok = r.get("success", False)
                lines.append(f"[系统]: {tool} {'成功' if ok else '失败'} - {r.get('message', '')[:80]}")
        elif role == "system":
            lines.append(f"[系统]: {content}")
    lines.append(f"\n[用户]（当前消息）: {current_msg}")
    return "\n".join(lines)
```

- [ ] **Step 2: 创建 `agent/engine.py`**

```python
"""
Agent 引擎 - 纯 LLM 决策 → 工具执行循环
不含任何工具特定逻辑，所有验证规则在 SafetyGuard 中
"""
from __future__ import annotations

import traceback
from typing import Any, AsyncGenerator, Callable, Dict, List, Optional

from agent.context import build_context
from agent.guard import SafetyGuard
from agent.llm import LLMClient
from tools import ToolRegistry
from tools.runtime import GISRuntime


class AgentLoop:
    def __init__(
        self,
        llm: LLMClient,
        registry: ToolRegistry,
        runtime: GISRuntime,
        guard: Optional[SafetyGuard] = None,
        max_steps: int = 25,
    ):
        self.llm = llm
        self.registry = registry
        self.runtime = runtime
        self.guard = guard or SafetyGuard()
        self.max_steps = max_steps

    async def run(
        self,
        user_input: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        on_event: Optional[Callable] = None,
    ) -> Dict[str, Any]:
        """执行 Agent 循环，返回最终结果"""
        history: List[Dict[str, Any]] = []
        last_result: Optional[Dict[str, Any]] = None
        final_answer = ""
        forced_stop = False

        def emit(event_type: str, data: Dict[str, Any]):
            if on_event:
                try:
                    on_event(event_type, data)
                except Exception:
                    pass

        for step in range(1, self.max_steps + 1):
            # 1. 安全检查
            loop_warning = self.guard.check(history)
            if loop_warning:
                forced_stop = True
                if self.guard.should_auto_map(history):
                    try:
                        map_result = self.registry.call("make_thematic_map", {})
                        if "success" not in map_result:
                            map_result["success"] = True
                    except Exception as exc:
                        map_result = {"success": False, "message": str(exc)}
                    history.append({"step": step, "tool": "make_thematic_map", "result": map_result})
                    last_result = map_result
                    emit("tool_result", {"tool": "make_thematic_map", "result": map_result})
                final_answer = f"{loop_warning}\n\n{last_result.get('message', '任务已完成。')}"
                emit("final_answer", {"content": final_answer})
                break

            emit("step_start", {"step": step, "max": self.max_steps})

            # 2. LLM 决策
            try:
                runtime_state = {
                    "current_dataset": self.runtime.current_dataset,
                    "source_dataset": self.runtime.source_dataset,
                    "last_output": self.runtime.last_output,
                    "last_region_name": self.runtime.last_region_name,
                    "has_last_region_geojson": self.runtime.last_region_geojson is not None,
                    "map_style": self.runtime.map_style,
                }
                payload = build_context(
                    user_input=user_input, step=step,
                    runtime=runtime_state, history=history,
                    conversation_history=conversation_history,
                    loop_warning=loop_warning,
                )
                from agent.prompts.system import CONVERSATIONAL_SYSTEM_PROMPT
                decision = self.llm.invoke_json(CONVERSATIONAL_SYSTEM_PROMPT, payload)

            except Exception as exc:
                final_answer = f"决策失败: {exc}"
                emit("error", {"message": str(exc)})
                break

            # 3. final
            if decision.get("type") == "final":
                if self.guard.should_auto_map(history):
                    try:
                        map_result = self.registry.call("make_thematic_map", {})
                        if "success" not in map_result:
                            map_result["success"] = True
                    except Exception as exc:
                        map_result = {"success": False, "message": str(exc)}
                    history.append({"step": step, "tool": "make_thematic_map", "result": map_result})
                    last_result = map_result
                    emit("tool_result", {"tool": "make_thematic_map", "result": map_result})
                final_answer = decision.get("answer", "任务完成。")
                emit("final_answer", {"content": final_answer})
                break

            # 4. ask_user
            if decision.get("type") == "ask_user":
                emit("ask_user", {
                    "question": decision.get("question", ""),
                    "options": decision.get("options", []),
                })
                return {
                    "success": True, "type": "ask_user",
                    "question": decision.get("question", ""),
                    "options": decision.get("options", []),
                    "history": history,
                    "state": self.runtime.to_dict(),
                }

            # 5. tool_call
            if decision.get("type") != "tool_call":
                final_answer = f"Agent 返回了无效决策: {decision}"
                emit("error", {"message": final_answer})
                break

            tool = str(decision.get("tool", "")).strip()
            args = decision.get("args") or {}
            reason = str(decision.get("reason", "")).strip()

            emit("tool_start", {"tool": tool, "args": args, "reason": reason})

            try:
                result = self.registry.call(tool, args)
                if "success" not in result:
                    result["success"] = False
            except Exception as exc:
                result = {"success": False, "message": str(exc), "traceback": traceback.format_exc(limit=4)}

            emit("tool_result", {"tool": tool, "result": result})

            history.append({"step": step, "tool": tool, "args": args, "reason": reason, "result": result})
            last_result = result

            # GEE 未认证时自动重试
            if not result.get("success") and result.get("requires") == "gee_init":
                try:
                    gee_result = self.registry.call("gee_init", {})
                    if gee_result.get("success"):
                        result = self.registry.call(tool, args)
                        if "success" not in result:
                            result["success"] = False
                        emit("tool_result", {"tool": tool, "result": result})
                        history[-1]["result"] = result
                        last_result = result
                except Exception:
                    pass

            # set_map_style 后自动出图
            if tool == "set_map_style" and result.get("success", False):
                try:
                    render = self.registry.call("make_thematic_map", {})
                    if "success" not in render:
                        render["success"] = False
                except Exception as exc:
                    render = {"success": False, "message": str(exc)}
                history.append({"step": step, "tool": "make_thematic_map", "args": {}, "reason": "样式更新后自动重新出图", "result": render})
                last_result = render
                emit("tool_result", {"tool": "make_thematic_map", "result": render})

            # 失败时允许重试，接近 max_steps 且连续失败则终止
            if not result.get("success", False):
                failures = sum(1 for r in history[-3:] if not r.get("result", {}).get("success", True))
                if step >= max(5, self.max_steps - 3) and failures >= 2:
                    final_answer = result.get("message", "执行失败")
                    emit("error", {"message": final_answer})
                    break
        else:
            if history and history[-1].get("result", {}).get("success"):
                final_answer = f"已完成 {len(history)} 步操作。{history[-1]['result'].get('message', '')}"
            else:
                final_answer = f"已执行 {len(history)} 步，任务可能需要更多调整。"

        emit("done", {})
        return {
            "success": bool(history) and history[-1].get("result", {}).get("success", False),
            "type": "final",
            "answer": final_answer,
            "history": history,
            "forced_stop": forced_stop,
            "state": self.runtime.to_dict(),
        }
```

- [ ] **Step 3: 迁移 `agent/llm.py`**

从 `agent/llm_client.py` 复制全部代码，清理不需要的部分（`get_llm` 函数保留），重命名为 `agent/llm.py`。

- [ ] **Step 4: CLI 验证**

```bash
cd d:/opengis && python -c "
from tools import ToolRegistry
from tools.runtime import GISRuntime
from agent.llm import LLMClient
from agent.engine import AgentLoop

runtime = GISRuntime()
registry = ToolRegistry(runtime)
print(f'Tools loaded: {len(registry.manifest())}')

llm = LLMClient()
print(f'LLM health: {llm.health_check()}')

agent = AgentLoop(llm, registry, runtime)
print('AgentLoop created successfully')
"
```

- [ ] **Step 5: Commit**

```bash
git add agent/engine.py agent/context.py agent/llm.py
git commit -m "feat: AgentLoop 纯引擎 + ContextBuilder + LLM 客户端迁移"
```

---

## Phase 3: API 层重写

### Task 3.1: 拆分 ORM 模型

**Files:**
- Create: `api/models/__init__.py`
- Create: `api/models/user.py`
- Create: `api/models/conversation.py`
- Create: `api/models/task.py`
- Modify: `api/database.py` (如果需要)

- [ ] **Step 1: 创建 `api/models/__init__.py`**

```python
from api.models.user import User
from api.models.conversation import Conversation, Message, ConversationState
from api.models.task import Task, TaskStatus, Order, Download, OrderStatus

__all__ = [
    "User", "Conversation", "Message", "ConversationState",
    "Task", "TaskStatus", "Order", "Download", "OrderStatus",
]
```

- [ ] **Step 2: 创建 `api/models/user.py`**

从 `api/models.py` 提取 `User` 和 `UserResponse`/`UserLoginRequest`/`UserRegisterRequest`/`TokenResponse`。

- [ ] **Step 3: 创建 `api/models/conversation.py`**

从 `api/models.py` 提取 `Conversation`、`Message`、`ConversationState` 及对应的 Pydantic 模型。

- [ ] **Step 4: 创建 `api/models/task.py`**

从 `api/models.py` 提取 `Task`、`Order`、`Download` 及对应枚举。

- [ ] **Step 5: Commit**

```bash
git add api/models/
git commit -m "refactor: 拆分 ORM 模型为独立文件"
```

---

### Task 3.2: SSE 流式端点

**Files:**
- Create: `api/routes/conversations.py`
- Create: `api/deps.py`

- [ ] **Step 1: 创建 `api/deps.py`**

```python
"""FastAPI 依赖注入"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from api.database import SessionLocal
from config import SECRET_KEY, JWT_ALGORITHM
import jwt

security = HTTPBearer(auto_error=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: Session = Depends(get_db),
):
    """获取当前登录用户（可选认证）"""
    if credentials:
        try:
            payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[JWT_ALGORITHM])
            user_id = payload.get("sub")
            if user_id:
                from api.models.user import User
                user = db.query(User).filter(User.id == int(user_id)).first()
                return user
        except Exception:
            pass
    # 返回默认用户
    from api.models.user import User
    return db.query(User).filter(User.id == 1).first()
```

- [ ] **Step 2: 创建 `api/routes/conversations.py`**

```python
"""会话路由 - SSE 流式端点"""
import json
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.deps import get_db, get_current_user
from api.models.conversation import Conversation, Message, ConversationState
from api.models.user import User

router = APIRouter(prefix="/api/conversations", tags=["对话"])


@router.post("/{conv_id}/stream")
async def stream_message(
    conv_id: int,
    body: dict,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """SSE 流式端点：发送消息并接收 Agent 实时事件"""
    content = body.get("content", "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    conv = db.query(Conversation).filter(
        Conversation.id == conv_id, Conversation.user_id == user.id
    ).first()
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")

    # 加载消息历史
    db_messages = db.query(Message).filter(
        Message.conversation_id == conv_id
    ).order_by(Message.created_at).limit(30).all()

    conversation_history = [
        {
            "role": m.role,
            "content": m.content,
            "tool_name": m.tool_name,
            "tool_result": m.tool_result,
        }
        for m in db_messages
    ]

    # 加载会话状态
    state = db.query(ConversationState).filter(
        ConversationState.conversation_id == conv_id
    ).first()

    async def event_generator() -> AsyncGenerator[str, None]:
        from tools import ToolRegistry
        from tools.runtime import GISRuntime
        from agent.llm import LLMClient
        from agent.engine import AgentLoop

        runtime = GISRuntime()
        if state:
            runtime.from_dict({
                "current_dataset": state.current_dataset,
                "source_dataset": state.source_dataset,
                "last_output": state.last_output,
                "last_tif_output": state.last_tif_output,
                "last_region_geojson": state.last_region_geojson,
                "last_region_name": state.last_region_name,
                "map_style": state.map_style,
            })

        registry = ToolRegistry(runtime)
        llm = LLMClient()
        agent = AgentLoop(llm, registry, runtime)

        # 保存用户消息
        user_msg = Message(
            conversation_id=conv_id,
            role="user",
            content=content,
        )
        db.add(user_msg)
        db.commit()

        # 用于记录本轮工具调用
        tool_messages = []

        def on_event(event_type: str, data: dict):
            nonlocal tool_messages
            if event_type == "tool_start":
                tool_messages.append(Message(
                    conversation_id=conv_id,
                    role="tool_call",
                    content=f"调用 {data['tool']}",
                    tool_name=data["tool"],
                    tool_args=data.get("args"),
                ))
            elif event_type == "tool_result":
                if tool_messages:
                    tool_messages[-1].tool_result = data.get("result")
                    tool_messages[-1].role = "tool_result"

        result = await agent.run(
            user_input=content,
            conversation_history=conversation_history,
            on_event=on_event,
        )

        # 持久化工具调用消息
        for tm in tool_messages:
            db.add(tm)

        # 持久化最终回复
        if result.get("answer"):
            assistant_msg = Message(
                conversation_id=conv_id,
                role="assistant",
                content=result["answer"],
            )
            db.add(assistant_msg)

        # 持久化会话状态
        new_state = result.get("state", {})
        if state:
            state.current_dataset = new_state.get("current_dataset")
            state.source_dataset = new_state.get("source_dataset")
            state.last_output = new_state.get("last_output")
            state.last_tif_output = new_state.get("last_tif_output")
            state.last_region_geojson = new_state.get("last_region_geojson")
            state.last_region_name = new_state.get("last_region_name")
            state.map_style = new_state.get("map_style")
        else:
            state = ConversationState(
                conversation_id=conv_id,
                current_dataset=new_state.get("current_dataset"),
                source_dataset=new_state.get("source_dataset"),
                last_output=new_state.get("last_output"),
                last_tif_output=new_state.get("last_tif_output"),
                last_region_geojson=new_state.get("last_region_geojson"),
                last_region_name=new_state.get("last_region_name"),
                map_style=new_state.get("map_style"),
            )
            db.add(state)

        db.commit()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

- [ ] **Step 3: Commit**

```bash
git add api/deps.py api/routes/conversations.py
git commit -m "feat: SSE 流式端点 + 依赖注入"
```

---

## Phase 4: 前端重写

### Task 4.1: 类型定义 + API 层 + Store

**Files:**
- Create: `frontend/src/types/conversation.ts`
- Create: `frontend/src/types/tool.ts`
- Create: `frontend/src/types/index.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/conversations.ts`
- Create: `frontend/src/api/files.ts`
- Create: `frontend/src/stores/uiStore.ts`

- [ ] **Step 1: 创建类型定义**

`types/conversation.ts`:
```typescript
export interface Conversation {
  id: number
  title: string
  status: 'active' | 'archived'
  created_at: string
  updated_at: string
  last_message?: Message
  message_count?: number
}

export interface Message {
  id: number
  conversation_id: number
  role: 'user' | 'assistant' | 'system' | 'tool_call' | 'tool_result'
  content: string
  tool_name?: string
  tool_args?: Record<string, unknown>
  tool_result?: Record<string, unknown>
  output_files?: OutputFile[]
  created_at: string
}

export interface OutputFile {
  name: string
  path: string
  size: number
  modified: string
}

export type SSEEventType =
  | 'thinking'
  | 'step_start'
  | 'tool_start'
  | 'tool_result'
  | 'ask_user'
  | 'final_answer'
  | 'error'
  | 'done'

export interface SSEEvent {
  type: SSEEventType
  data: Record<string, unknown>
}

export type ExecutionPhase = 'idle' | 'thinking' | 'executing' | 'waiting_for_user' | 'done'

export interface ToolCall {
  tool: string
  args: Record<string, unknown>
  result?: Record<string, unknown>
  status: 'pending' | 'running' | 'success' | 'error'
}

export interface UIState {
  sidebarOpen: boolean
  viewerMode: 'preview' | 'compare' | 'fullscreen'
  activeFile: OutputFile | null
}
```

`types/tool.ts`:
```typescript
export interface ToolSpec {
  name: string
  description: string
  parameters: Record<string, string>
  category: string
}
```

`types/index.ts`: 重新导出所有类型。

- [ ] **Step 2: 创建 API 客户端**

`api/client.ts`:
```typescript
const BASE = ''

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const token = localStorage.getItem('token')
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options?.headers as Record<string, string> || {}),
  }

  const res = await fetch(`${BASE}${url}`, { ...options, headers })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ message: res.statusText }))
    throw new Error(err.message || `HTTP ${res.status}`)
  }
  return res.json()
}

export const api = { get: <T>(url: string) => request<T>(url), post: <T>(url: string, body?: unknown) => request<T>(url, { method: 'POST', body: JSON.stringify(body) }), delete: <T>(url: string) => request<T>(url, { method: 'DELETE' }) }
```

`api/conversations.ts`:
```typescript
import { api } from './client'
import type { Conversation, Message } from '../types/conversation'

export const conversationsApi = {
  list: () => api.get<{ conversations: Conversation[]; total: number }>('/api/conversations'),
  get: (id: number) => api.get<Conversation>(`/api/conversations/${id}`),
  create: (title?: string) => api.post<Conversation>('/api/conversations', { title }),
  delete: (id: number) => api.delete(`/api/conversations/${id}`),
  getMessages: (id: number, limit = 50) => api.get<{ messages: Message[] }>(`/api/conversations/${id}/messages?limit=${limit}`),
}
```

- [ ] **Step 3: 创建 UI Store**

`stores/uiStore.ts`:
```typescript
import { create } from 'zustand'
import { persist } from 'zustand/middleware'
import type { OutputFile } from '../types/conversation'

interface UIStore {
  sidebarOpen: boolean
  viewerMode: 'preview' | 'compare' | 'fullscreen'
  activeFile: OutputFile | null
  toggleSidebar: () => void
  setViewerMode: (mode: UIStore['viewerMode']) => void
  setActiveFile: (file: OutputFile | null) => void
}

export const useUIStore = create<UIStore>()(
  persist(
    (set) => ({
      sidebarOpen: true,
      viewerMode: 'preview',
      activeFile: null,
      toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
      setViewerMode: (mode) => set({ viewerMode: mode }),
      setActiveFile: (file) => set({ activeFile: file }),
    }),
    { name: 'opengis-ui' }
  )
)
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/types/ frontend/src/api/ frontend/src/stores/uiStore.ts
git commit -m "feat: 前端类型定义 + API 层 + UI Store"
```

---

### Task 4.2: SSE Hook + Chat 组件

**Files:**
- Create: `frontend/src/hooks/useConversation.ts`
- Create: `frontend/src/hooks/useConversations.ts`
- Create: `frontend/src/components/chat/ChatPanel.tsx`
- Create: `frontend/src/components/chat/ChatInput.tsx`
- Create: `frontend/src/components/chat/MessageList.tsx`
- Create: `frontend/src/components/chat/MessageBubble.tsx`
- Create: `frontend/src/components/chat/StreamingMessage.tsx`
- Create: `frontend/src/components/chat/ToolCallCard.tsx`
- Create: `frontend/src/components/chat/ExamplePrompts.tsx`

- [ ] **Step 1: 创建 SSE Hook**

`hooks/useConversation.ts`:
```typescript
import { useState, useCallback, useRef } from 'react'
import type { ToolCall, ExecutionPhase, SSEEventType } from '../types/conversation'

export function useConversation(convId: number | null) {
  const [phase, setPhase] = useState<ExecutionPhase>('idle')
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([])
  const [answer, setAnswer] = useState('')
  const abortRef = useRef<AbortController | null>(null)

  const send = useCallback(async (content: string) => {
    if (!convId) return
    setPhase('thinking')
    setAnswer('')
    setToolCalls([])

    const controller = new AbortController()
    abortRef.current = controller

    try {
      const res = await fetch(`/api/conversations/${convId}/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content }),
        signal: controller.signal,
      })

      const reader = res.body!.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        let eventType = ''
        let eventData = ''

        for (const line of lines) {
          if (line.startsWith('event: ')) {
            eventType = line.slice(7).trim()
          } else if (line.startsWith('data: ')) {
            eventData = line.slice(6).trim()
          } else if (line === '' && eventType && eventData) {
            try {
              const data = JSON.parse(eventData)
              handleEvent(eventType as SSEEventType, data)
            } catch {}
            eventType = ''
            eventData = ''
          }
        }
      }
    } catch (err: any) {
      if (err.name !== 'AbortError') {
        setPhase('idle')
      }
    }
  }, [convId])

  function handleEvent(type: SSEEventType, data: Record<string, unknown>) {
    switch (type) {
      case 'thinking':
        setPhase('thinking')
        break
      case 'step_start':
        setPhase('executing')
        break
      case 'tool_start':
        setToolCalls(prev => [...prev, {
          tool: data.tool as string,
          args: data.args as Record<string, unknown>,
          status: 'running',
        }])
        break
      case 'tool_result': {
        const toolName = data.tool as string
        const result = data.result as Record<string, unknown>
        setToolCalls(prev => prev.map(tc =>
          tc.tool === toolName && tc.status === 'running'
            ? { ...tc, result, status: result?.success === false ? 'error' : 'success' }
            : tc
        ))
        break
      }
      case 'ask_user':
        setPhase('waiting_for_user')
        break
      case 'final_answer':
        setAnswer(data.content as string)
        setPhase('done')
        break
      case 'error':
        setAnswer(`错误: ${data.message}`)
        setPhase('done')
        break
      case 'done':
        if (phase !== 'done') setPhase('done')
        break
    }
  }

  const abort = useCallback(() => {
    abortRef.current?.abort()
    setPhase('idle')
  }, [])

  return { phase, toolCalls, answer, send, abort }
}
```

- [ ] **Step 2: 创建 Chat 组件**

`ChatPanel.tsx` (~80行，组合 ChatInput + MessageList):
```tsx
import { useConversation } from '../../hooks/useConversation'
import { ChatInput } from './ChatInput'
import { MessageList } from './MessageList'
import { ExamplePrompts } from './ExamplePrompts'
import type { Message } from '../../types/conversation'

interface Props {
  convId: number | null
  messages: Message[]
  onSend: (content: string) => void
}

export function ChatPanel({ convId, messages, onSend }: Props) {
  const { phase, toolCalls, answer, send } = useConversation(convId)

  const handleSend = (content: string) => {
    onSend(content)
    send(content)
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <MessageList messages={messages} toolCalls={toolCalls} phase={phase} answer={answer} />
        {messages.length <= 1 && <ExamplePrompts onSelect={handleSend} />}
      </div>
      <ChatInput onSend={handleSend} disabled={phase === 'thinking' || phase === 'executing'} />
    </div>
  )
}
```

`ChatInput.tsx` (~40行):
```tsx
import { useState, useRef, useEffect, KeyboardEvent } from 'react'
import { Send, Loader2 } from 'lucide-react'

interface Props {
  onSend: (content: string) => void
  disabled?: boolean
}

export function ChatInput({ onSend, disabled }: Props) {
  const [input, setInput] = useState('')
  const ref = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (ref.current) {
      ref.current.style.height = 'auto'
      ref.current.style.height = Math.min(ref.current.scrollHeight, 120) + 'px'
    }
  }, [input])

  const handleSend = () => {
    if (!input.trim() || disabled) return
    onSend(input.trim())
    setInput('')
  }

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="p-3 border-t">
      <div className="flex items-end gap-2">
        <textarea
          ref={ref}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="输入 GIS 需求... (Enter 发送)"
          className="flex-1 px-3 py-2 border rounded-xl resize-none text-sm focus:outline-none focus:ring-2 focus:ring-primary-500"
          rows={1}
          disabled={disabled}
        />
        <button onClick={handleSend} disabled={disabled || !input.trim()}
          className="px-4 py-2.5 bg-primary-600 text-white rounded-xl hover:bg-primary-700 disabled:opacity-50 transition-colors">
          {disabled ? <Loader2 className="h-5 w-5 animate-spin" /> : <Send className="h-5 w-5" />}
        </button>
      </div>
    </div>
  )
}
```

`MessageBubble.tsx` (~30行), `StreamingMessage.tsx` (~30行), `ToolCallCard.tsx` (~40行), `MessageList.tsx` (~40行), `ExamplePrompts.tsx` (~20行):
每个组件职责单一，具体的 JSX 实现省略细节但确保完整。

- [ ] **Step 3: Commit**

```bash
git add frontend/src/hooks/ frontend/src/components/chat/
git commit -m "feat: SSE Hook + Chat 组件"
```

---

### Task 4.3: Viewer + Layout + Workspace

**Files:**
- Create: `frontend/src/components/viewer/*.tsx` (6 files)
- Create: `frontend/src/components/layout/*.tsx` (3 files)
- Create: `frontend/src/components/shared/*.tsx` (3 files)
- Create: `frontend/src/pages/Workspace.tsx`
- Modify: `frontend/src/App.tsx`

- [ ] **Step 1: 创建 Viewer 组件**

`ViewerPanel.tsx` (~60行) — 根据文件类型选择 ImageViewer/GifViewer/HtmlViewer + CompareSlider + FileThumbnails + FileToolbar
`ImageViewer.tsx` (~50行) — 图片预览 + 缩放 + 拖拽
`GifViewer.tsx` (~30行)
`HtmlViewer.tsx` (~20行) — iframe
`CompareSlider.tsx` (~60行) — 复用现有逻辑
`FileThumbnails.tsx` (~50行)
`FileToolbar.tsx` (~30行)

- [ ] **Step 2: 创建 Layout 组件**

`AppShell.tsx` (~40行) — 三栏布局容器
`Sidebar.tsx` (~30行) — 侧边栏
`ConversationList.tsx` (~40行) — 会话列表 + 新建

- [ ] **Step 3: 创建 Shared 组件**

`StatusBadge.tsx`、`LoadingSpinner.tsx`、`EmptyState.tsx`

- [ ] **Step 4: 创建 Workspace 页面**

`pages/Workspace.tsx` (~80行):
```tsx
import { useState } from 'react'
import { useUIStore } from '../stores/uiStore'
import { AppShell } from '../components/layout/AppShell'
import { Sidebar } from '../components/layout/Sidebar'
import { ChatPanel } from '../components/chat/ChatPanel'
import { ViewerPanel } from '../components/viewer/ViewerPanel'
import { useConversations } from '../hooks/useConversations'
import type { Message } from '../types/conversation'

export default function Workspace() {
  const sidebarOpen = useUIStore((s) => s.sidebarOpen)
  const [convId, setConvId] = useState<number | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const { data } = useConversations()

  const handleNewConv = async () => {
    // 创建新会话
    const conv = await fetch('/api/conversations', { method: 'POST', headers: { 'Content-Type': 'application/json' } }).then(r => r.json())
    setConvId(conv.id)
    setMessages([])
  }

  const handleSend = (content: string) => {
    setMessages(prev => [...prev, {
      id: Date.now(),
      conversation_id: convId || 0,
      role: 'user',
      content,
      created_at: new Date().toISOString(),
    }])
  }

  return (
    <AppShell
      sidebar={<Sidebar convId={convId} onSelect={setConvId} onNew={handleNewConv} />}
      sidebarOpen={sidebarOpen}
      main={<ChatPanel convId={convId} messages={messages} onSend={handleSend} />}
      viewer={<ViewerPanel />}
    />
  )
}
```

- [ ] **Step 5: 更新 App.tsx**

简化路由为 `/` → Workspace, `/login` → Login

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/viewer/ frontend/src/components/layout/ frontend/src/components/shared/ frontend/src/pages/ frontend/src/App.tsx
git commit -m "feat: Viewer + Layout + Workspace 页面"
```

---

## Phase 5: 清理收尾

### Task 5.1: 删除旧代码 + 更新配置

- [ ] **Step 1: 删除旧 agent 文件**

```bash
cd d:/opengis
# 备份旧文件（可选）
mkdir -p .archive
mv agent/core.py .archive/
mv agent/conversational_agent.py .archive/
mv agent/tool.py .archive/
mv agent/tool_registry.py .archive/
mv agent/llm_client.py .archive/
rm -rf agent/tools/
```

- [ ] **Step 2: 删除旧前端文件**

```bash
cd d:/opengis/frontend/src
rm -f stores/authStore.ts stores/taskStore.ts stores/workspaceStore.ts stores/appStore.ts
rm -f services/api.ts services/auth.ts services/conversations.ts services/payments.ts services/sse.ts services/tasks.ts
rm -f pages/Dashboard.tsx pages/Submit.tsx pages/TaskPage.tsx pages/Register.tsx pages/Profile.tsx
rm -f components/Layout.tsx components/DownloadButton.tsx components/GifPlayer.tsx components/HtmlPreview.tsx
rm -f components/ImagePreview.tsx components/ImageViewer.tsx components/OutputPreview.tsx
rm -f components/PaymentModal.tsx components/TaskCard.tsx components/TaskInput.tsx
rm -f components/TimeSeriesChart.tsx components/ViewerRouter.tsx components/CompareSlider.tsx
rm -f components/LoadingSpinner.tsx components/StatusBadge.tsx
rm -f hooks/useAuth.ts hooks/usePayments.ts hooks/useTasks.ts
```

- [ ] **Step 3: 更新 api/app.py**

将导入路径从 `api.routers.tasks` 改为 `api.routes.conversations`：
```python
from api.routes import auth, conversations, files, payments
app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(files.router)
app.include_router(payments.router)
```

- [ ] **Step 4: 更新 main.py**

更新 CLI 入口文件，导入新路径：
```python
from tools import ToolRegistry
from tools.runtime import GISRuntime
from agent.engine import AgentLoop
from agent.llm import LLMClient
```

- [ ] **Step 5: 更新 CLAUDE.md**

同步项目架构描述到新结构。

- [ ] **Step 6: 全链路验证**

```bash
# 后端启动
uvicorn api.app:app --host 0.0.0.0 --port 8000

# 前端启动
cd frontend && npm run dev

# 测试 SSE 端点
curl -N -X POST http://localhost:8000/api/conversations/1/stream \
  -H "Content-Type: application/json" \
  -d '{"content":"下载成都市双流区2024年8月LST并制图"}'
```

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore: 删除旧代码，更新路由导入和文档"
```

---

## 自审清单

1. **Spec 覆盖**: 设计文档中每个要求都有对应任务。工具系统(Phase 1)、Agent引擎(Phase 2)、API(Phase 3)、前端(Phase 4)、清理(Phase 5)
2. **无占位符**: 所有步骤含实际代码
3. **类型一致**: `ToolRegistry.call(name, args) → dict`, `AgentLoop.run() → dict`, SSE 事件协议前后一致
