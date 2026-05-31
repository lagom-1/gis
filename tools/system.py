"""
系统工具：样式设置、偏好管理、上下文摘要
"""
from __future__ import annotations

from typing import Any, Dict

from tools.base import BaseTool, tool


@tool(
    name="set_map_style",
    description="更新地图样式参数。绝对位置用 legend_position/scalebar_position/north_position，微调偏移用 legend_xoffset/yoffset、north_xoffset/yoffset、scalebar_xoffset/yoffset。",
    parameters={
        "title": "标题",
        "colormap": "配色方案",
        "legend_position": "图例绝对位置 right/left/upper right/lower left 等",
        "legend_xoffset": "图例 X 偏移（用于微调，如 0.02 或 -0.02）",
        "legend_yoffset": "图例 Y 偏移（用于微调）",
        "dpi": "分辨率",
        "show_legend": "是否显示图例",
        "show_scalebar": "是否显示比例尺",
        "show_north": "是否显示指北针",
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
    description="更新长期用户偏好（默认导出格式、分类数、配色等）。",
    parameters={
        "export_format": "导出格式",
        "n_classes": "默认分类数",
        "colormap": "默认配色",
    },
    category="system",
)
class UpdatePreferencesTool(BaseTool):
    def execute(self, **kwargs) -> Dict[str, Any]:
        updated = {k: v for k, v in kwargs.items() if v is not None}
        self.runtime.preferences.update(updated)
        # 如果包含配色，同步更新 map_style
        if "colormap" in updated:
            self.runtime.map_style["colormap"] = updated["colormap"]
        return {"success": True, "message": "偏好已更新", "updated_preferences": updated}


@tool(
    name="summarize_context",
    description="返回当前会话上下文摘要。",
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
