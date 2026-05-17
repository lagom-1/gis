"""
GEE 时间序列模块 - 多年任意月份 LST 反演 + geemap 可视化
支持：任意月份、任意年份范围、时间序列 GIF、分屏对比、折线图
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import ee

from agent.gee_client import init_gee


# ============================================================
# 1. 月份解析
# ============================================================

_MONTH_NAMES = {
    "一月": 1, "二月": 2, "三月": 3, "四月": 4,
    "五月": 5, "六月": 6, "七月": 7, "八月": 8,
    "九月": 9, "十月": 10, "十一月": 11, "十二月": 12,
    "1月": 1, "2月": 2, "3月": 3, "4月": 4,
    "5月": 5, "6月": 6, "7月": 7, "8月": 8,
    "9月": 9, "10月": 10, "11月": 11, "12月": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4,
    "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def parse_month(text) -> int:
    """
    从各种格式解析月份。支持：数字、中文、英文。
    返回 1-12，解析失败默认 7。
    """
    if isinstance(text, int):
        if 1 <= text <= 12:
            return text
        return 7

    text = str(text).strip().lower()

    # 纯数字
    if text.isdigit():
        m = int(text)
        return m if 1 <= m <= 12 else 7

    # 中文/英文名称
    for name, val in _MONTH_NAMES.items():
        if name in text:
            return val

    return 7  # 默认七月


def _month_days(year: int, month: int) -> int:
    """获取某月天数"""
    import calendar
    return calendar.monthrange(year, month)[1]


# ============================================================
# 2. GEE 端 LST 反演（单通道算法）
# ============================================================

def _mask_clouds_qa(image: ee.Image) -> ee.Image:
    """Landsat Collection 2 QA_PIXEL 云掩膜"""
    qa = image.select("QA_PIXEL")
    cloud_bit = 1 << 3
    shadow_bit = 1 << 4
    mask = qa.bitwiseAnd(cloud_bit).eq(0).And(qa.bitwiseAnd(shadow_bit).eq(0))
    return image.updateMask(mask)


def _landsat89_l2_collection(region_geom, start_date: str, end_date: str, cloud_pct: float = 30):
    """合并 Landsat 8/9 Collection 2 Level-2 Tier 1"""
    col8 = (
        ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
        .filterBounds(region_geom)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lte("CLOUD_COVER", cloud_pct))
    )
    col9 = (
        ee.ImageCollection("LANDSAT/LC09/C02/T1_L2")
        .filterBounds(region_geom)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lte("CLOUD_COVER", cloud_pct))
    )
    return col8.merge(col9)


def _compute_lst_gee(image: ee.Image) -> ee.Image:
    """
    在 GEE 端执行单通道地表温度反演。
    输入：Landsat 8/9 L2 影像（含 SR_B4, SR_B5, ST_B10）
    输出：单波段 LST（°C）
    """
    red = image.select("SR_B4").multiply(0.0000275).add(-0.2)
    nir = image.select("SR_B5").multiply(0.0000275).add(-0.2)
    bt = image.select("ST_B10").multiply(0.00341802).add(149.0)

    ndvi = nir.subtract(red).divide(nir.add(red)).clamp(-1, 1)
    pv = ndvi.subtract(0.2).divide(0.3).pow(2).clamp(0, 1)
    emissivity = pv.multiply(0.004).add(0.986)

    lambda_ = 10.895e-6
    rho = 1.438e-2

    lst = bt.divide(
        ee.Image(1).add(
            bt.multiply(lambda_).divide(rho).multiply(emissivity.log())
        )
    ).subtract(273.15)

    return lst.rename("LST").copyProperties(image, ["system:time_start"])


# ============================================================
# 3. 多年指定月份 LST 合成
# ============================================================

def get_monthly_lst_collection(
    roi,
    start_year: int,
    end_year: int,
    month: int = 7,
    cloud_pct: float = 30,
) -> ee.ImageCollection:
    """
    获取多年指定月份 LST 合成影像集合。

    Args:
        roi: ee.Geometry 研究区
        start_year: 起始年份
        end_year: 结束年份（含）
        month: 月份（1-12）
        cloud_pct: 最大云量百分比

    Returns:
        ee.ImageCollection，每个影像代表一年该月的 LST 中值合成
    """
    month = parse_month(month)

    images = []
    skipped_years = []
    cloud_levels = sorted(set([cloud_pct, 40, 60, 80, 100]))  # 渐进放宽云量阈值
    for year in range(start_year, end_year + 1):
        start = f"{year}-{month:02d}-01"
        end_day = _month_days(year, month)
        end = f"{year}-{month:02d}-{end_day}"

        # 渐进式云量降级：从用户指定阈值逐步放宽到 100%
        col = None
        count = 0
        used_cloud_pct = cloud_pct
        for level in cloud_levels:
            col = _landsat89_l2_collection(roi, start, end, level)
            count = col.size().getInfo()
            if count > 0:
                used_cloud_pct = level
                break

        if count == 0:
            skipped_years.append(year)
            print(f"[GEE Timelapse] 警告：{year}年{month}月无任何 Landsat 影像，跳过")
            continue

        if used_cloud_pct > cloud_pct:
            print(f"[GEE Timelapse] {year}年{month}月：原始云量阈值 {cloud_pct}% 无影像，已放宽至 {used_cloud_pct}%（找到 {count} 景）")

        col = col.map(_mask_clouds_qa)
        composite = col.median().clip(roi)
        lst = _compute_lst_gee(composite)
        # 填补云掩膜造成的空洞（focal_mean radius=3, ~210m）
        lst_filled = lst.focal_mean(radius=3, kernelType="square", units="pixels")
        lst = lst.unmask(lst_filled)
        lst = lst.set("year", year)
        lst = lst.set("month", month)
        lst = lst.set("label", f"{year}年{month}月")
        lst = lst.set("system:time_start", ee.Date(f"{year}-{month:02d}-15").millis())
        images.append(lst)

    if skipped_years:
        print(f"[GEE Timelapse] 共跳过 {len(skipped_years)} 个年份: {skipped_years}")

    if not images:
        raise ValueError(
            f"{start_year}-{end_year}年{month}月期间无任何可用 Landsat 影像。"
            f"请尝试：扩大年份范围、提高 cloud_pct（当前{cloud_pct}%）、或换一个月份。"
        )

    return ee.ImageCollection(images)


# ============================================================
# 4. 时间序列 GIF 生成
# ============================================================

def generate_lst_timelapse(
    roi,
    output_dir: str,
    start_year: int = 2015,
    end_year: int = 2024,
    month: int = 7,
    cloud_pct: float = 30,
    title: str = "",
    fps: int = 2,
    dimensions: int = 600,
    vmin: float = 20,
    vmax: float = 45,
) -> Dict[str, Any]:
    """
    生成多年指定月份 LST 时间序列 GIF 动画。
    """
    try:
        init_gee()
        os.makedirs(output_dir, exist_ok=True)

        month = parse_month(month)
        if not title:
            title = f"{month}月地表温度变化 {start_year}-{end_year}"

        lst_col = get_monthly_lst_collection(roi, start_year, end_year, month, cloud_pct)

        vis_params = {
            "min": vmin,
            "max": vmax,
            "palette": ["313695", "4575b4", "74add1", "abd9e9",
                        "fee090", "fdae61", "f46d43", "d73027"],
            "dimensions": dimensions,
            "region": roi,
            "framesPerSecond": fps,
            "format": "gif",
        }

        out_gif = os.path.join(output_dir, f"lst_timelapse_{start_year}_{end_year}_m{month}.gif")

        try:
            import geemap
            geemap.download_ee_video(lst_col, vis_params, out_gif)
        except ImportError:
            url = lst_col.getVideoThumbURL(vis_params)
            import urllib.request
            urllib.request.urlretrieve(url, out_gif)

        # 检查 GIF 是否真的生成了
        if not os.path.exists(out_gif) or os.path.getsize(out_gif) < 1024:
            return {
                "success": False,
                "message": (
                    f"GIF 生成失败：GEE 返回了空数据。"
                    f"可能原因：{start_year}-{end_year}年{month}月在该区域无可用 Landsat 影像，"
                    f"或影像不含热红外波段（ST_B10）。"
                    f"请尝试：提高 cloud_pct、换月份、或扩大年份范围。"
                ),
            }

        # 添加年份标注
        texted_gif = os.path.join(output_dir, f"lst_timelapse_{start_year}_{end_year}_m{month}_labeled.gif")
        try:
            import geemap
            year_labels = [f"{y}年{month}月" for y in range(start_year, end_year + 1)]
            geemap.add_text_to_gif(
                out_gif, texted_gif,
                xy=("3%", "5%"),
                text_sequence=year_labels,
                font_size=26,
                font_color="#ffffff",
            )
            geemap.add_text_to_gif(
                texted_gif, texted_gif,
                xy=("2%", "88%"),
                text_sequence=title,
                font_size=20,
                font_color="#ffffff",
                progress_bar_color="cyan",
            )
        except ImportError:
            texted_gif = out_gif

        return {
            "success": True,
            "message": f"LST 时间序列 GIF 已生成: {start_year}-{end_year}年{month}月",
            "gif_path": texted_gif if os.path.exists(texted_gif) else out_gif,
            "raw_gif": out_gif,
            "years": list(range(start_year, end_year + 1)),
            "month": month,
            "vmin": vmin,
            "vmax": vmax,
        }

    except Exception as e:
        return {"success": False, "message": f"LST 时间序列 GIF 生成失败: {e}"}


# ============================================================
# 5. 分屏对比（首年 vs 末年）
# ============================================================

def generate_lst_split_panel(
    roi,
    output_path: str,
    year_a: int = 2015,
    year_b: int = 2024,
    month: int = 7,
    cloud_pct: float = 30,
    vmin: float = 20,
    vmax: float = 45,
) -> Dict[str, Any]:
    """生成两年 LST 的分屏对比地图（HTML）。"""
    try:
        init_gee()
        import geemap

        month = parse_month(month)
        lst_col = get_monthly_lst_collection(roi, min(year_a, year_b), max(year_a, year_b), month, cloud_pct)

        lst_a = lst_col.filter(ee.Filter.eq("year", year_a)).first()
        lst_b = lst_col.filter(ee.Filter.eq("year", year_b)).first()

        vis_params = {
            "min": vmin,
            "max": vmax,
            "palette": ["313695", "4575b4", "74add1", "abd9e9",
                        "fee090", "fdae61", "f46d43", "d73027"],
        }

        left_layer = geemap.ee_tile_layer(lst_a, vis_params, f"LST {year_a}年{month}月")
        right_layer = geemap.ee_tile_layer(lst_b, vis_params, f"LST {year_b}年{month}月")

        Map = geemap.Map()
        Map.split_map(left_layer, right_layer)
        Map.add_colorbar(vis_params, label="LST (°C)", position="bottomright")
        Map.centerObject(roi, 11)

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        Map.to_html(output_path)

        return {
            "success": True,
            "message": f"LST 分屏对比已生成: {year_a}年{month}月 vs {year_b}年{month}月",
            "output_path": output_path,
            "year_a": year_a,
            "year_b": year_b,
            "month": month,
        }

    except Exception as e:
        return {"success": False, "message": f"分屏对比生成失败: {e}"}


# ============================================================
# 6. 多年均值变化折线图
# ============================================================

def generate_lst_trend_chart(
    roi,
    output_path: str,
    start_year: int = 2015,
    end_year: int = 2024,
    month: int = 7,
    cloud_pct: float = 30,
    title: str = "",
) -> Dict[str, Any]:
    """生成多年 LST 均值变化折线图。"""
    try:
        init_gee()
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        month = parse_month(month)
        if not title:
            title = f"{month}月 LST 年际变化趋势 ({start_year}-{end_year})"

        lst_col = get_monthly_lst_collection(roi, start_year, end_year, month, cloud_pct)

        years = []
        means = []
        maxs = []
        mins = []

        for year in range(start_year, end_year + 1):
            img = lst_col.filter(ee.Filter.eq("year", year)).first()
            if img is None:
                continue

            stats = img.reduceRegion(
                reducer=ee.Reducer.mean().combine(
                    ee.Reducer.min(), sharedInputs=True
                ).combine(
                    ee.Reducer.max(), sharedInputs=True
                ),
                geometry=roi,
                scale=100,
                maxPixels=1e9,
            ).getInfo()

            lst_mean = stats.get("LST_mean")
            lst_min = stats.get("LST_min")
            lst_max = stats.get("LST_max")

            if lst_mean is not None:
                years.append(year)
                means.append(round(lst_mean, 2))
                mins.append(round(lst_min, 2) if lst_min else None)
                maxs.append(round(lst_max, 2) if lst_max else None)

        if not years:
            return {"success": False, "message": f"未获取到有效数据，请检查研究区或调整月份/云量参数"}

        # 绘图
        fig, ax = plt.subplots(figsize=(10, 5))
        ax.plot(years, means, "o-", color="#d73027", linewidth=2, markersize=8, label="均值")
        if mins and maxs and any(m is not None for m in mins):
            valid_mins = [m if m is not None else 0 for m in mins]
            valid_maxs = [m if m is not None else 0 for m in maxs]
            ax.fill_between(years, valid_mins, valid_maxs, alpha=0.2, color="#4575b4", label="极值范围")

        ax.set_xlabel("年份", fontsize=12)
        ax.set_ylabel("LST (°C)", fontsize=12)
        ax.set_title(title, fontsize=14, fontweight="bold")
        ax.legend(fontsize=10)
        ax.grid(alpha=0.3)
        ax.set_xticks(years)

        plt.tight_layout()
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        fig.savefig(output_path, dpi=200, bbox_inches="tight", facecolor="white")
        plt.close(fig)

        return {
            "success": True,
            "message": f"LST 趋势图已生成: {month}月 {start_year}-{end_year}",
            "output_path": output_path,
            "years": years,
            "means": means,
            "mins": mins,
            "maxs": maxs,
            "month": month,
        }

    except Exception as e:
        return {"success": False, "message": f"趋势图生成失败: {e}"}


# ============================================================
# 7. 【新增】本地版时间序列：逐下载 → 逐反演 → 合成 GIF
# ============================================================

def generate_lst_timelapse_local(
    roi,
    output_dir: str,
    start_year: int = 2015,
    end_year: int = 2024,
    month: int = 7,
    cloud_pct: float = 30,
    title: str = "",
    fps: int = 2,
    dpi: int = 150,
    vmin: float = None,
    vmax: float = None,
) -> Dict[str, Any]:
    """
    本地版 LST 时间序列：逐年从 GEE 下载 → 本地反演 → 合成 GIF。

    与 generate_lst_timelapse 的区别：
    - 每年单独下载一景 GeoTIFF（而非 GEE 端合成）
    - 在本地用 sca_runner 做 LST 反演（更可控）
    - 用 PIL 合成 GIF（不依赖 geemap 的视频功能）

    Args:
        roi: ee.Geometry 或 GeoJSON Feature（研究区）
        output_dir: 输出目录
        start_year: 起始年份
        end_year: 结束年份（含）
        month: 月份（1-12）
        cloud_pct: 最大云量百分比
        title: GIF 标题
        fps: 帧率
        dpi: 输出图片 DPI
        vmin: 色标最小值（°C），None 则自动
        vmax: 色标最大值（°C），None 则自动
    """
    from gis.gee_tools import gee_download_landsat_sca, _normalize_region
    from gis.sca_runner import run_sca
    from PIL import Image
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import rasterio

    try:
        init_gee()
    except Exception:
        pass

    month = parse_month(month)
    os.makedirs(output_dir, exist_ok=True)

    # 将 roi 转为 ee.Geometry
    try:
        ee_geom = _normalize_region(region=roi)
    except Exception as e:
        return {"success": False, "message": f"研究区转换失败: {e}"}

    if not title:
        title = f"{month}月地表温度变化 {start_year}-{end_year}"

    lst_pngs = []
    lst_tifs = []
    years_ok = []
    years_fail = []

    for year in range(start_year, end_year + 1):
        year_dir = os.path.join(output_dir, f"year_{year}")
        os.makedirs(year_dir, exist_ok=True)

        start_date = f"{year}-{month:02d}-01"
        import calendar
        end_day = calendar.monthrange(year, month)[1]
        end_date = f"{year}-{month:02d}-{end_day}"

        sca_tif = os.path.join(year_dir, f"gee_sca_{year}_{month:02d}.tif")
        lst_tif = os.path.join(year_dir, f"lst_{year}_{month:02d}.tif")
        lst_png = os.path.join(year_dir, f"lst_{year}_{month:02d}.png")

        # ── 步骤 1：从 GEE 下载（已有则跳过）──
        if os.path.exists(sca_tif) and os.path.getsize(sca_tif) > 1024:
            print(f"[Timelapse] {year}年{month}月：本地已有数据，跳过下载")
        else:
            print(f"[Timelapse] {year}年{month}月：从 GEE 下载（云量阈值 {cloud_pct}%）...")
            dl_result = gee_download_landsat_sca(
                start_date=start_date,
                end_date=end_date,
                output_tif=sca_tif,
                region=ee_geom,
                cloud_pct=cloud_pct,
                mask_clouds=True,
            )
            if not dl_result.get("success"):
                print(f"[Timelapse] {year}年 下载失败: {dl_result.get('message', '')}")
                years_fail.append(year)
                continue

            if not os.path.exists(sca_tif) or os.path.getsize(sca_tif) < 1024:
                print(f"[Timelapse] {year}年 下载文件无效")
                years_fail.append(year)
                continue

        # ── 步骤 2：本地 LST 反演（已有则跳过）──
        if os.path.exists(lst_tif) and os.path.getsize(lst_tif) > 1024 and os.path.exists(lst_png):
            print(f"[Timelapse] {year}年{month}月：本地已有反演结果，跳过")
        else:
            print(f"[Timelapse] {year}年{month}月：本地 LST 反演...")
            lst_result = run_sca(
                input_tif=sca_tif,
                output_tif=lst_tif,
                output_png=lst_png,
            )
            if not lst_result.get("success"):
                print(f"[Timelapse] {year}年 反演失败: {lst_result.get('message', '')}")
                years_fail.append(year)
                continue

        if os.path.exists(lst_png):
            lst_pngs.append(lst_png)
            lst_tifs.append(lst_tif)
            years_ok.append(year)
            print(f"[Timelapse] {year}年 ✓")
        else:
            print(f"[Timelapse] {year}年 反演图片未生成")
            years_fail.append(year)

    if not lst_pngs:
        return {
            "success": False,
            "message": (
                f"所有年份均失败。{start_year}-{end_year}年{month}月期间无法获取有效数据。"
                f"请尝试：提高 cloud_pct（当前{cloud_pct}%）、换月份、或检查研究区。"
            ),
            "years_failed": years_fail,
        }

    # ── 步骤 3：统一色标 ──
    if vmin is None or vmax is None:
        all_vals = []
        for tif in lst_tifs:
            try:
                with rasterio.open(tif) as src:
                    data = src.read(1).astype("float32")
                    nodata = src.nodata
                    if nodata is not None:
                        data = np.where(data == nodata, np.nan, data)
                    valid = data[np.isfinite(data)]
                    if valid.size > 0:
                        all_vals.extend(valid.tolist())
            except Exception:
                pass
        if all_vals:
            if vmin is None:
                vmin = float(np.percentile(all_vals, 2))
            if vmax is None:
                vmax = float(np.percentile(all_vals, 98))
        else:
            vmin = vmin or 20
            vmax = vmax or 45

    # ── 步骤 4：重新渲染统一色标的 PNG ──
    rendered_pngs = []
    for i, (tif, year) in enumerate(zip(lst_tifs, years_ok)):
        try:
            with rasterio.open(tif) as src:
                data = src.read(1).astype("float32")
                nodata = src.nodata
                if nodata is not None:
                    data = np.where(data == nodata, np.nan, data)

            fig, ax = plt.subplots(figsize=(8, 6))
            cmap = plt.get_cmap("coolwarm").copy()
            cmap.set_bad(color="white")
            im = ax.imshow(data, cmap=cmap, vmin=vmin, vmax=vmax)
            ax.set_title(f"{year}年{month}月 LST", fontsize=14, fontweight="bold")
            ax.axis("off")
            cbar = fig.colorbar(im, ax=ax, shrink=0.8, label="LST (°C)")

            png_path = os.path.join(output_dir, f"lst_{year}_m{month}_rendered.png")
            fig.savefig(png_path, dpi=dpi, bbox_inches="tight", facecolor="white")
            plt.close(fig)
            rendered_pngs.append(png_path)
        except Exception as e:
            print(f"[Timelapse] {year}年 渲染失败: {e}")

    if not rendered_pngs:
        return {"success": False, "message": "渲染阶段失败，无可用图片"}

    # ── 步骤 5：合成 GIF ──
    gif_path = os.path.join(output_dir, f"lst_timelapse_{start_year}_{end_year}_m{month}.gif")
    try:
        frames = []
        for png in rendered_pngs:
            img = Image.open(png).convert("RGB")
            frames.append(img)

        if frames:
            frames[0].save(
                gif_path,
                save_all=True,
                append_images=frames[1:],
                duration=int(1000 / fps),
                loop=0,
            )
    except Exception as e:
        return {"success": False, "message": f"GIF 合成失败: {e}"}

    if not os.path.exists(gif_path):
        return {"success": False, "message": "GIF 文件未生成"}

    gif_size_mb = os.path.getsize(gif_path) / (1024 * 1024)

    return {
        "success": True,
        "message": (
            f"LST 时间序列 GIF 已生成：{len(years_ok)} 年成功"
            + (f"，{len(years_fail)} 年跳过" if years_fail else "")
        ),
        "gif_path": gif_path,
        "output_dir": output_dir,
        "years_ok": years_ok,
        "years_failed": years_fail,
        "vmin": vmin,
        "vmax": vmax,
        "month": month,
        "gif_size_mb": round(gif_size_mb, 2),
        "lst_tifs": lst_tifs,
    }