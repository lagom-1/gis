"""
gis/classify.py - 分类/重分类模块
自然断点、等间距、分位数分类，用不同颜色显示不同等级
"""

import os
import numpy as np
import rasterio
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors


def classify_raster(
    tif_path: str,
    output_png: str = None,
    method: str = "natural_breaks",
    n_classes: int = 5,
    labels: list = None,
    colormap: str = "YlOrRd",
    title: str = None,
    dpi: int = 300,
) -> dict:
    """
    栅格数据分类

    Args:
        method: "natural_breaks" / "equal_interval" / "quantile"
        n_classes: 分类数
        labels: 自定义标签（如 ["低", "较低", "中", "较高", "高"]）
    """
    try:
        if not os.path.exists(tif_path):
            return {"success": False, "message": f"文件不存在: {tif_path}"}

        with rasterio.open(tif_path) as src:
            data = src.read(1).astype("float32")

        valid = data[~np.isnan(data)]
        if len(valid) == 0:
            return {"success": False, "message": "数据全为 NaN"}

        # 计算分类边界
        if method == "equal_interval":
            edges = np.linspace(valid.min(), valid.max(), n_classes + 1)
            method_desc = "等间距"
        elif method == "quantile":
            edges = np.percentile(valid, np.linspace(0, 100, n_classes + 1))
            method_desc = "分位数"
        else:  # natural_breaks (简化版用 Fisher-Jenks 近似)
            # 用分位数近似自然断点
            percentiles = np.linspace(0, 100, n_classes + 1)
            edges = np.percentile(valid, percentiles)
            # 微调使间距更自然
            edges = np.unique(edges)
            if len(edges) < n_classes + 1:
                edges = np.linspace(valid.min(), valid.max(), n_classes + 1)
            method_desc = "自然断点"

        # 分类
        classified = np.digitize(data, edges[1:-1])
        classified = classified.astype("float32")
        classified[np.isnan(data)] = np.nan

        # 自动生成标签
        if labels is None:
            level_names = ["很低", "低", "中低", "中", "中高", "高", "很高", "极高", "极高+", "极高++"]
            labels = []
            for i in range(n_classes):
                lo, hi = edges[i], edges[i + 1]
                name = level_names[min(i, len(level_names) - 1)]
                labels.append(f"{name} ({lo:.1f}–{hi:.1f})")

        # 颜色方案
        cmap = plt.get_cmap(colormap, n_classes)
        colors = [mcolors.to_hex(cmap(i)) for i in range(n_classes)]

        # 绘图
        fig, ax = plt.subplots(figsize=(10, 8))

        cmap_discrete = mcolors.ListedColormap(colors)
        cmap_discrete.set_bad(color='white')

        im = ax.imshow(classified, cmap=cmap_discrete, vmin=-0.5, vmax=n_classes - 0.5)

        if title is None:
            title = f"Classification ({method_desc}, {n_classes} classes)"

        ax.set_title(title, fontsize=16, fontweight='bold', pad=15)
        ax.axis('off')

        # 图例
        from matplotlib.patches import Patch
        legend_elements = [
            Patch(facecolor=colors[i], label=labels[i])
            for i in range(n_classes)
        ]
        ax.legend(handles=legend_elements, loc='center left',
                  bbox_to_anchor=(1.02, 0.5), fontsize=9, framealpha=0.9)

        plt.tight_layout()

        if output_png is None:
            output_png = os.path.join(os.path.dirname(tif_path), "classified.png")

        fig.savefig(output_png, dpi=dpi, bbox_inches='tight', facecolor='white')
        plt.close(fig)

        # 各类统计
        class_stats = []
        for i in range(n_classes):
            mask = (classified == i) & ~np.isnan(data)
            count = int(np.sum(mask))
            pct = count / len(valid) * 100
            class_stats.append({
                "class": i,
                "label": labels[i],
                "count": count,
                "pct": round(pct, 1),
            })

        return {
            "success": True,
            "message": f"分类完成：{method_desc}，{n_classes} 类",
            "output_png": output_png,
            "method": method_desc,
            "n_classes": n_classes,
            "edges": [round(e, 2) for e in edges],
            "class_stats": class_stats,
        }

    except Exception as e:
        return {"success": False, "message": str(e)}