"""
GEE 端分类模块 - 在 Google Earth Engine 上执行无监督/监督土地覆盖分类
基于 geemap notebooks 31 和 32

支持：
- 无监督分类：K-Means 聚类
- 监督分类：CART、RandomForest、NaiveBayes、SVM
- 分类结果导出 TIF + 专题图 PNG
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import ee

from gis.gee.client import init_gee


def ee_unsupervised_classify(
    region: Any,
    image_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    band_names: Optional[List[str]] = None,
    n_clusters: int = 5,
    scale: int = 30,
    num_pixels: int = 5000,
    output_tif: Optional[str] = None,
    output_png: Optional[str] = None,
    class_names: Optional[List[str]] = None,
    class_colors: Optional[List[str]] = None,
    title: str = "",
    seed: int = 0,
) -> Dict[str, Any]:
    """
    在 GEE 端执行无监督分类（K-Means 聚类）。

    流程：
    1) 加载影像（指定 image_id 或使用已下载的 Landsat）
    2) 采样训练数据
    3) 训练 K-Means 聚类器
    4) 对影像执行分类
    5) 导出结果 TIF + 专题图

    Args:
        region: 研究区（ee.Geometry 或 GeoJSON）
        image_id: GEE 影像 ID，如 "LANDSAT/LC08/C02/T1_L2/..."
                 为 None 时自动选择研究区内 Landsat 8 最少云量影像
        start_date/end_date: 日期范围（当 image_id 为 None 时使用）
        band_names: 用于分类的波段名，默认 Landsat B1-B7
        n_clusters: 聚类数量
        scale: 分析分辨率
        num_pixels: 训练采样像素数
        output_tif/output_png: 输出路径
        class_names: 分类标签名列表（长度需等于 n_clusters）
        class_colors: 分类颜色列表
        title: 专题图标题
        seed: 随机种子

    Returns:
        {"success": bool, "message": str, "output_tif": str, "output_png": str, ...}
    """
    try:
        init_result = init_gee()
        if not init_result.get("success"):
            return {"success": False, "message": f"GEE 初始化失败: {init_result.get('message', '')}",
                    "requires": "gee_init"}

        # ── 解析 region ──
        if isinstance(region, dict):
            from gis.gee_tools import _normalize_region
            ee_geom = _normalize_region(region=region)
        elif hasattr(region, "getInfo"):
            ee_geom = region
        else:
            return {"success": False, "message": f"无法识别的 region: {type(region).__name__}"}

        # ── 加载影像 ──
        if image_id:
            image = ee.Image(image_id)
            if band_names:
                image = image.select(band_names)
        else:
            if not start_date:
                start_date = "2020-01-01"
            if not end_date:
                end_date = "2020-12-31"

            # 从 Landsat 8 Collection 2 中选择最少云量影像
            default_bands = band_names or ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"]

            collection = (
                ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                .filterBounds(ee_geom)
                .filterDate(start_date, end_date)
                .sort("CLOUD_COVER")
            )

            count = collection.size().getInfo()
            if count == 0:
                return {"success": False, "message": f"在 {start_date}~{end_date} 无可用 Landsat 影像"}

            image = collection.first().select(default_bands)
            band_names = default_bands
            print(f"[EE Classify] 使用最少云量 Landsat 影像（共 {count} 景候选）")

        # ── 采样训练数据 ──
        print(f"[EE Classify] 采样 {num_pixels} 个训练像素...")
        training = image.sample(
            region=ee_geom,
            scale=scale,
            numPixels=num_pixels,
            seed=seed,
            geometries=False,
        )

        # ── 训练 K-Means 聚类器 ──
        print(f"[EE Classify] 训练 K-Means 聚类器 (k={n_clusters})...")
        clusterer = ee.Clusterer.wekaKMeans(n_clusters).train(training)

        # ── 执行分类 ──
        print("[EE Classify] 执行分类...")
        result = image.cluster(clusterer)

        # ── 导出 TIF ──
        if output_tif is None:
            output_tif = "ee_unsupervised_classified.tif"

        os.makedirs(os.path.dirname(output_tif) or ".", exist_ok=True)

        import geemap
        print(f"[EE Classify] 导出 TIF (scale={scale}m)...")
        try:
            geemap.ee_export_image(
                result, filename=output_tif, scale=scale,
                region=ee_geom, file_per_band=False,
            )
        except Exception as e:
            print(f"[EE Classify] geemap 导出失败，尝试直接下载: {e}")
            url = result.getDownloadURL({
                "scale": scale, "region": ee_geom,
                "format": "GeoTIFF", "crs": "EPSG:4326",
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
                from matplotlib.colors import ListedColormap
                import rasterio

                with rasterio.open(output_tif) as src:
                    data = src.read(1).astype("float32")

                # 默认颜色和标签
                default_colors = ["#8DD3C7", "#FFFFB3", "#BEBADA", "#FB8072", "#80B1D3",
                                  "#B3DE69", "#FCCDE5", "#D9D9D9", "#BC80BD", "#CCEBC5"]
                default_names = [f"类别 {i}" for i in range(n_clusters)]

                colors = class_colors or default_colors[:n_clusters]
                names = class_names or default_names

                cmap = ListedColormap(colors)

                fig, ax = plt.subplots(figsize=(10, 10))
                im = ax.imshow(data, cmap=cmap, vmin=-0.5, vmax=n_clusters - 0.5,
                               interpolation="nearest")
                ax.set_title(title or f"无监督分类 (K={n_clusters})", fontsize=14, fontweight="bold")
                ax.axis("off")

                patches = [mpatches.Patch(color=colors[i], label=names[i])
                           for i in range(min(n_clusters, len(colors)))]
                ax.legend(handles=patches, loc="lower right", fontsize=9,
                         title="分类", title_fontsize=10, framealpha=0.9)

                plt.tight_layout()
                os.makedirs(os.path.dirname(png_path) or ".", exist_ok=True)
                fig.savefig(png_path, dpi=200, bbox_inches="tight", facecolor="white")
                plt.close(fig)
                print(f"[EE Classify] 专题图已保存: {png_path}")

            except Exception as e:
                print(f"[EE Classify] 专题图生成失败: {e}")
                png_path = None

        return {
            "success": True,
            "message": f"无监督分类完成（{n_clusters} 类）",
            "output_tif": output_tif,
            "output_png": png_path,
            "n_clusters": n_clusters,
            "scale": scale,
            "method": "K-Means",
        }

    except Exception as e:
        return {"success": False, "message": f"无监督分类失败: {e}"}


def ee_supervised_classify(
    region: Any,
    image_id: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    band_names: Optional[List[str]] = None,
    classifier_type: str = "RandomForest",
    label_image_id: Optional[str] = None,
    label_band: str = "landcover",
    scale: int = 30,
    num_pixels: int = 5000,
    output_tif: Optional[str] = None,
    output_png: Optional[str] = None,
    class_values: Optional[List[int]] = None,
    class_names: Optional[List[str]] = None,
    class_colors: Optional[List[str]] = None,
    title: str = "",
    seed: int = 0,
) -> Dict[str, Any]:
    """
    在 GEE 端执行监督分类。

    支持 CART、RandomForest、NaiveBayes、SVM 等分类器。
    需要提供标签影像（如 NLCD）作为训练数据来源。

    Args:
        region: 研究区
        image_id: 待分类影像 ID（None 时自动选择 Landsat）
        start_date/end_date: 日期范围
        band_names: 分类波段
        classifier_type: 分类器类型 CART/RandomForest/NaiveBayes/SVM
        label_image_id: 标签影像 ID（如 "USGS/NLCD/NLCD2016"）
        label_band: 标签波段名
        scale: 分析分辨率
        num_pixels: 训练采样数
        output_tif/output_png: 输出路径
        class_values: 分类值列表
        class_names: 分类名称列表
        class_colors: 分类颜色列表
        title: 专题图标题
        seed: 随机种子

    Returns:
        {"success": bool, "message": str, "output_tif": str, "output_png": str, ...}
    """
    try:
        init_result = init_gee()
        if not init_result.get("success"):
            return {"success": False, "message": f"GEE 初始化失败: {init_result.get('message', '')}",
                    "requires": "gee_init"}

        # ── 解析 region ──
        if isinstance(region, dict):
            from gis.gee_tools import _normalize_region
            ee_geom = _normalize_region(region=region)
        elif hasattr(region, "getInfo"):
            ee_geom = region
        else:
            return {"success": False, "message": f"无法识别的 region: {type(region).__name__}"}

        # ── 加载待分类影像 ──
        if image_id:
            image = ee.Image(image_id)
        else:
            if not start_date:
                start_date = "2020-01-01"
            if not end_date:
                end_date = "2020-12-31"

            collection = (
                ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                .filterBounds(ee_geom)
                .filterDate(start_date, end_date)
                .sort("CLOUD_COVER")
            )
            count = collection.size().getInfo()
            if count == 0:
                return {"success": False, "message": f"在 {start_date}~{end_date} 无可用影像"}
            image = collection.first()

        # 默认波段
        if band_names is None:
            band_names = ["SR_B1", "SR_B2", "SR_B3", "SR_B4", "SR_B5", "SR_B6", "SR_B7"]
        image = image.select(band_names)

        # ── 加载标签影像 ──
        if label_image_id is None:
            return {"success": False, "message": "监督分类需要提供标签影像 ID（label_image_id），如 'USGS/NLCD/NLCD2016'"}

        label_image = ee.Image(label_image_id).select(label_band)
        label_image = label_image.clip(ee_geom)

        # ── 生成训练数据 ──
        print(f"[EE Supervised] 采样训练数据 ({num_pixels} 像素)...")
        points = label_image.sample(
            region=ee_geom,
            scale=scale,
            numPixels=num_pixels,
            seed=seed,
            geometries=True,
        )

        training = image.sampleRegions(
            collection=points,
            properties=[label_band],
            scale=scale,
        )

        train_count = training.size().getInfo()
        if train_count == 0:
            return {"success": False, "message": "训练数据为空，请检查标签影像和研究区是否重叠"}
        print(f"[EE Supervised] 训练样本数: {train_count}")

        # ── 训练分类器 ──
        classifier_map = {
            "CART": ee.Classifier.smileCart,
            "RANDOMFOREST": ee.Classifier.smileRandomForest,
            "NAIVEBAYES": ee.Classifier.smileNaiveBayes,
            "SVM": ee.Classifier.libsvm,
        }

        classifier_key = classifier_type.upper().replace("_", "").replace(" ", "")
        if classifier_key not in classifier_map:
            return {"success": False, "message": f"不支持的分类器: {classifier_type}，支持: {list(classifier_map.keys())}"}

        print(f"[EE Supervised] 训练 {classifier_type} 分类器...")
        trained = classifier_map[classifier_key]().train(training, label_band, band_names)

        # ── 执行分类 ──
        print("[EE Supervised] 执行分类...")
        result = image.classify(trained)

        # ── 导出 TIF ──
        if output_tif is None:
            output_tif = "ee_supervised_classified.tif"

        os.makedirs(os.path.dirname(output_tif) or ".", exist_ok=True)

        import geemap
        print(f"[EE Supervised] 导出 TIF (scale={scale}m)...")
        try:
            geemap.ee_export_image(
                result, filename=output_tif, scale=scale,
                region=ee_geom, file_per_band=False,
            )
        except Exception as e:
            print(f"[EE Supervised] geemap 导出失败: {e}")
            url = result.getDownloadURL({
                "scale": scale, "region": ee_geom,
                "format": "GeoTIFF", "crs": "EPSG:4326",
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
                from matplotlib.colors import ListedColormap
                import rasterio

                with rasterio.open(output_tif) as src:
                    data = src.read(1).astype("float32")

                if class_values and class_colors:
                    cmap = ListedColormap(class_colors)
                    vmin = min(class_values) - 0.5
                    vmax = max(class_values) + 0.5
                else:
                    unique_vals = np.unique(data[~np.isnan(data)])
                    n_classes = len(unique_vals)
                    default_colors = plt.cm.Set3(np.linspace(0, 1, max(n_classes, 3)))
                    cmap = ListedColormap(default_colors[:n_classes])
                    vmin = unique_vals.min() - 0.5 if n_classes > 0 else -0.5
                    vmax = unique_vals.max() + 0.5 if n_classes > 0 else 0.5

                fig, ax = plt.subplots(figsize=(10, 10))
                ax.imshow(data, cmap=cmap, vmin=vmin, vmax=vmax, interpolation="nearest")
                ax.set_title(title or f"监督分类 ({classifier_type})", fontsize=14, fontweight="bold")
                ax.axis("off")

                if class_values and class_names and class_colors:
                    patches = [mpatches.Patch(color=class_colors[i], label=class_names[i])
                               for i in range(len(class_values))]
                    ax.legend(handles=patches, loc="lower right", fontsize=9,
                             title="分类", title_fontsize=10, framealpha=0.9)

                plt.tight_layout()
                os.makedirs(os.path.dirname(png_path) or ".", exist_ok=True)
                fig.savefig(png_path, dpi=200, bbox_inches="tight", facecolor="white")
                plt.close(fig)
                print(f"[EE Supervised] 专题图已保存: {png_path}")

            except Exception as e:
                print(f"[EE Supervised] 专题图生成失败: {e}")
                png_path = None

        return {
            "success": True,
            "message": f"监督分类完成（{classifier_type}）",
            "output_tif": output_tif,
            "output_png": png_path,
            "classifier_type": classifier_type,
            "scale": scale,
            "train_samples": train_count,
            "label_image_id": label_image_id,
        }

    except Exception as e:
        return {"success": False, "message": f"监督分类失败: {e}"}
