"""
GEE 认证工具
"""
from __future__ import annotations

from typing import Any, Dict

from tools.base import BaseTool, tool


@tool(
    name="gee_init",
    description="初始化 Google Earth Engine 认证与项目配置。需要时调用，授权只需一次。",
    parameters={
        "project_id": "可选，GEE 项目 ID",
        "force_auth": "是否强制重新认证 true/false",
    },
    category="data",
)
class GeeInitTool(BaseTool):
    def execute(self, project_id=None, force_auth=False) -> Dict[str, Any]:
        from gis.gee_tools import gee_init
        return gee_init(
            project_id=project_id,
            force_auth=bool(force_auth),
        )
