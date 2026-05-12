"""
栅格检查模块 - 读取栅格元数据、波段统计、产品类型推断
"""

import os
from typing import Any, Dict, List

import numpy as np
import rasterio

from config import RASTER_EXTS


def _safe_stats(arr: np.ndarray) -> Dict[str, Any]:
    valid = arr[np.isfinite(arr)]
    if valid.size == 0:
        return {"count": 0}
    return {
        "count": int(valid.size),
        "min": float(np.min(valid)),
        "max": float(np.max(valid)),
        "mean": float(np.mean(valid)),
        "std": float(np.std(valid)),
        "p2": float(np.percentile(valid, 2)),
        "p98": float(np.percentile(valid, 98)),
    }


def _guess_product(meta: Dict[str, Any], band_stats: List[Dict[str, Any]]) -> Dict[str, Any]:
    """根据元数据和波段信息推断产品类型"""
    band_count = int(meta.get("band_count", 0))
    name = meta.get("name", "").lower()
    descriptions = " ".join(meta.get("descriptions") or []).lower()
    tags_text = " ".join(f"{k}:{v}" for k, v in (meta.get("tags") or {}).items()).lower()
    text = f"{name} {descriptions} {tags_text}"

    # Landsat 热红外
    if "landsat" in text and ("b10" in text or "tir" in text or "thermal" in text):
        return {"product_type": "Landsat 热红外产品", "ready_for_sca": True, "ready_for_thematic_map": band_count == 1}

    # Sentinel
    if "sentinel" in text:
        return {"product_type": "Sentinel 产品", "ready_for_sca": False, "ready_for_thematic_map": band_count in {1, 3}}

    # 已有 LST
    if "lst" in text or "land surface temperature" in text or "temperature" in text:
        return {"product_type": "LST 产品", "ready_for_sca": False, "ready_for_thematic_map": True}

    # NDVI
    if "ndvi" in text:
        return {"product_type": "NDVI 产品", "ready_for_sca": False, "ready_for_thematic_map": True}

    # 多波段（推测含热红外）
    if band_count >= 3:
        b3 = band_stats[2] if len(band_stats) > 2 else {}
        range3 = (b3.get("max", 0) - b3.get("min", 0)) if b3.get("count") else 0
        if range3 > 50 or any(x in text for x in ["thermal", "tir", "bt", "temperature", "亮度温度"]):
            return {
                "product_type": "可能含热红外的多波段影像",
                "ready_for_sca": True,
                "ready_for_thematic_map": False,
                "recommended_band_mapping": {"red": 1, "nir": 2, "brightness_temperature": 3},
            }

    # 多波段通用
    if band_count > 1:
        return {
            "product_type": f"{band_count} 波段影像",
            "ready_for_sca": band_count >= 3,
            "ready_for_thematic_map": False,
        }

    # 单波段
    if band_count == 1:
        return {"product_type": "单波段栅格", "ready_for_sca": False, "ready_for_thematic_map": True}

    return {"product_type": "未知栅格", "ready_for_sca": False, "ready_for_thematic_map": False}


def inspect_raster(path: str) -> Dict[str, Any]:
    """检查栅格文件的元数据和统计信息"""
    if not path or not os.path.exists(path):
        return {"success": False, "message": f"文件不存在: {path}"}

    ext = os.path.splitext(path)[1].lower()
    if ext not in RASTER_EXTS:
        return {"success": False, "message": f"暂不支持的栅格格式: {ext}"}

    try:
        with rasterio.open(path) as src:
            descriptions = [d or "" for d in src.descriptions]
            stats = []
            for idx in range(1, src.count + 1):
                arr = src.read(idx).astype("float32")
                nodata = src.nodata
                if nodata is not None:
                    arr = np.where(arr == nodata, np.nan, arr)
                s = _safe_stats(arr)
                s.update({
                    "band": idx,
                    "description": descriptions[idx - 1] if idx - 1 < len(descriptions) else "",
                    "dtype": str(src.dtypes[idx - 1]),
                })
                stats.append(s)

            metadata = {
                "path": path,
                "name": os.path.basename(path),
                "driver": src.driver,
                "width": int(src.width),
                "height": int(src.height),
                "shape": [int(src.height), int(src.width)],
                "band_count": int(src.count),
                "crs": str(src.crs) if src.crs else None,
                "bounds": [float(src.bounds.left), float(src.bounds.bottom),
                           float(src.bounds.right), float(src.bounds.top)],
                "res": [float(src.res[0]), float(src.res[1])],
                "nodata": None if src.nodata is None else float(src.nodata),
                "descriptions": descriptions,
                "tags": src.tags(),
            }

        metadata.update(_guess_product(metadata, stats))

        summary = {
            "path": metadata["path"],
            "band_count": metadata["band_count"],
            "product_type": metadata["product_type"],
            "ready_for_sca": metadata["ready_for_sca"],
            "ready_for_thematic_map": metadata["ready_for_thematic_map"],
        }

        return {
            "success": True,
            "message": "栅格检查完成",
            "path": path,
            "metadata": metadata,
            "band_stats": stats,
            "inspection_summary": summary,
        }
    except Exception as exc:
        return {"success": False, "message": str(exc)}