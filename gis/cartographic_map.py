from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Sequence, Tuple

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from affine import Affine
from matplotlib import font_manager as fm
from matplotlib import patheffects as pe
from matplotlib.patches import Polygon, Rectangle, FancyBboxPatch

try:
    from pyproj import Geod
except Exception:
    Geod = None

COLORMAPS = {
    "jet": {"cmap": "jet", "label": "Jet (彩虹)"},
    "terrain": {"cmap": "terrain", "label": "Terrain (地形)"},
    "viridis": {"cmap": "viridis", "label": "Viridis"},
    "plasma": {"cmap": "plasma", "label": "Plasma"},
    "coolwarm": {"cmap": "coolwarm", "label": "CoolWarm (冷暖)"},
    "RdYlBu_r": {"cmap": "RdYlBu_r", "label": "RdYlBu_r"},
    "YlOrRd": {"cmap": "YlOrRd", "label": "YlOrRd"},
    "hot": {"cmap": "hot", "label": "Hot"},
    "gray": {"cmap": "gray", "label": "Gray"},
    "ocean": {"cmap": "ocean", "label": "Ocean"},
    "Spectral": {"cmap": "Spectral", "label": "Spectral"},
    "RdYlGn": {"cmap": "RdYlGn", "label": "RdYlGn"},
    "YlGn": {"cmap": "YlGn", "label": "YlGn"},
    "Greens": {"cmap": "Greens", "label": "Greens"},
    "Blues": {"cmap": "Blues", "label": "Blues"},
    "Reds": {"cmap": "Reds", "label": "Reds"},
    "Purples": {"cmap": "Purples", "label": "Purples"},
}

_FONT_CANDIDATES = [
    "Microsoft YaHei", "SimHei", "Noto Sans CJK SC", "Noto Sans CJK JP",
    "Source Han Sans CN", "Source Han Sans SC", "WenQuanYi Micro Hei",
    "PingFang SC", "Heiti SC", "Arial Unicode MS", "DejaVu Sans",
]


