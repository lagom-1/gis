"""
点位时间序列提取模块 - 从 GEE ImageCollection 提取指定经纬度的时间序列
基于 geemap notebook 152: extract_timeseries_to_point

支持任意 ImageCollection（ERA5、MODIS、CHIRPS 等），输出 CSV + 折线图 PNG
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import ee

from gis.gee.client import init_gee


def extract_timeseries_to_point(
    lat: float,
    lon: float,
    image_collection_id: str,
    band_names: List[str],
    start_date: str,
    end_date: str,
    scale: int = 1000,
    output_csv: Optional[str] = None,
    output_png: Optional[str] = None,
    title: str = "",
    reducer: str = "mean",
    point_buffer_m: int = 0,
) -> Dict[str, Any]:
    """
    从 GEE ImageCollection 提取指定经纬度点的时间序列数据。

    流程：
    1) 初始化 GEE
    2) 加载 ImageCollection，按日期和波段过滤
    3) 在指定点位采样，提取每个影像的像素值
    4) 输出 CSV + matplotlib 折线图

    Args:
        lat: 纬度
        lon: 经度
        image_collection_id: GEE ImageCollection ID，如 "ECMWF/ERA5_LAND/DAILY_AGGR"
        band_names: 要提取的波段名列表，如 ["temperature_2m", "total_precipitation_sum"]
        start_date: 起始日期 "YYYY-MM-DD"
        end_date: 结束日期 "YYYY-MM-DD"
        scale: 采样分辨率（米），默认 1000
        output_csv: CSV 输出路径，None 则自动生成
        output_png: PNG 输出路径，None 则自动生成
        title: 图表标题，缺省自动生成
        reducer: 像素聚合方式 mean/first/median，默认 mean
        point_buffer_m: 点位缓冲区半径（米），0 表示单点采样

    Returns:
        {"success": bool, "message": str, "output_csv": str, "output_png": str, ...}
    """
    try:
        # ── 步骤 1：初始化 GEE ──
        init_result = init_gee()
        if not init_result.get("success"):
            return {
                "success": False,
                "message": f"GEE 初始化失败: {init_result.get('message', '未知错误')}。请先执行 gee_init。",
                "requires": "gee_init",
            }

        # ── 步骤 2：创建采样点 ──
        point = ee.Geometry.Point(lon, lat)
        if point_buffer_m > 0:
            region = point.buffer(point_buffer_m)
        else:
            region = point

        # ── 步骤 3：加载并过滤 ImageCollection ──
        collection = (
            ee.ImageCollection(image_collection_id)
            .filterDate(start_date, end_date)
            .filterBounds(region)
            .select(band_names)
        )

        count = collection.size().getInfo()
        if count == 0:
            return {
                "success": False,
                "message": (
                    f"在 {start_date} ~ {end_date} 期间，{image_collection_id} "
                    f"在点位 ({lat}, {lon}) 无可用数据。"
                    f"请检查日期范围、数据集 ID 和波段名称。"
                ),
            }

        print(f"[Timeseries] 找到 {count} 景影像，开始提取时间序列...")

        # ── 步骤 4：逐影像采样 ──
        def _extract_pixel(image):
            """提取单个影像在目标点的像素值"""
            if point_buffer_m > 0:
                reducer_fn = ee.Reducer.mean()
                stat = image.reduceRegion(
                    reducer=reducer_fn,
                    geometry=region,
                    scale=scale,
                    maxPixels=1e9,
                )
            else:
                stat = image.reduceRegion(
                    reducer=ee.Reducer.first() if reducer == "first" else ee.Reducer.mean(),
                    geometry=region,
                    scale=scale,
                    maxPixels=1e9,
                )

            # 获取时间戳
            time_ms = image.get("system:time_start")
            time_date = ee.Date(time_ms)

            # 构建结果 feature
            props = stat.set("system:time_start", time_ms)
            props = props.set("date", time_date.format("YYYY-MM-dd"))
            return ee.Feature(None, props)

        sampled = collection.map(_extract_pixel)

        # ── 步骤 5：获取数据到本地 ──
        features = sampled.getInfo().get("features", [])

        if not features:
            return {
                "success": False,
                "message": "采样结果为空，请检查点位是否在数据覆盖范围内。",
            }

        # ── 步骤 6：解析为表格数据 ──
        import pandas as pd

        rows = []
        for feat in features:
            props = feat.get("properties", {})
            row = {"date": props.get("date", "")}
            for band in band_names:
                row[band] = props.get(band)
            rows.append(row)

        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values("date").reset_index(drop=True)

        # 去除全为 NaN 的行
        df = df.dropna(subset=band_names, how="all")

        if df.empty:
            return {
                "success": False,
                "message": "提取的数据全部为空值，请检查波段名称是否正确。",
            }

        print(f"[Timeseries] 成功提取 {len(df)} 条记录")

        # ── 步骤 7：保存 CSV ──
        if output_csv is None:
            output_csv = str(
                Path(output_png).parent / f"timeseries_{lat}_{lon}.csv"
                if output_png
                else f"timeseries_{lat}_{lon}.csv"
            )
        os.makedirs(os.path.dirname(output_csv) or ".", exist_ok=True)
        df.to_csv(output_csv, index=False, encoding="utf-8-sig")
        print(f"[Timeseries] CSV 已保存: {output_csv}")

        # ── 步骤 8：生成折线图 ──
        if output_png is None:
            output_png = output_csv.replace(".csv", ".png")

        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        if not title:
            title = f"时间序列 ({lat}, {lon})"

        fig, ax = plt.subplots(figsize=(12, 5))
        colors = ["#d73027", "#4575b4", "#1a9850", "#fee090", "#762a83"]

        for i, band in enumerate(band_names):
            valid = df[["date", band]].dropna()
            if not valid.empty:
                color = colors[i % len(colors)]
                ax.plot(valid["date"], valid[band], "-", color=color,
                        linewidth=1.5, label=band)

        ax.set_xlabel("日期", fontsize=12)
        ax.set_ylabel("值", fontsize=12)
        ax.set_title(title, fontsize=14, fontweight="bold")
        if len(band_names) > 1:
            ax.legend(fontsize=10)
        ax.grid(alpha=0.3)
        fig.autofmt_xdate()

        plt.tight_layout()
        os.makedirs(os.path.dirname(output_png) or ".", exist_ok=True)
        fig.savefig(output_png, dpi=200, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        print(f"[Timeseries] 折线图已保存: {output_png}")

        # ── 步骤 9：返回结果 ──
        return {
            "success": True,
            "message": (
                f"时间序列提取完成：{len(df)} 条记录，"
                f"{len(band_names)} 个波段，"
                f"时间范围 {df['date'].min().strftime('%Y-%m-%d')} ~ "
                f"{df['date'].max().strftime('%Y-%m-%d')}"
            ),
            "output_csv": output_csv,
            "output_png": output_png,
            "lat": lat,
            "lon": lon,
            "record_count": len(df),
            "band_names": band_names,
            "start_date": start_date,
            "end_date": end_date,
            "scale": scale,
            "collection_id": image_collection_id,
            "date_range": [
                df["date"].min().strftime("%Y-%m-%d"),
                df["date"].max().strftime("%Y-%m-%d"),
            ],
        }

    except Exception as e:
        return {"success": False, "message": f"时间序列提取失败: {e}"}
