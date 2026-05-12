"""
GEE 图表模块 - 基于 geemap.chart 的丰富时间序列图表
基于 geemap notebook 146: chart_image_collection

支持三种图表类型：
- image_series: 时间序列折线图（单区域多波段）
- image_series_by_region: 多区域对比图
- image_doy_series: 年内日变化分析（物候分析）
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import ee

from agent.gee_client import init_gee


def _resolve_region(region: Any) -> Any:
    """统一处理 region 参数，支持 GeoJSON dict、ee.Geometry 等"""
    if hasattr(region, "getInfo"):
        return region
    if isinstance(region, dict):
        geo_type = region.get("type", "")
        if geo_type == "Feature":
            inner = region.get("geometry")
            if inner:
                return ee.Geometry(inner)
        if geo_type in ("Polygon", "MultiPolygon", "Point", "LineString"):
            return ee.Geometry(region)
        if geo_type == "FeatureCollection":
            return ee.FeatureCollection(region)
    raise ValueError(f"无法识别的 region 类型: {type(region).__name__}")


def gee_chart_timeseries(
    image_collection_id: str,
    region: Any,
    band_names: List[str],
    start_date: str,
    end_date: str,
    output_path: str,
    scale: int = 500,
    reducer: str = "mean",
    title: str = "",
    x_label: str = "日期",
    y_label: str = "值",
    chart_type: str = "LineChart",
    colors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    生成时间序列折线图（单区域多波段）。

    基于 geemap.chart.image_series()，将 ImageCollection 中每个影像
    在指定区域的统计值绘制成折线图。

    Args:
        image_collection_id: GEE ImageCollection ID
        region: 研究区（GeoJSON dict 或 ee.FeatureCollection/Geometry）
        band_names: 要分析的波段名列表
        start_date: 起始日期
        end_date: 结束日期
        output_path: PNG 输出路径
        scale: 采样分辨率（米）
        reducer: 聚合方式 mean/min/max/median
        title: 图表标题
        x_label: X 轴标签
        y_label: Y 轴标签
        chart_type: 图表类型 LineChart/BarChart/ScatterChart
        colors: 自定义颜色列表

    Returns:
        {"success": bool, "message": str, "output_path": str, ...}
    """
    try:
        init_result = init_gee()
        if not init_result.get("success"):
            return {"success": False, "message": f"GEE 初始化失败: {init_result.get('message', '')}",
                    "requires": "gee_init"}

        import geemap
        from geemap import chart as ee_chart

        ee_region = _resolve_region(region)

        collection = (
            ee.ImageCollection(image_collection_id)
            .filterDate(start_date, end_date)
            .filterBounds(ee_region)
            .select(band_names)
        )

        count = collection.size().getInfo()
        if count == 0:
            return {"success": False, "message": f"集合 {image_collection_id} 在 {start_date}~{end_date} 无数据"}

        print(f"[GEE Charts] 找到 {count} 景影像，生成时间序列图...")

        # 映射 reducer
        reducer_map = {
            "mean": ee.Reducer.mean(),
            "min": ee.Reducer.min(),
            "max": ee.Reducer.max(),
            "median": ee.Reducer.median(),
        }
        ee_reducer = reducer_map.get(reducer.lower(), ee.Reducer.mean())

        if not title:
            title = f"时间序列 - {image_collection_id.split('/')[-1]}"

        fig = ee_chart.image_series(
            collection,
            region=ee_region,
            reducer=ee_reducer,
            scale=scale,
            x_property="system:time_start",
            chart_type=chart_type,
            x_cols="date",
            y_cols=band_names,
            colors=colors or ["#e37d05", "#1d6b99", "#0f8755", "#f0af07", "#76b349"],
            title=title,
            x_label=x_label,
            y_label=y_label,
            legend_location="right",
        )

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        fig.savefig(output_path, dpi=200, bbox_inches="tight", facecolor="white")
        print(f"[GEE Charts] 时间序列图已保存: {output_path}")

        return {
            "success": True,
            "message": f"时间序列图表已生成（{count} 景影像，{len(band_names)} 波段）",
            "output_path": output_path,
            "image_count": count,
            "band_names": band_names,
        }

    except Exception as e:
        return {"success": False, "message": f"时间序列图表生成失败: {e}"}


