"""
数据工具：文件搜索、数据集管理、栅格检查、行政区解析
"""
from __future__ import annotations

import os
from typing import Any, Dict

from tools.base import BaseTool, tool


@tool(
    name="search_local_files",
    description="在本地电脑常见目录中搜索文件，适合根据模糊文件名找影像或 GeoJSON",
    parameters={
        "query": "要查找的文件名或关键词",
        "roots": "可选，搜索根目录列表",
        "extensions": "可选扩展名列表",
    },
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
        return {"success": True, "message": "当前数据已切换", "path": path, "selected_path": path}


@tool(
    name="inspect_raster",
    description="读取当前或指定栅格的波段、值域、分辨率、CRS、产品类型推断",
    parameters={"path": "可选，栅格路径，不填则使用当前数据集"},
    category="data",
)
class InspectRasterTool(BaseTool):
    def execute(self, path=None) -> Dict[str, Any]:
        target = path or self.runtime.current_tif()
        from gis.inspect import inspect_raster
        return inspect_raster(target)


@tool(
    name="resolve_admin_region",
    description="根据中国市/县/区名称，从本地 GeoJSON 中自动匹配行政边界，返回 GeoJSON 与 bbox",
    parameters={
        "region_name": "行政区名称，如 广元市 / 旺苍县 / 广元市旺苍县",
    },
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
