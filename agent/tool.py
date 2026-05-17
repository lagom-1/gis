"""
工具构建模块 - 注册所有 GIS 工具到 ToolRegistry
统一管理工具的规格定义和处理器实现

【修改】新增 GEE 时间序列工具（timelapse / split_panel / trend_chart）
【修复】GISRuntime.reset_for_new_task() 仅重置跨任务易污染的状态
"""

from __future__ import annotations

import os
import re
from datetime import date, timedelta
from pathlib import Path

from typing import Any, Dict

from config import WORKSPACE_DIR, DEFAULT_MAP_STYLE, GEE_DRIVE_FOLDER, GDRIVE_SYNC_DIR
import config as app_config
from agent.tool_registry import ToolRegistry, ToolSpec

# ── GIS 处理模块 ──────────────────────────────────────
from gis.sca_runner import run_sca
from gis.statistics import analyze_raster
from gis.cartographic_map import generate_cartographic_map
from gis.classify import classify_raster
from gis.threshold import threshold_highlight
from gis.enhance import enhance_raster
from gis.profile import profile_analysis
from gis.view3d import render_3d
from gis.compare import compare_views
from gis.transform import transform_raster
from gis.export import export_image
from gis.inspect import inspect_raster
from gis.file_discovery import find_local_files
from gis.report import generate_html_report, try_convert_pdf
from gis.web_map import generate_web_map, generate_timelapse_web_map
from gis.admin_region import resolve_admin_region

# ── GEE / geemap 工具 ─────────────────────────────────
from gis.gee_tools import gee_init, gee_compute_lst, gee_download_landsat_sca, gee_download_monthly_lst, gee_download_yearly_lst, gee_download_multi_year_lst

# ── GEE 时间序列工具（新增）────────────────────────────
from gis.gee_timelapse import (
    generate_lst_timelapse,
    generate_lst_timelapse_local,
    generate_lst_split_panel,
    generate_lst_trend_chart,
    parse_month,
)

# ── A1: 点位时间序列提取 ──────────────────────────────
from gis.timeseries_extract import extract_timeseries_to_point

# ── A2: 时间序列对比检查器 ────────────────────────────
from gis.timeseries_inspector import timeseries_inspector

# ── A3: 丰富图表类型 ─────────────────────────────────
from gis.gee_charts import gee_chart_timeseries, gee_chart_by_region, gee_chart_phenology

# ── A4: Dynamic World 土地覆盖 ────────────────────────
from gis.dynamic_world import dynamic_world_landcover

# ── A5: 增强下载（在 gee_tools.py 中）─────────────────
from gis.gee_tools import gee_download_image_collection, gee_download_tiled

# ── A6: 交互式时间滑块 ───────────────────────────────
from gis.time_slider import generate_time_slider_map

# ── A7: GEE 端分类 ───────────────────────────────────
from gis.ee_classification import ee_unsupervised_classify, ee_supervised_classify

# ── A8: 分区统计 ─────────────────────────────────────
from gis.zonal_stats import gee_zonal_statistics


class GISRuntime:
    """运行时状态：当前数据集、上次输出、地图样式、最近解析的行政区"""

    def __init__(self) -> None:
        self.current_dataset: str | None = None
        self.source_dataset: str | None = None
        self.last_output: str | None = None
        self.last_tif_output: str | None = None
        self.last_region_geojson: Dict[str, Any] | None = None
        self.last_region_name: str | None = None
        self.map_style: Dict[str, Any] = dict(DEFAULT_MAP_STYLE)

    def reset_for_new_task(self) -> None:
        """
        新任务开始时重置跨任务易污染的状态。
        防止上一个任务的行政区边界、数据集等泄漏到新任务中。

        修复：跨任务状态污染问题 - last_region_geojson 等状态在新任务中
        必须清空，否则前一个任务的行政区边界会被错误地用于新任务。
        """
        self.current_dataset = None
        self.source_dataset = None
        self.last_region_geojson = None
        self.last_region_name = None
        # last_output 和 map_style 保留，因为它们属于会话级偏好

    def current_tif(self) -> str | None:
        if self.current_dataset and os.path.exists(self.current_dataset):
            return self.current_dataset
        if self.last_tif_output and os.path.exists(self.last_tif_output):
            return self.last_tif_output
        return None


def _safe_stem(path: str | None, fallback: str = "result") -> str:
    if path:
        return Path(path).stem
    return fallback


def _sanitize_filename(name: str) -> str:
    """移除文件名中不允许的字符"""
    return re.sub(r'[\\/:*?"<>|\s]+', '_', name).strip('_')


def build_task_filename(
    region_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    year: int | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    month: int | None = None,
    product: str = "LST",
    quality: str | None = None,
    suffix: str = ".tif",
) -> str:
    """
    生成可读的任务输出文件名。

    示例：
      build_task_filename(region_name="旺苍县", start_date="2024-07-01", end_date="2024-07-31", product="LST")
        → "旺苍县_2024年7月_LST.tif"
      build_task_filename(region_name="旺苍县", year=2025, product="LST")
        → "旺苍县_2025年全年_LST"
      build_task_filename(region_name="旺苍县", start_year=2020, end_year=2025, month=8, product="LST")
        → "旺苍县_2020-2025年8月_LST"
      build_task_filename(region_name="温江区", start_date="2024-07-01", end_date="2024-07-31", product="Landsat_SCA")
        → "温江区_2024年7月_Landsat_SCA.tif"
    """
    parts = []

    # 区域名
    if region_name:
        # 只取最后一级名称（如"四川省广元市旺苍县" → "旺苍县"）
        best_idx = -1
        for sep in ["省", "市", "区", "县", "旗"]:
            idx = region_name.rfind(sep)
            # 只取不在字符串末尾的分隔符（防止"旺苍县"→""）
            if idx > best_idx and idx < len(region_name) - 1:
                best_idx = idx
        if best_idx >= 0:
            region_name = region_name[best_idx + 1:]
        parts.append(_sanitize_filename(region_name))

    # 时间信息
    if start_year and end_year and month:
        parts.append(f"{start_year}-{end_year}年{month}月")
    elif year and not start_date:
        parts.append(f"{year}年全年")
    elif start_date and end_date:
        from datetime import datetime
        try:
            sd = datetime.strptime(start_date, "%Y-%m-%d")
            ed = datetime.strptime(end_date, "%Y-%m-%d")
            if sd.year == ed.year and sd.month == ed.month:
                parts.append(f"{sd.year}年{sd.month}月")
            else:
                parts.append(f"{start_date}_至_{end_date}")
        except ValueError:
            parts.append(f"{start_date}_至_{end_date}")

    # 产品类型
    parts.append(product)

    # 质量等级（可选）
    if quality:
        parts.append(f"质量{quality}")

    name = "_".join(parts)
    if suffix and not name.endswith(suffix):
        name += suffix
    return name


def _default_last_full_month() -> tuple[str, str]:
    """
    默认时间范围：上一个完整自然月
    例如当前是 2026-04-20，则返回 2026-03-01 ~ 2026-03-31
    """
    today = date.today()
    first_day_this_month = today.replace(day=1)
    last_day_prev_month = first_day_this_month - timedelta(days=1)
    first_day_prev_month = last_day_prev_month.replace(day=1)
    return first_day_prev_month.isoformat(), last_day_prev_month.isoformat()


