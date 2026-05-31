"""
GEE ET 工具：基于 SEBAL 模型的云端蒸散发反演

工具清单：
- gee_compute_et: GEE 云端 SEBAL 计算（推荐）
- gee_download_monthly_et: 月度 ET 合成
- gee_download_yearly_et: 年度 ET 批量
"""
from __future__ import annotations

import os
import re
import shutil
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

from config import GEE_DRIVE_FOLDER, GDRIVE_SYNC_DIR
import config as app_config
from tools.base import BaseTool, tool


def _out_dir(runtime=None) -> Path:
    if runtime:
        return runtime.session_dir
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


def build_task_filename(
    region_name: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    year: int | None = None,
    start_year: int | None = None,
    end_year: int | None = None,
    month: int | None = None,
    product: str = "ET",
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


class _GeeETBase(BaseTool):
    """GEE ET 工具基类：共享 region 解析和 runtime 更新逻辑"""

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
    name="gee_compute_et",
    description="【推荐】在 GEE 云端基于 SEBAL 模型计算地表蒸散发(ET)，仅下载日ET(mm/d) TIF。一步完成，无需后续本地处理。",
    parameters={
        "start_date": "开始日期 YYYY-MM-DD，缺省时默认上一个完整自然月",
        "end_date": "结束日期 YYYY-MM-DD，缺省时默认上一个完整自然月",
        "cloud_pct": "最大云量百分比 0-100，默认 30",
        "scale": "分辨率(米)，默认 30",
        "region": "可选，AOI 边界（GeoJSON dict 或 bbox [xmin,ymin,xmax,ymax]），缺省使用已解析的行政区",
        "region_path": "可选，本地 GeoJSON 文件路径",
    },
    category="data",
)
class GeeComputeETTool(_GeeETBase):
    def execute(self, start_date=None, end_date=None, cloud_pct=30, scale=30,
                region=None, region_path=None, project_id=None,
                download_timeout=7200) -> Dict[str, Any]:
        if not start_date or not end_date:
            start_date, end_date = _default_last_full_month()

        region = region or self._get_region({})
        if region is None:
            return {
                "success": False,
                "message": "缺少研究区边界。请先调用 resolve_admin_region 解析行政区边界。",
                "requires": "resolve_admin_region",
            }

        from gis.gee_tools import gee_compute_et
        region_name = self.runtime.last_region_name or ""
        filename = build_task_filename(
            region_name=region_name, start_date=start_date,
            end_date=end_date, product="ET"
        )
        output_tif = str(_out_dir(self.runtime) / filename)

        result = gee_compute_et(
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
    name="gee_download_monthly_et",
    description="月度 ET 智能合成。自动选取当月最优 Landsat 场景，逐景 SEBAL 计算后合成，输出日ET（mm/d）。若未给日期，默认上一个完整自然月。",
    parameters={
        "start_date": "开始日期 YYYY-MM-DD，缺省时默认上一个完整自然月",
        "end_date": "结束日期 YYYY-MM-DD，缺省时默认上一个完整自然月",
        "scale": "导出分辨率，默认30",
        "region": "可选，AOI 边界，缺省使用已解析的行政区",
        "region_path": "可选，本地 GeoJSON 文件路径",
    },
    category="data",
)
class GeeDownloadMonthlyETTool(_GeeETBase):
    def execute(self, start_date=None, end_date=None, scale=30, region=None,
                region_path=None, project_id=None, drive_folder=None,
                local_drive_path=None, download_timeout=7200) -> Dict[str, Any]:
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

        from gis.gee_tools import gee_download_monthly_et
        region_name = self.runtime.last_region_name or ""
        filename = build_task_filename(
            region_name=region_name, start_date=start_date,
            end_date=end_date, product="ET"
        )
        output_tif = str(_out_dir(self.runtime) / filename)

        result = gee_download_monthly_et(
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
    name="gee_download_yearly_et",
    description="批量下载全年（或指定月份）的月度 ET。在 GEE 云端逐月执行 SEBAL 计算。默认下载全年12个月。需要先用 resolve_admin_region 设置研究区。",
    parameters={
        "year": "年份，如 2025",
        "months": "可选，要下载的月份列表，如 [1,2,3,4,5,6]。不传则默认全部 12 个月",
        "output_dir": "输出目录，存放各月的 TIF 文件",
        "scale": "导出分辨率，默认30",
        "region": "可选，AOI 边界，缺省使用已解析的行政区",
        "region_path": "可选，本地 GeoJSON 文件路径",
    },
    category="data",
)
class GeeDownloadYearlyETTool(_GeeETBase):
    def execute(self, year=2025, months=None, output_dir=None, scale=30,
                region=None, region_path=None, project_id=None,
                drive_folder=None, local_drive_path=None,
                download_timeout=7200) -> Dict[str, Any]:
        region = region or self._get_region({})
        if region is None:
            return {
                "success": False,
                "message": "缺少研究区边界。请先调用 resolve_admin_region 解析边界。",
                "requires": "resolve_admin_region",
            }

        if months is None:
            months = list(range(1, 13))

        region_name = self.runtime.last_region_name or ""
        out_dir = Path(output_dir) if output_dir else _out_dir(self.runtime)
        out_dir.mkdir(parents=True, exist_ok=True)

        from gis.gee_tools import gee_download_monthly_et

        results = []
        for m in months:
            # 计算月份的起止日期
            start = f"{year}-{m:02d}-01"
            if m == 12:
                end = f"{year}-12-31"
            else:
                end_date = date(year, m + 1, 1) - timedelta(days=1)
                end = end_date.isoformat()

            filename = build_task_filename(
                region_name=region_name, year=year, month=m, product="ET"
            )
            output_tif = str(out_dir / filename)

            print(f"[GEE ET] 处理 {year}年{m}月...")
            result = gee_download_monthly_et(
                start_date=start,
                end_date=end,
                output_tif=output_tif,
                region=region,
                region_path=region_path,
                scale=int(scale),
                project_id=project_id,
                drive_folder=drive_folder or GEE_DRIVE_FOLDER,
                local_drive_path=local_drive_path or str(GDRIVE_SYNC_DIR),
                download_timeout=int(download_timeout),
            )
            results.append({
                "month": m,
                "success": result.get("success", False),
                "output_tif": result.get("output_tif"),
                "message": result.get("message"),
            })

        # 统计结果
        success_count = sum(1 for r in results if r["success"])
        total = len(results)

        return {
            "success": success_count > 0,
            "message": f"年度 ET 下载完成：成功 {success_count}/{total} 个月",
            "results": results,
            "output_dir": str(out_dir),
        }
