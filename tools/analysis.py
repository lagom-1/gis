"""
栅格分析工具：统计、分类、阈值、增强、剖面
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import config as app_config
from tools.base import BaseTool, tool


def _out_dir() -> Path:
    d = Path(app_config.OUTPUTS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stem(path: str | None) -> str:
    return Path(path).stem if path else "result"


class _AnalysisBase(BaseTool):
    def _get_tif(self, tif_path=None) -> str | None:
        return tif_path or self.runtime.current_tif()


@tool(
    name="statistics",
    description="对当前单波段栅格做统计分析并输出直方图。",
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
    description="对当前单波段结果自动分类并出分类图。",
    parameters={
        "method": "natural_breaks/equal_interval/quantile，默认 natural_breaks",
        "n_classes": "分类数，默认 5",
        "colormap": "配色方案，默认 YlOrRd",
    },
    category="analysis",
)
class ClassifyMapTool(_AnalysisBase):
    def execute(self, tif_path=None, method="natural_breaks", n_classes=5,
                colormap="YlOrRd", title=None, dpi=300) -> Dict[str, Any]:
        tif = self._get_tif(tif_path)
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        from gis.classify import classify_raster
        result = classify_raster(
            tif_path=tif,
            output_png=str(_out_dir() / f"{_stem(tif)}_classified.png"),
            method=method, n_classes=int(n_classes),
            colormap=colormap, title=title, dpi=int(dpi),
        )
        if result.get("success"):
            self.runtime.last_output = result.get("output_png")
        return result


@tool(
    name="threshold_highlight",
    description="高亮超过阈值或位于某个区间的区域。",
    parameters={
        "operator": ">/< /between/outside",
        "value": "阈值",
        "value_upper": "上限（between/outside 时使用）",
        "highlight_color": "高亮颜色，默认 red",
        "base_colormap": "底色配色，默认 gray",
    },
    category="analysis",
)
class ThresholdHighlightTool(_AnalysisBase):
    def execute(self, tif_path=None, operator=">", value=30, value_upper=None,
                highlight_color="red", base_colormap="gray", title=None,
                dpi=300) -> Dict[str, Any]:
        tif = self._get_tif(tif_path)
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        from gis.threshold import threshold_highlight
        result = threshold_highlight(
            tif_path=tif,
            output_path=str(_out_dir() / f"{_stem(tif)}_threshold.png"),
            operator=operator, value=float(value),
            value_upper=float(value_upper) if value_upper is not None else None,
            highlight_color=highlight_color, base_colormap=base_colormap,
            title=title, dpi=int(dpi),
        )
        if result.get("success"):
            self.runtime.last_output = result.get("output_png")
        return result


@tool(
    name="enhance_raster",
    description="对当前栅格做增强或去噪（高斯/中值/直方图均衡/锐化）。",
    parameters={
        "method": "gaussian/median/histogram_eq/clahe/sharpen",
        "kernel_size": "核大小，默认 5",
    },
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
    description="对当前栅格做剖面分析。",
    parameters={
        "start": "起点[col,row]",
        "end": "终点[col,row]",
        "n_points": "采样点数，默认 200",
    },
    category="analysis",
)
class ProfileAnalysisTool(_AnalysisBase):
    def execute(self, tif_path=None, start=None, end=None, n_points=200) -> Dict[str, Any]:
        tif = self._get_tif(tif_path)
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        from gis.profile import profile_analysis
        return profile_analysis(
            tif_path=tif,
            output_png=str(_out_dir() / f"{_stem(tif)}_profile.png"),
            start=start, end=end, n_points=int(n_points),
        )
