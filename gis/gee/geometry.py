"""
GEE 几何工具：GeoJSON → ee.Geometry 转换 + AOI 标准化
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

import ee


def load_geojson(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def geojson_to_ee_geometry(geojson: Dict[str, Any]) -> ee.Geometry:
    """
    纯本地将 GeoJSON dict 转为 ee.Geometry，不发 HTTP 请求。
    支持：
      - 直接 geometry: {"type": "Polygon", "coordinates": [...]}
      - Feature:       {"type": "Feature", "geometry": {...}}
      - FeatureCollection: 自动 union
    """
    if hasattr(geojson, "getInfo"):
        if hasattr(geojson, "geometry") and callable(geojson.geometry):
            try:
                return geojson.geometry()
            except Exception:
                return geojson
        return geojson

    if not isinstance(geojson, dict):
        raise ValueError(f"无法识别的 region 类型: {type(geojson).__name__}")

    geo_type = geojson.get("type", "")

    if geo_type == "Feature":
        inner = geojson.get("geometry")
        if not inner:
            raise ValueError("Feature 缺少 geometry 字段")
        return geojson_to_ee_geometry(inner)

    if geo_type == "FeatureCollection":
        features = geojson.get("features", [])
        if not features:
            raise ValueError("FeatureCollection 为空")
        geoms = [geojson_to_ee_geometry(f) for f in features]
        if len(geoms) == 1:
            return geoms[0]
        union = geoms[0]
        for g in geoms[1:]:
            union = union.union(g)
        return union

    VALID_GEOM_TYPES = {
        "Point", "MultiPoint", "LineString", "MultiLineString",
        "Polygon", "MultiPolygon", "GeometryCollection",
    }
    if geo_type in VALID_GEOM_TYPES:
        return ee.Geometry(geojson)

    raise ValueError(f"不支持的 GeoJSON 类型: {geo_type}")


def normalize_region(region: Any = None, region_path: Optional[str] = None) -> ee.Geometry:
    """
    支持三种 AOI 输入：
    1) bbox list: [xmin, ymin, xmax, ymax]
    2) GeoJSON dict (Feature / FeatureCollection / 直接 geometry)
    3) GeoJSON 文件路径
    """
    if region_path:
        if not os.path.exists(region_path):
            raise ValueError(f"region_path 不存在: {region_path}")
        region = load_geojson(region_path)

    if region is None:
        raise ValueError("缺少 region 或 region_path")

    if hasattr(region, "getInfo"):
        geom_method = getattr(region, "geometry", None)
        if callable(geom_method):
            try:
                return geom_method()
            except Exception:
                return region
        return region

    if isinstance(region, (list, tuple)) and len(region) == 4:
        xmin, ymin, xmax, ymax = [float(x) for x in region]
        return ee.Geometry.Rectangle([xmin, ymin, xmax, ymax])

    if isinstance(region, dict):
        return geojson_to_ee_geometry(region)

    raise ValueError("region 仅支持 bbox [xmin,ymin,xmax,ymax]、GeoJSON dict 或 region_path")
