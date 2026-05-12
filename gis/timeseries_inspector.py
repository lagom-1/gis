"""
时间序列对比检查器模块 - 使用 geemap ts_inspector 创建分屏对比交互式地图
基于 geemap notebook 20: timeseries_inspector

支持逐年/逐月影像对比，生成带下拉选择的分屏 HTML 地图
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import ee

from agent.gee_client import init_gee


def _create_landsat_annual_composites(
    roi: ee.Geometry,
    start_year: int,
    end_year: int,
    start_mmdd: str = "01-01",
    end_mmdd: str = "12-31",
    cloud_pct: float = 30,
) -> ee.ImageCollection:
    """创建 Landsat 逐年合成影像集合"""
    images = []
    for year in range(start_year, end_year + 1):
        s = f"{year}-{start_mmdd}"
        e = f"{year}-{end_mmdd}"

        col8 = (
            ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
            .filterBounds(roi)
            .filterDate(s, e)
            .filter(ee.Filter.lte("CLOUD_COVER", cloud_pct))
        )
        col9 = (
            ee.ImageCollection("LANDSAT/LC09/C02/T1_L2")
            .filterBounds(roi)
            .filterDate(s, e)
            .filter(ee.Filter.lte("CLOUD_COVER", cloud_pct))
        )
        merged = col8.merge(col9)

        count = merged.size().getInfo()
        if count == 0:
            print(f"[Inspector] {year}年无可用影像，跳过")
            continue

        # 云掩膜
        def mask_clouds(img):
            qa = img.select("QA_PIXEL")
            mask = qa.bitwiseAnd(1 << 3).eq(0).And(qa.bitwiseAnd(1 << 4).eq(0))
            return img.updateMask(mask)

        merged = merged.map(mask_clouds)

        # 转为反射率并合成
        def scale_l2(img):
            optical = img.select("SR_B[1-7]").multiply(0.0000275).add(-0.2)
            return optical.copyProperties(img, img.propertyNames())

        composite = merged.map(scale_l2).median().clip(roi)
        composite = composite.set("system:time_start", ee.Date(f"{year}-07-01").millis())
        composite = composite.set("label", str(year))
        images.append(composite)

    if not images:
        raise ValueError(f"{start_year}-{end_year}年间无可用 Landsat 影像")

    return ee.ImageCollection(images)


def timeseries_inspector(
    roi: Any,
    output_path: str,
    image_collection_id: Optional[str] = None,
    start_year: int = 2015,
    end_year: int = 2024,
    start_mmdd: str = "01-01",
    end_mmdd: str = "12-31",
    band_names: Optional[List[str]] = None,
    vis_params: Optional[Dict[str, Any]] = None,
    cloud_pct: float = 30,
    center_zoom: int = 10,
) -> Dict[str, Any]:
    """
    创建时间序列对比检查器（分屏交互式 HTML 地图）。

    使用 geemap 的 ts_inspector 功能，生成左右两屏带下拉菜单的对比地图。
    用户可以选择不同年份/时期进行对比。

    Args:
        roi: ee.Geometry 研究区
        output_path: HTML 输出路径
        image_collection_id: 可选，自定义 GEE ImageCollection ID。
                           为 None 时使用 Landsat 合成。
        start_year: 起始年份
        end_year: 结束年份
        start_mmdd: 每年采样起始月日
        end_mmdd: 每年采样结束月日
        band_names: 波段名称列表（用于自定义集合）
        vis_params: 可视化参数
        cloud_pct: 云量阈值（仅 Landsat 模式）
        center_zoom: 地图缩放级别

    Returns:
        {"success": bool, "message": str, "output_path": str, ...}
    """
    try:
        init_result = init_gee()
        if not init_result.get("success"):
            return {
                "success": False,
                "message": f"GEE 初始化失败: {init_result.get('message', '')}",
                "requires": "gee_init",
            }

        import geemap

        # ── 准备影像集合 ──
        if image_collection_id:
            # 使用自定义 ImageCollection
            collection = ee.ImageCollection(image_collection_id)
            if band_names:
                collection = collection.select(band_names)
            # 按年份过滤
            collection = collection.filterDate(
                f"{start_year}-01-01", f"{end_year + 1}-01-01"
            ).filterBounds(roi)

            count = collection.size().getInfo()
            if count == 0:
                return {
                    "success": False,
                    "message": f"集合 {image_collection_id} 在 {start_year}-{end_year} 无数据",
                }

            # 按年创建合成
            ts_images = []
            for year in range(start_year, end_year + 1):
                yearly = collection.filterDate(
                    f"{year}-{start_mmdd}", f"{year}-{end_mmdd}"
                )
                if yearly.size().getInfo() > 0:
                    composite = yearly.median().clip(roi)
                    composite = composite.set("system:time_start",
                                              ee.Date(f"{year}-07-01").millis())
                    composite = composite.set("label", str(year))
                    ts_images.append(composite)

            if not ts_images:
                return {"success": False, "message": "未生成任何有效合成影像"}

            ts_collection = ee.ImageCollection(ts_images)
            layer_names = [str(y) for y in range(start_year, end_year + 1)
                           if any(f.get("properties", {}).get("label") == str(y)
                                  for f in ts_collection.getInfo().get("features", []))]
        else:
            # 使用 Landsat 合成
            print(f"[Inspector] 创建 Landsat {start_year}-{end_year} 年度合成...")
            ts_collection = _create_landsat_annual_composites(
                roi, start_year, end_year, start_mmdd, end_mmdd, cloud_pct
            )
            layer_names = [f"Landsat {y}" for y in range(start_year, end_year + 1)]

        # ── 默认可视化参数 ──
        if vis_params is None:
            if image_collection_id:
                vis_params = {"min": 0, "max": 1, "gamma": 1.4}
            else:
                vis_params = {
                    "min": 0,
                    "max": 0.3,
                    "gamma": [1, 1, 1],
                    "bands": ["SR_B5", "SR_B4", "SR_B3"],
                }

        # ── 获取实际可用的图层名 ──
        actual_count = ts_collection.size().getInfo()
        layer_names = layer_names[:actual_count]

        if len(layer_names) < 2:
            return {
                "success": False,
                "message": f"有效影像数量不足（仅 {len(layer_names)} 景），至少需要 2 景才能对比。",
            }

        # ── 创建分屏地图 ──
        print(f"[Inspector] 创建分屏对比地图（{len(layer_names)} 个时期）...")
        Map = geemap.Map()
        Map.ts_inspector(
            left_ts=ts_collection,
            right_ts=ts_collection,
            left_names=layer_names,
            right_names=layer_names,
            left_vis=vis_params,
            right_vis=vis_params,
        )
        Map.centerObject(roi, zoom=center_zoom)

        # ── 保存 HTML ──
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        Map.to_html(output_path)
        print(f"[Inspector] 分屏对比地图已保存: {output_path}")

        return {
            "success": True,
            "message": f"时间序列对比检查器已生成：{len(layer_names)} 个时期",
            "output_path": output_path,
            "layer_count": len(layer_names),
            "layer_names": layer_names,
            "start_year": start_year,
            "end_year": end_year,
        }

    except Exception as e:
        return {"success": False, "message": f"时间序列检查器生成失败: {e}"}
