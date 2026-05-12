"""
分区统计模块 - 按行政区划计算 GEE 影像的统计量
基于 geemap notebook 12: zonal_statistics

使用 ee.Image.reduceRegions() 按 FeatureCollection 中的每个区域
计算 mean、min、max、std、sum 等统计量，输出 CSV。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import ee

from agent.gee_client import init_gee


# 支持的统计类型映射
_STAT_TYPE_MAP = {
    "mean": ee.Reducer.mean(),
    "MEAN": ee.Reducer.mean(),
    "min": ee.Reducer.min(),
    "MINIMUM": ee.Reducer.min(),
    "max": ee.Reducer.max(),
    "MAXIMUM": ee.Reducer.max(),
    "median": ee.Reducer.median(),
    "MEDIAN": ee.Reducer.median(),
    "std": ee.Reducer.stdDev(),
    "STD": ee.Reducer.stdDev(),
    "sum": ee.Reducer.sum(),
    "SUM": ee.Reducer.sum(),
    "min_max": ee.Reducer.minMax(),
    "MIN_MAX": ee.Reducer.minMax(),
    "variance": ee.Reducer.variance(),
    "VARIANCE": ee.Reducer.variance(),
}


def _get_reducer(stat_type: str) -> ee.Reducer:
    """根据统计类型名称返回对应的 ee.Redducer"""
    reducer = _STAT_TYPE_MAP.get(stat_type)
    if reducer is None:
        raise ValueError(
            f"不支持的统计类型: {stat_type}。"
            f"支持: {list(set(k.lower() for k in _STAT_TYPE_MAP.keys()))}"
        )
    return reducer


def _resolve_regions(regions: Any) -> ee.FeatureCollection:
    """统一处理 regions 参数"""
    if hasattr(regions, "getInfo"):
        return regions
    if isinstance(regions, dict):
        geo_type = regions.get("type", "")
        if geo_type == "FeatureCollection":
            return ee.FeatureCollection(regions)
        if geo_type == "Feature":
            return ee.FeatureCollection([ee.Feature(regions)])
    raise ValueError(f"无法识别的 regions 类型: {type(regions).__name__}")


def gee_zonal_statistics(
    image: Any,
    regions: Any,
    output_csv: str,
    stat_type: str = "MEAN",
    scale: int = 1000,
    label_property: Optional[str] = None,
    tile_scale: int = 1,
) -> Dict[str, Any]:
    """
    按区域计算影像的分区统计量。

    使用 ee.Image.reduceRegions() 对 FeatureCollection 中每个 Feature
    计算指定统计量，结果保存为 CSV 文件。

    Args:
        image: 输入影像（ee.Image 或 GEE 影像 ID 字符串）
        regions: 区域 FeatureCollection（如行政区划）
        output_csv: CSV 输出路径
        stat_type: 统计类型，支持 mean/min/max/median/std/sum/min_max/variance
        scale: 分析分辨率（米）
        label_property: 用于标识区域的属性名（如 "NAME"）
        tile_scale: 并行度缩放因子（处理大区域时增大）

    Returns:
        {"success": bool, "message": str, "output_csv": str, "stats": dict, ...}
    """
    try:
        init_result = init_gee()
        if not init_result.get("success"):
            return {"success": False, "message": f"GEE 初始化失败: {init_result.get('message', '')}",
                    "requires": "gee_init"}

        # ── 解析 image ──
        if isinstance(image, str):
            ee_image = ee.Image(image)
        elif hasattr(image, "getInfo"):
            ee_image = image
        else:
            return {"success": False, "message": f"无法识别的 image 类型: {type(image).__name__}"}

        # ── 解析 regions ──
        ee_regions = _resolve_regions(regions)

        # ── 获取 reducer ──
        reducer = _get_reducer(stat_type)

        # ── 获取波段名 ──
        band_names = ee_image.bandNames().getInfo()
        if not band_names:
            return {"success": False, "message": "影像无波段"}

        print(f"[ZonalStats] 对 {len(band_names)} 个波段执行 {stat_type} 统计...")

        # ── 执行分区统计 ──
        stats = ee_image.reduceRegions(
            collection=ee_regions,
            reducer=reducer,
            scale=scale,
            tileScale=tile_scale,
        )

        # ── 获取结果 ──
        print("[ZonalStats] 获取统计结果...")
        stats_info = stats.getInfo()

        features = stats_info.get("features", [])
        if not features:
            return {"success": False, "message": "统计结果为空，请检查影像和区域是否重叠。"}

        # ── 解析为表格数据 ──
        import pandas as pd

        rows = []
        for feat in features:
            props = feat.get("properties", {})
            row = {}

            # 区域标签
            if label_property and label_property in props:
                row["region_name"] = props[label_property]
            else:
                # 尝试常见属性名
                for key in ["NAME", "name", "NAME_1", "NAME_2", "ADM1_NAME", "ADM2_NAME", "label"]:
                    if key in props:
                        row["region_name"] = props[key]
                        break
                if "region_name" not in row:
                    row["region_name"] = f"区域_{len(rows) + 1}"

            # 统计值
            for band in band_names:
                stat_key = f"{band}_{stat_type.lower()}"
                if stat_key in props:
                    row[band] = props[stat_key]
                elif band in props:
                    row[band] = props[band]
                else:
                    # 尝试直接匹配
                    for key, val in props.items():
                        if band in key:
                            row[band] = val
                            break

            rows.append(row)

        df = pd.DataFrame(rows)

        # ── 保存 CSV ──
        os.makedirs(os.path.dirname(output_csv) or ".", exist_ok=True)
        df.to_csv(output_csv, index=False, encoding="utf-8-sig")
        print(f"[ZonalStats] CSV 已保存: {output_csv} ({len(df)} 条记录)")

        # ── 生成统计摘要 ──
        summary = {}
        for band in band_names:
            if band in df.columns:
                vals = df[band].dropna()
                if not vals.empty:
                    summary[band] = {
                        "count": len(vals),
                        "mean": round(float(vals.mean()), 4),
                        "min": round(float(vals.min()), 4),
                        "max": round(float(vals.max()), 4),
                        "std": round(float(vals.std()), 4) if len(vals) > 1 else 0,
                    }

        return {
            "success": True,
            "message": f"分区统计完成：{len(df)} 个区域，{len(band_names)} 个波段，统计类型 {stat_type}",
            "output_csv": output_csv,
            "region_count": len(df),
            "band_names": band_names,
            "stat_type": stat_type,
            "scale": scale,
            "summary": summary,
        }

    except Exception as e:
        return {"success": False, "message": f"分区统计失败: {e}"}


def gee_zonal_stats_admin(
    image: Any,
    admin_region_name: str,
    output_csv: str,
    stat_type: str = "MEAN",
    admin_level: str = "county",
    scale: int = 1000,
    label_property: Optional[str] = None,
) -> Dict[str, Any]:
    """
    按中国行政区划计算分区统计的便捷函数。

    自动解析行政区名称，加载对应的 GeoJSON 边界，
    然后调用 gee_zonal_statistics 执行统计。

    Args:
        image: 输入影像（ee.Image 或 ID 字符串）
        admin_region_name: 行政区名称（如 "四川省"、"温江区"）
        output_csv: CSV 输出路径
        stat_type: 统计类型
        admin_level: 行政级别 province/city/county
        scale: 分析分辨率
        label_property: 区域标识属性名

    Returns:
        {"success": bool, "message": str, "output_csv": str, ...}
    """
    try:
        # ── 解析行政区 ──
        from gis.admin_region import resolve_admin_region
        region_result = resolve_admin_region(admin_region_name)

        if not region_result.get("success"):
            return {
                "success": False,
                "message": f"行政区解析失败: {region_result.get('message', '')}",
            }

        region_geojson = region_result.get("region_geojson")
        if not region_geojson:
            return {"success": False, "message": "行政区 GeoJSON 为空"}

        # 转为 ee.FeatureCollection
        ee_geom = ee.Geometry(region_geojson.get("geometry", region_geojson))
        ee_feature = ee.Feature(ee_geom, {"NAME": region_result.get("matched_name", admin_region_name)})
        ee_fc = ee.FeatureCollection([ee_feature])

        # ── 执行统计 ──
        if label_property is None:
            label_property = "NAME"

        return gee_zonal_statistics(
            image=image,
            regions=ee_fc,
            output_csv=output_csv,
            stat_type=stat_type,
            scale=scale,
            label_property=label_property,
        )

    except Exception as e:
        return {"success": False, "message": f"行政区划统计失败: {e}"}
