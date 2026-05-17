"""
交互式 Web 地图模块 - 用 Folium 生成 Leaflet 交互式地图
支持栅格叠加、热力图、分类图层、弹窗信息、图层切换
单文件 HTML，浏览器直接打开，可分享
"""

from __future__ import annotations

import base64
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np


def _raster_to_png_overlay(
    tif_path: str,
    colormap: str = "viridis",
    band: int = 1,
    rescale_factor: int = 4,
) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    将栅格转为 PNG overlay + 边界坐标，用于 Folium ImageOverlay
    resample 降低分辨率以加速渲染
    """
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.enums import Resampling
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.cm as cm

    with rasterio.open(tif_path) as src:
        # 降采样
        if rescale_factor > 1:
            out_shape = (src.count, src.height // rescale_factor, src.width // rescale_factor)
            data = src.read(band, out_shape=out_shape, resampling=Resampling.bilinear).astype("float32")
        else:
            data = src.read(band).astype("float32")

        # 处理 nodata
        nodata = src.nodata
        if nodata is not None:
            data[data == nodata] = np.nan

        bounds = src.bounds
        crs = src.crs

        # 转 WGS84 边界
        if crs and crs.to_epsg() != 4326:
            try:
                wgs_bounds = transform_bounds(crs, "EPSG:4326", *bounds)
            except Exception:
                wgs_bounds = [bounds.left, bounds.bottom, bounds.right, bounds.top]
        else:
            wgs_bounds = [bounds.left, bounds.bottom, bounds.right, bounds.top]

    valid = data[np.isfinite(data)]
    if valid.size == 0:
        return None, {}

    vmin, vmax = np.percentile(valid, 2), np.percentile(valid, 98)
    if vmin == vmax:
        vmin, vmax = valid.min(), valid.max()

    # 归一化
    normed = np.clip((data - vmin) / (vmax - vmin + 1e-10), 0, 1)

    # 应用 colormap
    cmap = cm.get_cmap(colormap)
    rgba = cmap(normed)
    # 透明处理 NaN
    rgba[np.isnan(data)] = [0, 0, 0, 0]

    # 转 uint8
    img_uint8 = (rgba * 255).astype(np.uint8)

    # 保存为 PNG
    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    from PIL import Image
    Image.fromarray(img_uint8, "RGBA").save(tmp.name)
    tmp.close()

    bounds_dict = {
        "south": wgs_bounds[1],
        "west": wgs_bounds[0],
        "north": wgs_bounds[3],
        "east": wgs_bounds[2],
        "vmin": float(vmin),
        "vmax": float(vmax),
        "valid_count": int(valid.size),
        "mean": float(np.mean(valid)),
        "std": float(np.std(valid)),
    }

    return tmp.name, bounds_dict


def _raster_to_heatmap_data(
    tif_path: str,
    max_points: int = 5000,
    band: int = 1,
) -> List[List[float]]:
    """
    提取栅格热点数据用于热力图
    返回 [[lat, lon, value], ...]
    """
    import rasterio
    from rasterio.warp import transform as rio_transform
    from rasterio.enums import Resampling

    with rasterio.open(tif_path) as src:
        # 重度降采样
        factor = max(1, int(np.sqrt(src.width * src.height / max_points)))
        out_shape = (src.height // factor, src.width // factor)
        data = src.read(band, out_shape=out_shape, resampling=Resampling.bilinear).astype("float32")
        nodata = src.nodata
        if nodata is not None:
            data[data == nodata] = np.nan

        transform = src.transform * src.transform.scale(
            (src.width / data.shape[1]),
            (src.height / data.shape[0]),
        )
        crs = src.crs

    valid_mask = np.isfinite(data)
    rows, cols = np.where(valid_mask)
    if len(rows) == 0:
        return []

    # 像元中心 → 地理坐标
    xs, ys = transform * (cols + 0.5, rows + 0.5)
    values = data[valid_mask]

    # 转 WGS84
    if crs and crs.to_epsg() != 4326:
        try:
            lons, lats = rio_transform(crs, "EPSG:4326", xs, ys)
        except Exception:
            lats, lons = ys, xs
    else:
        lats, lons = ys, xs

    # 归一化值用于热力图权重
    vmin, vmax = float(np.percentile(values, 5)), float(np.percentile(values, 95))
    if vmax == vmin:
        normed = np.ones_like(values) * 0.5
    else:
        normed = np.clip((values - vmin) / (vmax - vmin), 0, 1)

    # 采样（避免太多点）
    n = len(lats)
    if n > max_points:
        idx = np.random.choice(n, max_points, replace=False)
        lats = np.array(lats)[idx]
        lons = np.array(lons)[idx]
        normed = normed[idx]

    return [[float(lats[i]), float(lons[i]), float(normed[i])] for i in range(len(lats))]


def _raster_to_value_grid(
    tif_path: str,
    grid_size: int = 80,
    band: int = 1,
) -> Dict[str, Any]:
    """
    提取低分辨率值网格，用于悬停取值
    返回 {"grid": [[...], ...], "bounds": [...], "rows": N, "cols": M}
    """
    import rasterio
    from rasterio.warp import transform_bounds
    from rasterio.enums import Resampling

    with rasterio.open(tif_path) as src:
        out_shape = (grid_size, int(grid_size * src.width / src.height))
        data = src.read(band, out_shape=out_shape, resampling=Resampling.nearest).astype("float32")
        nodata = src.nodata
        if nodata is not None:
            data[data == nodata] = np.nan

        bounds = src.bounds
        crs = src.crs
        if crs and crs.to_epsg() != 4326:
            try:
                wgs_bounds = transform_bounds(crs, "EPSG:4326", *bounds)
            except Exception:
                wgs_bounds = [bounds.left, bounds.bottom, bounds.right, bounds.top]
        else:
            wgs_bounds = [bounds.left, bounds.bottom, bounds.right, bounds.top]

    # 替换 NaN 为 null (Python None → JSON null)
    grid = []
    for row in data:
        grid.append([None if (not np.isfinite(v)) else round(float(v), 4) for v in row])

    return {
        "grid": grid,
        "south": wgs_bounds[1],
        "west": wgs_bounds[0],
        "north": wgs_bounds[3],
        "east": wgs_bounds[2],
        "rows": len(grid),
        "cols": len(grid[0]) if grid else 0,
    }


def generate_web_map(
    tif_path: str,
    output_path: str,
    title: str = "交互式地图",
    colormap: str = "viridis",
    overlay_opacity: float = 0.7,
    show_heatmap: bool = False,
    additional_layers: List[Dict[str, Any]] = None,
    popup_info: Dict[str, Any] = None,
    center_lat: float = None,
    center_lon: float = None,
    zoom_start: int = 12,
) -> Dict[str, Any]:
    """
    生成交互式 Leaflet Web 地图

    Args:
        tif_path: 栅格文件路径
        output_path: 输出 HTML 路径
        title: 地图标题
        colormap: matplotlib colormap 名称
        overlay_opacity: 栅格叠加透明度
        show_heatmap: 是否显示热力图层
        additional_layers: 额外栅格图层 [{"path": "...", "name": "...", "colormap": "..."}]
        popup_info: 弹窗信息 {"数据集": "...", "分析方法": "..."}
        center_lat/center_lon: 地图中心（可选，自动从栅格边界计算）
        zoom_start: 初始缩放级别
    """
    try:
        import folium
        from folium.plugins import HeatMap, MeasureControl, MousePosition, Draw
    except ImportError:
        return {"success": False, "message": "folium 未安装，请执行: pip install folium"}

    try:
        # 主图层 → PNG overlay
        overlay_path, bounds = _raster_to_png_overlay(tif_path, colormap=colormap)
        if not overlay_path:
            return {"success": False, "message": "栅格数据为空或无法读取"}

        # 计算中心
        if center_lat is None:
            center_lat = (bounds["south"] + bounds["north"]) / 2
        if center_lon is None:
            center_lon = (bounds["west"] + bounds["east"]) / 2

        # 创建底图
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=zoom_start,
            tiles=None,
            control_scale=True,
        )

        # 多种底图
        folium.TileLayer("OpenStreetMap", name="🗺️ OpenStreetMap").add_to(m)
        folium.TileLayer(
            "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri", name="🛰️ 卫星影像"
        ).add_to(m)
        folium.TileLayer(
            "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
            attr="OpenTopoMap", name="🏔️ 地形图"
        ).add_to(m)

        # 栅格叠加
        try:
            from folium.raster_layers import ImageOverlay
        except ImportError:
            from folium import ImageOverlay
        image_overlay = ImageOverlay(
            image=overlay_path,
            bounds=[[bounds["south"], bounds["west"]], [bounds["north"], bounds["east"]]],
            opacity=overlay_opacity,
            name=f"📊 {Path(tif_path).stem}",
            interactive=True,
            show=True,
        )
        image_overlay.add_to(m)

        # 弹窗信息
        popup_html = ""
        if popup_info:
            rows = "".join(f"<tr><td style='padding:3px 8px;color:#666'>{k}</td>"
                           f"<td style='padding:3px 8px;font-weight:bold'>{v}</td></tr>"
                           for k, v in popup_info.items())
            popup_html = f"<table style='font-size:13px'>{rows}</table>"

        # 统计信息弹窗
        stats_html = f"""
        <div style="font-family:sans-serif;min-width:200px">
            <h4 style="margin:0 0 8px;color:#2c3e50">{Path(tif_path).stem}</h4>
            <table style="font-size:12px;color:#555">
                <tr><td>数值范围</td><td style='font-weight:bold'>[{bounds['vmin']:.4f}, {bounds['vmax']:.4f}]</td></tr>
                <tr><td>均值</td><td style='font-weight:bold'>{bounds['mean']:.4f}</td></tr>
                <tr><td>标准差</td><td style='font-weight:bold'>{bounds['std']:.4f}</td></tr>
                <tr><td>有效像元</td><td style='font-weight:bold'>{bounds['valid_count']:,}</td></tr>
            </table>
            {popup_html}
        </div>
        """

        marker = folium.Marker(
            location=[center_lat, center_lon],
            popup=folium.Popup(stats_html, max_width=350),
            tooltip="📊 点击查看数据统计",
            icon=folium.Icon(color="blue", icon="info-sign"),
        )
        marker.add_to(m)

        # 热力图层
        if show_heatmap:
            heat_data = _raster_to_heatmap_data(tif_path)
            if heat_data:
                HeatMap(
                    heat_data,
                    name="🔥 热力图",
                    min_opacity=0.3,
                    radius=15,
                    blur=20,
                    gradient={0.2: 'blue', 0.4: 'lime', 0.6: 'yellow', 0.8: 'orange', 1.0: 'red'},
                    show=False,
                ).add_to(m)

        # 额外图层
        for layer in (additional_layers or []):
            layer_path = layer.get("path", "")
            layer_name = layer.get("name", Path(layer_path).stem)
            layer_cmap = layer.get("colormap", "coolwarm")
            layer_opacity = layer.get("opacity", 0.6)
            if os.path.exists(layer_path):
                lp, lb = _raster_to_png_overlay(layer_path, colormap=layer_cmap)
                if lp:
                    ImageOverlay(
                        image=lp,
                        bounds=[[lb["south"], lb["west"]], [lb["north"], lb["east"]]],
                        opacity=layer_opacity,
                        name=f"📌 {layer_name}",
                        show=False,
                    ).add_to(m)

        # 控件
        folium.LayerControl(collapsed=False).add_to(m)
        MeasureControl(position="topleft").add_to(m)
        MousePosition(position="bottomleft", separator=" | ",
                       prefix="坐标:").add_to(m)
        Draw(position="topleft", export=False).add_to(m)

        # 图例 HTML
        legend_html = f"""
        <div style="position:fixed;bottom:30px;right:10px;z-index:1000;
                     background:white;padding:10px 14px;border-radius:8px;
                     box-shadow:0 2px 8px rgba(0,0,0,0.2);font-size:12px;font-family:sans-serif">
            <div style="font-weight:bold;margin-bottom:6px;color:#2c3e50">{title}</div>
            <div style="display:flex;align-items:center;gap:4px">
                <span style="color:#666">{bounds['vmin']:.2f}</span>
                <div style="width:120px;height:12px;border-radius:3px;
                            background:linear-gradient(to right,
                            {_colormap_css_gradient(colormap)})"></div>
                <span style="color:#666">{bounds['vmax']:.2f}</span>
            </div>
        </div>
        """
        m.get_root().html.add_child(folium.Element(legend_html))

        # 标题
        title_html = f"""
        <div style="position:fixed;top:10px;left:60px;z-index:1000;
                     background:rgba(255,255,255,0.9);padding:8px 16px;border-radius:8px;
                     box-shadow:0 2px 6px rgba(0,0,0,0.15);font-family:sans-serif">
            <span style="font-size:16px;font-weight:bold;color:#2c3e50">{title}</span>
        </div>
        """
        m.get_root().html.add_child(folium.Element(title_html))

        # 悬停取值：渲染 HTML → 找 map 变量名 → 注入代码
        try:
            value_grid = _raster_to_value_grid(tif_path)
            grid_json = json.dumps(value_grid["grid"])

            hover_div = """
            <div id="hover-value" style="position:fixed;bottom:30px;left:10px;z-index:1000;
                 background:rgba(0,0,0,0.75);color:#fff;padding:6px 12px;border-radius:6px;
                 font-size:13px;font-family:sans-serif;display:none;pointer-events:none;">
            </div>
            """
            m.get_root().html.add_child(folium.Element(hover_div))

            # 先渲染完整 HTML，再 post-process 找 map 变量名
            full_html = m.get_root().render()
            import re
            match = re.search(r'var\s+(map_\w+)\s*=\s*L\.map\(', full_html)
            if match:
                map_var = match.group(1)
                script_final = (
                    '\n<script>(function(){'
                    'var grid=' + grid_json + ';'
                    'var south=' + str(value_grid['south']) + ',north=' + str(value_grid['north']) + ';'
                    'var west=' + str(value_grid['west']) + ',east=' + str(value_grid['east']) + ';'
                    'var rows=' + str(value_grid['rows']) + ',cols=' + str(value_grid['cols']) + ';'
                    'var el=document.getElementById("hover-value");'
                    'if(!el||typeof ' + map_var + '==="undefined")return;'
                    'var map=' + map_var + ';'
                    'map.on("mousemove",function(e){'
                    'var lat=e.latlng.lat,lng=e.latlng.lng;'
                    'if(lat<south||lat>north||lng<west||lng>east){el.style.display="none";return;}'
                    'var r=Math.floor((north-lat)/(north-south)*rows);'
                    'var c=Math.floor((lng-west)/(east-west)*cols);'
                    'r=Math.max(0,Math.min(rows-1,r));'
                    'c=Math.max(0,Math.min(cols-1,c));'
                    'var val=grid[r]?grid[r][c]:null;'
                    'if(val!==null&&val!==undefined){'
                    'el.innerHTML=lat.toFixed(5)+", "+lng.toFixed(5)+" &rarr; <b>"+val+"</b>";'
                    '}else{'
                    'el.innerHTML=lat.toFixed(5)+", "+lng.toFixed(5)+" &rarr; NoData";'
                    '}'
                    'el.style.display="block";'
                    '});'
                    'map.on("mouseout",function(){el.style.display="none";});'
                    '})();</script>'
                )
                # 注入到最后一个 </script> 之后（确保在 map 定义之后）
                last_script = full_html.rfind('</script>')
                if last_script >= 0:
                    insert_pos = last_script + len('</script>')
                    full_html = full_html[:insert_pos] + script_final + full_html[insert_pos:]
                else:
                    full_html = full_html.replace('</body>', script_final + '\n</body>')
                os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(full_html)
            else:
                os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
                m.save(output_path)
        except Exception:
            os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
            m.save(output_path)

        # 清理临时文件
        try:
            os.unlink(overlay_path)
        except Exception:
            pass

        return {
            "success": True,
            "message": f"交互式地图已生成: {output_path}",
            "output_path": output_path,
            "format": "html",
            "center": [center_lat, center_lon],
            "bounds": bounds,
            "layers": [Path(tif_path).stem] + [l.get("name", "") for l in (additional_layers or [])],
        }

    except Exception as e:
        import traceback
        return {"success": False, "message": f"Web 地图生成失败: {e}", "traceback": traceback.format_exc(limit=3)}


def _colormap_css_gradient(colormap: str) -> str:
    """将 matplotlib colormap 名转为 CSS 渐变"""
    gradients = {
        "viridis": "#440154, #3b528b, #21918c, #5ec962, #fde725",
        "plasma": "#0d0887, #7e03a8, #cc4778, #f89540, #f0f921",
        "inferno": "#000004, #57106e, #bb3754, #f98e09, #fcffa4",
        "coolwarm": "#3b4cc0, #7092d5, #c0c0c0, #d5706f, #b40426",
        "YlOrRd": "#ffffcc, #fd8d3c, #fc4e2a, #e31a1c, #800026",
        "terrain": "#333399, #4682b4, #228b22, #90ee90, #daa520, #8b4513",
        "RdYlGn": "#d73027, #fc8d59, #fee08b, #d9ef8b, #91cf60, #1a9850",
        "jet": "#00007f, #0000ff, #00ffff, #ffff00, #ff0000, #7f0000",
        "hot": "#000000, #900000, #ff0000, #ffff00, #ffffff",
        "gray": "#000000, #ffffff",
    }
    return gradients.get(colormap, gradients["viridis"])


# ============================================================
# 多年时间序列交互式地图（带年份滑块 + 悬停取值）
# ============================================================

def generate_timelapse_web_map(
    lst_tif_paths: List[str],
    years: List[int],
    output_path: str,
    title: str = "LST 时间序列",
    colormap: str = "coolwarm",
    overlay_opacity: float = 0.7,
    month: int = 8,
    vmin: float = None,
    vmax: float = None,
) -> Dict[str, Any]:
    """
    生成多年 LST 时间序列交互式地图。
    支持年份滑块切换 + 悬停查看所有年份温度值。

    Args:
        lst_tif_paths: 每年的 LST GeoTIFF 路径列表
        years: 对应的年份列表
        output_path: 输出 HTML 路径
        title: 地图标题
        colormap: matplotlib colormap 名称
        overlay_opacity: 栅格叠加透明度
        month: 月份（用于标签显示）
    """
    try:
        import folium
        from folium.plugins import MeasureControl, MousePosition
    except ImportError:
        return {"success": False, "message": "folium 未安装，请执行: pip install folium"}

    try:
        import rasterio
        from rasterio.warp import transform_bounds
    except ImportError:
        return {"success": False, "message": "rasterio 未安装"}

    if len(lst_tif_paths) != len(years):
        return {"success": False, "message": "lst_tif_paths 和 years 长度不一致"}

    # ── 读取所有年份数据 ──
    all_grids = {}
    all_bounds = {}
    global_vmin = float("inf")
    global_vmax = float("-inf")

    for tif_path, year in zip(lst_tif_paths, years):
        if not os.path.exists(tif_path):
            continue

        try:
            with rasterio.open(tif_path) as src:
                # 降采样用于悬停取值
                factor = max(1, int(np.sqrt(src.width * src.height / 8000)))
                from rasterio.enums import Resampling
                out_shape = (src.height // factor, src.width // factor)
                data = src.read(1, out_shape=out_shape, resampling=Resampling.bilinear).astype("float32")
                nodata = src.nodata
                if nodata is not None:
                    data[data == nodata] = np.nan

                bounds = src.bounds
                crs = src.crs
                if crs and crs.to_epsg() != 4326:
                    try:
                        wgs_bounds = transform_bounds(crs, "EPSG:4326", *bounds)
                    except Exception:
                        wgs_bounds = [bounds.left, bounds.bottom, bounds.right, bounds.top]
                else:
                    wgs_bounds = [bounds.left, bounds.bottom, bounds.right, bounds.top]

            valid = data[np.isfinite(data)]
            if valid.size == 0:
                continue

            # 构建值网格
            grid = []
            for row in data:
                grid.append([None if not np.isfinite(v) else round(float(v), 2) for v in row])

            all_grids[year] = grid
            all_bounds[year] = {
                "south": wgs_bounds[1], "west": wgs_bounds[0],
                "north": wgs_bounds[3], "east": wgs_bounds[2],
                "rows": len(grid), "cols": len(grid[0]) if grid else 0,
            }

            if vmin is None:
                vmin = float(np.percentile(valid, 2))
            if vmax is None:
                vmax = float(np.percentile(valid, 98))
            global_vmin = min(global_vmin, vmin)
            global_vmax = max(global_vmax, vmax)

        except Exception as e:
            print(f"[WebMap] 读取 {year} 年数据失败: {e}")

    if not all_grids:
        return {"success": False, "message": "无有效数据"}

    # ── 生成 PNG overlay ──
    overlays = {}
    for tif_path, year in zip(lst_tif_paths, years):
        if year not in all_grids:
            continue
        png_path, _ = _raster_to_png_overlay(
            tif_path, colormap=colormap, rescale_factor=2,
        )
        if png_path:
            overlays[year] = png_path

    # ── 计算地图中心 ──
    first_year = list(all_bounds.keys())[0]
    b = all_bounds[first_year]
    center_lat = (b["south"] + b["north"]) / 2
    center_lon = (b["west"] + b["east"]) / 2

    # ── 创建 Folium 地图 ──
    m = folium.Map(location=[center_lat, center_lon], zoom_start=12, tiles=None, control_scale=True)

    folium.TileLayer("OpenStreetMap", name="🗺️ OpenStreetMap").add_to(m)
    folium.TileLayer(
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri", name="🛰️ 卫星影像"
    ).add_to(m)
    folium.TileLayer(
        "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        attr="OpenTopoMap", name="🏔️ 地形图"
    ).add_to(m)

    # ── 添加每年的 ImageOverlay ──
    try:
        from folium.raster_layers import ImageOverlay
    except ImportError:
        from folium import ImageOverlay

    sorted_years = sorted(all_grids.keys())
    for i, year in enumerate(sorted_years):
        if year not in overlays:
            continue
        b = all_bounds[year]
        is_visible = (year == sorted_years[-1])  # 最新一年默认显示
        overlay = ImageOverlay(
            image=overlays[year],
            bounds=[[b["south"], b["west"]], [b["north"], b["east"]]],
            opacity=overlay_opacity,
            name=f"📊 {year}年{month}月 LST",
            interactive=True,
            show=is_visible,
        )
        overlay.add_to(m)

    # ── 悬停取值：注入 JS ──
    hover_div = """
    <div id="hover-value" style="position:fixed;bottom:30px;left:10px;z-index:1000;
         background:rgba(0,0,0,0.85);color:#fff;padding:10px 16px;border-radius:8px;
         font-size:13px;font-family:sans-serif;display:none;pointer-events:none;
         max-width:400px;box-shadow:0 2px 8px rgba(0,0,0,0.3);">
    </div>
    """
    m.get_root().html.add_child(folium.Element(hover_div))

    # 构建所有年份的网格数据 JSON
    grids_json = json.dumps({str(y): all_grids[y] for y in sorted_years})
    bounds_json = json.dumps({str(y): all_bounds[y] for y in sorted_years})

    # ── 图例 ──
    legend_html = f"""
    <div style="position:fixed;bottom:30px;right:10px;z-index:1000;
                 background:white;padding:12px 16px;border-radius:8px;
                 box-shadow:0 2px 8px rgba(0,0,0,0.2);font-size:12px;font-family:sans-serif">
        <div style="font-weight:bold;margin-bottom:6px;color:#2c3e50">{title}</div>
        <div style="display:flex;align-items:center;gap:4px">
            <span style="color:#666">{global_vmin:.1f}°C</span>
            <div style="width:120px;height:12px;border-radius:3px;
                        background:linear-gradient(to right,
                        {_colormap_css_gradient(colormap)})"></div>
            <span style="color:#666">{global_vmax:.1f}°C</span>
        </div>
        <div style="margin-top:8px;color:#888;font-size:11px">悬停查看各年温度</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    # ── 标题 ──
    title_html = f"""
    <div style="position:fixed;top:10px;left:60px;z-index:1000;
                 background:rgba(255,255,255,0.9);padding:8px 16px;border-radius:8px;
                 box-shadow:0 2px 6px rgba(0,0,0,0.15);font-family:sans-serif">
        <span style="font-size:16px;font-weight:bold;color:#2c3e50">{title}</span>
    </div>
    """
    m.get_root().html.add_child(folium.Element(title_html))

    # ── 控件 ──
    folium.LayerControl(collapsed=False).add_to(m)
    MeasureControl(position="topleft").add_to(m)
    MousePosition(position="bottomleft", separator=" | ", prefix="坐标:").add_to(m)

    # ── 渲染 HTML 并注入悬停 JS ──
    full_html = m.get_root().render()

    import re
    map_match = re.search(r'var\s+(map_\w+)\s*=\s*L\.map\(', full_html)
    if map_match:
        map_var = map_match.group(1)
        hover_script = f"""
<script>
(function() {{
    var grids = {grids_json};
    var allBounds = {bounds_json};
    var years = {json.dumps([str(y) for y in sorted_years])};
    var el = document.getElementById("hover-value");
    var map = {map_var};
    if (!el || !map) return;

    map.on("mousemove", function(e) {{
        var lat = e.latlng.lat, lng = e.latlng.lng;
        var lines = [];
        for (var yi = 0; yi < years.length; yi++) {{
            var yr = years[yi];
            var b = allBounds[yr];
            var grid = grids[yr];
            if (!b || !grid) continue;
            if (lat < b.south || lat > b.north || lng < b.west || lng > b.east) continue;
            var rows = b.rows, cols = b.cols;
            var r = Math.floor((b.north - lat) / (b.north - b.south) * rows);
            var c = Math.floor((lng - b.west) / (b.east - b.west) * cols);
            r = Math.max(0, Math.min(rows - 1, r));
            c = Math.max(0, Math.min(cols - 1, c));
            var val = grid[r] ? grid[r][c] : null;
            if (val !== null && val !== undefined) {{
                lines.push("<b>" + yr + "</b>: " + val + "°C");
            }}
        }}
        if (lines.length > 0) {{
            el.innerHTML = "<div style='margin-bottom:4px;color:#aaa;font-size:11px'>"
                + lat.toFixed(5) + ", " + lng.toFixed(5) + "</div>"
                + lines.join("<br>");
            el.style.display = "block";
        }} else {{
            el.style.display = "none";
        }}
    }});
    map.on("mouseout", function() {{ el.style.display = "none"; }});
}})();
</script>
"""
        last_script = full_html.rfind('</script>')
        if last_script >= 0:
            full_html = full_html[:last_script + len('</script>')] + hover_script + full_html[last_script + len('</script>'):]
        else:
            full_html = full_html.replace('</body>', hover_script + '\n</body>')

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(full_html)

    # 清理临时 PNG
    for png in overlays.values():
        try:
            os.unlink(png)
        except Exception:
            pass

    return {
        "success": True,
        "message": f"交互式时间序列地图已生成: {output_path}",
        "output_path": output_path,
        "years": sorted_years,
        "vmin": global_vmin,
        "vmax": global_vmax,
        "center": [center_lat, center_lon],
    }