def _pick_font() -> Optional[str]:
    available = {f.name for f in fm.fontManager.ttflist}
    for name in _FONT_CANDIDATES:
        if name in available:
            plt.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            plt.rcParams["axes.unicode_minus"] = False
            return name
    plt.rcParams["font.sans-serif"] = ["DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    return None


_FONT_NAME = _pick_font()


def _font(size: Optional[int] = None, weight: Optional[str] = None):
    if not _FONT_NAME:
        return None
    return fm.FontProperties(family=_FONT_NAME, size=size, weight=weight)


def _trim_nan_border(data: np.ndarray) -> Tuple[np.ndarray, int, int]:
    valid = np.isfinite(data)
    if not valid.any():
        return data, 0, 0
    rows = np.where(valid.any(axis=1))[0]
    cols = np.where(valid.any(axis=0))[0]
    r0, r1 = int(rows[0]), int(rows[-1]) + 1
    c0, c1 = int(cols[0]), int(cols[-1]) + 1
    return data[r0:r1, c0:c1], r0, c0


def _safe_percentile(data: np.ndarray, q: float, fallback: float) -> float:
    valid = data[np.isfinite(data)]
    if valid.size == 0:
        return fallback
    return float(np.nanpercentile(valid, q))


def _auto_figsize(rows: int, cols: int) -> Tuple[float, float]:
    aspect = cols / max(rows, 1)
    width = 13.8 if aspect > 1.7 else 12.6 if aspect > 1.2 else 11.6
    height = min(max(width / max(aspect, 0.55) + 2.7, 8.2), 10.4)
    return round(width, 2), round(height, 2)


def _calc_trimmed_extent(transform: Optional[Affine], rows: int, cols: int, row0: int, col0: int) -> Optional[Tuple[float, float, float, float]]:
    if transform is None:
        return None
    shifted = transform * Affine.translation(col0, row0)
    left, top = shifted * (0, 0)
    right, bottom = shifted * (cols, rows)
    x0, x1 = sorted([left, right])
    y0, y1 = sorted([bottom, top])
    return (x0, x1, y0, y1)


def _meters_per_map_unit(transform: Optional[Affine], crs, extent) -> Optional[float]:
    if transform is None or crs is None or extent is None:
        return None
    if getattr(crs, "is_projected", False):
        try:
            factor = getattr(crs, "linear_units_factor", None)
            if factor is not None:
                factor = factor[0] if isinstance(factor, (list, tuple)) else factor
                return float(factor)
        except Exception:
            pass
        return 1.0
    center_lat = (extent[2] + extent[3]) / 2.0
    if Geod is not None:
        try:
            geod = Geod(ellps="WGS84")
            x0 = extent[0]
            lon_step = abs(transform.a)
            _, _, dist = geod.inv(x0, center_lat, x0 + lon_step, center_lat)
            return abs(dist / lon_step) if lon_step else None
        except Exception:
            pass
    return 111320.0 * math.cos(math.radians(center_lat))


def _nice_length(max_length: float) -> float:
    if not max_length or max_length <= 0:
        return 1000.0
    exponent = math.floor(math.log10(max_length))
    base = 10 ** exponent
    scaled = max_length / base
    if scaled <= 1:
        nice = 1
    elif scaled <= 2:
        nice = 2
    elif scaled <= 5:
        nice = 5
    else:
        nice = 10
    value = nice * base
    if value > max_length:
        if nice == 10:
            value = 5 * base
        elif nice == 5:
            value = 2 * base
        elif nice == 2:
            value = 1 * base
    return float(value)


def _format_distance(length_m: float) -> str:
    if length_m >= 1000:
        km = length_m / 1000.0
        return f"{int(km)} km" if abs(km - round(km)) < 1e-6 else f"{km:.1f} km"
    return f"{int(round(length_m))} m"


def _normalize_position(position: str, default: str) -> str:
    value = (position or default).strip().lower()
    aliases = {
        "左上": "upper left", "upper left": "upper left", "top left": "upper left",
        "右上": "upper right", "upper right": "upper right", "top right": "upper right",
        "左下": "lower left", "lower left": "lower left", "bottom left": "lower left",
        "右下": "lower right", "lower right": "lower right", "bottom right": "lower right",
        "左边": "left", "right": "right", "左侧": "left", "右边": "right", "右侧": "right",
        "上边": "top", "上方": "top", "下边": "bottom", "下方": "bottom",
        "left": "left", "right": "right", "top": "top", "bottom": "bottom",
    }
    return aliases.get(value, default)


def _compute_layout(fig_w: float, fig_h: float, data_shape: Tuple[int, int], legend_position: str,
                    map_margin: float, map_frame_scale: float) -> Tuple[Dict[str, float], List[float], List[float], str]:
    outer = {
        "left": 0.045,
        "right": 0.955,
        "bottom": 0.08,
        "top": 0.92,
    }
    margin = min(max(map_margin, 0.015), 0.09)
    map_frame_scale = min(max(map_frame_scale, 0.72), 1.10)
    legend_position = _normalize_position(legend_position, "right")

    reserve_right = 0.16 if legend_position == "right" else 0.08
    reserve_left = 0.16 if legend_position == "left" else 0.08
    reserve_top = 0.11 if legend_position == "top" else 0.08
    reserve_bottom = 0.13 if legend_position == "bottom" else 0.09

    inner_box = [
        outer["left"] + reserve_left + margin,
        outer["bottom"] + reserve_bottom + margin,
        (outer["right"] - outer["left"] - reserve_left - reserve_right - 2 * margin),
        (outer["top"] - outer["bottom"] - reserve_top - reserve_bottom - 2 * margin),
    ]

    rows, cols = data_shape
    data_ratio = cols / max(rows, 1)
    box_ratio = (fig_w * inner_box[2]) / max(fig_h * inner_box[3], 1e-6)

    if data_ratio >= box_ratio:
        map_w = inner_box[2] * map_frame_scale
        map_h = map_w * fig_w / max(data_ratio * fig_h, 1e-6)
    else:
        map_h = inner_box[3] * map_frame_scale
        map_w = map_h * data_ratio * fig_h / max(fig_w, 1e-6)

    map_w = min(map_w, inner_box[2])
    map_h = min(map_h, inner_box[3])
    map_left = inner_box[0] + (inner_box[2] - map_w) / 2
    map_bottom = inner_box[1] + (inner_box[3] - map_h) / 2
    map_rect = [map_left, map_bottom, map_w, map_h]

    control_rect = [outer["left"], outer["bottom"], outer["right"] - outer["left"], outer["top"] - outer["bottom"]]
    return outer, map_rect, control_rect, legend_position


def _anchor_in_outer(outer: Dict[str, float], position: str, pad_x: float = 0.016, pad_y: float = 0.02) -> Tuple[float, float, str, str]:
    p = _normalize_position(position, "lower right")
    if p == "upper left":
        return outer["left"] + pad_x, outer["top"] - pad_y, "left", "top"
    if p == "upper right":
        return outer["right"] - pad_x, outer["top"] - pad_y, "right", "top"
    if p == "lower left":
        return outer["left"] + pad_x, outer["bottom"] + pad_y, "left", "bottom"
    return outer["right"] - pad_x, outer["bottom"] + pad_y, "right", "bottom"


def _draw_outer_frame(panel_ax, outer: Dict[str, float], bg_color: str, frame: bool = True) -> None:
    panel_ax.add_patch(
        Rectangle(
            (outer["left"], outer["bottom"]),
            outer["right"] - outer["left"],
            outer["top"] - outer["bottom"],
            transform=panel_ax.transAxes,
            facecolor=bg_color,
            edgecolor="#808080" if frame else bg_color,
            linewidth=1.2 if frame else 0.0,
            zorder=0,
        )
    )


def _draw_map_frame(panel_ax, map_rect: Sequence[float], frame: bool = True) -> None:
    panel_ax.add_patch(
        Rectangle(
            (map_rect[0], map_rect[1]), map_rect[2], map_rect[3],
            transform=panel_ax.transAxes,
            facecolor="white",
            edgecolor="#707070" if frame else "white",
            linewidth=1.0 if frame else 0.0,
            zorder=1,
        )
    )


def _draw_north_arrow(panel_ax, outer: Dict[str, float], position: str = "upper right", fontsize: int = 13,
                      xoffset: float = 0.0, yoffset: float = 0.0) -> None:
    cx, cy, ha, va = _anchor_in_outer(outer, position, pad_x=0.06, pad_y=0.07)
    cx += xoffset
    cy += yoffset
    size = min(max(fontsize / 13.0, 0.8), 1.55)
    panel_ax.add_patch(
        FancyBboxPatch(
            (cx - 0.03 * size if ha != "left" else cx, cy - 0.085 * size),
            0.06 * size,
            0.11 * size,
            boxstyle="round,pad=0.006,rounding_size=0.005",
            fc="white",
            ec="#B9B9B9",
            lw=0.8,
            transform=panel_ax.transAxes,
            zorder=5,
            alpha=0.96,
        )
    )
    x_mid = cx if ha == "center" else (cx - 0.0 if ha == "left" else cx)
    north = Polygon(
        [(x_mid, cy + 0.02 * size), (x_mid - 0.012 * size, cy - 0.02 * size), (x_mid, cy - 0.002 * size), (x_mid + 0.012 * size, cy - 0.02 * size)],
        closed=True, transform=panel_ax.transAxes, fc="#111111", ec="#111111", lw=0.8, zorder=7,
    )
    south = Polygon(
        [(x_mid, cy - 0.048 * size), (x_mid - 0.010 * size, cy - 0.018 * size), (x_mid + 0.010 * size, cy - 0.018 * size)],
        closed=True, transform=panel_ax.transAxes, fc="#BFBFBF", ec="#111111", lw=0.7, zorder=6,
    )
    panel_ax.add_patch(north)
    panel_ax.add_patch(south)
    panel_ax.text(
        x_mid, cy + 0.034 * size, "N",
        transform=panel_ax.transAxes, ha="center", va="bottom",
        fontsize=fontsize, fontweight="bold", color="#141414", zorder=8,
        fontproperties=_font(fontsize, "bold"),
    )


def _draw_scalebar(panel_ax, outer: Dict[str, float], extent, transform, crs,
                   position: str = "lower left", font_size: int = 10, length_ratio: float = 0.16,
                   xoffset: float = 0.0, yoffset: float = 0.0) -> str:
    anchor_x, anchor_y, ha, va = _anchor_in_outer(outer, position, pad_x=0.03, pad_y=0.035)
    anchor_x += xoffset
    anchor_y += yoffset
    meter_per_unit = _meters_per_map_unit(transform, crs, extent)
    if meter_per_unit is None or extent is None:
        return ""
    total_width_units = extent[1] - extent[0]
    total_width_m = abs(total_width_units * meter_per_unit)
    target = total_width_m * min(max(length_ratio, 0.08), 0.22)
    length_m = _nice_length(target)
    label = _format_distance(length_m)

    max_box_w = min(0.20, outer["right"] - outer["left"] - 0.12)
    bar_w = min(max_box_w, 0.08 + 0.45 * min(max(length_ratio, 0.08), 0.22))
    bar_h = 0.018

    if ha == "left":
        left = anchor_x
    else:
        left = anchor_x - bar_w - 0.01
    bottom = anchor_y + 0.008

    panel_ax.add_patch(
        FancyBboxPatch(
            (left - 0.008, bottom - 0.012),
            bar_w + 0.016, bar_h + 0.045,
            boxstyle="round,pad=0.004,rounding_size=0.004",
            fc="white", ec="#BFBFBF", lw=0.8, alpha=0.96,
            transform=panel_ax.transAxes, zorder=5,
        )
    )
    seg_w = bar_w / 2.0
    for i in range(2):
        panel_ax.add_patch(
            Rectangle(
                (left + i * seg_w, bottom), seg_w, bar_h,
                transform=panel_ax.transAxes,
                facecolor="#202020" if i % 2 == 0 else "white",
                edgecolor="#4E4E4E", linewidth=0.7, zorder=6,
            )
        )
    panel_ax.text(
        left + bar_w / 2, bottom + bar_h + 0.012, label,
        transform=panel_ax.transAxes, ha="center", va="bottom",
        fontsize=font_size, color="#222222", zorder=7,
        fontproperties=_font(font_size),
    )
    return label


def _add_annotations(ax, annotation_items: Sequence[Dict], extent) -> None:
    if not annotation_items:
        return
    x0, x1, y0, y1 = extent
    for item in annotation_items:
        try:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            coord = item.get("coord", "axes")
            color = item.get("color", "#1F1F1F")
            fontsize = int(item.get("fontsize", 11))
            if coord == "axes":
                x = float(item.get("x", 0.05))
                y = float(item.get("y", 0.05))
                trans = ax.transAxes
            else:
                x = float(item.get("x", x0 + 0.05 * (x1 - x0)))
                y = float(item.get("y", y0 + 0.05 * (y1 - y0)))
                trans = ax.transData
            ax.text(
                x, y, text,
                transform=trans,
                fontsize=fontsize,
                color=color,
                fontproperties=_font(fontsize),
                bbox=dict(boxstyle="round,pad=0.18", fc="white", ec="#B7B7B7", alpha=0.82),
                path_effects=[pe.withStroke(linewidth=1.2, foreground="white")],
                zorder=20,
            )
        except Exception:
            continue


def generate_cartographic_map(
    tif_path: str,
    output_path: Optional[str] = None,
    title: str = "Land Surface Temperature (SCA)",
    colormap: str = "jet",
    show_legend: bool = True,
    show_scalebar: bool = True,
    show_north: bool = True,
    dpi: int = 300,
    figsize: Optional[Tuple[float, float]] = None,
    vmin: Optional[float] = None,
    vmax: Optional[float] = None,
    unit_label: str = "LST (°C)",
    crop_bounds: Optional[Tuple[int, int, int, int]] = None,
    alpha: float = 1.0,
    bg_color: str = "#EFEFEF",
    title_color: str = "#1A1A1A",
    grid: bool = False,
    frame: bool = True,
    legend_label_fontsize: int = 12,
    legend_tick_fontsize: int = 10,
    legend_shrink: float = 0.88,
    legend_position: str = "right",
    scalebar_position: str = "lower left",
    scalebar_fontsize: int = 10,
    scalebar_length_ratio: float = 0.16,
    north_position: str = "upper right",
    north_fontsize: int = 13,
    title_fontsize: int = 18,
    annotation_items: Optional[Sequence[Dict]] = None,
    map_margin: float = 0.035,
    map_frame_scale: float = 0.94,
    legend_xoffset: float = 0.0,
    legend_yoffset: float = 0.0,
    north_xoffset: float = 0.0,
    north_yoffset: float = 0.0,
    scalebar_xoffset: float = 0.0,
    scalebar_yoffset: float = 0.0,
) -> Dict:
    try:
        if not os.path.exists(tif_path):
            return {"success": False, "message": f"输入文件不存在: {tif_path}"}

        with rasterio.open(tif_path) as src:
            data = src.read(1).astype("float32")
            profile = src.profile.copy()
            transform = src.transform
            crs = src.crs
            nodata = src.nodata

        if nodata is not None:
            data = np.where(data == nodata, np.nan, data)
        data = np.where(np.isfinite(data), data, np.nan)

        if crop_bounds and len(crop_bounds) == 4:
            r0, c0, r1, c1 = [int(v) for v in crop_bounds]
            data = data[r0:r1, c0:c1]
            row_off, col_off = r0, c0
        else:
            data, row_off, col_off = _trim_nan_border(data)

        if not np.isfinite(data).any():
            return {"success": False, "message": "栅格中没有有效像元"}

        rows, cols = data.shape
        extent = _calc_trimmed_extent(transform, rows, cols, row_off, col_off)

        if figsize is None:
            figsize = _auto_figsize(rows, cols)
        fig_w, fig_h = float(figsize[0]), float(figsize[1])

        if vmin is None:
            vmin = _safe_percentile(data, 2, float(np.nanmin(data)))
        if vmax is None:
            vmax = _safe_percentile(data, 98, float(np.nanmax(data)))
        if vmax <= vmin:
            vmax = vmin + 1e-6

        cmap_name = COLORMAPS.get(colormap, {}).get("cmap", colormap)
        cmap = plt.get_cmap(cmap_name).copy()
        cmap.set_bad("#F2F2F2")

        outer, map_rect, _, norm_legend_pos = _compute_layout(fig_w, fig_h, data.shape, legend_position, map_margin, map_frame_scale)

        fig = plt.figure(figsize=(fig_w, fig_h), facecolor=bg_color)
        panel_ax = fig.add_axes([0, 0, 1, 1])
        panel_ax.set_axis_off()
        _draw_outer_frame(panel_ax, outer, bg_color, frame=frame)
        _draw_map_frame(panel_ax, map_rect, frame=frame)

        ax = fig.add_axes(map_rect)
        extent_img = [extent[0], extent[1], extent[2], extent[3]] if extent else None
        image = ax.imshow(
            data,
            cmap=cmap,
            vmin=vmin,
            vmax=vmax,
            origin="upper",
            extent=extent_img,
            aspect="auto",
            interpolation="nearest",
            alpha=min(max(alpha, 0.0), 1.0),
        )
        ax.set_title(title, fontsize=title_fontsize, color=title_color, pad=10, fontweight="bold", fontproperties=_font(title_fontsize, "bold"))
        if crs and getattr(crs, "is_geographic", False):
            ax.set_xlabel("Longitude", fontsize=10)
            ax.set_ylabel("Latitude", fontsize=10)
        else:
            ax.set_xlabel("X", fontsize=10)
            ax.set_ylabel("Y", fontsize=10)
        ax.tick_params(labelsize=8)
        if grid:
            ax.grid(color="#999999", linestyle="--", linewidth=0.5, alpha=0.55)
        if not frame:
            for spine in ax.spines.values():
                spine.set_visible(False)

        if annotation_items:
            _add_annotations(ax, annotation_items, extent)

        if show_legend:
            legend_shrink = min(max(float(legend_shrink), 0.55), 1.10)
            # 微调偏移：legend_xoffset 正=右移，负=左移；legend_yoffset 正=上移，负=下移
            lx_off = min(max(float(legend_xoffset), -0.30), 0.30)
            ly_off = min(max(float(legend_yoffset), -0.30), 0.30)
            if norm_legend_pos == "right":
                cax = fig.add_axes([outer["right"] - 0.05 + lx_off, outer["bottom"] + 0.07 + ly_off, 0.022, 0.22 * legend_shrink])
                orientation = "vertical"
            elif norm_legend_pos == "left":
                cax = fig.add_axes([outer["left"] + 0.028 + lx_off, outer["bottom"] + 0.07 + ly_off, 0.022, 0.22 * legend_shrink])
                orientation = "vertical"
            elif norm_legend_pos == "top":
                width = min(map_rect[2] * 0.42 * legend_shrink, 0.25)
                cax = fig.add_axes([map_rect[0] + map_rect[2] - width + lx_off, outer["top"] - 0.055 + ly_off, width, 0.018])
                orientation = "horizontal"
            else:
                width = min(map_rect[2] * 0.40 * legend_shrink, 0.24)
                cax = fig.add_axes([outer["right"] - width - 0.03 + lx_off, outer["bottom"] + 0.04 + ly_off, width, 0.018])
                orientation = "horizontal"
            cbar = fig.colorbar(image, cax=cax, orientation=orientation)
            cbar.set_label(unit_label, fontsize=legend_label_fontsize, fontweight="bold", fontproperties=_font(legend_label_fontsize, "bold"))
            cbar.ax.tick_params(labelsize=legend_tick_fontsize)

        scalebar_label = ""
        if show_scalebar:
            scalebar_label = _draw_scalebar(panel_ax, outer, extent, transform, crs, scalebar_position, scalebar_fontsize, scalebar_length_ratio, scalebar_xoffset, scalebar_yoffset)
        if show_north:
            _draw_north_arrow(panel_ax, outer, north_position, north_fontsize, north_xoffset, north_yoffset)

        footer_parts = []
        if crs is not None:
            footer_parts.append(f"CRS: {crs}")
        footer_parts.append(f"Size: {cols}×{rows} px")
        footer_parts.append(f"Range: {float(np.nanmin(data)):.2f} – {float(np.nanmax(data)):.2f} {unit_label}")
        if scalebar_label:
            footer_parts.append(f"Scale bar: {scalebar_label}")
        panel_ax.text(
            0.5, outer["bottom"] - 0.03, "  |  ".join(footer_parts),
            transform=panel_ax.transAxes, ha="center", va="center",
            fontsize=8, color="#666666", fontproperties=_font(8),
        )

        if output_path is None:
            output_path = os.path.join(os.path.dirname(tif_path), "cartographic_map.png")
        fig.savefig(output_path, dpi=int(dpi), bbox_inches="tight", facecolor=fig.get_facecolor())
        plt.close(fig)
        return {
            "success": True,
            "message": "GIS 标准制图生成完成",
            "output_png": output_path,
            "title": title,
            "colormap": colormap,
            "vmin": float(vmin),
            "vmax": float(vmax),
            "legend_position": norm_legend_pos,
            "scalebar_position": _normalize_position(scalebar_position, "lower left"),
            "north_position": _normalize_position(north_position, "upper right"),
            "data_shape": [rows, cols],
        }
    except Exception as exc:
        return {"success": False, "message": str(exc)}