def gee_chart_by_region(
    image_collection_id: str,
    regions: Any,
    band_name: str,
    start_date: str,
    end_date: str,
    output_path: str,
    scale: int = 500,
    series_property: str = "label",
    title: str = "",
    x_label: str = "日期",
    y_label: str = "值",
    colors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    生成多区域对比时间序列图。

    基于 geemap.chart.image_series_by_region()，比较不同区域
    在同一波段上的时间变化差异。

    Args:
        image_collection_id: GEE ImageCollection ID
        regions: 多区域 FeatureCollection（需含 series_property 标签属性）
        band_name: 要分析的波段名
        start_date: 起始日期
        end_date: 结束日期
        output_path: PNG 输出路径
        scale: 采样分辨率
        series_property: 用于区分区域的属性名
        title: 图表标题
        x_label/y_label: 轴标签
        colors: 自定义颜色列表

    Returns:
        {"success": bool, "message": str, "output_path": str, ...}
    """
    try:
        init_result = init_gee()
        if not init_result.get("success"):
            return {"success": False, "message": f"GEE 初始化失败: {init_result.get('message', '')}",
                    "requires": "gee_init"}

        from geemap import chart as ee_chart

        ee_regions = _resolve_region(regions)

        collection = (
            ee.ImageCollection(image_collection_id)
            .filterDate(start_date, end_date)
            .filterBounds(ee_regions)
            .select([band_name])
        )

        count = collection.size().getInfo()
        if count == 0:
            return {"success": False, "message": f"集合在 {start_date}~{end_date} 无数据"}

        print(f"[GEE Charts] 多区域对比：{count} 景影像...")

        if not title:
            title = f"{band_name} 多区域对比"

        fig = ee_chart.image_series_by_region(
            collection,
            regions=ee_regions,
            reducer=ee.Reducer.mean(),
            band=band_name,
            scale=scale,
            x_property="system:time_start",
            series_property=series_property,
            chart_type="LineChart",
            x_cols="index",
            y_cols=None,  # 自动从 series_property 获取
            title=title,
            x_label=x_label,
            y_label=y_label,
            colors=colors or ["#f0af07", "#0f8755", "#76b349", "#e37d05", "#1d6b99"],
            stroke_width=3,
            legend_location="bottom-left",
        )

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        fig.savefig(output_path, dpi=200, bbox_inches="tight", facecolor="white")
        print(f"[GEE Charts] 多区域对比图已保存: {output_path}")

        return {
            "success": True,
            "message": f"多区域对比图表已生成（{band_name}）",
            "output_path": output_path,
            "image_count": count,
            "band_name": band_name,
        }

    except Exception as e:
        return {"success": False, "message": f"多区域对比图表生成失败: {e}"}


def gee_chart_phenology(
    image_collection_id: str,
    region: Any,
    band_names: List[str],
    start_date: str,
    end_date: str,
    output_path: str,
    scale: int = 500,
    title: str = "",
    x_label: str = "年内日序 (DOY)",
    y_label: str = "值",
    colors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    生成年内日变化分析图（物候分析）。

    基于 geemap.chart.image_doy_series()，分析植被指数等
    在一年中不同日期的平均变化规律。

    Args:
        image_collection_id: GEE ImageCollection ID
        region: 研究区
        band_names: 要分析的波段名列表
        start_date: 起始日期
        end_date: 结束日期
        output_path: PNG 输出路径
        scale: 采样分辨率
        title: 图表标题
        x_label/y_label: 轴标签
        colors: 自定义颜色列表

    Returns:
        {"success": bool, "message": str, "output_path": str, ...}
    """
    try:
        init_result = init_gee()
        if not init_result.get("success"):
            return {"success": False, "message": f"GEE 初始化失败: {init_result.get('message', '')}",
                    "requires": "gee_init"}

        from geemap import chart as ee_chart

        ee_region = _resolve_region(region)

        collection = (
            ee.ImageCollection(image_collection_id)
            .filterDate(start_date, end_date)
            .filterBounds(ee_region)
            .select(band_names)
        )

        count = collection.size().getInfo()
        if count == 0:
            return {"success": False, "message": f"集合在 {start_date}~{end_date} 无数据"}

        print(f"[GEE Charts] 物候分析：{count} 景影像...")

        if not title:
            title = f"年内日变化分析 - {', '.join(band_names)}"

        fig = ee_chart.image_doy_series(
            image_collection=collection,
            region=ee_region,
            scale=scale,
            chart_type="LineChart",
            title=title,
            x_label=x_label,
            y_label=y_label,
            colors=colors or ["#f0af07", "#0f8755", "#76b349"],
            stroke_width=5,
        )

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        fig.savefig(output_path, dpi=200, bbox_inches="tight", facecolor="white")
        print(f"[GEE Charts] 物候分析图已保存: {output_path}")

        return {
            "success": True,
            "message": f"物候分析图表已生成（{count} 景影像，{len(band_names)} 波段）",
            "output_path": output_path,
            "image_count": count,
            "band_names": band_names,
        }

    except Exception as e:
        return {"success": False, "message": f"物候分析图表生成失败: {e}"}
