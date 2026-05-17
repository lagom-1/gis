"""
GISRuntime — Agent 会话状态
唯一状态源，工具通过读写 runtime 属性传递状态
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


class GISRuntime:
    """Agent 运行时会话状态"""

    def __init__(self):
        self.current_dataset: Optional[str] = None      # 当前数据集路径
        self.source_dataset: Optional[str] = None       # 原始数据集（首次加载时保存）
        self.last_region_geojson: Optional[dict] = None  # 上次解析的研究区边界
        self.last_region_name: Optional[str] = None     # 上次解析的研究区名称
        self.last_output: Optional[str] = None          # 上次输出文件路径
        self.last_tif_output: Optional[str] = None      # 上次 TIF 输出
        self.map_style: Dict[str, Any] = {
            "colormap": "coolwarm",
            "title": "专题图",
            "show_legend": True,
            "show_scalebar": True,
            "show_north": True,
            "dpi": 300,
            "legend_position": "right",
            "scalebar_position": "lower left",
            "north_position": "upper right",
        }

    def reset_for_new_task(self) -> None:
        """新任务时重置数据集和区域（保留样式）"""
        self.current_dataset = None
        self.source_dataset = None
        self.last_region_geojson = None
        self.last_region_name = None
        self.last_tif_output = None

    def current_tif(self) -> Optional[str]:
        """当前可用的 TIF 路径"""
        return self.current_dataset or self.last_tif_output


def out_dir() -> Path:
    """输出目录"""
    from config import OUTPUTS_DIR
    return OUTPUTS_DIR


def build_task_filename(region_name: str = "", start_date: str = "",
                        end_date: str = "", product: str = "LST") -> str:
    """生成任务输出文件名"""
    parts = [product]
    if region_name:
        parts.append(region_name)
    if start_date:
        d = start_date.replace("-", "")
        parts.append(d[:6] if len(d) >= 6 else d)
    if end_date and end_date != start_date:
        d = end_date.replace("-", "")
        parts.append(d[:6] if len(d) >= 6 else d)
    return "_".join(parts) + ".tif"
