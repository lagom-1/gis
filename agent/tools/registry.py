"""
工具注册中心 + 所有工具定义和处理器
"""

from __future__ import annotations

import os
import traceback
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from .runtime import GISRuntime, out_dir, build_task_filename


class ToolRegistry:
    """工具注册和调用中心"""

    def __init__(self, runtime: GISRuntime):
        self.runtime = runtime
        self._tools: Dict[str, Callable] = {}
        self._defs: list = []
        self.call_timeout = 600

    def register(self, name: str, handler: Callable, description: str,
                 params: Dict[str, str] = None, category: str = "general"):
        self._tools[name] = handler
        self._defs.append({
            "name": name, "description": description,
            "params": params or {}, "category": category,
        })

    def call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name not in self._tools:
            return {"success": False, "message": f"未知工具: {name}"}
        try:
            return self._tools[name](args)
        except Exception as e:
            return {"success": False, "message": str(e),
                    "traceback": traceback.format_exc(limit=4)}

    def get_definitions(self) -> list:
        return self._defs

    def list_tools(self) -> list:
        return list(self._tools.keys())


def register_all_tools(registry: ToolRegistry, runtime: GISRuntime):
    """注册所有 LLM 可见工具"""
    import json
    from datetime import datetime, timedelta

    # ── 辅助函数 ──
    def _default_dates():
        today = datetime.now()
        end = today.replace(day=1) - timedelta(days=1)
        start = end.replace(day=1)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    # ── resolve_admin_region ──
    def resolve_admin_region_tool(args):
        from gis.admin_region import resolve_admin_region
        name = args.get("name", "")
        result = resolve_admin_region(admin_name=name)
        if result.get("success"):
            runtime.last_region_geojson = result.get("geojson")
            runtime.last_region_name = name
        return result

    registry.register("resolve_admin_region", resolve_admin_region_tool,
        "解析中国行政区名称（如'温江区''成都市'）为 GeoJSON 边界。所有 GEE 操作前必须调用此工具。",
        {"name": "行政区名称，如'双流区''成都市'", "adm_level": "行政级别: district/city/province"})

    # ── search_local_files ──
    def search_local_files_tool(args):
        from gis.file_discovery import find_local_files
        query = args.get("query", "")
        limit = int(args.get("limit", 20))
        return find_local_files(query=query, max_results=limit)

    registry.register("search_local_files", search_local_files_tool,
        "根据关键词搜索本地栅格文件（.tif/.nc 等）。用户明确提到本地文件时使用。",
        {"query": "搜索关键词（地名或文件名）", "limit": "最大返回数量，默认20"})

    # ── inspect_raster ──
    def inspect_raster_tool(args):
        from gis.inspect import inspect_raster
        path = args.get("path") or runtime.current_tif()
        if not path:
            return {"success": False, "message": "没有可查看的栅格文件，请先下载数据"}
        result = inspect_raster(path)
        if result.get("success"):
            runtime.current_dataset = path
        return result

    registry.register("inspect_raster", inspect_raster_tool,
        "查看栅格文件元数据（波段数/分辨率/投影/统计值/产品类型）。",
        {"path": "栅格文件路径，缺省使用当前数据集"})

    # ── gee_download_lst ──
    def gee_download_lst_tool(args):
        from gis.gee import init_gee, filter_collection, mask_clouds_qa, reduce_collection, compute_lst, download_tif
        from gis.gee_tools import _normalize_region

        start_date = args.get("start_date")
        end_date = args.get("end_date")
        if not start_date or not end_date:
            start_date, end_date = _default_dates()

        region = args.get("region") or runtime.last_region_geojson
        if not region:
            return {"success": False, "message": "缺少研究区。请先用 resolve_admin_region 解析行政区",
                    "requires": "resolve_admin_region"}
        region_name = runtime.last_region_name or ""
        scale = int(args.get("scale", 30))
        cloud_pct = float(args.get("cloud_pct", 30))

        filename = build_task_filename(region_name, start_date, end_date, "LST")
        output_tif = args.get("output_tif") or str(out_dir() / filename)

        try:
            init = init_gee()
            if not init.get("success"):
                return init

            geom = _normalize_region(region=region)
            col = filter_collection(geom, start_date, end_date, cloud_pct)
            count = col.size().getInfo()
            if count == 0:
                return {"success": False, "message": f"{start_date}~{end_date} 云量≤{cloud_pct}% 无可用影像"}

            img = reduce_collection(col, args.get("reducer", "median"), mask_clouds=True, region_geom=geom)
            lst = compute_lst(img)

            stats = lst.reduceRegion(
                reducer="first",  # no, use minMax
                geometry=geom, scale=scale, bestEffort=True
            ).getInfo()

            result = download_tif(lst, geom, output_tif, scale=scale)
            if not result.get("success"):
                return result

            if os.path.exists(output_tif):
                runtime.current_dataset = output_tif
                runtime.last_tif_output = output_tif
                if runtime.source_dataset is None:
                    runtime.source_dataset = output_tif

            stats_info = {}
            try:
                s = lst.reduceRegion(geometry=geom, scale=scale, bestEffort=True,
                    reducer="min").combine("max").combine("mean").getInfo()
                stats_info = {"min": round(s.get("LST_min", 0), 1),
                              "max": round(s.get("LST_max", 0), 1),
                              "mean": round(s.get("LST_mean", 0), 1)}
            except Exception:
                stats_info = {"min": 0, "max": 0, "mean": 0}

            return {"success": True,
                    "message": f"LST 反演完成：{count}景合成，{stats_info['min']}~{stats_info['max']}°C",
                    "output_tif": output_tif, "scene_count": count, **stats_info}

        except Exception as e:
            return {"success": False, "message": f"LST 下载失败: {e}"}

    registry.register("gee_download_lst", gee_download_lst_tool,
        "【核心工具】从 GEE 下载 Landsat LST 地表温度数据。自动完成：筛选影像→去云→中值合成→单通道温度反演→下载单波段TIF。适用于单时相温度反演。",
        {"start_date": "开始日期 YYYY-MM-DD", "end_date": "结束日期 YYYY-MM-DD",
         "cloud_pct": "最大云量 0-100，默认30", "scale": "分辨率米，默认30"})

    # ── gee_lst_timelapse ──
    def gee_lst_timelapse_tool(args):
        from gis.gee import init_gee, filter_collection, mask_clouds_qa, reduce_collection, compute_lst, download_tif
        from gis.gee_tools import _normalize_region
        from gis.gee_timelapse import generate_lst_timelapse

        start_year = int(args.get("start_year", 2020))
        end_year = int(args.get("end_year", 2024))
        month = int(args.get("month", 8))
        region = args.get("region") or runtime.last_region_geojson
        if not region:
            return {"success": False, "message": "缺少研究区", "requires": "resolve_admin_region"}
        region_name = runtime.last_region_name or ""
        cloud_pct = float(args.get("cloud_pct", 30))
        scale = int(args.get("scale", 30))

        init = init_gee()
        if not init.get("success"):
            return init

        geom = _normalize_region(region=region)
        result = generate_lst_timelapse(
            roi=geom, start_year=start_year, end_year=end_year, month=month,
            cloud_pct=cloud_pct, scale=scale, region_name=region_name,
            output_dir=str(out_dir()),
        )
        return result

    registry.register("gee_lst_timelapse", gee_lst_timelapse_tool,
        "【时间序列】生成多年指定月份 LST 动画(GIF)。自动逐年下载+合成动画。",
        {"start_year": "起始年份", "end_year": "结束年份", "month": "月份 1-12",
         "cloud_pct": "最大云量", "scale": "分辨率"})

    # ── classify ──
    def classify_tool(args):
        from gis.classify import classify_raster
        path = args.get("path") or runtime.current_tif()
        if not path:
            return {"success": False, "message": "没有可分类的数据"}
        return classify_raster(tif_path=path, method=args.get("method", "natural_breaks"),
                               n_classes=int(args.get("n_classes", 5)))

    registry.register("classify", classify_tool,
        "对当前 LST 结果分类（自然断点/等间隔/分位数）。",
        {"method": "natural_breaks / equal_interval / quantile", "n_classes": "分类数，默认5"})

    # ── set_map_style ──
    def set_map_style_tool(args):
        style_map = {"colormap": "colormap", "title": "title", "cmap": "colormap",
                     "color": "colormap", "配色": "colormap", "图例": "legend_position",
                     "标题": "title", "指北针": "show_north", "比例尺": "show_scalebar"}
        for k, v in args.items():
            key = style_map.get(k, k)
            runtime.map_style[key] = v
        return {"success": True, "message": f"样式已更新: {args}", "map_style": dict(runtime.map_style)}

    registry.register("set_map_style", set_map_style_tool,
        "修改专题图样式（配色方案/标题/图例位置/指北针显隐等）。修改后自动重新出图。",
        {"colormap": "配色方案: viridis/coolwarm/plasma/inferno/terrain/rdylbu/jet",
         "title": "地图标题", "legend_position": "图例位置: right/left/top/bottom",
         "show_north": "是否显示指北针 true/false"})

    # ── make_thematic_map ──
    def make_thematic_map_tool(args):
        from gis.cartographic_map import make_thematic_map
        tif = args.get("path") or runtime.current_tif()
        if not tif:
            return {"success": False, "message": "没有可制图的数据"}
        output_png = args.get("output_png") or tif.replace(".tif", "_map.png")
        result = make_thematic_map(tif_path=tif, output_png=output_png,
                                   style=dict(runtime.map_style))
        if result.get("success"):
            runtime.last_output = result.get("output_png")
        return result

    registry.register("make_thematic_map", make_thematic_map_tool,
        "生成标准专题图（图例/比例尺/指北针）。LST下载后自动调用。",
        {"path": "TIF路径，缺省用当前数据", "output_png": "输出PNG路径"})

    # ── statistics ──
    def statistics_tool(args):
        from gis.statistics import compute_statistics
        path = args.get("path") or runtime.current_tif()
        if not path:
            return {"success": False, "message": "没有可统计的数据"}
        return compute_statistics(tif_path=path)

    registry.register("statistics", statistics_tool,
        "计算当前数据的统计信息（min/max/mean/std/直方图）。",
        {"path": "TIF路径，缺省用当前数据"})

    # ── export_result ──
    def export_result_tool(args):
        from gis.export import export_raster
        path = args.get("path") or runtime.current_tif()
        fmt = args.get("format", "png")
        output = args.get("output") or str(out_dir() / f"export.{fmt}")
        return export_raster(input_path=path, output_path=output, target_format=fmt)

    registry.register("export_result", export_result_tool,
        "导出当前结果为指定格式（PNG/JPG/PDF/TIFF）。",
        {"format": "png/jpg/pdf/tiff", "output": "输出路径"})

    # ── compare_views ──
    def compare_views_tool(args):
        from gis.compare import compare_views
        before = args.get("before") or runtime.source_dataset
        after = args.get("after") or runtime.current_tif()
        if not before or not after:
            return {"success": False, "message": "缺少对比数据"}
        output = args.get("output") or str(out_dir() / "compare.png")
        return compare_views(tif_original=before, tif_result=after, output_png=output)

    registry.register("compare_views", compare_views_tool,
        "并排对比原始数据和当前结果。",
        {"before": "原始数据路径", "after": "结果数据路径", "mode": "side_by_side/difference"})

    # ── gee_init ──
    def gee_init_tool(args):
        from gis.gee import init_gee
        return init_gee(force_auth=bool(args.get("force_auth", False)))

    registry.register("gee_init", gee_init_tool,
        "初始化 Google Earth Engine 认证。GEE 操作失败提示未认证时调用。",
        {"force_auth": "是否强制重新认证"})
