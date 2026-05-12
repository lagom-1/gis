from __future__ import annotations

import os

import matplotlib.pyplot as plt
import numpy as np
import rasterio


def run_sca(input_tif: str, output_tif: str, output_png: str) -> dict:
    try:
        if not os.path.exists(input_tif):
            return {"success": False, "message": f"输入文件不存在: {input_tif}"}

        with rasterio.open(input_tif) as src:
            if src.count < 3:
                return {"success": False, "message": "输入影像至少需要 3 个波段（Red、NIR、Brightness Temperature）"}
            red = src.read(1).astype("float32")
            nir = src.read(2).astype("float32")
            bt = src.read(3).astype("float32")
            profile = src.profile.copy()
            nodata = src.nodata
            transform = src.transform
            crs = src.crs

        # ── Nodata 过滤 ──────────────────────────────────────
        # 1) GeoTIFF 显式 nodata tag
        if nodata is not None:
            red = np.where(red == nodata, np.nan, red)
            nir = np.where(nir == nodata, np.nan, nir)
            bt = np.where(bt == nodata, np.nan, bt)

        # 2) 兜底：Landsat L2 的无效像元通常是 0，
        #    geemap 导出可能不设 nodata tag，需要额外过滤
        zero_mask = (red == 0) | (nir == 0) | (bt == 0)
        if zero_mask.any():
            red = np.where(zero_mask, np.nan, red)
            nir = np.where(zero_mask, np.nan, nir)
            bt = np.where(zero_mask, np.nan, bt)

        valid = np.isfinite(red) & np.isfinite(nir) & np.isfinite(bt)
        if not valid.any():
            return {"success": False, "message": "输入影像没有有效像元"}

        # ── 亮温转换 ────────────────────────────────────────
        bt_kelvin = bt * 0.00341802 + 149.0

        # ── NDVI ────────────────────────────────────────────
        with np.errstate(divide="ignore", invalid="ignore"):
            ndvi = (nir - red) / (nir + red)
        ndvi = np.where(valid, ndvi, np.nan)
        ndvi = np.clip(ndvi, -1.0, 1.0)

        # ── 植被覆盖度 Pv → 比辐射率 ε ──────────────────────
        ndvi_min, ndvi_max = 0.2, 0.5
        pv = ((ndvi - ndvi_min) / (ndvi_max - ndvi_min)) ** 2
        pv = np.clip(pv, 0.0, 1.0)
        emissivity = 0.986 + 0.004 * pv
        emissivity = np.where(valid & (emissivity > 0), emissivity, np.nan)

        # ── 单通道 LST 反演 ─────────────────────────────────
        lambda_ = 10.895e-6
        rho = 1.438e-2
        with np.errstate(divide="ignore", invalid="ignore"):
            lst = bt_kelvin / (1 + (lambda_ * bt_kelvin / rho) * np.log(emissivity)) - 273.15
        lst = np.where(valid, lst, np.nan).astype("float32")

        # ── 写出 GeoTIFF ────────────────────────────────────
        profile.update(dtype=rasterio.float32, count=1, nodata=np.nan)
        os.makedirs(os.path.dirname(output_tif), exist_ok=True)
        with rasterio.open(output_tif, "w", **profile) as dst:
            dst.write(lst, 1)

        # ── 预览图 ──────────────────────────────────────────
        display_min = float(np.nanpercentile(lst, 2))
        display_max = float(np.nanpercentile(lst, 98))
        plt.figure(figsize=(8, 6))
        plt.imshow(lst, cmap="coolwarm", vmin=display_min, vmax=display_max)
        plt.colorbar(label="LST (°C)")
        plt.title("Land Surface Temperature (SCA)")
        plt.axis("off")
        plt.tight_layout()
        plt.savefig(output_png, dpi=300)
        plt.close()

        return {
            "success": True,
            "message": "SCA 地表温度反演完成",
            "input_tif": input_tif,
            "output_tif": output_tif,
            "output_png": output_png,
            "lst_min": float(np.nanmin(lst)),
            "lst_max": float(np.nanmax(lst)),
            "display_min": display_min,
            "display_max": display_max,
            "crs": str(crs) if crs else None,
            "transform": list(transform) if transform else None,
            "data_shape": list(lst.shape),
        }
    except Exception as exc:
        return {"success": False, "message": str(exc)}