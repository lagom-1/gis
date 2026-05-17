"""
交互式时间滑块模块 - 使用 geemap 创建带时间滑块的交互式地图
基于 geemap notebook 62: time_slider

支持任意 ImageCollection，生成带滑块控件的 HTML 地图，
用户可以拖动滑块查看不同时期的影像变化。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import ee

from gis.gee.client import init_gee


def generate_time_slider_map(
    image_collection_id: str,
    region: Any,
    start_date: str,
    end_date: str,
    output_path: str,
    band_names: Optional[List[str]] = None,
    vis_params: Optional[Dict[str, Any]] = None,
    labels: Optional[List[str]] = None,
    time_interval: int = 1,
    opacity: float = 0.8,
    center_lat: Optional[float] = None,
    center_lon: Optional[float] = None,
    zoom: int = 8,
    title: str = "",
) -> Dict[str, Any]:
    """
    生成带时间滑块的交互式 HTML 地图。

    使用 geemap 的 add_time_slider 功能，在地图上添加滑块控件，
    用户可以拖动滑块查看 ImageCollection 中不同时期的影像。

    Args:
        image_collection_id: GEE ImageCollection ID
        region: 研究区（用于 filterBounds）
        start_date: 起始日期
        end_date: 结束日期
        output_path: HTML 输出路径
        band_names: 要选择的波段名列表
        vis_params: 可视化参数 {"min": ..., "max": ..., "palette": [...]}
        labels: 时间标签列表（与影像数量对应）
        time_interval: 时间间隔（秒），控制自动播放速度
        opacity: 图层透明度（0-1）
        center_lat/center_lon: 地图中心点
        zoom: 缩放级别
        title: 地图标题

    Returns:
        {"success": bool, "message": str, "output_path": str, ...}
    """
    try:
        init_result = init_gee()
        if not init_result.get("success"):
            return {"success": False, "message": f"GEE 初始化失败: {init_result.get('message', '')}",
                    "requires": "gee_init"}

        import geemap

        # ── 解析 region ──
        if isinstance(region, dict):
            from gis.gee_tools import _normalize_region
            ee_geom = _normalize_region(region=region)
        elif hasattr(region, "getInfo"):
            ee_geom = region
        else:
            return {"success": False, "message": f"无法识别的 region: {type(region).__name__}"}

        # ── 加载 ImageCollection ──
        collection = (
            ee.ImageCollection(image_collection_id)
            .filterDate(start_date, end_date)
            .filterBounds(ee_geom)
        )

        if band_names:
            collection = collection.select(band_names)

        count = collection.size().getInfo()
        if count == 0:
            return {
                "success": False,
                "message": f"集合 {image_collection_id} 在 {start_date}~{end_date} 无数据",
            }

        print(f"[TimeSlider] 找到 {count} 景影像，创建时间滑块地图...")

        # ── 默认可视化参数 ──
        if vis_params is None:
            vis_params = {"min": 0, "max": 1, "gamma": 1.4}

        # ── 创建标签 ──
        if labels is None:
            # 尝试从影像获取日期作为标签
            try:
                dates = collection.aggregate_array("system:time_start").getInfo()
                from datetime import datetime
                labels = [
                    datetime.fromtimestamp(d / 1000).strftime("%Y-%m-%d")
                    for d in dates
                ]
            except Exception:
                labels = [f"影像 {i+1}" for i in range(count)]

        # 限制标签数量与影像数量一致
        labels = labels[:count]

        # ── 创建地图 ──
        Map = geemap.Map()

        if center_lat is not None and center_lon is not None:
            Map.setCenter(center_lon, center_lat, zoom)
        else:
            Map.centerObject(ee_geom, zoom)

        # 添加第一个影像作为底图
        first = collection.first()
        Map.addLayer(first, vis_params, labels[0] if labels else "影像", shown=True, opacity=opacity)

        # 添加时间滑块
        Map.add_time_slider(
            collection,
            vis_params,
            labels=labels,
            time_interval=time_interval,
            opacity=opacity,
        )

        # ── 保存 HTML ──
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        Map.to_html(output_path)
        print(f"[TimeSlider] 时间滑块地图已保存: {output_path}")

        return {
            "success": True,
            "message": f"时间滑块地图已生成（{count} 景影像）",
            "output_path": output_path,
            "image_count": count,
            "labels": labels[:5],  # 返回前 5 个标签作为预览
            "collection_id": image_collection_id,
            "start_date": start_date,
            "end_date": end_date,
        }

    except Exception as e:
        return {"success": False, "message": f"时间滑块地图生成失败: {e}"}


def generate_weather_timeslider(
    region: Any,
    output_path: str,
    date: str = "2018-12-22",
    band: str = "temperature_2m_above_ground",
    vis_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    生成天气数据时间滑块（24 小时逐时温度）。

    便捷函数，使用 NOAA GFS 数据生成逐时温度滑块地图。

    Args:
        region: 研究区
        output_path: HTML 输出路径
        date: 日期 "YYYY-MM-DD"
        band: 波段名
        vis_params: 可视化参数

    Returns:
        {"success": bool, "message": str, "output_path": str, ...}
    """
    try:
        init_result = init_gee()
        if not init_result.get("success"):
            return {"success": False, "message": f"GEE 初始化失败", "requires": "gee_init"}

        import geemap

        if isinstance(region, dict):
            from gis.gee_tools import _normalize_region
            ee_geom = _normalize_region(region=region)
        elif hasattr(region, "getInfo"):
            ee_geom = region
        else:
            ee_geom = ee.Geometry.BBox(-180, -90, 180, 90)

        next_date = ee.Date(date).advance(1, "day").format("YYYY-MM-dd").getInfo()

        collection = (
            ee.ImageCollection("NOAA/GFS0P25")
            .filterDate(date, next_date)
            .limit(24)
            .select(band)
        )

        if vis_params is None:
            vis_params = {
                "min": -40.0,
                "max": 35.0,
                "palette": ["blue", "purple", "cyan", "green", "yellow", "red"],
            }

        labels = [str(n).zfill(2) + ":00" for n in range(24)]

        Map = geemap.Map()
        Map.setCenter(0, 25, 2)
        Map.add_time_slider(collection, vis_params, labels=labels, time_interval=1, opacity=0.8)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        Map.to_html(output_path)

        return {
            "success": True,
            "message": f"天气时间滑块已生成（{date}，24 小时）",
            "output_path": output_path,
            "date": date,
        }

    except Exception as e:
        return {"success": False, "message": f"天气时间滑块生成失败: {e}"}
