"""
gis/enhance.py - 图像增强与滤波模块
平滑、去噪、锐化、直方图均衡化
"""

import os
import numpy as np
import rasterio
import matplotlib.pyplot as plt
from scipy.ndimage import gaussian_filter, median_filter, uniform_filter
from skimage import exposure


def enhance_raster(
    tif_path: str,
    output_tif: str = None,
    output_png: str = None,
    method: str = "gaussian",
    kernel_size: int = 5,
) -> dict:
    """
    栅格图像增强

    Args:
        method: "gaussian" / "median" / "histogram_eq" / "clahe" / "sharpen" / "unsharp"
        kernel_size: 滤波核大小
    """
    try:
        if not os.path.exists(tif_path):
            return {"success": False, "message": f"文件不存在: {tif_path}"}

        with rasterio.open(tif_path) as src:
            data = src.read(1).astype("float32")
            profile = src.profile.copy()

        # 归一化到 0-1 用于处理
        valid = data[~np.isnan(data)]
        d_min, d_max = valid.min(), valid.max()
        normalized = (data - d_min) / (d_max - d_min + 1e-8)

        # 应用滤波
        if method == "gaussian":
            sigma = kernel_size / 2
            result_norm = gaussian_filter(normalized, sigma=sigma)
            desc = f"高斯平滑 (σ={sigma:.1f})"

        elif method == "median":
            result_norm = median_filter(normalized, size=kernel_size)
            desc = f"中值滤波 (核={kernel_size})"

        elif method == "histogram_eq":
            # 掩盖 NaN 做均衡化
            mask = ~np.isnan(normalized)
            temp = normalized.copy()
            temp[~mask] = 0
            result_norm = exposure.equalize_hist(temp, mask=mask)
            result_norm[~mask] = np.nan
            desc = "直方图均衡化"

        elif method == "clahe":
            mask = ~np.isnan(normalized)
            temp = normalized.copy()
            temp[~mask] = 0
            result_norm = exposure.equalize_adapthist(temp, clip_limit=0.03)
            result_norm[~mask] = np.nan
            desc = "CLAHE 自适应均衡化"

        elif method == "sharpen" or method == "unsharp":
            sigma = kernel_size / 2
            blurred = gaussian_filter(normalized, sigma=sigma)
            result_norm = normalized + 1.5 * (normalized - blurred)
            result_norm = np.clip(result_norm, 0, 1)
            desc = f"锐化 (σ={sigma:.1f}, 强度=1.5)"

        else:
            return {"success": False, "message": f"不支持的方法: {method}"}

        # 反归一化
        result = result_norm * (d_max - d_min) + d_min
        result[np.isnan(data)] = np.nan

        # 输出 TIF
        if output_tif is None:
            base = os.path.splitext(tif_path)[0]
            output_tif = f"{base}_enhanced.tif"

        if os.path.exists(output_tif):
            os.remove(output_tif)

        with rasterio.open(output_tif, "w", **profile) as dst:
            dst.write(result.astype("float32"), 1)

        # 对比图
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))

        cmap = "jet"
        vmin = float(np.nanpercentile(data, 2))
        vmax = float(np.nanpercentile(data, 98))

        axes[0].imshow(data, cmap=cmap, vmin=vmin, vmax=vmax)
        axes[0].set_title("Original", fontsize=14, fontweight='bold')
        axes[0].axis('off')

        axes[1].imshow(result, cmap=cmap, vmin=vmin, vmax=vmax)
        axes[1].set_title(desc, fontsize=14, fontweight='bold')
        axes[1].axis('off')

        plt.suptitle("Image Enhancement", fontsize=16, fontweight='bold', y=1.02)
        plt.tight_layout()

        if output_png is None:
            output_png = os.path.join(os.path.dirname(tif_path), "enhanced_compare.png")

        fig.savefig(output_png, dpi=200, bbox_inches='tight', facecolor='white')
        plt.close(fig)

        return {
            "success": True,
            "message": f"图像增强完成：{desc}",
            "method": method,
            "output_tif": output_tif,
            "output_png": output_png,
        }

    except Exception as e:
        return {"success": False, "message": str(e)}