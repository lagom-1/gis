"""
GEE 高级分析工具：时间序列提取、图表、分类、土地覆盖、分区统计、下载、时间滑块
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import config as app_config
from tools.base import BaseTool, tool


def _out_dir() -> Path:
    d = Path(app_config.OUTPUTS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ensure_gee(runtime) -> Dict[str, Any] | None:
    from gis.gee.client import init_gee
    r = init_gee()
    if not r.get("success"):
        return {"success": False, "message": f"GEE 未认证: {r.get('message', '')}", "requires": "gee_init"}
    return None


def _resolve_roi(runtime, args: Dict[str, Any]) -> tuple:
    roi = args.get("region") or runtime.last_region_geojson
    if roi is None:
        return None, {"success": False, "message": "缺少研究区。请先用 resolve_admin_region 解析。"}
    try:
        from gis.gee_tools import _normalize_region
        return _normalize_region(region=roi), None
    except Exception as e:
        return None, {"success": False, "message": f"研究区转换失败: {e}"}


@tool(
    name="extract_timeseries_to_point",
    description="从 GEE ImageCollection 提取指定经纬度点的时间序列数据，输出 CSV 和折线图。",
    parameters={
        "lat": "纬度",
        "lon": "经度",
        "image_collection_id": "GEE ImageCollection ID，如 ECMWF/ERA5_LAND/DAILY_AGGR",
        "band_names": "要提取的波段名列表，如 [temperature_2m]",
        "start_date": "起始日期 YYYY-MM-DD",
        "end_date": "结束日期 YYYY-MM-DD",
        "scale": "采样分辨率（米），默认 1000",
        "title": "图表标题",
    },
    category="analysis",
)
class ExtractTimeseriesTool(BaseTool):
    def execute(self, lat, lon, image_collection_id="ECMWF/ERA5_LAND/DAILY_AGGR",
                band_names=None, start_date="2020-01-01", end_date="2020-12-31",
                scale=1000, title="", reducer="mean", point_buffer_m=0) -> Dict[str, Any]:
        err = _ensure_gee(self.runtime)
        if err:
            return err
        from gis.timeseries_extract import extract_timeseries_to_point
        name = self.runtime.last_region_name or f"{lat}_{lon}"
        csv_path = str(_out_dir() / f"timeseries_{name}.csv")
        png_path = str(_out_dir() / f"timeseries_{name}.png")
        result = extract_timeseries_to_point(
            lat=float(lat), lon=float(lon),
            image_collection_id=image_collection_id,
            band_names=band_names or ["temperature_2m"],
            start_date=start_date, end_date=end_date,
            scale=int(scale), output_csv=csv_path, output_png=png_path,
            title=title, reducer=reducer, point_buffer_m=int(point_buffer_m),
        )
        if result.get("success"):
            self.runtime.last_output = result.get("png_path")
        return result


@tool(
    name="dynamic_world_landcover",
    description="获取 Dynamic World 10m 分辨率全球土地覆盖分类（9类：水体/树木/草地/淹没植被/农作物/灌木/建筑/裸地/冰雪）。",
    parameters={
        "start_date": "起始日期", "end_date": "结束日期",
        "return_type": "class（原始分类值）或 hillshade（带阴影可视化）",
        "scale": "导出分辨率，默认 10", "title": "专题图标题",
    },
    category="analysis",
)
class DynamicWorldTool(BaseTool):
    def execute(self, start_date="2021-01-01", end_date="2022-01-01",
                return_type="class", scale=10, title="") -> Dict[str, Any]:
        err = _ensure_gee(self.runtime)
        if err:
            return err
        ee_geom, err2 = _resolve_roi(self.runtime, {})
        if err2:
            return err2
        name = self.runtime.last_region_name or "dw"
        tif_path = str(_out_dir() / f"{name}_dynamic_world.tif")
        png_path = str(_out_dir() / f"{name}_dynamic_world.png")
        try:
            from gis.dynamic_world import dynamic_world_landcover
            result = dynamic_world_landcover(
                region=ee_geom, start_date=start_date, end_date=end_date,
                output_tif=tif_path, output_png=png_path,
                return_type=return_type, scale=int(scale), title=title,
            )
        except Exception as e:
            msg = str(e)
            return {
                "success": False,
                "message": f"GEE Dynamic World 不可用（{msg[:100]}）。建议改用本地工具：classify_map 或 ee_unsupervised_classify 对已有数据进行分类。不要重试 dynamic_world_landcover！",
            }
        if result.get("success"):
            self.runtime.last_tif_output = result.get("output_tif")
            self.runtime.last_output = result.get("output_png")
        return result


@tool(
    name="ee_unsupervised_classify",
    description="在 GEE 端执行无监督分类（K-Means 聚类），自动采样训练数据并分类，输出 TIF 和专题图。",
    parameters={
        "n_clusters": "聚类数，默认 5", "scale": "分辨率，默认 30",
        "start_date": "日期范围起始", "end_date": "日期范围结束",
        "band_names": "分类波段列表", "title": "专题图标题",
    },
    category="analysis",
)
class UnsupervisedClassifyTool(BaseTool):
    def execute(self, n_clusters=5, scale=30, start_date=None, end_date=None,
                band_names=None, title="", num_pixels=5000) -> Dict[str, Any]:
        err = _ensure_gee(self.runtime)
        if err:
            return err
        ee_geom, err2 = _resolve_roi(self.runtime, {})
        if err2:
            return err2
        from gis.ee_classification import ee_unsupervised_classify
        name = self.runtime.last_region_name or "classify"
        tif_path = str(_out_dir() / f"{name}_unsupervised.tif")
        png_path = str(_out_dir() / f"{name}_unsupervised.png")
        result = ee_unsupervised_classify(
            region=ee_geom, n_clusters=int(n_clusters), scale=int(scale),
            start_date=start_date, end_date=end_date,
            band_names=band_names, output_tif=tif_path, output_png=png_path,
            title=title, num_pixels=int(num_pixels),
        )
        if result.get("success"):
            self.runtime.last_tif_output = result.get("output_tif")
            self.runtime.last_output = result.get("output_png")
        return result


@tool(
    name="generate_timeslider_map",
    description="生成带时间滑块的交互式 HTML 地图，用户可拖动滑块查看不同时期的影像变化。",
    parameters={
        "image_collection_id": "GEE ImageCollection ID",
        "start_date": "起始日期", "end_date": "结束日期",
        "band_names": "波段名列表", "opacity": "透明度，默认 0.8",
    },
    category="visualization",
)
class TimeSliderTool(BaseTool):
    def execute(self, image_collection_id="NOAA/GFS0P25",
                start_date="2018-12-22", end_date="2018-12-23",
                band_names=None, opacity=0.8, time_interval=1,
                center_lat=None, center_lon=None, zoom=8) -> Dict[str, Any]:
        err = _ensure_gee(self.runtime)
        if err:
            return err
        ee_geom, err2 = _resolve_roi(self.runtime, {})
        if err2:
            return err2
        from gis.time_slider import generate_time_slider_map
        name = self.runtime.last_region_name or "timeslider"
        output_path = str(_out_dir() / f"{name}_time_slider.html")
        result = generate_time_slider_map(
            image_collection_id=image_collection_id,
            region=ee_geom, start_date=start_date, end_date=end_date,
            output_path=output_path, band_names=band_names,
            time_interval=int(time_interval), opacity=float(opacity),
            center_lat=center_lat, center_lon=center_lon, zoom=int(zoom),
        )
        if result.get("success"):
            self.runtime.last_output = output_path
        return result


@tool(
    name="gee_zonal_statistics",
    description="按区域计算影像的分区统计量（mean/min/max/std/sum），输出 CSV。支持行政区划统计。",
    parameters={
        "image_id": "GEE 影像 ID 或本地 TIF 路径",
        "stat_type": "统计类型 mean/min/max/median/std/sum，默认 MEAN",
        "scale": "分析分辨率（米），默认 1000",
    },
    category="analysis",
)
class ZonalStatsTool(BaseTool):
    def execute(self, image_id=None, stat_type="MEAN", scale=1000) -> Dict[str, Any]:
        import ee
        err = _ensure_gee(self.runtime)
        if err:
            return err
        image_input = image_id or self.runtime.current_tif()
        if not image_input:
            return {"success": False, "message": "缺少影像参数（image_id 或 tif_path）"}
        roi = self.runtime.last_region_geojson
        if roi is None:
            return {"success": False, "message": "缺少研究区"}
        from gis.gee_tools import _normalize_region
        from gis.zonal_stats import gee_zonal_statistics
        try:
            ee_geom = _normalize_region(region=roi)
            ee_fc = ee.FeatureCollection([ee.Feature(ee_geom)])
        except Exception as e:
            return {"success": False, "message": f"区域转换失败: {e}"}
        name = self.runtime.last_region_name or "zonal"
        csv_path = str(_out_dir() / f"{name}_zonal_stats.csv")
        result = gee_zonal_statistics(
            image=image_input, regions=ee_fc, output_csv=csv_path,
            stat_type=stat_type, scale=int(scale),
        )
        if result.get("success"):
            self.runtime.last_output = csv_path
        return result
