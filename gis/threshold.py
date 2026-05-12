"""
阈值高亮模块 - 高亮/标记超过阈值或位于区间的像素
"""

import os
import numpy as np
import rasterio
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors


def threshold_highlight(
    tif_path: str,
    output_path: str = None,
    operator: str = ">",
    value: float = 30.0,
    value_upper: float = None,
    highlight_color: str = "red",
    base_colormap: str = "gray",
    title: str = None,
    dpi: int = 300,
) -> dict:
    """
    阈值高亮

    Args:
        operator: ">" / "<" / "between" / "outside"
        value: 阈值（或 between/outside 的下界）
        value_upper: between/outside 的上界
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

        # 生成掩码
        if operator == ">":
            mask = data > value
            desc = f"值 > {value}"
        elif operator == "<":
            mask = data < value
            desc = f"值 < {value}"
        elif operator == "between":
            if value_upper is None:
                return {"success": False, "message": "between 模式需要 value_upper"}
            mask = (data >= value) & (data <= value_upper)
            desc = f"{value} ≤ 值 ≤ {value_upper}"
        elif operator == "outside":
            if value_upper is None:
                return {"success": False, "message": "outside 模式需要 value_upper"}
            mask = (data < value) | (data > value_upper)
            desc = f"值 < {value} 或 值 > {value_upper}"
        else:
            return {"success": False, "message": f"不支持的操作符: {operator}"}

        # 生成彩色叠加图
        vmin = float(np.nanpercentile(data, 2))
        vmax = float(np.nanpercentile(data, 98))

        # 创建自定义 colormap：底图 + 高亮色
        base_cmap = plt.get_cmap(base_colormap).copy()
        base_cmap.set_bad(color="white")

        fig, ax = plt.subplots(figsize=(10, 8))
        ax.imshow(data, cmap=base_cmap, vmin=vmin, vmax=vmax)

        # 高亮覆盖
        overlay = np.zeros((*data.shape, 4))
        color_map = {"red": (1, 0, 0, 0.6), "blue": (0, 0, 1, 0.6),
                     "green": (0, 1, 0, 0.6), "yellow": (1, 1, 0, 0.6),
                     "orange": (1, 0.5, 0, 0.6), "purple": (0.5, 0, 1, 0.6)}
        rgba = color_map.get(highlight_color.lower(), (1, 0, 0, 0.6))
        overlay[mask] = rgba
        overlay[~np.isfinite(data)] = [0, 0, 0, 0]
        ax.imshow(overlay)

        count = int(np.sum(mask))
        pct = count / valid.size * 100
        if title is None:
            title = f"Threshold Highlight ({desc})"
        ax.set_title(f"{title}\n命中 {count:,} 像元 ({pct:.1f}%)", fontsize=14, fontweight="bold")
        ax.axis("off")

        plt.tight_layout()
        if output_path is None:
            output_path = os.path.splitext(tif_path)[0] + "_threshold.png"

        fig.savefig(output_path, dpi=dpi, bbox_inches="tight", facecolor="white")
        plt.close(fig)

        return {
            "success": True,
            "message": f"阈值高亮完成：{desc}，命中 {count} 像元",
            "output_png": output_path,
            "operator": operator,
            "value": value,
            "value_upper": value_upper,
            "highlight_count": count,
            "highlight_pct": round(pct, 2),
        }
    except Exception as e:
        return {"success": False, "message": str(e)}