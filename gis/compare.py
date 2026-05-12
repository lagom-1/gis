"""
gis/compare.py - 对比视图模块
原图与结果图并排对比、差异图
"""

import os
import numpy as np
import rasterio
import matplotlib.pyplot as plt


def compare_views(
    tif_original: str,
    tif_result: str,
    output_png: str = None,
    mode: str = "side_by_side",
    title_original: str = "Original",
    title_result: str = "Result",
    colormap: str = "jet",
    dpi: int = 200,
) -> dict:
    """
    对比视图

    Args:
        mode: "side_by_side" / "difference"
    """
    try:
        if not os.path.exists(tif_original):
            return {"success": False, "message": f"原图不存在: {tif_original}"}
        if not os.path.exists(tif_result):
            return {"success": False, "message": f"结果图不存在: {tif_result}"}

        with rasterio.open(tif_original) as src:
            data_orig = src.read(1).astype("float32")
        with rasterio.open(tif_result) as src:
            data_result = src.read(1).astype("float32")

        if mode == "difference":
            # 差异图
            diff = data_result - data_orig

            fig, axes = plt.subplots(1, 3, figsize=(18, 6))

            vmin_o = float(np.nanpercentile(data_orig, 2))
            vmax_o = float(np.nanpercentile(data_orig, 98))
            vmin_r = float(np.nanpercentile(data_result, 2))
            vmax_r = float(np.nanpercentile(data_result, 98))

            axes[0].imshow(data_orig, cmap=colormap, vmin=vmin_o, vmax=vmax_o)
            axes[0].set_title(title_original, fontsize=13, fontweight='bold')
            axes[0].axis('off')

            axes[1].imshow(data_result, cmap=colormap, vmin=vmin_r, vmax=vmax_r)
            axes[1].set_title(title_result, fontsize=13, fontweight='bold')
            axes[1].axis('off')

            vmax_diff = float(np.nanpercentile(np.abs(diff), 98))
            im = axes[2].imshow(diff, cmap="coolwarm", vmin=-vmax_diff, vmax=vmax_diff)
            axes[2].set_title("Difference (Result - Original)", fontsize=13, fontweight='bold')
            axes[2].axis('off')
            fig.colorbar(im, ax=axes[2], fraction=0.046, pad=0.04, label='Δ Value')

        else:
            # 左右对比
            fig, axes = plt.subplots(1, 2, figsize=(14, 6))

            cmap = plt.get_cmap(colormap).copy()
            cmap.set_bad(color='white')

            vmin = min(
                float(np.nanpercentile(data_orig, 2)),
                float(np.nanpercentile(data_result, 2)),
            )
            vmax = max(
                float(np.nanpercentile(data_orig, 98)),
                float(np.nanpercentile(data_result, 98)),
            )

            axes[0].imshow(data_orig, cmap=cmap, vmin=vmin, vmax=vmax)
            axes[0].set_title(title_original, fontsize=14, fontweight='bold')
            axes[0].axis('off')

            axes[1].imshow(data_result, cmap=cmap, vmin=vmin, vmax=vmax)
            axes[1].set_title(title_result, fontsize=14, fontweight='bold')
            axes[1].axis('off')

        plt.suptitle("Comparison", fontsize=16, fontweight='bold', y=1.02)
        plt.tight_layout()

        if output_png is None:
            output_png = os.path.join(os.path.dirname(tif_result), "compare.png")

        fig.savefig(output_png, dpi=dpi, bbox_inches='tight', facecolor='white')
        plt.close(fig)

        return {
            "success": True,
            "message": f"对比视图完成（{mode}）",
            "output_png": output_png,
            "mode": mode,
        }

    except Exception as e:
        return {"success": False, "message": str(e)}