def register_tools(registry: ToolRegistry, runtime: GISRuntime, preferences: Dict[str, Any]) -> None:
    """将所有工具注册到 registry 中"""
    def out_dir() -> Path:
        """动态获取输出目录，跟随 config.OUTPUTS_DIR 的切换"""
        d = Path(app_config.OUTPUTS_DIR)
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ─────────────────────────────────────────────────────
    # 数据发现工具
    # ─────────────────────────────────────────────────────

    def search_local_files_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        query = args.get("query") or args.get("name") or ""
        roots = args.get("roots")
        extensions = args.get("extensions")
        return find_local_files(query=query, roots=roots, extensions=extensions)

    def set_current_dataset(args: Dict[str, Any]) -> Dict[str, Any]:
        path = args.get("path")
        if not path or not os.path.exists(path):
            return {"success": False, "message": f"文件不存在: {path}"}
        runtime.current_dataset = path
        if runtime.source_dataset is None:
            runtime.source_dataset = path
        return {"success": True, "message": "当前数据已切换", "path": path, "selected_path": path}

    def inspect_current_or_path(args: Dict[str, Any]) -> Dict[str, Any]:
        path = args.get("path") or runtime.current_tif()
        return inspect_raster(path)

    def resolve_admin_region_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        region_name = args.get("region_name")
        result = resolve_admin_region(region_name)
        if result.get("success"):
            runtime.last_region_geojson = result.get("region_geojson")
            runtime.last_region_name = result.get("matched_name")
        return result

    # ─────────────────────────────────────────────────────
    # GEE / geemap 工具
    # ─────────────────────────────────────────────────────

    def gee_init_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        return gee_init(
            project_id=args.get("project_id"),
            force_auth=bool(args.get("force_auth", False)),
        )

    def gee_download_landsat_sca_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        start_date = args.get("start_date")
        end_date = args.get("end_date")

        if not start_date or not end_date:
            start_date, end_date = _default_last_full_month()

        # ── 关键检查：region 不能为 None，禁止静默回退到旧区域 ──
        region = args.get("region")
        if region is None:
            # 仅当当前任务已通过 resolve_admin_region 设置了区域时才允许使用
            region = runtime.last_region_geojson
        if region is None:
            return {
                "success": False,
                "message": (
                    "缺少研究区边界（region）。"
                    "如果是行政区名称（如'温江区'），请先调用 resolve_admin_region 解析边界；"
                    "如果是 bbox 坐标，请直接传入 region=[xmin,ymin,xmax,ymax]。"
                ),
                "requires": "resolve_admin_region 或 region 参数",
            }

        region_name = runtime.last_region_name or ""
        filename = build_task_filename(region_name=region_name, start_date=start_date, end_date=end_date, product="Landsat_SCA")
        output_tif = args.get("output_tif") or str(out_dir() / filename)

        result = gee_download_landsat_sca(
            start_date=start_date,
            end_date=end_date,
            output_tif=output_tif,
            region=region,
            region_path=args.get("region_path"),
            scale=int(args.get("scale", 30)),
            reducer=args.get("reducer", "median"),
            cloud_pct=float(args.get("cloud_pct", 30)),
            mask_clouds=bool(args.get("mask_clouds", True)),
            project_id=args.get("project_id"),
            drive_folder=args.get("drive_folder") or GEE_DRIVE_FOLDER,
            local_drive_path=args.get("local_drive_path") or str(GDRIVE_SYNC_DIR),
            download_timeout=int(args.get("download_timeout", 1800)),
        )

        if result.get("success") and result.get("output_tif") and os.path.exists(result["output_tif"]):
            runtime.current_dataset = result.get("output_tif")
            runtime.last_tif_output = result.get("output_tif")
            runtime.last_output = None
            if runtime.source_dataset is None:
                runtime.source_dataset = result.get("output_tif")

        return result

    # ─────────────────────────────────────────────────────
    # GEE 云端 LST 反演（直接下载单波段结果）
    # ─────────────────────────────────────────────────────

    def gee_compute_lst_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        start_date = args.get("start_date")
        end_date = args.get("end_date")
        if not start_date or not end_date:
            start_date, end_date = _default_last_full_month()

        region = args.get("region")
        if region is None:
            region = runtime.last_region_geojson
        if region is None:
            return {
                "success": False,
                "message": "缺少研究区边界。请先调用 resolve_admin_region 解析行政区边界。",
                "requires": "resolve_admin_region",
            }

        region_name = runtime.last_region_name or ""
        filename = build_task_filename(
            region_name=region_name, start_date=start_date, end_date=end_date, product="LST"
        )
        output_tif = args.get("output_tif") or str(out_dir() / filename)

        result = gee_compute_lst(
            start_date=start_date,
            end_date=end_date,
            output_tif=output_tif,
            region=region,
            region_path=args.get("region_path"),
            scale=int(args.get("scale", 30)),
            cloud_pct=float(args.get("cloud_pct", 30)),
            project_id=args.get("project_id"),
            download_timeout=int(args.get("download_timeout", 1800)),
        )

        if result.get("success") and result.get("output_tif") and os.path.exists(result["output_tif"]):
            runtime.current_dataset = result.get("output_tif")
            runtime.last_tif_output = result.get("output_tif")
            runtime.last_output = None
            if runtime.source_dataset is None:
                runtime.source_dataset = result.get("output_tif")

        return result

    # ─────────────────────────────────────────────────────
    # 月度 LST 合成（逐景反演后均值）
    # ─────────────────────────────────────────────────────

    def gee_download_monthly_lst_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        start_date = args.get("start_date")
        end_date = args.get("end_date")

        if not start_date or not end_date:
            start_date, end_date = _default_last_full_month()

        region = args.get("region")
        if region is None:
            region = runtime.last_region_geojson
        if region is None:
            return {
                "success": False,
                "message": (
                    "缺少研究区边界（region）。"
                    "如果是行政区名称（如'温江区'），请先调用 resolve_admin_region 解析边界；"
                    "如果是 bbox 坐标，请直接传入 region=[xmin,ymin,xmax,ymax]。"
                ),
                "requires": "resolve_admin_region 或 region 参数",
            }

        region_name = runtime.last_region_name or ""
        filename = build_task_filename(region_name=region_name, start_date=start_date, end_date=end_date, product="LST")
        output_tif = args.get("output_tif") or str(out_dir() / filename)

        result = gee_download_monthly_lst(
            start_date=start_date,
            end_date=end_date,
            output_tif=output_tif,
            region=region,
            region_path=args.get("region_path"),
            scale=int(args.get("scale", 30)),
            project_id=args.get("project_id"),
            drive_folder=args.get("drive_folder") or GEE_DRIVE_FOLDER,
            local_drive_path=args.get("local_drive_path") or str(GDRIVE_SYNC_DIR),
            download_timeout=int(args.get("download_timeout", 1800)),
        )

        if result.get("success") and result.get("output_tif") and os.path.exists(result["output_tif"]):
            runtime.current_dataset = result.get("output_tif")
            runtime.last_tif_output = result.get("output_tif")
            runtime.last_output = None
            if runtime.source_dataset is None:
                runtime.source_dataset = result.get("output_tif")

        return result

    # ─────────────────────────────────────────────────────
    # 年度批量 LST 合成
    # ─────────────────────────────────────────────────────

    def gee_download_yearly_lst_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        year = int(args.get("year", 2025))

        region = args.get("region")
        if region is None:
            region = runtime.last_region_geojson
        if region is None:
            return {
                "success": False,
                "message": (
                    "缺少研究区边界（region）。"
                    "如果是行政区名称（如'旺苍县'），请先调用 resolve_admin_region 解析边界；"
                    "如果是 bbox 坐标，请直接传入 region=[xmin,ymin,xmax,ymax]。"
                ),
                "requires": "resolve_admin_region 或 region 参数",
            }

        region_name = runtime.last_region_name or ""
        dir_name = build_task_filename(region_name=region_name, year=year, product="全年LST", suffix="")
        output_dir = args.get("output_dir") or str(out_dir() / dir_name)

        months = args.get("months")  # 可选，如 [1,2,3,4,5,6]

        result = gee_download_yearly_lst(
            year=year,
            output_dir=output_dir,
            region=region,
            region_path=args.get("region_path"),
            region_name=region_name,
            months=months,
            scale=int(args.get("scale", 30)),
            project_id=args.get("project_id"),
            drive_folder=args.get("drive_folder") or GEE_DRIVE_FOLDER,
            local_drive_path=args.get("local_drive_path") or str(GDRIVE_SYNC_DIR),
            download_timeout=int(args.get("download_timeout", 1800)),
        )

        if result.get("success") and result.get("results"):
            # 设置最后一个成功月份为当前数据集
            last = result["results"][-1]
            if last.get("output_tif") and os.path.exists(last["output_tif"]):
                runtime.current_dataset = last["output_tif"]
                runtime.last_tif_output = last["output_tif"]

        return result

    # ─────────────────────────────────────────────────────
    # 跨多年单月 LST 批量反演
    # ─────────────────────────────────────────────────────

    def gee_download_multi_year_lst_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        start_year = int(args.get("start_year", 2020))
        end_year = int(args.get("end_year", 2025))
        month = int(args.get("month", 8))

        region = args.get("region")
        if region is None:
            region = runtime.last_region_geojson
        if region is None:
            return {
                "success": False,
                "message": (
                    "缺少研究区边界（region）。"
                    "如果是行政区名称，请先调用 resolve_admin_region 解析边界；"
                    "如果是 bbox 坐标，请直接传入 region=[xmin,ymin,xmax,ymax]。"
                ),
                "requires": "resolve_admin_region 或 region 参数",
            }

        region_name = runtime.last_region_name or ""
        dir_name = build_task_filename(region_name=region_name, start_year=start_year, end_year=end_year, month=month, product="LST", suffix="")
        output_dir = args.get("output_dir") or str(out_dir() / dir_name)

        result = gee_download_multi_year_lst(
            start_year=start_year,
            end_year=end_year,
            month=month,
            output_dir=output_dir,
            region=region,
            region_path=args.get("region_path"),
            region_name=region_name,
            scale=int(args.get("scale", 30)),
            project_id=args.get("project_id"),
            drive_folder=args.get("drive_folder") or GEE_DRIVE_FOLDER,
            local_drive_path=args.get("local_drive_path") or str(GDRIVE_SYNC_DIR),
            download_timeout=int(args.get("download_timeout", 1800)),
        )

        if result.get("success") and result.get("results"):
            last = result["results"][-1]
            if last.get("output_tif") and os.path.exists(last["output_tif"]):
                runtime.current_dataset = last["output_tif"]
                runtime.last_tif_output = last["output_tif"]

        return result

    # ─────────────────────────────────────────────────────
    # 【新增】GEE 时间序列工具
    # ─────────────────────────────────────────────────────

    def gee_lst_timelapse_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        """生成多年指定月份 LST 时间序列 GIF 动画"""
        roi = runtime.last_region_geojson
        if roi is None:
            return {
                "success": False,
                "message": "缺少研究区。请先用 resolve_admin_region 解析行政区边界，或用 gee_download_landsat_sca 下载过数据（会自动保存区域）。",
            }

        # 【关键】先初始化 GEE，失败则明确提示用户执行 gee_init
        from agent.gee_client import init_gee
        init_result = init_gee()
        if not init_result.get("success"):
            return {
                "success": False,
                "message": (
                    f"GEE 未认证：{init_result.get('message', '未知错误')}。"
                    "请先执行 gee_init（输入'初始化GEE'或'认证Earth Engine'）完成 Google 账号授权。"
                    "授权只需一次，之后自动使用本地 token。"
                ),
                "requires": "gee_init",
            }

        # 将 GeoJSON Feature 转为 ee.Geometry
        try:
            from gis.gee_tools import _normalize_region
            ee_geom = _normalize_region(region=roi)
        except Exception as e:
            return {"success": False, "message": f"研究区转换失败: {e}"}

        start_year = int(args.get("start_year", 2015))
        end_year = int(args.get("end_year", 2024))
        month = parse_month(args.get("month", 7))
        cloud_pct = float(args.get("cloud_pct", 30))
        title = args.get("title", "")
        fps = int(args.get("fps", 2))
        dimensions = int(args.get("dimensions", 600))
        vmin = float(args.get("vmin", 20))
        vmax = float(args.get("vmax", 45))

        gif_dir = str(out_dir() / "timelapse")
        os.makedirs(gif_dir, exist_ok=True)

        result = generate_lst_timelapse(
            roi=ee_geom,
            output_dir=gif_dir,
            start_year=start_year,
            end_year=end_year,
            month=month,
            cloud_pct=cloud_pct,
            title=title,
            fps=fps,
            dimensions=dimensions,
            vmin=vmin,
            vmax=vmax,
        )

        if result.get("success") and result.get("gif_path"):
            runtime.last_output = result["gif_path"]

        return result

    def gee_lst_split_panel_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        """生成两年 LST 分屏对比地图（HTML）"""
        roi = runtime.last_region_geojson
        if roi is None:
            return {"success": False, "message": "缺少研究区。请先用 resolve_admin_region 解析行政区边界。"}

        from agent.gee_client import init_gee
        init_result = init_gee()
        if not init_result.get("success"):
            return {
                "success": False,
                "message": f"GEE 未认证：{init_result.get('message', '')}。请先执行 gee_init 完成授权。",
                "requires": "gee_init",
            }

        try:
            from gis.gee_tools import _normalize_region
            ee_geom = _normalize_region(region=roi)
        except Exception as e:
            return {"success": False, "message": f"研究区转换失败: {e}"}

        year_a = int(args.get("year_a", 2015))
        year_b = int(args.get("year_b", 2024))
        month = parse_month(args.get("month", 7))
        cloud_pct = float(args.get("cloud_pct", 30))
        vmin = float(args.get("vmin", 20))
        vmax = float(args.get("vmax", 45))

        region_name = runtime.last_region_name or "region"
        output_path = str(out_dir() / f"{region_name}_split_{year_a}_vs_{year_b}_m{month}.html")

        result = generate_lst_split_panel(
            roi=ee_geom,
            output_path=output_path,
            year_a=year_a,
            year_b=year_b,
            month=month,
            cloud_pct=cloud_pct,
            vmin=vmin,
            vmax=vmax,
        )

        if result.get("success"):
            runtime.last_output = output_path

        return result

    def gee_lst_trend_chart_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        """生成多年 LST 均值变化折线图"""
        roi = runtime.last_region_geojson
        if roi is None:
            return {"success": False, "message": "缺少研究区。请先用 resolve_admin_region 解析行政区边界。"}

        from agent.gee_client import init_gee
        init_result = init_gee()
        if not init_result.get("success"):
            return {
                "success": False,
                "message": f"GEE 未认证：{init_result.get('message', '')}。请先执行 gee_init 完成授权。",
                "requires": "gee_init",
            }

        try:
            from gis.gee_tools import _normalize_region
            ee_geom = _normalize_region(region=roi)
        except Exception as e:
            return {"success": False, "message": f"研究区转换失败: {e}"}

        start_year = int(args.get("start_year", 2015))
        end_year = int(args.get("end_year", 2024))
        month = parse_month(args.get("month", 7))
        cloud_pct = float(args.get("cloud_pct", 30))
        title = args.get("title", "")

        region_name = runtime.last_region_name or "region"
        month_val = parse_month(month)
        output_path = str(out_dir() / f"{region_name}_trend_{start_year}_{end_year}_m{month_val}.png")

        result = generate_lst_trend_chart(
            roi=ee_geom,
            output_path=output_path,
            start_year=start_year,
            end_year=end_year,
            month=month,
            cloud_pct=cloud_pct,
            title=title,
        )

        if result.get("success"):
            runtime.last_output = output_path

        return result

    def gee_lst_timelapse_local_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        """本地版时间序列：逐年从 GEE 下载 → 本地反演 → 合成 GIF"""
        roi = runtime.last_region_geojson
        if roi is None:
            return {"success": False, "message": "缺少研究区。请先用 resolve_admin_region 解析行政区边界。"}

        from agent.gee_client import init_gee
        init_result = init_gee()
        if not init_result.get("success"):
            return {
                "success": False,
                "message": f"GEE 未认证：{init_result.get('message', '')}。请先执行 gee_init 完成授权。",
                "requires": "gee_init",
            }

        try:
            from gis.gee_tools import _normalize_region
            ee_geom = _normalize_region(region=roi)
        except Exception as e:
            return {"success": False, "message": f"研究区转换失败: {e}"}

        start_year = int(args.get("start_year", 2015))
        end_year = int(args.get("end_year", 2024))
        month = parse_month(args.get("month", 7))
        cloud_pct = float(args.get("cloud_pct", 30))
        title = args.get("title", "")
        fps = int(args.get("fps", 2))
        dpi = int(args.get("dpi", 150))
        vmin = args.get("vmin")
        vmax = args.get("vmax")
        if vmin is not None:
            vmin = float(vmin)
        if vmax is not None:
            vmax = float(vmax)

        gif_dir = str(out_dir() / "timelapse")
        os.makedirs(gif_dir, exist_ok=True)

        result = generate_lst_timelapse_local(
            roi=ee_geom,
            output_dir=gif_dir,
            start_year=start_year,
            end_year=end_year,
            month=month,
            cloud_pct=cloud_pct,
            title=title,
            fps=fps,
            dpi=dpi,
            vmin=vmin,
            vmax=vmax,
        )

        if result.get("success") and result.get("gif_path"):
            runtime.last_output = result["gif_path"]

            # 自动生成交互式 Web 地图（带悬停取值）
            lst_tifs = result.get("lst_tifs", [])
            years_ok = result.get("years_ok", [])
            if lst_tifs and years_ok:
                web_map_path = str(out_dir() / "timelapse" / f"lst_timelapse_{start_year}_{end_year}_m{month}_interactive.html")
                web_result = generate_timelapse_web_map(
                    lst_tif_paths=lst_tifs,
                    years=years_ok,
                    output_path=web_map_path,
                    title=title or f"{month}月地表温度变化 {start_year}-{end_year}",
                    month=month,
                )
                if web_result.get("success"):
                    result["web_map_path"] = web_map_path
                    result["message"] += f"\n📊 交互式地图: {web_map_path}"

        return result

    # ─────────────────────────────────────────────────────
    # 【新增】A1-A8: geemap 集成工具
    # ─────────────────────────────────────────────────────

    def _ensure_gee() -> Dict[str, Any] | None:
        """确保 GEE 已初始化，返回 None 表示成功，否则返回错误 dict"""
        from agent.gee_client import init_gee
        result = init_gee()
        if not result.get("success"):
            return {
                "success": False,
                "message": f"GEE 未认证：{result.get('message', '')}。请先执行 gee_init。",
                "requires": "gee_init",
            }
        return None

    def _resolve_roi(args: Dict[str, Any]):
        """从 args 或 runtime 获取 roi ee.Geometry"""
        roi = args.get("region") or runtime.last_region_geojson
        if roi is None:
            return None, {
                "success": False,
                "message": "缺少研究区。请先用 resolve_admin_region 解析行政区边界，或传入 region 参数。",
            }
        try:
            from gis.gee_tools import _normalize_region
            return _normalize_region(region=roi), None
        except Exception as e:
            return None, {"success": False, "message": f"研究区转换失败: {e}"}

    # ── A1: 点位时间序列提取 ──
    def extract_timeseries_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        err = _ensure_gee()
        if err:
            return err

        lat = args.get("lat")
        lon = args.get("lon")
        if lat is None or lon is None:
            return {"success": False, "message": "缺少经纬度参数 lat/lon"}

        collection_id = args.get("image_collection_id", "ECMWF/ERA5_LAND/DAILY_AGGR")
        band_names = args.get("band_names", ["temperature_2m"])
        start_date = args.get("start_date", "2020-01-01")
        end_date = args.get("end_date", "2020-12-31")
        scale = int(args.get("scale", 1000))

        region_name = runtime.last_region_name or f"{lat}_{lon}"
        csv_path = str(out_dir() / f"timeseries_{region_name}_{lat}_{lon}.csv")
        png_path = str(out_dir() / f"timeseries_{region_name}_{lat}_{lon}.png")

        result = extract_timeseries_to_point(
            lat=float(lat), lon=float(lon),
            image_collection_id=collection_id,
            band_names=band_names,
            start_date=start_date, end_date=end_date,
            scale=scale,
            output_csv=csv_path, output_png=png_path,
            title=args.get("title", ""),
            reducer=args.get("reducer", "mean"),
            point_buffer_m=int(args.get("point_buffer_m", 0)),
        )
        if result.get("success"):
            runtime.last_output = result.get("png_path")
        return result

    # ── A2: 时间序列对比检查器 ──
    def timeseries_inspector_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        err = _ensure_gee()
        if err:
            return err

        roi, err = _resolve_roi(args)
        if err:
            return err

        region_name = runtime.last_region_name or "region"
        output_path = str(out_dir() / f"{region_name}_ts_inspector.html")

        result = timeseries_inspector(
            roi=roi, output_path=output_path,
            image_collection_id=args.get("image_collection_id"),
            start_year=int(args.get("start_year", 2015)),
            end_year=int(args.get("end_year", 2024)),
            start_mmdd=args.get("start_mmdd", "01-01"),
            end_mmdd=args.get("end_mmdd", "12-31"),
            band_names=args.get("band_names"),
            vis_params=args.get("vis_params"),
            cloud_pct=float(args.get("cloud_pct", 30)),
            center_zoom=int(args.get("center_zoom", 10)),
        )
        if result.get("success"):
            runtime.last_output = output_path
        return result

    # ── A3: 时间序列图表 ──
    def gee_chart_timeseries_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        err = _ensure_gee()
        if err:
            return err

        roi, err = _resolve_roi(args)
        if err:
            return err

        region_name = runtime.last_region_name or "chart"
        collection_id = args.get("image_collection_id", "MODIS/061/MOD13A1")
        output_path = str(out_dir() / f"{region_name}_chart_timeseries.png")

        result = gee_chart_timeseries(
            image_collection_id=collection_id,
            region=roi,
            band_names=args.get("band_names", ["NDVI"]),
            start_date=args.get("start_date", "2010-01-01"),
            end_date=args.get("end_date", "2020-01-01"),
            output_path=output_path,
            scale=int(args.get("scale", 500)),
            reducer=args.get("reducer", "mean"),
            title=args.get("title", ""),
            x_label=args.get("x_label", "日期"),
            y_label=args.get("y_label", "值"),
            chart_type=args.get("chart_type", "LineChart"),
            colors=args.get("colors"),
        )
        if result.get("success"):
            runtime.last_output = output_path
        return result

    def gee_chart_by_region_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        err = _ensure_gee()
        if err:
            return err

        roi, err = _resolve_roi(args)
        if err:
            return err

        region_name = runtime.last_region_name or "chart"
        collection_id = args.get("image_collection_id", "MODIS/061/MOD13A1")
        output_path = str(out_dir() / f"{region_name}_chart_by_region.png")

        result = gee_chart_by_region(
            image_collection_id=collection_id,
            regions=roi,
            band_name=args.get("band_name", "NDVI"),
            start_date=args.get("start_date", "2010-01-01"),
            end_date=args.get("end_date", "2020-01-01"),
            output_path=output_path,
            scale=int(args.get("scale", 500)),
            series_property=args.get("series_property", "label"),
            title=args.get("title", ""),
            colors=args.get("colors"),
        )
        if result.get("success"):
            runtime.last_output = output_path
        return result

    def gee_chart_phenology_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        err = _ensure_gee()
        if err:
            return err

        roi, err = _resolve_roi(args)
        if err:
            return err

        region_name = runtime.last_region_name or "phenology"
        collection_id = args.get("image_collection_id", "MODIS/061/MOD13A1")
        output_path = str(out_dir() / f"{region_name}_phenology.png")

        result = gee_chart_phenology(
            image_collection_id=collection_id,
            region=roi,
            band_names=args.get("band_names", ["NDVI", "EVI"]),
            start_date=args.get("start_date", "2010-01-01"),
            end_date=args.get("end_date", "2020-01-01"),
            output_path=output_path,
            scale=int(args.get("scale", 500)),
            title=args.get("title", ""),
            colors=args.get("colors"),
        )
        if result.get("success"):
            runtime.last_output = output_path
        return result

    # ── A4: Dynamic World ──
    def dynamic_world_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        err = _ensure_gee()
        if err:
            return err

        roi, err = _resolve_roi(args)
        if err:
            return err

        region_name = runtime.last_region_name or "dw"
        start_date = args.get("start_date", "2021-01-01")
        end_date = args.get("end_date", "2022-01-01")
        tif_path = str(out_dir() / f"{region_name}_dynamic_world.tif")
        png_path = str(out_dir() / f"{region_name}_dynamic_world.png")

        result = dynamic_world_landcover(
            region=roi,
            start_date=start_date, end_date=end_date,
            output_tif=tif_path, output_png=png_path,
            return_type=args.get("return_type", "class"),
            scale=int(args.get("scale", 10)),
            title=args.get("title", ""),
        )
        if result.get("success"):
            runtime.last_tif_output = result.get("output_tif")
            runtime.last_output = result.get("output_png")
        return result

    # ── A5: 增强下载 ──
    def gee_download_collection_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        err = _ensure_gee()
        if err:
            return err

        collection_id = args.get("image_collection_id")
        if not collection_id:
            return {"success": False, "message": "缺少 image_collection_id 参数"}

        roi = args.get("region") or runtime.last_region_geojson
        region_name = runtime.last_region_name or "collection"
        output_dir_path = str(out_dir() / f"gee_collection_{region_name}")

        result = gee_download_image_collection(
            image_collection_id=collection_id,
            output_dir=output_dir_path,
            region=roi,
            region_path=args.get("region_path"),
            start_date=args.get("start_date"),
            end_date=args.get("end_date"),
            band_names=args.get("band_names"),
            scale=int(args.get("scale", 30)),
            crs=args.get("crs", "EPSG:4326"),
            max_images=int(args.get("max_images", 50)),
        )
        return result

    def gee_download_tiled_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        err = _ensure_gee()
        if err:
            return err

        image = args.get("image_id")
        if not image:
            return {"success": False, "message": "缺少 image_id 参数"}

        roi = args.get("region") or runtime.last_region_geojson
        if roi is None:
            return {"success": False, "message": "缺少研究区参数"}

        region_name = runtime.last_region_name or "tiled"
        output_dir_path = str(out_dir() / f"gee_tiles_{region_name}")

        result = gee_download_tiled(
            image=image, region=roi,
            output_dir=output_dir_path,
            scale=int(args.get("scale", 30)),
            crs=args.get("crs", "EPSG:4326"),
            rows=int(args.get("rows", 2)),
            cols=int(args.get("cols", 2)),
            prefix=args.get("prefix", "tile"),
            parallel=bool(args.get("parallel", True)),
        )
        return result

    # ── A6: 时间滑块 ──
    def time_slider_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        err = _ensure_gee()
        if err:
            return err

        roi, err = _resolve_roi(args)
        if err:
            return err

        collection_id = args.get("image_collection_id", "NOAA/GFS0P25")
        region_name = runtime.last_region_name or "timeslider"
        output_path = str(out_dir() / f"{region_name}_time_slider.html")

        result = generate_time_slider_map(
            image_collection_id=collection_id,
            region=roi,
            start_date=args.get("start_date", "2018-12-22"),
            end_date=args.get("end_date", "2018-12-23"),
            output_path=output_path,
            band_names=args.get("band_names"),
            vis_params=args.get("vis_params"),
            labels=args.get("labels"),
            time_interval=int(args.get("time_interval", 1)),
            opacity=float(args.get("opacity", 0.8)),
            center_lat=args.get("center_lat"),
            center_lon=args.get("center_lon"),
            zoom=int(args.get("zoom", 8)),
        )
        if result.get("success"):
            runtime.last_output = output_path
        return result

    # ── A7: GEE 端分类 ──
    def ee_unsupervised_classify_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        err = _ensure_gee()
        if err:
            return err

        roi, err = _resolve_roi(args)
        if err:
            return err

        region_name = runtime.last_region_name or "classify"
        tif_path = str(out_dir() / f"{region_name}_unsupervised.tif")
        png_path = str(out_dir() / f"{region_name}_unsupervised.png")

        result = ee_unsupervised_classify(
            region=roi,
            image_id=args.get("image_id"),
            start_date=args.get("start_date"),
            end_date=args.get("end_date"),
            band_names=args.get("band_names"),
            n_clusters=int(args.get("n_clusters", 5)),
            scale=int(args.get("scale", 30)),
            num_pixels=int(args.get("num_pixels", 5000)),
            output_tif=tif_path, output_png=png_path,
            class_names=args.get("class_names"),
            class_colors=args.get("class_colors"),
            title=args.get("title", ""),
        )
        if result.get("success"):
            runtime.last_tif_output = result.get("output_tif")
            runtime.last_output = result.get("output_png")
        return result

    def ee_supervised_classify_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        err = _ensure_gee()
        if err:
            return err

        roi, err = _resolve_roi(args)
        if err:
            return err

        region_name = runtime.last_region_name or "classify"
        tif_path = str(out_dir() / f"{region_name}_supervised.tif")
        png_path = str(out_dir() / f"{region_name}_supervised.png")

        result = ee_supervised_classify(
            region=roi,
            image_id=args.get("image_id"),
            start_date=args.get("start_date"),
            end_date=args.get("end_date"),
            band_names=args.get("band_names"),
            classifier_type=args.get("classifier_type", "RandomForest"),
            label_image_id=args.get("label_image_id"),
            label_band=args.get("label_band", "landcover"),
            scale=int(args.get("scale", 30)),
            num_pixels=int(args.get("num_pixels", 5000)),
            output_tif=tif_path, output_png=png_path,
            class_values=args.get("class_values"),
            class_names=args.get("class_names"),
            class_colors=args.get("class_colors"),
            title=args.get("title", ""),
        )
        if result.get("success"):
            runtime.last_tif_output = result.get("output_tif")
            runtime.last_output = result.get("output_png")
        return result

    # ── A8: 分区统计 ──
    def zonal_stats_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        err = _ensure_gee()
        if err:
            return err

        # 获取影像
        image_input = args.get("image_id") or args.get("tif_path") or runtime.current_tif()
        if not image_input:
            return {"success": False, "message": "缺少影像参数（image_id 或 tif_path）"}

        # 获取区域
        roi = args.get("region") or runtime.last_region_geojson
        if roi is None:
            return {"success": False, "message": "缺少研究区。请先用 resolve_admin_region 或传入 region。"}

        from gis.gee_tools import _normalize_region
        try:
            ee_geom = _normalize_region(region=roi)
            ee_fc = ee.FeatureCollection([ee.Feature(ee_geom)])
        except Exception as e:
            return {"success": False, "message": f"区域转换失败: {e}"}

        region_name = runtime.last_region_name or "zonal"
        csv_path = str(out_dir() / f"{region_name}_zonal_stats.csv")

        result = gee_zonal_statistics(
            image=image_input,
            regions=ee_fc,
            output_csv=csv_path,
            stat_type=args.get("stat_type", "MEAN"),
            scale=int(args.get("scale", 1000)),
            label_property=args.get("label_property"),
        )
        if result.get("success"):
            runtime.last_output = csv_path
        return result

    # ─────────────────────────────────────────────────────
    # 分析工具
    # ─────────────────────────────────────────────────────

    def run_lst_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        input_tif = args.get("input_tif") or runtime.current_tif()
        if not input_tif:
            return {"success": False, "message": "没有可用输入影像"}
        stem = _safe_stem(input_tif, "lst")
        output_tif = args.get("output_tif") or str(out_dir() / f"{stem}_lst.tif")
        output_png = args.get("output_png") or str(out_dir() / f"{stem}_lst.png")
        result = run_sca(input_tif=input_tif, output_tif=output_tif, output_png=output_png)
        if result.get("success"):
            runtime.current_dataset = output_tif
            runtime.last_tif_output = output_tif
            runtime.last_output = output_png
        return result

    def statistics_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        tif = args.get("tif_path") or runtime.current_tif()
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        result = analyze_raster(tif)
        if result.get("success") and result.get("histogram_png"):
            runtime.last_output = result.get("histogram_png")
        return result

    def classify_map_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        tif = args.get("tif_path") or runtime.current_tif()
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        result = classify_raster(
            tif_path=tif,
            output_png=args.get("output_png") or str(out_dir() / f"{_safe_stem(tif)}_classified.png"),
            method=args.get("method", preferences.get("classification_method", "natural_breaks")),
            n_classes=int(args.get("n_classes", preferences.get("n_classes", 5))),
            colormap=args.get("colormap", preferences.get("colormap", "YlOrRd")),
            title=args.get("title"),
            dpi=int(args.get("dpi", 300)),
        )
        if result.get("success"):
            runtime.last_output = result.get("output_png")
        return result

    def threshold_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        tif = args.get("tif_path") or runtime.current_tif()
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        result = threshold_highlight(
            tif_path=tif,
            output_path=args.get("output_path") or str(out_dir() / f"{_safe_stem(tif)}_threshold.png"),
            operator=args.get("operator", ">"),
            value=float(args.get("value", 30)),
            value_upper=args.get("value_upper"),
            highlight_color=args.get("highlight_color", "red"),
            base_colormap=args.get("base_colormap", "gray"),
            title=args.get("title"),
            dpi=int(args.get("dpi", 300)),
        )
        if result.get("success"):
            runtime.last_output = result.get("output_png")
        return result

    def enhance_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        tif = args.get("tif_path") or runtime.current_tif()
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        result = enhance_raster(
            tif_path=tif,
            output_tif=args.get("output_tif") or str(out_dir() / f"{_safe_stem(tif)}_enhanced.tif"),
            output_png=args.get("output_png") or str(out_dir() / f"{_safe_stem(tif)}_enhanced.png"),
            method=args.get("method", "gaussian"),
            kernel_size=int(args.get("kernel_size", 5)),
        )
        if result.get("success"):
            runtime.current_dataset = result.get("output_tif")
            runtime.last_tif_output = result.get("output_tif")
            runtime.last_output = result.get("output_png")
        return result

    def profile_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        tif = args.get("tif_path") or runtime.current_tif()
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        return profile_analysis(
            tif_path=tif,
            output_png=args.get("output_png") or str(out_dir() / f"{_safe_stem(tif)}_profile.png"),
            start=args.get("start"),
            end=args.get("end"),
            n_points=int(args.get("n_points", 200)),
        )

    def view3d_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        tif = args.get("tif_path") or runtime.current_tif()
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        result = render_3d(
            tif_path=tif,
            output_png=args.get("output_png") or str(out_dir() / f"{_safe_stem(tif)}_3d.png"),
            elevation=float(args.get("elevation", 45)),
            azimuth=float(args.get("azimuth", 225)),
            vertical_exaggeration=float(args.get("vertical_exaggeration", 1.0)),
            colormap=args.get("colormap", preferences.get("colormap", "terrain")),
            render_mode=args.get("render_mode", "surface"),
        )
        if result.get("success"):
            runtime.last_output = result.get("output_png")
        return result

    def compare_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        tif_original = args.get("tif_original") or runtime.source_dataset
        tif_result = args.get("tif_result") or runtime.current_tif()
        if not tif_original or not tif_result:
            return {"success": False, "message": "缺少对比所需原始图或结果图"}
        result = compare_views(
            tif_original=tif_original,
            tif_result=tif_result,
            output_png=args.get("output_png") or str(out_dir() / f"{_safe_stem(tif_result)}_compare.png"),
            mode=args.get("mode", "side_by_side"),
        )
        if result.get("success"):
            runtime.last_output = result.get("output_png")
        return result

    def transform_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        tif = args.get("tif_path") or runtime.current_tif()
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        result = transform_raster(
            tif_path=tif,
            output_tif=args.get("output_tif") or str(out_dir() / f"{_safe_stem(tif)}_{args.get('operation', 'flip_h')}.tif"),
            output_png=args.get("output_png") or str(out_dir() / f"{_safe_stem(tif)}_{args.get('operation', 'flip_h')}.png"),
            operation=args.get("operation", "flip_h"),
        )
        if result.get("success"):
            runtime.current_dataset = result.get("output_tif")
            runtime.last_tif_output = result.get("output_tif")
            runtime.last_output = result.get("output_png")
        return result

    # ─────────────────────────────────────────────────────
    # 制图工具
    # ─────────────────────────────────────────────────────

    def make_thematic_map_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        tif = args.get("tif_path") or runtime.current_tif()
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        style = dict(runtime.map_style)
        style.update({k: v for k, v in args.items() if v is not None})
        title = style.get("title") or f"专题图 - {_safe_stem(tif)}"
        output_path = args.get("output_path") or str(out_dir() / f"{_safe_stem(tif)}_map.png")
        result = generate_cartographic_map(
            tif_path=tif,
            output_path=output_path,
            title=title,
            colormap=style.get("colormap", preferences.get("colormap", "coolwarm")),
            show_legend=bool(style.get("show_legend", True)),
            show_scalebar=bool(style.get("show_scalebar", True)),
            show_north=bool(style.get("show_north", True)),
            dpi=int(style.get("dpi", 300)),
            legend_position=style.get("legend_position", preferences.get("legend_position", "right")),
            scalebar_position=style.get("scalebar_position", "lower left"),
            north_position=style.get("north_position", "upper right"),
            figsize=style.get("figsize"),
            alpha=float(style.get("alpha", 1.0)),
            bg_color=style.get("bg_color", "#EFEFEF"),
            title_color=style.get("title_color", "#1A1A1A"),
            grid=bool(style.get("grid", False)),
            frame=bool(style.get("frame", True)),
            legend_tick_fontsize=int(style.get("legend_tick_fontsize", 10)),
            legend_label_fontsize=int(style.get("legend_label_fontsize", 12)),
            legend_shrink=float(style.get("legend_shrink", 0.88)),
            scalebar_fontsize=int(style.get("scalebar_fontsize", 10)),
            scalebar_length_ratio=float(style.get("scalebar_length_ratio", 0.16)),
            north_fontsize=int(style.get("north_fontsize", 13)),
            title_fontsize=int(style.get("title_fontsize", 18)),
            map_margin=float(style.get("map_margin", 0.035)),
            map_frame_scale=float(style.get("map_frame_scale", 0.94)),
            legend_xoffset=float(style.get("legend_xoffset", 0.0)),
            legend_yoffset=float(style.get("legend_yoffset", 0.0)),
            north_xoffset=float(style.get("north_xoffset", 0.0)),
            north_yoffset=float(style.get("north_yoffset", 0.0)),
            scalebar_xoffset=float(style.get("scalebar_xoffset", 0.0)),
            scalebar_yoffset=float(style.get("scalebar_yoffset", 0.0)),
        )
        if result.get("success"):
            runtime.last_output = output_path
            runtime.map_style.update(style)
        return result

    # ─────────────────────────────────────────────────────
    # 导出与样式
    # ─────────────────────────────────────────────────────

    def export_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        input_path = args.get("input_path") or runtime.last_output
        if not input_path:
            return {"success": False, "message": "没有可导出的结果图"}
        fmt = args.get("format", preferences.get("export_format", "png"))
        output_path = args.get("output_path") or str(out_dir() / f"{_safe_stem(input_path)}_export.{fmt}")
        result = export_image(
            input_path=input_path,
            output_path=output_path,
            format=fmt,
            dpi=int(args.get("dpi", 300)),
        )
        if result.get("success"):
            runtime.last_output = result.get("output_path")
        return result

    def set_map_style(args: Dict[str, Any]) -> Dict[str, Any]:
        style = {k: v for k, v in args.items() if v is not None}
        runtime.map_style.update(style)
        return {"success": True, "message": "地图样式已更新", "map_style": runtime.map_style}

    def update_preferences(args: Dict[str, Any]) -> Dict[str, Any]:
        updated = {k: v for k, v in args.items() if v is not None}
        preferences.update(updated)
        return {"success": True, "message": "偏好已更新", "updated_preferences": updated}

    def generate_report_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        report_items = args.get("report_items", [])
        title = args.get("title", "GIS 实验报告")
        subtitle = args.get("subtitle", "")
        conclusion = args.get("conclusion", "")
        dataset_name = args.get("dataset_name") or _safe_stem(runtime.current_dataset, "未知数据集")
        output_format = args.get("format", "html")

        if not report_items:
            report_items = _auto_collect_report_items(args, dataset_name)

        if not report_items:
            return {
                "success": False,
                "message": "没有可用的分析结果来生成报告。请先执行统计分析、分类或制图等操作。",
            }

        output_path = args.get("output_path") or str(out_dir() / f"{dataset_name}_experiment_report.html")
        if not output_path.endswith(".html"):
            output_path += ".html"

        result = generate_html_report(
            report_items=report_items,
            output_path=output_path,
            title=title,
            subtitle=subtitle,
            dataset_name=dataset_name,
            conclusion=conclusion,
        )

        if result.get("success") and output_format == "pdf":
            pdf_result = try_convert_pdf(output_path)
            if pdf_result.get("success"):
                result["pdf_path"] = pdf_result["pdf_path"]

        if result.get("success"):
            runtime.last_output = output_path

        return result

    def _auto_collect_report_items(args: Dict[str, Any], dataset_name: str) -> list:
        items = []
        seen_images = set()

        hist_png = None
        tif = runtime.current_tif()
        if tif:
            try:
                stats_result = analyze_raster(tif)
                if stats_result.get("success"):
                    hist_png = stats_result.get("histogram_png")
                    items.append({
                        "section_title": "数据统计分析",
                        "item_type": "statistics",
                        "image_path": hist_png or "",
                        "image_caption": f"{dataset_name} 像元值分布直方图",
                        "stats": stats_result.get("statistics", {}),
                    })
                    if hist_png:
                        seen_images.add(hist_png)
            except Exception:
                pass

        custom_images = args.get("images", [])
        for img in custom_images:
            if isinstance(img, str) and os.path.exists(img) and img not in seen_images:
                items.append({
                    "section_title": f"分析结果 - {Path(img).stem}",
                    "item_type": "map",
                    "image_path": img,
                    "image_caption": Path(img).stem,
                })
                seen_images.add(img)
            elif isinstance(img, dict):
                img_path = img.get("path", "")
                if os.path.exists(img_path) and img_path not in seen_images:
                    items.append({
                        "section_title": img.get("title", f"分析结果 - {Path(img_path).stem}"),
                        "item_type": img.get("item_type", "map"),
                        "image_path": img_path,
                        "image_caption": img.get("caption", Path(img_path).stem),
                        "text": img.get("text", ""),
                    })
                    seen_images.add(img_path)

        if (
            runtime.last_output
            and runtime.last_output.endswith((".png", ".jpg", ".jpeg"))
            and os.path.exists(runtime.last_output)
            and runtime.last_output not in seen_images
        ):
            items.append({
                "section_title": "专题图",
                "item_type": "map",
                "image_path": runtime.last_output,
                "image_caption": f"{dataset_name} 专题图",
            })

        return items

    def generate_web_map_tool(args: Dict[str, Any]) -> Dict[str, Any]:
        tif = args.get("tif_path") or runtime.current_tif()
        if not tif:
            return {"success": False, "message": "没有可用栅格"}
        output_path = args.get("output_path") or str(out_dir() / f"{_safe_stem(tif)}_interactive_map.html")
        if not output_path.endswith(".html"):
            output_path += ".html"

        result = generate_web_map(
            tif_path=tif,
            output_path=output_path,
            title=args.get("title", f"交互式地图 - {_safe_stem(tif)}"),
            colormap=args.get("colormap", preferences.get("colormap", "viridis")),
            overlay_opacity=float(args.get("overlay_opacity", 0.7)),
            show_heatmap=bool(args.get("show_heatmap", False)),
            additional_layers=args.get("additional_layers"),
            popup_info=args.get("popup_info"),
            center_lat=args.get("center_lat"),
            center_lon=args.get("center_lon"),
            zoom_start=int(args.get("zoom_start", 12)),
        )
        if result.get("success"):
            runtime.last_output = output_path
        return result

    def summarize_context(args: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": True,
            "message": "当前上下文摘要",
            "context": {
                "current_dataset": runtime.current_dataset,
                "source_dataset": runtime.source_dataset,
                "last_output": runtime.last_output,
                "last_tif_output": runtime.last_tif_output,
                "last_region_name": runtime.last_region_name,
                "map_style": runtime.map_style,
            },
        }

    # ─────────────────────────────────────────────────────
    # 工具定义列表（新增 3 个 timelapse 工具）
    # ─────────────────────────────────────────────────────

    tool_defs = [
        ("search_local_files", "在本地电脑常见目录中搜索文件，适合根据模糊文件名找影像或 GeoJSON。", {"query": "要查找的文件名或关键词", "extensions": "可选扩展名列表"}, "data"),
        ("set_current_dataset", "将某个找到的栅格文件设置为当前工作数据。", {"path": "本地文件完整路径"}, "data"),
        ("inspect_raster", "读取当前或指定栅格的波段、值域、分辨率、CRS、产品类型推断。", {"path": "可选，栅格路径"}, "data"),
        ("resolve_admin_region", "根据中国市/县/区名称，从本地 中国_市.geojson / 中国_县.geojson 中自动匹配行政边界，并返回 GeoJSON 与 bbox。", {
            "region_name": "行政区名称，如 广元市 / 旺苍县 / 广元市旺苍县"
        }, "data"),

        ("gee_init", "初始化 Google Earth Engine 认证与项目配置。", {"project_id": "可选，GEE 项目 ID", "force_auth": "是否强制重新认证 true/false"}, "data"),
        ("gee_compute_lst", "【推荐】在 GEE 云端直接进行单通道地表温度反演，仅下载单波段 LST(°C) TIF。一步完成，无需后续本地 run_lst。适合下载单时相 LST 并制图。", {
            "start_date": "开始日期 YYYY-MM-DD，缺省时默认上一个完整自然月",
            "end_date": "结束日期 YYYY-MM-DD，缺省时默认上一个完整自然月",
            "cloud_pct": "最大云量百分比 0-100，默认 30",
            "scale": "分辨率(米)，默认 30",
        }, "data"),
        ("gee_download_landsat_sca", "从 GEE 下载适合本地 SCA 单通道地表温度反演的 Landsat 8/9 Level-2 三波段数据（red, nir, bt_raw）。已不推荐，优先使用 gee_compute_lst。", {
            "start_date": "开始日期 YYYY-MM-DD，缺省时默认上一个完整自然月",
            "end_date": "结束日期 YYYY-MM-DD，缺省时默认上一个完整自然月",
            "region": "AOI，可传 [xmin,ymin,xmax,ymax] 或 GeoJSON Feature",
            "region_path": "可选，本地 GeoJSON 文件路径",
            "scale": "导出分辨率，默认30",
            "cloud_pct": "最大云量百分比，默认30",
            "reducer": "median/mean/mosaic/first，默认 median",
            "mask_clouds": "是否在 GEE 端像素级去云（QA_PIXEL），默认 true",
            "project_id": "可选，GEE 项目 ID",
            "drive_folder": "Google Drive 导出文件夹名，默认 GEE_Exports",
            "local_drive_path": "本地 Google Drive 同步目录，默认读 config.GDRIVE_SYNC_DIR",
            "download_timeout": "等待下载/导出/同步的超时秒数，默认 1800",
        }, "data"),

        ("gee_download_monthly_lst", "月度 LST 智能合成（分级降级）。自动选取当月最优 Landsat 8/9 场景，逐景 SCA 单通道反演后合成，输出单波段 LST（°C）。降级策略：云<15%≥3景均值→云<20%≥2景均值→云<25%≥2景中值→云<40%单景→全部去云中值。返回质量等级（A+~C）。若未给日期，默认上一个完整自然月。", {
            "start_date": "开始日期 YYYY-MM-DD，缺省时默认上一个完整自然月",
            "end_date": "结束日期 YYYY-MM-DD，缺省时默认上一个完整自然月",
            "region": "AOI，可传 [xmin,ymin,xmax,ymax] 或 GeoJSON Feature",
            "region_path": "可选，本地 GeoJSON 文件路径",
            "scale": "导出分辨率，默认30",
            "project_id": "可选，GEE 项目 ID",
            "drive_folder": "Google Drive 导出文件夹名，默认 GEE_Exports",
            "local_drive_path": "本地 Google Drive 同步目录，默认读 config.GDRIVE_SYNC_DIR",
            "download_timeout": "等待下载/导出/同步的超时秒数，默认 1800",
        }, "data"),

        ("gee_download_yearly_lst", "批量下载全年（或指定月份）的月度 LST。在 GEE 云端逐月执行分级降级选景 + 逐景 SCA 反演。默认下载全年12个月，可通过 months 参数指定月份列表（如 [1,2,3,4,5,6]）。需要先用 resolve_admin_region 设置研究区。", {
            "year": "年份，如 2025",
            "months": "可选，要下载的月份列表，如 [1,2,3,4,5,6]。不传则默认全部 12 个月",
            "output_dir": "输出目录，存放各月的 TIF 文件",
            "region": "AOI，可传 [xmin,ymin,xmax,ymax] 或 GeoJSON Feature",
            "region_path": "可选，本地 GeoJSON 文件路径",
            "scale": "导出分辨率，默认30",
            "project_id": "可选，GEE 项目 ID",
            "drive_folder": "Google Drive 导出文件夹名，默认 GEE_Exports",
            "local_drive_path": "本地 Google Drive 同步目录，默认读 config.GDRIVE_SYNC_DIR",
            "download_timeout": "等待下载/导出/同步的超时秒数，默认 1800",
        }, "data"),

        ("gee_download_multi_year_lst", "跨多年单月 LST 批量反演。对指定年份范围内每一年的同一月份，执行分级降级选景 + 逐景 SCA 反演，输出 N 个单波段 LST TIF（°C）。典型用法：'2020-2025年每年8月的地表温度'。需要先用 resolve_admin_region 设置研究区。", {
            "start_year": "起始年份，如 2020",
            "end_year": "结束年份，如 2025",
            "month": "月份 1-12，如 8 表示每年8月",
            "output_dir": "输出目录，存放各年的 TIF 文件",
            "region": "AOI，可传 [xmin,ymin,xmax,ymax] 或 GeoJSON Feature",
            "region_path": "可选，本地 GeoJSON 文件路径",
            "scale": "导出分辨率，默认30",
            "project_id": "可选，GEE 项目 ID",
            "drive_folder": "Google Drive 导出文件夹名，默认 GEE_Exports",
            "local_drive_path": "本地 Google Drive 同步目录，默认读 config.GDRIVE_SYNC_DIR",
            "download_timeout": "等待下载/导出/同步的超时秒数，默认 1800",
        }, "data"),

        # ── 【新增】GEE 时间序列工具 ──
        ("gee_lst_timelapse", "在 GEE 端完成多年指定月份 LST 反演并生成时间序列 GIF 动画。需要先用 resolve_admin_region 设置研究区。", {
            "start_year": "起始年份，默认 2015",
            "end_year": "结束年份（含），默认 2024",
            "month": "月份（1-12 或中文如'七月'），默认 7",
            "cloud_pct": "最大云量百分比，默认 30",
            "title": "GIF 标题，缺省自动生成",
            "fps": "帧率，默认 2",
            "dimensions": "图片尺寸（像素），默认 600",
            "vmin": "色标最小值（°C），默认 20",
            "vmax": "色标最大值（°C），默认 45",
        }, "visualization"),
        ("gee_lst_split_panel", "生成两年指定月份 LST 的分屏对比交互式地图（HTML），可在浏览器中左右拖动对比。", {
            "year_a": "第一年，默认 2015",
            "year_b": "第二年，默认 2024",
            "month": "月份，默认 7",
            "cloud_pct": "最大云量百分比，默认 30",
            "vmin": "色标最小值（°C），默认 20",
            "vmax": "色标最大值（°C），默认 45",
        }, "visualization"),
        ("gee_lst_trend_chart", "生成多年指定月份 LST 均值变化折线图（含极值范围阴影），用于分析温度年际趋势。", {
            "start_year": "起始年份，默认 2015",
            "end_year": "结束年份（含），默认 2024",
            "month": "月份，默认 7",
            "cloud_pct": "最大云量百分比，默认 30",
            "title": "图表标题，缺省自动生成",
        }, "visualization"),
        ("gee_lst_timelapse_local", "【推荐】逐年从 GEE 下载 Landsat 数据到本地，本地执行 LST 反演，再合成 GIF 动画。比 GEE 端合成更稳定可靠。", {
            "start_year": "起始年份，默认 2015",
            "end_year": "结束年份（含），默认 2024",
            "month": "月份（1-12 或中文如'七月'），默认 7",
            "cloud_pct": "最大云量百分比，默认 30",
            "title": "GIF 标题，缺省自动生成",
            "fps": "帧率，默认 2",
            "dpi": "输出图片分辨率，默认 150",
            "vmin": "色标最小值（°C），默认自动",
            "vmax": "色标最大值（°C），默认自动",
        }, "visualization"),

        # ── 【新增】A1-A8: geemap 集成工具 ──
        ("extract_timeseries_to_point", "从 GEE ImageCollection 提取指定经纬度点的时间序列数据，输出 CSV 和折线图。支持 ERA5、MODIS、CHIRPS 等任意数据集。", {
            "lat": "纬度",
            "lon": "经度",
            "image_collection_id": "GEE ImageCollection ID，如 ECMWF/ERA5_LAND/DAILY_AGGR",
            "band_names": "要提取的波段名列表，如 [temperature_2m]",
            "start_date": "起始日期 YYYY-MM-DD",
            "end_date": "结束日期 YYYY-MM-DD",
            "scale": "采样分辨率（米），默认 1000",
            "title": "图表标题",
        }, "analysis"),
        ("gee_timeseries_inspector", "创建时间序列分屏对比检查器（交互式 HTML），支持逐年 Landsat 合成或自定义 ImageCollection，可左右拖动对比不同时期影像。", {
            "image_collection_id": "可选，自定义 ImageCollection ID，不填则用 Landsat 年度合成",
            "start_year": "起始年份，默认 2015",
            "end_year": "结束年份，默认 2024",
            "band_names": "波段列表",
            "vis_params": "可视化参数 dict",
            "cloud_pct": "云量阈值，默认 30",
        }, "visualization"),
        ("gee_chart_timeseries", "生成 GEE 时间序列折线图（单区域多波段），基于 geemap.chart。支持 MODIS NDVI、ERA5 温度等任意数据集。", {
            "image_collection_id": "GEE ImageCollection ID",
            "band_names": "波段名列表",
            "start_date": "起始日期",
            "end_date": "结束日期",
            "scale": "采样分辨率（米）",
            "reducer": "聚合方式 mean/min/max/median",
            "title": "图表标题",
        }, "visualization"),
        ("gee_chart_by_region", "生成多区域对比时间序列图，比较不同区域在同一波段上的时间变化差异。", {
            "image_collection_id": "GEE ImageCollection ID",
            "band_name": "波段名",
            "start_date": "起始日期",
            "end_date": "结束日期",
            "series_property": "区分区域的属性名，默认 label",
            "title": "图表标题",
        }, "visualization"),
        ("gee_chart_phenology", "生成年内日变化分析图（物候分析），分析植被指数在一年中不同日期的平均变化规律。", {
            "image_collection_id": "GEE ImageCollection ID",
            "band_names": "波段名列表，如 [NDVI, EVI]",
            "start_date": "起始日期",
            "end_date": "结束日期",
            "title": "图表标题",
        }, "visualization"),
        ("dynamic_world_landcover", "获取 Dynamic World 10m 分辨率全球土地覆盖分类（9类：水体/树木/草地/淹没植被/农作物/灌木/建筑/裸地/冰雪）。", {
            "start_date": "起始日期",
            "end_date": "结束日期",
            "return_type": "class（原始分类值）或 hillshade（带阴影可视化）",
            "scale": "导出分辨率，默认 10",
            "title": "专题图标题",
        }, "analysis"),
        ("gee_download_collection", "下载完整 ImageCollection 中的每景影像到本地目录，支持逐景下载 ERA5、Landsat 等数据集。", {
            "image_collection_id": "GEE ImageCollection ID",
            "start_date": "起始日期",
            "end_date": "结束日期",
            "band_names": "波段名列表",
            "scale": "分辨率（米）",
            "max_images": "最大下载数，默认 50",
        }, "data"),
        ("gee_download_tiled", "鱼网分割 + 并行下载大区域影像，将大区域分割为网格瓦片逐片下载。", {
            "image_id": "GEE 影像 ID",
            "scale": "分辨率（米）",
            "rows": "行分割数，默认 2",
            "cols": "列分割数，默认 2",
            "prefix": "文件名前缀",
            "parallel": "是否并行下载，默认 true",
        }, "data"),
        ("generate_timeslider_map", "生成带时间滑块的交互式 HTML 地图，用户可拖动滑块查看 ImageCollection 不同时期的影像变化。", {
            "image_collection_id": "GEE ImageCollection ID",
            "start_date": "起始日期",
            "end_date": "结束日期",
            "band_names": "波段名列表",
            "vis_params": "可视化参数 dict",
            "time_interval": "自动播放间隔（秒），默认 1",
            "opacity": "图层透明度，默认 0.8",
        }, "visualization"),
        ("ee_unsupervised_classify", "在 GEE 端执行无监督分类（K-Means 聚类），自动采样训练数据并分类，输出 TIF 和专题图。", {
            "image_id": "可选，GEE 影像 ID，不填则自动选最少云量 Landsat",
            "start_date": "日期范围起始",
            "end_date": "日期范围结束",
            "band_names": "分类波段列表",
            "n_clusters": "聚类数，默认 5",
            "scale": "分辨率，默认 30",
            "title": "专题图标题",
        }, "analysis"),
        ("ee_supervised_classify", "在 GEE 端执行监督分类（CART/RandomForest/NaiveBayes/SVM），需要提供标签影像（如 NLCD）。", {
            "image_id": "可选，待分类影像 ID",
            "classifier_type": "分类器类型 CART/RandomForest/NaiveBayes/SVM",
            "label_image_id": "标签影像 ID（如 USGS/NLCD/NLCD2016）",
            "label_band": "标签波段名，默认 landcover",
            "band_names": "分类波段列表",
            "scale": "分辨率，默认 30",
            "title": "专题图标题",
        }, "analysis"),
        ("gee_zonal_statistics", "按区域计算影像的分区统计量（mean/min/max/std/sum），输出 CSV。支持行政区划统计。", {
            "image_id": "GEE 影像 ID 或本地 TIF 路径",
            "stat_type": "统计类型 mean/min/max/median/std/sum，默认 MEAN",
            "scale": "分析分辨率（米），默认 1000",
            "label_property": "区域标识属性名",
        }, "analysis"),

        ("run_lst", "对当前多波段影像执行地表温度反演（SCA算法），生成 LST 栅格和预览图。", {"input_tif": "可选，输入栅格路径"}, "analysis"),
        ("statistics", "对当前单波段栅格做统计分析并输出直方图。", {"tif_path": "可选，栅格路径"}, "analysis"),
        ("classify_map", "对当前单波段结果自动分类并出分类图。", {"method": "natural_breaks/equal_interval/quantile", "n_classes": "分类数"}, "analysis"),
        ("threshold_highlight", "高亮超过阈值或位于某个区间的区域。", {"operator": ">/< /between/outside", "value": "阈值"}, "analysis"),
        ("enhance_raster", "对当前栅格做增强或去噪（高斯/中值/直方图均衡/锐化）。", {"method": "gaussian/median/histogram_eq/clahe/sharpen", "kernel_size": "核大小"}, "analysis"),
        ("profile_analysis", "对当前栅格做剖面分析。", {"start": "起点[col,row]", "end": "终点[col,row]"}, "analysis"),

        ("make_thematic_map", "将当前单波段结果做成标准专题图（含图例、比例尺、指北针）。", {"title": "标题", "colormap": "配色", "legend_position": "图例位置", "dpi": "分辨率"}, "visualization"),
        ("view_3d", "将当前单波段栅格生成 3D 可视化。", {"elevation": "俯仰角", "azimuth": "方位角"}, "visualization"),
        ("compare_views", "对比原始图和当前结果图。", {"mode": "side_by_side 或 difference"}, "visualization"),
        ("transform_raster", "对当前栅格做翻转或旋转。", {"operation": "flip_h/flip_v/rotate_90/rotate_180/rotate_270"}, "visualization"),

        ("export_result", "把最近结果图导出为 png/jpg/pdf/tif。", {"format": "png/jpg/pdf/tif"}, "export"),
        ("set_map_style", "更新地图样式参数。绝对位置用 legend_position/scalebar_position/north_position，微调偏移用 legend_xoffset/yoffset、north_xoffset/yoffset、scalebar_xoffset/yoffset。", {"title": "标题", "colormap": "配色", "legend_position": "绝对位置"}, "system"),
        ("update_preferences", "更新长期用户偏好（默认导出格式、分类数、配色等）。", {"export_format": "导出格式", "n_classes": "默认分类数"}, "system"),
        ("summarize_context", "返回当前会话上下文摘要。", {}, "system"),
        ("generate_report", "生成带文字解读的图文实验报告（HTML格式）。", {"title": "报告标题", "subtitle": "副标题", "conclusion": "总结文字", "format": "html或pdf", "images": "可选，指定要包含的图片路径列表"}, "export"),
        ("generate_web_map", "生成交互式 Web 地图（Leaflet HTML）。支持鼠标悬停查看坐标、图层切换、热力图叠加、绘制工具、数据统计弹窗。", {"title": "地图标题", "colormap": "配色方案", "show_heatmap": "是否显示热力图(true/false)", "overlay_opacity": "透明度(0~1)", "additional_layers": "额外图层列表"}, "visualization"),
    ]

    handler_map = {
        "search_local_files": search_local_files_tool,
        "set_current_dataset": set_current_dataset,
        "inspect_raster": inspect_current_or_path,
        "resolve_admin_region": resolve_admin_region_tool,
        "gee_init": gee_init_tool,
        "gee_compute_lst": gee_compute_lst_tool,
        "gee_download_landsat_sca": gee_download_landsat_sca_tool,
        "gee_download_monthly_lst": gee_download_monthly_lst_tool,
        "gee_download_yearly_lst": gee_download_yearly_lst_tool,
        "gee_download_multi_year_lst": gee_download_multi_year_lst_tool,
        # ── 新增 ──
        "gee_lst_timelapse": gee_lst_timelapse_tool,
        "gee_lst_split_panel": gee_lst_split_panel_tool,
        "gee_lst_trend_chart": gee_lst_trend_chart_tool,
        "gee_lst_timelapse_local": gee_lst_timelapse_local_tool,
        # ── A1-A8: geemap 集成工具 ──
        "extract_timeseries_to_point": extract_timeseries_tool,
        "gee_timeseries_inspector": timeseries_inspector_tool,
        "gee_chart_timeseries": gee_chart_timeseries_tool,
        "gee_chart_by_region": gee_chart_by_region_tool,
        "gee_chart_phenology": gee_chart_phenology_tool,
        "dynamic_world_landcover": dynamic_world_tool,
        "gee_download_collection": gee_download_collection_tool,
        "gee_download_tiled": gee_download_tiled_tool,
        "generate_timeslider_map": time_slider_tool,
        "ee_unsupervised_classify": ee_unsupervised_classify_tool,
        "ee_supervised_classify": ee_supervised_classify_tool,
        "gee_zonal_statistics": zonal_stats_tool,
        "run_lst": run_lst_tool,
        "statistics": statistics_tool,
        "classify_map": classify_map_tool,
        "threshold_highlight": threshold_tool,
        "enhance_raster": enhance_tool,
        "profile_analysis": profile_tool,
        "make_thematic_map": make_thematic_map_tool,
        "view_3d": view3d_tool,
        "compare_views": compare_tool,
        "transform_raster": transform_tool,
        "export_result": export_tool,
        "set_map_style": set_map_style,
        "update_preferences": update_preferences,
        "summarize_context": summarize_context,
        "generate_report": generate_report_tool,
        "generate_web_map": generate_web_map_tool,
    }

    for name, desc, schema, cat in tool_defs:
        registry.register(
            ToolSpec(name=name, description=desc, input_schema=schema, category=cat),
            handler_map[name],
        )
