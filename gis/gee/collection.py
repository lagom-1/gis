"""
GEE 影像筛选 + 云掩膜 + 合成
"""

from __future__ import annotations

import ee
from typing import Any, Dict, List, Optional, Tuple

# Landsat C2 QA_PIXEL: Bit0 Fill, Bit1 Dilated Cloud, Bit2 Cirrus, Bit3 Cloud, Bit4 Shadow
_QA_PIXEL_MASK = int("11111", 2)

_DEFAULT_CLOUD_LEVELS = (30.0, 40.0, 60.0, 80.0, 100.0)


def mask_clouds_qa(image: ee.Image) -> ee.Image:
    """Landsat C2 QA_PIXEL 掩膜（对齐 geemap / USGS：Fill + 膨胀云 + 卷云 + 云 + 云影）"""
    qa_mask = image.select("QA_PIXEL").bitwiseAnd(_QA_PIXEL_MASK).eq(0)
    return image.updateMask(qa_mask)


def fill_holes(image: ee.Image, radius: int = 3) -> ee.Image:
    """用邻域均值填补云掩膜后的小空洞（约 3 像元 / ~90m）"""
    filled = image.focal_mean(radius=radius, kernelType="square", units="pixels")
    return image.unmask(filled)


def _base_landsat_collection(
    region_geom: Any,
    start_date: str,
    end_date: str,
) -> ee.ImageCollection:
    l8 = (
        ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
        .filterBounds(region_geom)
        .filterDate(start_date, end_date)
    )
    l9 = (
        ee.ImageCollection("LANDSAT/LC09/C02/T1_L2")
        .filterBounds(region_geom)
        .filterDate(start_date, end_date)
    )
    return l8.merge(l9)


def filter_collection(
    region_geom: Any,
    start_date: str,
    end_date: str,
    cloud_pct: float = 30,
    relax_if_empty: bool = True,
    max_scenes: int = 30,
) -> ee.ImageCollection:
    """
    筛选 Landsat 8/9 L2 Tier 1 影像。

    relax_if_empty=True 时，若目标云量无景，会按 30→40→60→80→100 放宽；
    景数过多时按 CLOUD_COVER 取云量最低的 max_scenes 景，利于 median 合成。
    """
    base = _base_landsat_collection(region_geom, start_date, end_date)

    if cloud_pct >= 100 and not relax_if_empty:
        return _limit_scenes(base, max_scenes)

    if not relax_if_empty:
        col = base
        if cloud_pct < 100:
            col = col.filter(ee.Filter.lte("CLOUD_COVER", cloud_pct))
        return _limit_scenes(col, max_scenes)

    levels: List[float] = sorted(set([float(cloud_pct), *_DEFAULT_CLOUD_LEVELS]))
    for level in levels:
        if level < float(cloud_pct):
            continue
        candidate = base
        if level < 100:
            candidate = candidate.filter(ee.Filter.lte("CLOUD_COVER", level))
        if candidate.size().getInfo() > 0:
            return _limit_scenes(candidate, max_scenes)

    return _limit_scenes(base, max_scenes)


def filter_collection_with_meta(
    region_geom: Any,
    start_date: str,
    end_date: str,
    cloud_pct: float = 30,
    relax_if_empty: bool = True,
    max_scenes: int = 30,
) -> Tuple[ee.ImageCollection, Dict[str, Any]]:
    """同 filter_collection，并返回实际使用的云量阈值与景数"""
    base = _base_landsat_collection(region_geom, start_date, end_date)
    used_cloud_pct = float(cloud_pct)
    col: Optional[ee.ImageCollection] = None

    if relax_if_empty:
        levels = sorted(set([float(cloud_pct), *_DEFAULT_CLOUD_LEVELS]))
        for level in levels:
            if level < float(cloud_pct):
                continue
            candidate = base
            if level < 100:
                candidate = candidate.filter(ee.Filter.lte("CLOUD_COVER", level))
            count = candidate.size().getInfo()
            if count > 0:
                used_cloud_pct = level
                col = _limit_scenes(candidate, max_scenes)
                break
    else:
        candidate = base
        if cloud_pct < 100:
            candidate = candidate.filter(ee.Filter.lte("CLOUD_COVER", cloud_pct))
        col = _limit_scenes(candidate, max_scenes)

    if col is None:
        col = _limit_scenes(base, max_scenes)

    count = col.size().getInfo()
    return col, {"used_cloud_pct": used_cloud_pct, "scene_count": count}


def _limit_scenes(col: ee.ImageCollection, max_scenes: int) -> ee.ImageCollection:
    if max_scenes and max_scenes > 0:
        return col.sort("CLOUD_COVER").limit(max_scenes)
    return col


def reduce_collection(
    col: ee.ImageCollection,
    method: str = "median",
    mask_clouds: bool = True,
    region_geom: Any = None,
    fill_holes_after: bool = True,
    fill_radius: int = 3,
) -> ee.Image:
    """去云 + 中值/均值合成 + 可选邻域填补空洞"""
    if mask_clouds:
        col = col.map(mask_clouds_qa)

    reducer = (method or "median").lower()
    if reducer == "mean":
        img = col.mean()
    elif reducer == "mosaic":
        img = col.mosaic()
    else:
        img = col.median()

    if region_geom:
        img = img.clip(region_geom)

    if fill_holes_after:
        img = fill_holes(img, radius=fill_radius)
        if region_geom:
            img = img.clip(region_geom)

    return img
