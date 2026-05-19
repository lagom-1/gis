"""
Dynamic World 土地覆盖模块 - 10m 分辨率全球土地覆盖分类
基于 geemap notebook 114: dynamic_world

使用 Google Dynamic World V1 数据集，支持：
- 10m 分辨率土地覆盖分类（9 类）
- hillshade 可视化模式和原始 class 模式
- 输出 TIF + 专题图 PNG

Dynamic World 分类体系：
0: Water（水体）
1: Trees（树木）
2: Grass（草地）
3: Flooded Vegetation（淹没植被）
4: Crops（农作物）
5: Shrub and Scrub（灌木）
6: Built（建筑）
7: Bare（裸地）
8: Snow and Ice（冰雪）
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import ee

from gis.gee.client import init_gee

# Dynamic World 分类标签和颜色
DW_CLASSES = {
    0: {"name": "Water", "name_zh": "水体", "color": "#419BDF"},
    1: {"name": "Trees", "name_zh": "树木", "color": "#397D49"},
    2: {"name": "Grass", "name_zh": "草地", "color": "#88B053"},
    3: {"name": "Flooded Vegetation", "name_zh": "淹没植被", "color": "#7A87C6"},
    4: {"name": "Crops", "name_zh": "农作物", "color": "#E49635"},
    5: {"name": "Shrub and Scrub", "name_zh": "灌木", "color": "#DFC35A"},
    6: {"name": "Built", "name_zh": "建筑", "color": "#C4281B"},
    7: {"name": "Bare", "name_zh": "裸地", "color": "#A59B8F"},
    8: {"name": "Snow and Ice", "name_zh": "冰雪", "color": "#B39FE1"},
}

DW_LABELS = [v["name"] for v in DW_CLASSES.values()]
DW_COLORS = [v["color"] for v in DW_CLASSES.values()]
DW_LABELS_ZH = [v["name_zh"] for v in DW_CLASSES.values()]


def dynamic_world_landcover(
    region: Any,
    start_date: str,
    end_date: str,
    output_tif: Optional[str] = None,
    output_png: Optional[str] = None,
    return_type: str = "class",
    scale: int = 10,
    include_s2: bool = False,
    title: str = "",
) -> Dict[str, Any]:
    """
    获取 Dynamic World 10m 分辨率土地覆盖分类结果。

    使用 Google Dynamic World V1 数据集，该数据集由 Sentinel-2 影像
    通过深度学习模型生成，提供 9 类土地覆盖分类。

    Args:
        region: 研究区（ee.Geometry 或 GeoJSON dict/bbox）
        start_date: 起始日期 "YYYY-MM-DD"
        end_date: 结束日期 "YYYY-MM-DD"
        output_tif: TIF 输出路径，None 则自动生成
        output_png: PNG 专题图输出路径，None 则自动生成
        return_type: 返回类型 "class"（原始分类值）或 "hillshade"（带阴影可视化）
        scale: 导出分辨率（米），默认 10
        include_s2: 是否同时导出 Sentinel-2 RGB 合成
        title: 专题图标题

    Returns:
        {"success": bool, "message": str, "output_tif": str, "output_png": str, ...}
    """
    try:
        init_result = init_gee()
        if not init_result.get("success"):
            return {"success": False, "message": f"GEE 初始化失败: {init_result.get('message', '')}",
                    "requires": "gee_init"}

        import geemap

        # ── 解析 region ──
        if isinstance(region, dict):
            from gis.gee_tools import _normalize_region
            ee_geom = _normalize_region(region=region)
        elif hasattr(region, "getInfo"):
            ee_geom = region
        else:
            return {"success": False, "message": f"无法识别的 region 类型: {type(region).__name__}"}

        print(f"[Dynamic World] 获取 {start_date} ~ {end_date} 土地覆盖...")

        # ── 获取 Dynamic World 分类 ──
        dw = geemap.dynamic_world(ee_geom, start_date, end_date, return_type=return_type)

        if dw is None:
            return {"success": False, "message": "Dynamic World 未返回有效数据，请检查日期范围和研究区。"}

        # ── 导出 TIF ──
        if output_tif is None:
            output_tif = "dynamic_world_landcover.tif"

        os.makedirs(os.path.dirname(output_tif) or ".", exist_ok=True)

        print(f"[Dynamic World] 导出 TIF (scale={scale}m)...")
        try:
            geemap.ee_export_image(
                dw,
                filename=output_tif,
                scale=scale,
                region=ee_geom,
                file_per_band=False,
            )
        except Exception as e:
            # 回退到直接下载
            print(f"[Dynamic World] geemap 导出失败，尝试直接下载: {e}")
            url = dw.getDownloadURL({
                "scale": scale,
                "region": ee_geom,
                "format": "GeoTIFF",
                "crs": "EPSG:4326",
                "formatOptions": {"noData": -9999},
            })
            import urllib.request
            urllib.request.urlretrieve(url, output_tif)

        # ── 生成专题图 ──
        png_path = None
        if output_png:
            png_path = output_png
        elif output_tif:
            png_path = output_tif.replace(".tif", "_map.png")

        if png_path:
            try:
                import matplotlib
                matplotlib.use("Agg")
                import matplotlib.pyplot as plt
                import matplotlib.patches as mpatches
                import numpy as np

                # 尝试用 rasterio 读取 TIF
                try:
                    import rasterio
                    with rasterio.open(output_tif) as src:
                        data = src.read(1).astype("float32")
                        nodata = src.nodata
                        if nodata is not None:
                            data = np.where(data == nodata, np.nan, data)
                except Exception:
                    # 如果 TIF 无法读取，用 geemap 缩略图
                    print("[Dynamic World] 无法读取 TIF 生成专题图，跳过")
                    png_path = None

                if png_path is not None:
                    fig, ax = plt.subplots(figsize=(10, 10))

                    # 创建分类色彩映射
                    from matplotlib.colors import ListedColormap
                    cmap = ListedColormap(DW_COLORS)

                    valid = data[~np.isnan(data)]
                    if valid.size > 0:
                        im = ax.imshow(data, cmap=cmap, vmin=-0.5, vmax=8.5, interpolation="nearest")
                    else:
                        ax.text(0.5, 0.5, "无有效数据", transform=ax.transAxes,
                                ha="center", va="center", fontsize=16)
                        im = None

                    ax.set_title(title or "Dynamic World 土地覆盖", fontsize=14, fontweight="bold")
                    ax.axis("off")

                    # 添加图例
                    patches = []
                    for cls_id, cls_info in DW_CLASSES.items():
                        patch = mpatches.Patch(
                            color=cls_info["color"],
                            label=f"{cls_id}: {cls_info['name_zh']}"
                        )
                        patches.append(patch)
                    ax.legend(handles=patches, loc="lower right", fontsize=8,
                             title="土地覆盖类型", title_fontsize=9, framealpha=0.9)

                    plt.tight_layout()
                    os.makedirs(os.path.dirname(png_path) or ".", exist_ok=True)
                    fig.savefig(png_path, dpi=200, bbox_inches="tight", facecolor="white")
                    plt.close(fig)
                    print(f"[Dynamic World] 专题图已保存: {png_path}")

            except Exception as e:
                print(f"[Dynamic World] 专题图生成失败: {e}")
                png_path = None

        # ── 统计分类面积 ──
        stats_msg = ""
        try:
            if return_type == "class":
                pixel_count = dw.reduceRegion(
                    reducer=ee.Reducer.frequencyHistogram(),
                    geometry=ee_geom,
                    scale=scale,
                    maxPixels=1e9,
                ).getInfo()

                if pixel_count:
                    label_prop = list(pixel_count.keys())[0]
                    counts = pixel_count.get(label_prop, {})
                    if counts:
                        total = sum(counts.values())
                        stats_lines = []
                        for cls_id_str, count in sorted(counts.items(), key=lambda x: int(x[0])):
                            cls_id = int(cls_id_str)
                            if cls_id in DW_CLASSES:
                                pct = count / total * 100
                                stats_lines.append(
                                    f"  {DW_CLASSES[cls_id]['name_zh']}: {pct:.1f}%"
                                )
                        stats_msg = "\n".join(stats_lines)
                        print(f"[Dynamic World] 分类统计:\n{stats_msg}")
        except Exception:
            pass

        return {
            "success": True,
            "message": f"Dynamic World 土地覆盖已获取（{return_type} 模式）",
            "output_tif": output_tif,
            "output_png": png_path,
            "return_type": return_type,
            "start_date": start_date,
            "end_date": end_date,
            "scale": scale,
            "classification_stats": stats_msg,
            "dw_classes": DW_CLASSES,
        }

    except Exception as e:
        return {"success": False, "message": f"Dynamic World 土地覆盖获取失败: {e}"}
