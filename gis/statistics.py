"""
统计分析模块 - 单波段栅格统计 + 直方图
"""

import os
import numpy as np
import rasterio
import matplotlib.pyplot as plt
from matplotlib import font_manager as fm


def _pick_font():
    for name in ["Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "WenQuanYi Micro Hei", "PingFang SC", "DejaVu Sans"]:
        available = {f.name for f in fm.fontManager.ttflist}
        if name in available:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return name
    return None

_PICKED_FONT = _pick_font()


def analyze_raster(
    tif_path: str,
    output_png: str = None,
    bins: int = 64,
) -> dict:
    """对单波段栅格做统计分析，输出直方图"""
    try:
        if not os.path.exists(tif_path):
            return {"success": False, "message": f"文件不存在: {tif_path}"}

        with rasterio.open(tif_path) as src:
            data = src.read(1).astype("float32")
            nodata = src.nodata

        if nodata is not None:
            data = np.where(data == nodata, np.nan, data)

        valid = data[np.isfinite(data)]
        if valid.size == 0:
            return {"success": False, "message": "栅格中没有有效像元"}

        stats = {
            "count": int(valid.size),
            "min": float(np.min(valid)),
            "max": float(np.max(valid)),
            "mean": float(np.mean(valid)),
            "std": float(np.std(valid)),
            "median": float(np.median(valid)),
            "p2": float(np.percentile(valid, 2)),
            "p5": float(np.percentile(valid, 5)),
            "p25": float(np.percentile(valid, 25)),
            "p75": float(np.percentile(valid, 75)),
            "p95": float(np.percentile(valid, 95)),
            "p98": float(np.percentile(valid, 98)),
            "nodata_count": int(np.sum(~np.isfinite(data))),
        }

        # 生成直方图
        fig, ax = plt.subplots(figsize=(8, 5))
        ax.hist(valid, bins=bins, color="#4A90D9", edgecolor="white", alpha=0.85)
        ax.axvline(stats["mean"], color="red", linestyle="--", linewidth=1.5, label=f'Mean: {stats["mean"]:.2f}')
        ax.axvline(stats["median"], color="orange", linestyle="--", linewidth=1.5, label=f'Median: {stats["median"]:.2f}')
        ax.set_xlabel("Value", fontsize=12)
        ax.set_ylabel("Pixel Count", fontsize=12)
        ax.set_title("Raster Value Distribution", fontsize=14, fontweight="bold")
        ax.legend(fontsize=10)
        ax.grid(axis="y", alpha=0.3)

        # 添加统计文本
        textstr = f"N = {stats['count']:,}\nStd = {stats['std']:.4f}\nRange: [{stats['min']:.4f}, {stats['max']:.4f}]"
        props = dict(boxstyle="round", facecolor="wheat", alpha=0.8)
        ax.text(0.97, 0.97, textstr, transform=ax.transAxes, fontsize=9,
                verticalalignment="top", horizontalalignment="right", bbox=props)

        plt.tight_layout()

        if output_png is None:
            output_png = os.path.splitext(tif_path)[0] + "_histogram.png"

        fig.savefig(output_png, dpi=200, bbox_inches="tight", facecolor="white")
        plt.close(fig)

        return {
            "success": True,
            "message": "统计分析完成",
            "statistics": stats,
            "histogram_png": output_png,
            "tif_path": tif_path,
        }
    except Exception as e:
        return {"success": False, "message": str(e)}