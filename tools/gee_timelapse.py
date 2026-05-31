"""
GEE 时间序列可视化工具：时间序列动画、分屏对比、趋势图
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict

import config as app_config
from tools.base import BaseTool, ensure_gee_and_roi, tool


def _out_dir(runtime=None) -> Path:
    if runtime:
        return runtime.session_dir
    d = Path(app_config.OUTPUTS_DIR)
    d.mkdir(parents=True, exist_ok=True)
    return d


@tool(
    name="gee_lst_timelapse",
    description="在 GEE 端完成多年指定月份 LST 反演并生成时间序列 GIF 动画。需要先用 resolve_admin_region 设置研究区。",
    parameters={
        "start_year": "起始年份，默认 2015",
        "end_year": "结束年份（含），默认 2024",
        "month": "月份（1-12 或中文如'七月'），默认 7",
        "cloud_pct": "最大云量百分比，默认 30",
        "title": "GIF 标题，缺省自动生成",
        "fps": "帧率，默认 2",
        "dimensions": "图片尺寸（像素），默认 600",
        "vmin": "色标最小值（°C），默认 20",
        "vmax": "色标最大值（°C），默认 45",
    },
    category="visualization",
)
class GeeLSTTimelapseTool(BaseTool):
    def execute(self, start_year=2015, end_year=2024, month=7, cloud_pct=30,
                title="", fps=2, dimensions=600, vmin=20, vmax=45) -> Dict[str, Any]:
        ee_geom, err = ensure_gee_and_roi(self.runtime)
        if err:
            return err

        from gis.gee_timelapse import generate_lst_timelapse, parse_month
        gif_dir = str(_out_dir(self.runtime) / "timelapse")
        os.makedirs(gif_dir, exist_ok=True)

        result = generate_lst_timelapse(
            roi=ee_geom, output_dir=gif_dir,
            start_year=int(start_year), end_year=int(end_year),
            month=parse_month(month), cloud_pct=float(cloud_pct),
            title=title, fps=int(fps), dimensions=int(dimensions),
            vmin=float(vmin), vmax=float(vmax),
        )
        if result.get("success") and result.get("gif_path"):
            self.runtime.last_output = result["gif_path"]
            result["output_gif"] = result["gif_path"]
        return result


@tool(
    name="gee_lst_split_panel",
    description="生成两年指定月份 LST 的分屏对比交互式地图（HTML），可在浏览器中左右拖动对比。",
    parameters={
        "year_a": "第一年，默认 2015",
        "year_b": "第二年，默认 2024",
        "month": "月份，默认 7",
        "cloud_pct": "最大云量百分比，默认 30",
        "vmin": "色标最小值（°C），默认 20",
        "vmax": "色标最大值（°C），默认 45",
    },
    category="visualization",
)
class GeeLSTSplitPanelTool(BaseTool):
    def execute(self, year_a=2015, year_b=2024, month=7, cloud_pct=30,
                vmin=20, vmax=45) -> Dict[str, Any]:
        ee_geom, err = ensure_gee_and_roi(self.runtime)
        if err:
            return err

        from gis.gee_timelapse import generate_lst_split_panel, parse_month
        name = self.runtime.last_region_name or "region"
        output_path = str(_out_dir(self.runtime) / f"{name}_split_{year_a}_vs_{year_b}_m{month}.html")

        result = generate_lst_split_panel(
            roi=ee_geom, output_path=output_path,
            year_a=int(year_a), year_b=int(year_b),
            month=parse_month(month), cloud_pct=float(cloud_pct),
            vmin=float(vmin), vmax=float(vmax),
        )
        if result.get("success"):
            self.runtime.last_output = output_path
            result["output_html"] = output_path
        return result


@tool(
    name="gee_lst_trend_chart",
    description="生成多年指定月份 LST 均值变化折线图（含极值范围阴影），用于分析温度年际趋势。",
    parameters={
        "start_year": "起始年份，默认 2015",
        "end_year": "结束年份（含），默认 2024",
        "month": "月份，默认 7",
        "cloud_pct": "最大云量百分比，默认 30",
        "title": "图表标题，缺省自动生成",
    },
    category="visualization",
)
class GeeLSTTrendChartTool(BaseTool):
    def execute(self, start_year=2015, end_year=2024, month=7, cloud_pct=30,
                title="") -> Dict[str, Any]:
        ee_geom, err = ensure_gee_and_roi(self.runtime)
        if err:
            return err

        from gis.gee_timelapse import generate_lst_trend_chart, parse_month
        name = self.runtime.last_region_name or "region"
        month_val = parse_month(month)
        output_path = str(_out_dir(self.runtime) / f"{name}_trend_{start_year}_{end_year}_m{month_val}.png")

        result = generate_lst_trend_chart(
            roi=ee_geom, output_path=output_path,
            start_year=int(start_year), end_year=int(end_year),
            month=month, cloud_pct=float(cloud_pct), title=title,
        )
        if result.get("success"):
            self.runtime.last_output = output_path
            result["output_png"] = output_path
        return result


@tool(
    name="gee_lst_timelapse_local",
    description="【推荐】逐年从 GEE 下载 Landsat 数据到本地，本地执行 LST 反演，再合成 GIF 动画。比 GEE 端合成更稳定可靠。",
    parameters={
        "start_year": "起始年份，默认 2015",
        "end_year": "结束年份（含），默认 2024",
        "month": "月份（1-12 或中文如'七月'），默认 7",
        "cloud_pct": "最大云量百分比，默认 30",
        "title": "GIF 标题，缺省自动生成",
        "fps": "帧率，默认 2",
        "dpi": "输出图片分辨率，默认 150",
        "vmin": "色标最小值（°C），默认自动",
        "vmax": "色标最大值（°C），默认自动",
    },
    category="visualization",
)
class GeeLSTTimelapseLocalTool(BaseTool):
    def execute(self, start_year=2015, end_year=2024, month=7, cloud_pct=30,
                title="", fps=2, dpi=150, vmin=None, vmax=None) -> Dict[str, Any]:
        ee_geom, err = ensure_gee_and_roi(self.runtime)
        if err:
            return err

        from gis.gee_timelapse import generate_lst_timelapse_local, parse_month
        from gis.web_map import generate_timelapse_web_map

        gif_dir = str(_out_dir(self.runtime) / "timelapse")
        os.makedirs(gif_dir, exist_ok=True)

        result = generate_lst_timelapse_local(
            roi=ee_geom, output_dir=gif_dir,
            start_year=int(start_year), end_year=int(end_year),
            month=parse_month(month), cloud_pct=float(cloud_pct),
            title=title, fps=int(fps), dpi=int(dpi),
            vmin=float(vmin) if vmin is not None else None,
            vmax=float(vmax) if vmax is not None else None,
        )
        if result.get("success") and result.get("gif_path"):
            self.runtime.last_output = result["gif_path"]
            # 统一输出字段：前端按 output_gif / output_html 提取文件
            result["output_gif"] = result["gif_path"]
            lst_tifs = result.get("lst_tifs", [])
            years_ok = result.get("years_ok", [])
            if lst_tifs and years_ok:
                m = parse_month(month)
                web_path = str(_out_dir(self.runtime) / f"timelapse_lst_{start_year}_{end_year}_m{m}_interactive.html")
                web_result = generate_timelapse_web_map(
                    lst_tif_paths=lst_tifs, years=years_ok,
                    output_path=web_path,
                    title=title or f"{month}月地表温度变化 {start_year}-{end_year}",
                    month=m,
                )
                if web_result.get("success"):
                    result["web_map_path"] = web_path
                    result["output_html"] = web_path
        return result
