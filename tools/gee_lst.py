"""
GEE LST 工具：云端反演、波段下载、月度/年度/跨年批量
"""
from __future__ import annotations

import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict

from config import GEE_DRIVE_FOLDER, GDRIVE_SYNC_DIR
import config as app_config
from tools.base import BaseTool, tool


def _out_dir() -> Path:
    d = Path(app_config.OUTPUTS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _default_last_full_month() -> tuple[str, str]:
    """默认时间范围：上一个完整自然月"""
    today = date.today()
    first_day_this_month = today.replace(day=1)
    last_day_prev_month = first_day_this_month - timedelta(days=1)
    first_day_prev_month = last_day_prev_month.replace(day=1)
    return first_day_prev_month.isoformat(), last_day_prev_month.isoformat()


def _sanitize_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', '_', name).strip('_')


def _safe_stem(path: str | None, fallback: str = "result") -> str:
    if path:
        return Path(path).stem
    return fallback


def build_task_filename(
    region_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    year: int | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    month: int | None = None,
    product: str = "LST",
    suffix: str = ".tif",
) -> str:
    """生成可读的任务输出文件名"""
    parts = []
    if region_name:
        best_idx = -1
        for sep in ["省", "市", "区", "县", "旗"]:
            idx = region_name.rfind(sep)
            if idx > best_idx and idx < len(region_name) - 1:
                best_idx = idx
        if best_idx >= 0:
            region_name = region_name[best_idx + 1:]
        parts.append(_sanitize_filename(region_name))

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

    parts.append(product)
    name = "_".join(parts)
    if suffix and not name.endswith(suffix):
        name += suffix
    return name


class _GeeLSTBase(BaseTool):
    """GEE LST 工具基类：共享 region 解析和 runtime 更新逻辑"""

    def _get_region(self, args: Dict[str, Any]) -> Any:
        return args.get("region") or self.runtime.last_region_geojson

    def _on_success(self, result: Dict[str, Any]):
        if result.get("success") and result.get("output_tif") and os.path.exists(result["output_tif"]):
            self.runtime.current_dataset = result["output_tif"]
            self.runtime.last_tif_output = result["output_tif"]
            self.runtime.last_output = None
            if self.runtime.source_dataset is None:
                self.runtime.source_dataset = result["output_tif"]


@tool(
    name="gee_compute_lst",
    description="【推荐】在 GEE 云端直接进行单通道地表温度反演，仅下载单波段 LST(°C) TIF。一步完成，无需后续本地 run_lst。",
    parameters={
        "start_date": "开始日期 YYYY-MM-DD，缺省时默认上一个完整自然月",
        "end_date": "结束日期 YYYY-MM-DD，缺省时默认上一个完整自然月",
        "cloud_pct": "最大云量百分比 0-100，默认 30",
        "scale": "分辨率(米)，默认 30",
    },
    category="data",
)
class GeeComputeLSTTool(_GeeLSTBase):
    def execute(self, start_date=None, end_date=None, cloud_pct=30, scale=30,
                region=None, region_path=None, project_id=None,
                download_timeout=1800) -> Dict[str, Any]:
        if not start_date or not end_date:
            start_date, end_date = _default_last_full_month()

        region = region or self._get_region({})
        if region is None:
            return {
                "success": False,
                "message": "缺少研究区边界。请先调用 resolve_admin_region 解析行政区边界。",
                "requires": "resolve_admin_region",
            }

        from gis.gee_tools import gee_compute_lst
        region_name = self.runtime.last_region_name or ""
        filename = build_task_filename(
            region_name=region_name, start_date=start_date,
            end_date=end_date, product="LST"
        )
        output_tif = str(_out_dir() / filename)

        result = gee_compute_lst(
            start_date=start_date,
            end_date=end_date,
            output_tif=output_tif,
            region=region,
            region_path=region_path,
            scale=int(scale),
            cloud_pct=float(cloud_pct),
            project_id=project_id,
            download_timeout=int(download_timeout),
        )
        self._on_success(result)
        return result


@tool(
    name="gee_download_landsat_sca",
    description="从 GEE 下载适合本地 SCA 单通道地表温度反演的 Landsat 8/9 Level-2 三波段数据（red, nir, bt_raw）。已不推荐，优先使用 gee_compute_lst。",
    parameters={
        "start_date": "开始日期 YYYY-MM-DD",
        "end_date": "结束日期 YYYY-MM-DD",
        "region": "AOI，可传 [xmin,ymin,xmax,ymax] 或 GeoJSON Feature",
        "region_path": "可选，本地 GeoJSON 文件路径",
        "scale": "导出分辨率，默认30",
        "cloud_pct": "最大云量百分比，默认30",
        "reducer": "median/mean/mosaic/first，默认 median",
        "mask_clouds": "是否在 GEE 端像素级去云，默认 true",
    },
    category="data",
)
class GeeDownloadLandsatSCATool(_GeeLSTBase):
    def execute(self, start_date=None, end_date=None, region=None, region_path=None,
                scale=30, cloud_pct=30, reducer="median", mask_clouds=True,
                project_id=None, drive_folder=None, local_drive_path=None,
                download_timeout=1800, output_tif=None) -> Dict[str, Any]:
        if not start_date or not end_date:
            start_date, end_date = _default_last_full_month()

        region = region or self._get_region({})
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

        from gis.gee_tools import gee_download_landsat_sca
        region_name = self.runtime.last_region_name or ""
        filename = build_task_filename(
            region_name=region_name, start_date=start_date,
            end_date=end_date, product="Landsat_SCA"
        )
        output_tif = output_tif or str(_out_dir() / filename)

        result = gee_download_landsat_sca(
            start_date=start_date,
            end_date=end_date,
            output_tif=output_tif,
            region=region,
            region_path=region_path,
            scale=int(scale),
            reducer=reducer,
            cloud_pct=float(cloud_pct),
            mask_clouds=bool(mask_clouds),
            project_id=project_id,
            drive_folder=drive_folder or GEE_DRIVE_FOLDER,
            local_drive_path=local_drive_path or str(GDRIVE_SYNC_DIR),
            download_timeout=int(download_timeout),
        )
        self._on_success(result)
        return result


@tool(
    name="gee_download_monthly_lst",
    description="月度 LST 智能合成（分级降级）。自动选取当月最优 Landsat 8/9 场景，逐景 SCA 单通道反演后合成，输出单波段 LST（°C）。若未给日期，默认上一个完整自然月。",
    parameters={
        "start_date": "开始日期 YYYY-MM-DD，缺省时默认上一个完整自然月",
        "end_date": "结束日期 YYYY-MM-DD，缺省时默认上一个完整自然月",
        "scale": "导出分辨率，默认30",
    },
    category="data",
)
class GeeDownloadMonthlyLSTTool(_GeeLSTBase):
    def execute(self, start_date=None, end_date=None, scale=30, region=None,
                region_path=None, project_id=None, drive_folder=None,
                local_drive_path=None, download_timeout=1800) -> Dict[str, Any]:
        if not start_date or not end_date:
            start_date, end_date = _default_last_full_month()

        region = region or self._get_region({})
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

        from gis.gee_tools import gee_download_monthly_lst
        region_name = self.runtime.last_region_name or ""
        filename = build_task_filename(
            region_name=region_name, start_date=start_date,
            end_date=end_date, product="LST"
        )
        output_tif = str(_out_dir() / filename)

        result = gee_download_monthly_lst(
            start_date=start_date,
            end_date=end_date,
            output_tif=output_tif,
            region=region,
            region_path=region_path,
            scale=int(scale),
            project_id=project_id,
            drive_folder=drive_folder or GEE_DRIVE_FOLDER,
            local_drive_path=local_drive_path or str(GDRIVE_SYNC_DIR),
            download_timeout=int(download_timeout),
        )
        self._on_success(result)
        return result


@tool(
    name="gee_download_yearly_lst",
    description="批量下载全年（或指定月份）的月度 LST。在 GEE 云端逐月执行分级降级选景 + 逐景 SCA 反演。默认下载全年12个月。需要先用 resolve_admin_region 设置研究区。",
    parameters={
        "year": "年份，如 2025",
        "months": "可选，要下载的月份列表，如 [1,2,3,4,5,6]。不传则默认全部 12 个月",
        "output_dir": "输出目录，存放各月的 TIF 文件",
        "scale": "导出分辨率，默认30",
    },
    category="data",
)
class GeeDownloadYearlyLSTTool(_GeeLSTBase):
    def execute(self, year=2025, months=None, output_dir=None, scale=30,
                region=None, region_path=None, project_id=None,
                drive_folder=None, local_drive_path=None,
                download_timeout=1800) -> Dict[str, Any]:
        region = region or self._get_region({})
        if region is None:
            return {
                "success": False,
                "message": "缺少研究区边界。请先调用 resolve_admin_region 解析边界。",
                "requires": "resolve_admin_region",
            }

        from gis.gee_tools import gee_download_yearly_lst
        region_name = self.runtime.last_region_name or ""
        dir_name = build_task_filename(
            region_name=region_name, year=int(year), product="全年LST", suffix=""
        )
        output_dir = output_dir or str(_out_dir() / dir_name)

        result = gee_download_yearly_lst(
            year=int(year),
            output_dir=output_dir,
            region=region,
            region_path=region_path,
            region_name=region_name,
            months=months,
            scale=int(scale),
            project_id=project_id,
            drive_folder=drive_folder or GEE_DRIVE_FOLDER,
            local_drive_path=local_drive_path or str(GDRIVE_SYNC_DIR),
            download_timeout=int(download_timeout),
        )
        if result.get("success") and result.get("results"):
            last = result["results"][-1]
            if last.get("output_tif") and os.path.exists(last["output_tif"]):
                self.runtime.current_dataset = last["output_tif"]
                self.runtime.last_tif_output = last["output_tif"]
        return result


@tool(
    name="gee_download_multi_year_lst",
    description="跨多年单月 LST 批量反演。对指定年份范围内每一年的同一月份，执行分级降级选景 + 逐景 SCA 反演，输出 N 个单波段 LST TIF（°C）。典型用法：'2020-2025年每年8月的地表温度'。",
    parameters={
        "start_year": "起始年份，如 2020",
        "end_year": "结束年份，如 2025",
        "month": "月份 1-12，如 8 表示每年8月",
        "output_dir": "输出目录，存放各年的 TIF 文件",
        "scale": "导出分辨率，默认30",
    },
    category="data",
)
class GeeDownloadMultiYearLSTTool(_GeeLSTBase):
    def execute(self, start_year=2020, end_year=2025, month=8, output_dir=None,
                scale=30, region=None, region_path=None, project_id=None,
                drive_folder=None, local_drive_path=None,
                download_timeout=1800) -> Dict[str, Any]:
        region = region or self._get_region({})
        if region is None:
            return {
                "success": False,
                "message": "缺少研究区边界。请先调用 resolve_admin_region 解析边界。",
                "requires": "resolve_admin_region",
            }

        from gis.gee_tools import gee_download_multi_year_lst
        region_name = self.runtime.last_region_name or ""
        dir_name = build_task_filename(
            region_name=region_name, start_year=int(start_year),
            end_year=int(end_year), month=int(month), product="LST", suffix=""
        )
        output_dir = output_dir or str(_out_dir() / dir_name)

        result = gee_download_multi_year_lst(
            start_year=int(start_year),
            end_year=int(end_year),
            month=int(month),
            output_dir=output_dir,
            region=region,
            region_path=region_path,
            region_name=region_name,
            scale=int(scale),
            project_id=project_id,
            drive_folder=drive_folder or GEE_DRIVE_FOLDER,
            local_drive_path=local_drive_path or str(GDRIVE_SYNC_DIR),
            download_timeout=int(download_timeout),
        )
        if result.get("success") and result.get("results"):
            last = result["results"][-1]
            if last.get("output_tif") and os.path.exists(last["output_tif"]):
                self.runtime.current_dataset = last["output_tif"]
                self.runtime.last_tif_output = last["output_tif"]
        return result
