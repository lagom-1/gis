"""
3D 可视化模块 - 表面、线框、等高线渲染
"""

import os
import numpy as np
import rasterio
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401


def render_3d(
    tif_path: str,
    output_png: str = None,
    elevation: float = 45,
    azimuth: float = 225,
    vertical_exaggeration: float = 1.0,
    colormap: str = "terrain",
    render_mode: str = "surface",
    title: str = None,
    dpi: int = 200,
    downsample: int = 4,
) -> dict:
    """
    3D 渲染

    Args:
        render_mode: "surface" / "wireframe" / "contour"
        downsample: 降采样因子（避免大图3D太慢）
    """
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

        # 降采样
        if downsample > 1:
            data = data[::downsample, ::downsample]

        rows, cols = data.shape
        x = np.arange(cols)
        y = np.arange(rows)
        X, Y = np.meshgrid(x, y)
        Z = data.copy()

        # 归一化 Z 用于 vertical_exaggeration
        z_min, z_max = float(np.nanmin(Z)), float(np.nanmax(Z))
        if z_max > z_min:
            Z_norm = (Z - z_min) / (z_max - z_min) * vertical_exaggeration
        else:
            Z_norm = Z

        fig = plt.figure(figsize=(12, 9))
        ax = fig.add_subplot(111, projection="3d")

        cmap = plt.get_cmap(colormap).copy()

        if render_mode == "wireframe":
            ax.plot_wireframe(X, Y, Z_norm, cmap=cmap, linewidth=0.5, alpha=0.8)
            mode_desc = "线框"
        elif render_mode == "contour":
            ax.contour3D(X, Y, Z_norm, 50, cmap=cmap, alpha=0.8)
            mode_desc = "等高线"
        else:
            surf = ax.plot_surface(X, Y, Z_norm, cmap=cmap, alpha=0.9,
                                   linewidth=0, antialiased=True)
            fig.colorbar(surf, ax=ax, shrink=0.5, aspect=10, label="Value")
            mode_desc = "表面"

        ax.view_init(elev=elevation, azim=azimuth)
        ax.set_xlabel("X (px)", fontsize=10)
        ax.set_ylabel("Y (px)", fontsize=10)
        ax.set_zlabel("Z", fontsize=10)

        if title is None:
            title = f"3D Visualization ({mode_desc})"
        ax.set_title(title, fontsize=14, fontweight="bold", pad=20)

        plt.tight_layout()
        if output_png is None:
            output_png = os.path.splitext(tif_path)[0] + "_3d.png"

        fig.savefig(output_png, dpi=dpi, bbox_inches="tight", facecolor="white")
        plt.close(fig)

        return {
            "success": True,
            "message": f"3D 可视化完成（{mode_desc}）",
            "output_png": output_png,
            "render_mode": render_mode,
            "elevation": elevation,
            "azimuth": azimuth,
        }
    except Exception as e:
        return {"success": False, "message": str(e)}