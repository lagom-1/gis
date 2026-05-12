"""
剖面分析模块 - 沿指定路径提取栅格值并绘制剖面图
"""

import os
import numpy as np
import rasterio
import matplotlib.pyplot as plt


def profile_analysis(
    tif_path: str,
    output_png: str = None,
    start: list = None,
    end: list = None,
    n_points: int = 200,
    title: str = None,
    dpi: int = 200,
) -> dict:
    """
    剖面分析

    Args:
        start: 起点 [col, row]，None 则取左中
        end: 终点 [col, row]，None 则取右中
        n_points: 采样点数
    """
    try:
        if not os.path.exists(tif_path):
            return {"success": False, "message": f"文件不存在: {tif_path}"}

        with rasterio.open(tif_path) as src:
            data = src.read(1).astype("float32")
            nodata = src.nodata

        if nodata is not None:
            data = np.where(data == nodata, np.nan, data)

        rows, cols = data.shape

        # 默认剖面：水平中线
        if start is None:
            start = [0, rows // 2]
        if end is None:
            end = [cols - 1, rows // 2]

        c0, r0 = int(start[0]), int(start[1])
        c1, r1 = int(end[0]), int(end[1])

        # 生成采样坐标
        cols_idx = np.linspace(c0, c1, n_points).astype(int)
        rows_idx = np.linspace(r0, r1, n_points).astype(int)

        # 裁剪到有效范围
        cols_idx = np.clip(cols_idx, 0, cols - 1)
        rows_idx = np.clip(rows_idx, 0, rows - 1)

        values = data[rows_idx, cols_idx]
        distances = np.sqrt((cols_idx - c0) ** 2 + (rows_idx - r0) ** 2)
        distances = distances / max(distances[-1], 1)  # 归一化到 0-1

        # 绘图
        fig, axes = plt.subplots(2, 1, figsize=(10, 8), gridspec_kw={"height_ratios": [1, 1.5]})

        # 上图：原图 + 剖面线
        vmin = float(np.nanpercentile(data, 2))
        vmax = float(np.nanpercentile(data, 98))
        cmap = plt.get_cmap("jet").copy()
        cmap.set_bad(color="white")
        axes[0].imshow(data, cmap=cmap, vmin=vmin, vmax=vmax)
        axes[0].plot([c0, c1], [r0, r1], "r-", linewidth=2, label="Profile")
        axes[0].plot(c0, r0, "go", markersize=8, label="Start")
        axes[0].plot(c1, r1, "rs", markersize=8, label="End")
        axes[0].legend(fontsize=9)
        axes[0].set_title("Raster with Profile Line", fontsize=13, fontweight="bold")
        axes[0].axis("off")

        # 下图：剖面曲线
        axes[1].plot(distances, values, color="#2196F3", linewidth=1.5)
        axes[1].fill_between(distances, values, alpha=0.15, color="#2196F3")
        axes[1].set_xlabel("Relative Distance (0–1)", fontsize=11)
        axes[1].set_ylabel("Pixel Value", fontsize=11)
        if title is None:
            title = "Elevation / Value Profile"
        axes[1].set_title(title, fontsize=13, fontweight="bold")
        axes[1].grid(alpha=0.3)

        plt.tight_layout()
        if output_png is None:
            output_png = os.path.splitext(tif_path)[0] + "_profile.png"

        fig.savefig(output_png, dpi=dpi, bbox_inches="tight", facecolor="white")
        plt.close(fig)

        valid_vals = values[np.isfinite(values)]
        return {
            "success": True,
            "message": "剖面分析完成",
            "output_png": output_png,
            "start": [c0, r0],
            "end": [c1, r1],
            "n_points": n_points,
            "profile_min": float(np.nanmin(valid_vals)) if valid_vals.size else None,
            "profile_max": float(np.nanmax(valid_vals)) if valid_vals.size else None,
            "profile_mean": float(np.nanmean(valid_vals)) if valid_vals.size else None,
        }
    except Exception as e:
        return {"success": False, "message": str(e)}