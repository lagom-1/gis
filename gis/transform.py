"""
栅格变换模块 - 翻转、旋转
"""

import os
import numpy as np
import rasterio
import matplotlib.pyplot as plt


def transform_raster(
    tif_path: str,
    output_tif: str = None,
    output_png: str = None,
    operation: str = "flip_h",
) -> dict:
    """
    栅格空间变换

    Args:
        operation: "flip_h" / "flip_v" / "rotate_90" / "rotate_180" / "rotate_270"
    """
    try:
        if not os.path.exists(tif_path):
            return {"success": False, "message": f"文件不存在: {tif_path}"}

        with rasterio.open(tif_path) as src:
            data = src.read(1).astype("float32")
            profile = src.profile.copy()
            nodata = src.nodata

        if operation == "flip_h":
            result = np.fliplr(data)
            desc = "水平翻转"
        elif operation == "flip_v":
            result = np.flipud(data)
            desc = "垂直翻转"
        elif operation == "rotate_90":
            result = np.rot90(data, k=-1)
            desc = "旋转 90°"
        elif operation == "rotate_180":
            result = np.rot90(data, k=2)
            desc = "旋转 180°"
        elif operation == "rotate_270":
            result = np.rot90(data, k=1)
            desc = "旋转 270°"
        else:
            return {"success": False, "message": f"不支持的操作: {operation}"}

        # 输出 TIF
        if output_tif is None:
            base = os.path.splitext(tif_path)[0]
            output_tif = f"{base}_{operation}.tif"

        if result.shape != data.shape:
            profile.update(width=result.shape[1], height=result.shape[0])

        os.makedirs(os.path.dirname(output_tif) or ".", exist_ok=True)
        if os.path.exists(output_tif):
            os.remove(output_tif)
        with rasterio.open(output_tif, "w", **profile) as dst:
            dst.write(result.astype("float32"), 1)

        # 对比图
        vmin = float(np.nanpercentile(data, 2))
        vmax = float(np.nanpercentile(data, 98))
        cmap = plt.get_cmap("jet").copy()
        cmap.set_bad(color="white")

        fig, axes = plt.subplots(1, 2, figsize=(12, 5))
        axes[0].imshow(data, cmap=cmap, vmin=vmin, vmax=vmax)
        axes[0].set_title("Original", fontsize=13, fontweight="bold")
        axes[0].axis("off")
        axes[1].imshow(result, cmap=cmap, vmin=vmin, vmax=vmax)
        axes[1].set_title(desc, fontsize=13, fontweight="bold")
        axes[1].axis("off")
        plt.suptitle("Raster Transform", fontsize=15, fontweight="bold")
        plt.tight_layout()

        if output_png is None:
            output_png = os.path.splitext(output_tif)[0] + ".png"
        fig.savefig(output_png, dpi=200, bbox_inches="tight", facecolor="white")
        plt.close(fig)

        return {
            "success": True,
            "message": f"栅格变换完成：{desc}",
            "output_tif": output_tif,
            "output_png": output_png,
            "operation": operation,
        }
    except Exception as e:
        return {"success": False, "message": str(e)}