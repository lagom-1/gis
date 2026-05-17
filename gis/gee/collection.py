"""
GEE 影像筛选 + 云掩膜 + 合成
"""

from __future__ import annotations

import ee
from typing import Any


def mask_clouds_qa(image: ee.Image) -> ee.Image:
    """Landsat Collection 2 QA_PIXEL 云掩膜: Cloud(Bit3) + Cloud Shadow(Bit4)"""
    qa = image.select("QA_PIXEL")
    cloud_bit = 1 << 3
    shadow_bit = 1 << 4
    mask = qa.bitwiseAnd(cloud_bit).eq(0).And(qa.bitwiseAnd(shadow_bit).eq(0))
    return image.updateMask(mask)


def filter_collection(
    region_geom: Any,
    start_date: str,
    end_date: str,
    cloud_pct: float = 30,
) -> ee.ImageCollection:
    """筛选 Landsat 8/9 L2 Tier 1 影像，可选云量过滤"""
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
    col = l8.merge(l9)

    if cloud_pct < 100:
        col = col.filter(ee.Filter.lte("CLOUD_COVER", cloud_pct))

    return col


def reduce_collection(
    col: ee.ImageCollection,
    method: str = "median",
    mask_clouds: bool = True,
    region_geom: Any = None,
) -> ee.Image:
    """去云 + 中值/均值合成"""
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

    return img
