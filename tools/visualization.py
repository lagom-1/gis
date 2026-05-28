"""
可视化工具：3D、对比、变换、专题图、Web 地图
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict

from tools.base import BaseTool, tool


def _stem(path: str | None) -> str:
    return Path(path).stem if path else "result"


def _derive_title_from_tif(tif_path: str, fallback: str = "专题图") -> str:
    """从 TIF 文件名中提取区域、年份、月份，动态生成图面标题。
    示例: 温江区_2026_02_lst.tif -> '温江区2026年2月地表温度(LST)'
    """
    fname = Path(tif_path).stem
    # 提取区域名（第一个下划线前的部分，或第一个看起来像年份前的部分）
    region = ""
    year = ""
    month = ""

    # 匹配 _YYYY_MM_ 或 _YYYY年M月_ 或 _YYYY年MM月_ 模式
    m = re.search(r'_(\d{4})[年_]?(\d{1,2})月?', fname)
    if m and m.group(2):
        # 验证第二个分组确实是月份（1-12）
        mo = int(m.group(2))
        if mo < 1 or mo > 12:
            m = None  # 不是有效月份，回退到纯年份匹配
    if not m:
        m = re.search(r'_(\d{4})[年_]?(\d{2})', fname)
    if m:
        year = m.group(1)
        month = m.group(2).lstrip('0')
        region = fname[:m.start()]
        # 清理区域名末尾的下划线
        region = region.rstrip('_')
    else:
        # 单独匹配年份
        m = re.search(r'_(\d{4})', fname)
        if m:
            year = m.group(1)
            region = fname[:m.start()].rstrip('_')

    # 清理区域名中的 lst/LST 后缀
    region = re.sub(r'_?[Ll][Ss][Tt]$', '', region)

    parts = []
    if region:
        parts.append(region)
    if year and month:
        parts.append(f"{year}年{month}月")
    elif year:
        parts.append(f"{year}年")

    parts.append("LST专题图")
    return "".join(parts) if parts else fallback


class _VisBase(BaseTool):
    def _get_tif(self, tif_path=None) -> str | None:
        return tif_path or self.runtime.current_tif()

    def _out_dir(self) -> Path:
        return self.runtime.session_dir


@tool(
    name="view_3d",
    description="将当前单波段栅格生成 3D 可视化。",
    parameters={
        "elevation": "俯仰角，默认 45",
        "azimuth": "方位角，默认 225",
        "vertical_exaggeration": "垂直夸张系数，默认 1.0",
        "colormap": "配色方案，默认 terrain",
        "render_mode": "surface/wireframe/contour，默认 surface",
    },
    category="visualization",
)
class View3DTool(_VisBase):
    def execute(self, tif_path=None, elevation=45, azimuth=225,
                vertical_exaggeration=1.0, colormap="terrain",
                render_mode="surface") -> Dict[str, Any]:
        tif = self._get_tif(tif_path)
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        from gis.view3d import render_3d
        result = render_3d(
            tif_path=tif,
            output_png=str(self._out_dir() / f"{_stem(tif)}_3d.png"),
            elevation=float(elevation), azimuth=float(azimuth),
            vertical_exaggeration=float(vertical_exaggeration),
            colormap=colormap, render_mode=render_mode,
        )
        if result.get("success"):
            self.runtime.last_output = result.get("output_png")
        return result


@tool(
    name="compare_views",
    description="对比原始图和当前结果图。",
    parameters={
        "mode": "side_by_side 或 difference",
        "tif_original": "可选，原始数据路径，缺省使用 source_dataset",
        "tif_result": "可选，结果数据路径，缺省使用 current_dataset",
    },
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
            output_png=str(self._out_dir() / f"{_stem(tif_res)}_compare.png"),
            mode=mode,
        )
        if result.get("success"):
            self.runtime.last_output = result.get("output_png")
        return result


@tool(
    name="transform_raster",
    description="对当前栅格做翻转或旋转。",
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
            output_tif=str(self._out_dir() / f"{_stem(tif)}_{operation}.tif"),
            output_png=str(self._out_dir() / f"{_stem(tif)}_{operation}.png"),
            operation=operation,
        )
        if result.get("success"):
            self.runtime.current_dataset = result.get("output_tif")
            self.runtime.last_tif_output = result.get("output_tif")
            self.runtime.last_output = result.get("output_png")
        return result


@tool(
    name="make_thematic_map",
    description="将当前单波段结果做成标准专题图（含图例、比例尺、指北针）。",
    parameters={
        "title": "标题",
        "colormap": "配色方案",
        "legend_position": "图例位置",
        "dpi": "分辨率，默认 300",
        "tif_path": "可选，栅格路径",
    },
    category="visualization",
)
class MakeThematicMapTool(_VisBase):
    def execute(self, tif_path=None, title=None, colormap=None,
                legend_position=None, dpi=None, **kwargs) -> Dict[str, Any]:
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
        else:
            # 无显式标题时从 TIF 文件名动态派生，避免使用上一个月的残留标题
            style["title"] = _derive_title_from_tif(tif)
        if legend_position:
            style["legend_position"] = legend_position
        if dpi:
            style["dpi"] = int(dpi)

        # 文件名包含配色方案，不同配色生成不同文件，方便用户比较
        colormap_name = style.get("colormap", "coolwarm")
        output_path = kwargs.get("output_path") or str(self._out_dir() / f"{_stem(tif)}_{colormap_name}_专题图.png")
        result = generate_cartographic_map(
            tif_path=tif, output_path=output_path,
            title=style["title"],
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
            self.runtime.register_output(output_path, "image")
            self.runtime.map_style.update(style)
        return result


@tool(
    name="generate_web_map",
    description="生成交互式 Web 地图（Leaflet HTML）。支持鼠标悬停查看坐标、图层切换、热力图叠加。",
    parameters={
        "title": "地图标题",
        "colormap": "配色方案",
        "show_heatmap": "是否显示热力图(true/false)",
        "overlay_opacity": "透明度(0~1)",
        "tif_path": "可选，栅格路径",
        "center_lat": "地图中心纬度", "center_lon": "地图中心经度",
        "zoom_start": "初始缩放级别，默认 12",
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
        output_path = str(self._out_dir() / f"{_stem(tif)}_interactive_map.html")
        result = generate_web_map(
            tif_path=tif, output_path=output_path,
            title=title or f"交互式地图 - {_stem(tif)}",
            colormap=colormap,
            overlay_opacity=float(overlay_opacity),
            show_heatmap=bool(show_heatmap),
            additional_layers=kwargs.get("additional_layers"),
            popup_info=kwargs.get("popup_info"),
            center_lat=kwargs.get("center_lat"),
            center_lon=kwargs.get("center_lon"),
            zoom_start=int(kwargs.get("zoom_start", 12)),
        )
        if result.get("success"):
            self.runtime.last_output = output_path
            self.runtime.register_output(output_path, "html")
        return result
