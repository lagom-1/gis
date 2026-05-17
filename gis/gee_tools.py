from __future__ import annotations

import glob
import json
import os
import shutil
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

import ee

from agent.gee_client import init_gee
from config import GEE_DRIVE_FOLDER, GDRIVE_SYNC_DIR


def _ensure_parent(path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)


def _save_preview_png(tif_path: str) -> str:
    """从单波段 TIF 生成同名 PNG 预览图，返回 png 路径"""
    import numpy as np
    import rasterio
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    png_path = os.path.splitext(tif_path)[0] + ".png"
    if os.path.exists(png_path):
        return png_path

    try:
        with rasterio.open(tif_path) as src:
            data = src.read(1).astype("float32")
            if src.nodata is not None:
                data = np.where(data == src.nodata, np.nan, data)
            data = np.where(data == 0, np.nan, data)

        valid = np.isfinite(data)
        if not valid.any():
            return ""

        vmin = float(np.nanpercentile(data, 2))
        vmax = float(np.nanpercentile(data, 98))
        if vmin == vmax:
            vmax = vmin + 1

        fig, ax = plt.subplots(figsize=(10, 8))
        ax.imshow(data, cmap="coolwarm", vmin=vmin, vmax=vmax)
        ax.axis("off")
        plt.colorbar(ax.images[0], ax=ax, fraction=0.046, pad=0.04)
        plt.tight_layout()
        plt.savefig(png_path, dpi=150, bbox_inches="tight")
        plt.close()
        return png_path
    except Exception:
        return ""


def _load_geojson(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _geojson_to_ee_geometry_local(geojson: Dict[str, Any]) -> ee.Geometry:
    """
    纯本地将 GeoJSON dict 转为 ee.Geometry，不发 HTTP 请求。
    支持：
      - 直接 geometry: {"type": "Polygon", "coordinates": [...]}
      - Feature:       {"type": "Feature", "geometry": {...}}
      - bbox list:     [xmin, ymin, xmax, ymax]
    """
    if hasattr(geojson, "getInfo"):
        if hasattr(geojson, "geometry") and callable(geojson.geometry):
            try:
                return geojson.geometry()
            except Exception:
                return geojson
        return geojson

    if not isinstance(geojson, dict):
        raise ValueError(f"无法识别的 region 类型: {type(geojson).__name__}")

    geo_type = geojson.get("type", "")

    if geo_type == "Feature":
        inner = geojson.get("geometry")
        if not inner:
            raise ValueError("Feature 缺少 geometry 字段")
        return _geojson_to_ee_geometry_local(inner)

    if geo_type == "FeatureCollection":
        features = geojson.get("features", [])
        if not features:
            raise ValueError("FeatureCollection 为空")
        geoms = [_geojson_to_ee_geometry_local(f) for f in features]
        if len(geoms) == 1:
            return geoms[0]
        union = geoms[0]
        for g in geoms[1:]:
            union = union.union(g)
        return union

    VALID_GEOM_TYPES = {
        "Point", "MultiPoint", "LineString", "MultiLineString",
        "Polygon", "MultiPolygon", "GeometryCollection",
    }
    if geo_type in VALID_GEOM_TYPES:
        return ee.Geometry(geojson)

    raise ValueError(f"不支持的 GeoJSON 类型: {geo_type}")


def _normalize_region(region: Any = None, region_path: Optional[str] = None):
    """
    支持三种 AOI 输入：
    1) bbox list: [xmin, ymin, xmax, ymax]
    2) GeoJSON dict (Feature / FeatureCollection / 直接 geometry)
    3) GeoJSON 文件路径
    """
    if region_path:
        if not os.path.exists(region_path):
            raise ValueError(f"region_path 不存在: {region_path}")
        region = _load_geojson(region_path)

    if region is None:
        raise ValueError("缺少 region 或 region_path")

    if hasattr(region, "getInfo"):
        geom_method = getattr(region, "geometry", None)
        if callable(geom_method):
            try:
                return geom_method()
            except Exception:
                return region
        return region

    if isinstance(region, (list, tuple)) and len(region) == 4:
        xmin, ymin, xmax, ymax = [float(x) for x in region]
        return ee.Geometry.Rectangle([xmin, ymin, xmax, ymax])

    if isinstance(region, dict):
        return _geojson_to_ee_geometry_local(region)

    raise ValueError("region 仅支持 bbox [xmin,ymin,xmax,ymax]、GeoJSON dict 或 region_path")


from ._gee_common import mask_clouds_qa as _mask_clouds_qa


def _landsat89_l2_collection(region_geom, start_date: str, end_date: str, cloud_pct: float = 15, hard_filter: bool = True, max_scenes: int | None = None, distribute_periods: int | None = None):
    """
    合并 Landsat 8/9 Collection 2 Level-2 Tier 1。

    Args:
        hard_filter: True 时硬性过滤云量 <= cloud_pct；False 时按云量排序取前 N 景
        max_scenes: 场景上限，None 时 hard_filter=True 不限、hard_filter=False 取 20
        distribute_periods: 若指定，将日期范围等分为 N 段，每段取云量最少的 1 景，
            确保所选场景在时间上均匀分布（适合月度合成）
    """
    col8 = (
        ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
        .filterBounds(region_geom)
        .filterDate(start_date, end_date)
    )
    col9 = (
        ee.ImageCollection("LANDSAT/LC09/C02/T1_L2")
        .filterBounds(region_geom)
        .filterDate(start_date, end_date)
    )
    merged = col8.merge(col9)

    if distribute_periods and distribute_periods > 0:
        # 月份内均匀分布选景：等分时间段，每段取云量最少的 1 景
        from datetime import datetime, timedelta
        sd = datetime.strptime(start_date, "%Y-%m-%d")
        ed = datetime.strptime(end_date, "%Y-%m-%d")
        total_days = (ed - sd).days + 1
        period_days = max(total_days // distribute_periods, 1)

        selected = []
        for i in range(distribute_periods):
            p_start = sd + timedelta(days=i * period_days)
            p_end = p_start + timedelta(days=period_days - 1)
            if i == distribute_periods - 1:
                p_end = ed  # 最后一段包含末尾
            sub_col = merged.filterDate(p_start.strftime("%Y-%m-%d"), (p_end + timedelta(days=1)).strftime("%Y-%m-%d"))
            sub_col = sub_col.filter(ee.Filter.lte("CLOUD_COVER", cloud_pct))
            # 每段取云量最少的 1 景
            best = sub_col.sort("CLOUD_COVER").limit(1)
            selected.append(best)

        # 合并各段选出的影像
        result = selected[0]
        for c in selected[1:]:
            result = result.merge(c)
        return result

    if hard_filter:
        merged = merged.filter(ee.Filter.lte("CLOUD_COVER", cloud_pct))
    else:
        limit = max_scenes if max_scenes is not None else 20
        merged = merged.sort("CLOUD_COVER").limit(limit)

    return merged


def _reduce_collection(col, reducer: str = "median", mask_clouds: bool = True) -> ee.Image:
    if mask_clouds:
        col = col.map(__mask_clouds_qa)

    reducer = (reducer or "median").lower()
    if reducer == "mean":
        return col.mean()
    if reducer == "mosaic":
        return col.mosaic()
    if reducer == "first":
        return ee.Image(col.first())
    return col.median()


def _estimate_download_size(geom, scale: int = 30) -> Optional[Dict[str, Any]]:
    """粗略估算下载区域大小"""
    try:
        coords = geom.getInfo().get("coordinates", [[]])
        if not coords or not coords[0]:
            return None

        lons = [c[0] for c in coords[0]]
        lats = [c[1] for c in coords[0]]
        lon_range = max(lons) - min(lons)
        lat_range = max(lats) - min(lats)

        meters_per_deg = 111320.0
        width_px = int(lon_range * meters_per_deg / scale)
        height_px = int(lat_range * meters_per_deg / scale)
        total_px = width_px * height_px

        size_mb = total_px * 12 / (1024 * 1024)

        return {
            "width": width_px,
            "height": height_px,
            "total_pixels": total_px,
            "size_mb": round(size_mb, 1),
        }
    except Exception:
        return None


def _download_direct(
    export_img: ee.Image,
    geom,
    scale: int,
    output_tif: str,
    timeout_sec: int = 300,
) -> Dict[str, Any]:
    """先尝试 GEE 直接下载（适合小区域）。太大则回退 Drive。"""
    try:
        size_info = _estimate_download_size(geom, scale)
        if size_info and size_info["size_mb"] > 45:
            return {
                "success": False,
                "too_large": True,
                "message": f"区域太大（约 {size_info['size_mb']}MB），直接下载不适用，回退到 Drive 导出",
                "size_info": size_info,
            }

        print(f"[GEE] 尝试直接下载（scale={scale}m）...")
        url = export_img.getDownloadURL({
            "scale": scale,
            "region": geom,
            "format": "GeoTIFF",
            "crs": "EPSG:4326",
        })

        _ensure_parent(output_tif)
        tmp_path = output_tif + ".downloading"

        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            content_length = resp.headers.get("Content-Length")
            total_bytes = int(content_length) if content_length else None
            downloaded = 0
            last_pct = -1

            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_bytes:
                        pct = int(downloaded * 100 / total_bytes)
                        if pct != last_pct:
                            last_pct = pct
                            bar = "█" * (pct // 5) + "░" * (20 - pct // 5)
                            print(f"\r[GEE] 下载中 |{bar}| {pct}%", end="", flush=True)

            if total_bytes:
                print(f"\r[GEE] 下载中 |{'█' * 20}| 100%", flush=True)

        os.replace(tmp_path, output_tif)
        file_size = os.path.getsize(output_tif) / (1024 * 1024)
        print(f"[GEE] 直接下载完成: {output_tif} ({file_size:.1f}MB)")

        return {
            "success": True,
            "message": f"GEE 直接下载完成（{file_size:.1f}MB）",
            "source": "direct_download",
            "file_size_mb": round(file_size, 1),
        }

    except Exception as e:
        err = str(e)
        tmp_path = output_tif + ".downloading"
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

        too_large = any(k in err.lower() for k in ["too large", "memory", "limit", "timeout", "50331648"])
        return {
            "success": False,
            "too_large": too_large,
            "message": f"直接下载失败: {err}",
        }


def _wait_drive_file(
    export_img: ee.Image,
    task_name: str,
    folder: str,
    scale: int,
    geom,
    sync_dir: str,
    timeout_sec: int = 900,
) -> Optional[str]:
    """导出到 Google Drive，等待完成，从本地同步目录获取文件路径。"""
    task = ee.batch.Export.image.toDrive(
        image=export_img,
        description=task_name,
        folder=folder,
        fileNamePrefix=task_name,
        scale=scale,
        region=geom,
        crs="EPSG:4326",
        maxPixels=1e13,
        fileFormat="GeoTIFF",
        formatOptions={"noData": 0},
    )
    task.start()
    task_id = task.id
    print(f"[GEE] Drive 导出任务已启动: {task_name} (id={task_id})")

    task_result = _wait_for_drive_task(task_id, timeout_sec=timeout_sec)
    if not task_result.get("success"):
        print(f"[GEE] Drive 导出失败: {task_result.get('message')}")
        return None

    print(f"[GEE] Drive 导出完成，正在本地同步目录查找 {task_name}*.tif...")
    elapsed = 0
    while elapsed < timeout_sec:
        local_path = _find_drive_file(task_name, folder, local_drive_path=sync_dir)
        if local_path:
            print(f"[GEE] 在本地同步目录找到: {local_path}")
            return local_path
        time.sleep(5)
        elapsed += 5

    print(f"[GEE] 在本地同步目录未找到 {task_name}*.tif")
    return None


def _export_to_drive(export_img: ee.Image, task_name: str, folder: str, scale: int, geom) -> ee.batch.Task:
    task = ee.batch.Export.image.toDrive(
        image=export_img,
        description=task_name,
        folder=folder,
        fileNamePrefix=task_name,
        scale=scale,
        region=geom,
        crs="EPSG:4326",
        maxPixels=1e13,
        fileFormat="GeoTIFF",
        formatOptions={"noData": 0},
    )
    task.start()
    return task


def _wait_for_drive_task(task_id: str, timeout_sec: int = 900, poll_interval: int = 15) -> Dict[str, Any]:
    """轮询 GEE task 状态直到完成或超时。"""
    start = time.time()
    while True:
        status = ee.data.getTaskStatus(task_id)
        state = status[0].get("state", "UNKNOWN")

        if state == "COMPLETED":
            return {"success": True, "state": state, "task_id": task_id}

        if state in ("FAILED", "CANCELLED", "CANCELLING"):
            error_msg = status[0].get("error_message", "")
            return {
                "success": False,
                "state": state,
                "task_id": task_id,
                "message": f"GEE 导出任务 {state}: {error_msg}",
            }

        elapsed = time.time() - start
        if elapsed > timeout_sec:
            return {
                "success": False,
                "state": state,
                "task_id": task_id,
                "message": f"GEE 导出超时（已等待 {int(elapsed)}s），任务仍在 {state} 状态",
            }

        time.sleep(poll_interval)


def _candidate_sync_dirs(folder: str, local_drive_path: Optional[str] = None):
    """生成本地同步目录候选路径。"""
    candidates = []

    def add_dir(p: str):
        if p and p not in candidates:
            candidates.append(p)

    if local_drive_path:
        root = os.path.normpath(os.path.expanduser(local_drive_path))
        if folder and os.path.basename(root).lower() == folder.lower():
            add_dir(root)
        else:
            if folder:
                add_dir(os.path.join(root, folder))
            add_dir(root)

    if GDRIVE_SYNC_DIR:
        cfg = os.path.normpath(str(GDRIVE_SYNC_DIR))
        if folder and os.path.basename(cfg).lower() == folder.lower():
            add_dir(cfg)
        else:
            if folder:
                add_dir(os.path.join(cfg, folder))
            add_dir(cfg)

    home = Path.home()
    common = [
        str(home / "Google Drive" / folder),
        str(home / "GoogleDrive" / folder),
        str(home / "我的云端硬盘" / folder),
        str(home / "Google 我的云端硬盘" / folder),
        str(home / "Google 云端硬盘" / folder),
        r"G:\我的云端硬盘" + (f"\\{folder}" if folder else ""),
        r"G:\My Drive" + (f"\\{folder}" if folder else ""),
    ]
    for p in common:
        add_dir(os.path.normpath(p))

    return candidates


def _find_drive_file(task_name: str, folder: str, local_drive_path: Optional[str] = None) -> Optional[str]:
    """在本地 Google Drive 同步目录中查找导出的文件。"""
    search_dirs = _candidate_sync_dirs(folder, local_drive_path=local_drive_path)

    for candidate in search_dirs:
        if os.path.isdir(candidate):
            pattern1 = os.path.join(candidate, f"{task_name}*.tif")
            pattern2 = os.path.join(candidate, f"{task_name}*.tiff")
            matches = glob.glob(pattern1) + glob.glob(pattern2)
            if matches:
                matches.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                return matches[0]
    return None


def _drive_download(
    task_id: str,
    task_name: str,
    folder: str,
    output_tif: str,
    timeout_sec: int = 900,
    local_drive_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Drive 下载流程：等待导出完成 → 从本地同步目录查找文件。"""
    print(f"[GEE] 等待 GEE 导出任务完成（最长 {timeout_sec}s）...")
    task_result = _wait_for_drive_task(task_id, timeout_sec=timeout_sec)
    if not task_result.get("success"):
        return task_result

    print("[GEE] 导出完成，正在从本地 Drive 同步目录获取文件...")

    local_path = None
    start = time.time()
    while time.time() - start <= timeout_sec:
        local_path = _find_drive_file(task_name, folder, local_drive_path=local_drive_path)
        if local_path:
            break
        time.sleep(5)

    if local_path:
        _ensure_parent(output_tif)
        shutil.copy2(local_path, output_tif)
        return {
            "success": True,
            "message": f"从本地 Drive 同步目录复制: {local_path}",
            "source": "local_sync",
        }

    return {
        "success": False,
        "message": f"文件已导出到 Google Drive，但在本地同步目录未找到（请确认 {local_drive_path or str(GDRIVE_SYNC_DIR)} 已同步）",
    }


def gee_init(project_id: Optional[str] = None, force_auth: bool = False) -> Dict[str, Any]:
    return init_gee(project_id=project_id, force_auth=force_auth)


def gee_download_landsat_sca(
    start_date: str,
    end_date: str,
    output_tif: str,
    region: Any = None,
    region_path: Optional[str] = None,
    scale: int = 30,
    reducer: str = "median",
    cloud_pct: float = 30,
    mask_clouds: bool = True,
    project_id: Optional[str] = None,
    drive_folder: str = "",
    local_drive_path: Optional[str] = None,
    download_timeout: int = 900,
) -> Dict[str, Any]:
    """
    从 GEE 下载适合本地 SCA 单通道反演的数据。

    流程：
    1) 先尝试直接 HTTP 下载
    2) 文件太大或直接下载失败时，回退到 Google Drive 导出
    3) 从本地同步目录复制 tif 到 output_tif

    导出三波段顺序固定为：
    1) red    -> SR_B4
    2) nir    -> SR_B5
    3) bt_raw -> ST_B10
    """
    init_result = init_gee(project_id=project_id)
    if not init_result.get("success"):
        return init_result

    try:
        try:
            geom = _normalize_region(region=region, region_path=region_path)
        except Exception as e:
            return {
                "success": False,
                "message": f"AOI 解析失败: {e}",
                "region_type": type(region).__name__ if region is not None else None,
                "region_path": region_path,
            }

        _ensure_parent(output_tif)

        folder_name = (drive_folder or GEE_DRIVE_FOLDER).strip() or GEE_DRIVE_FOLDER
        sync_dir = local_drive_path or str(GDRIVE_SYNC_DIR)

        cloud_levels = sorted(set([float(cloud_pct), 40, 60, 80, 100]))
        col = None
        count = 0
        used_cloud_pct = float(cloud_pct)
        for level in cloud_levels:
            if level < used_cloud_pct:
                continue
            col = _landsat89_l2_collection(
                region_geom=geom,
                start_date=start_date,
                end_date=end_date,
                cloud_pct=float(level),
            )
            count = col.size().getInfo()
            if count > 0:
                used_cloud_pct = level
                break

        if count == 0:
            return {
                "success": False,
                "message": f"未找到 {start_date}~{end_date} 内的 Landsat 8/9 影像。请尝试扩大日期范围或检查研究区。",
            }

        if used_cloud_pct > float(cloud_pct):
            print(f"[GEE] 注意：原始云量阈值 {cloud_pct}% 无可用影像，已放宽至 {used_cloud_pct}%（找到 {count} 景）")

        image = _reduce_collection(col, reducer=reducer, mask_clouds=mask_clouds).clip(geom)

        # ── 填补云掩膜/边缘空洞 ──────────────────────────────
        # QA_PIXEL 云掩膜后常有散云造成的几像素空洞，以及边缘覆盖不足的 NoData
        # 用 focal_mean(radius=3, ~210m) 填补，足以覆盖多数碎云间隙
        filled_bands = []
        for band_name in ["SR_B4", "SR_B5", "ST_B10"]:
            band = image.select(band_name)
            filled = band.focal_mean(radius=3, kernelType="square", units="pixels")
            band = band.unmask(filled)
            filled_bands.append(band)

        image = ee.Image.cat(filled_bands).clip(geom)

        export_img = image.select(
            [0, 1, 2],
            ["red", "nir", "bt_raw"],
        )

        import time as _time
        _ts = int(_time.time()) % 100000
        task_name = f"gee_sca_{start_date.replace('-', '')}_{end_date.replace('-', '')}_{_ts}"
        task_id = None
        download_source = "unknown"

        # 1) 先尝试直接下载
        direct_result = _download_direct(
            export_img=export_img,
            geom=geom,
            scale=int(scale),
            output_tif=output_tif,
            timeout_sec=min(int(download_timeout), 300),
        )

        if direct_result.get("success"):
            download_source = "direct_download"
        else:
            print(f"[GEE] {direct_result.get('message', '直接下载失败，回退 Drive')}")

            # 2) 回退到 Drive 导出
            print(f"[GEE] 启动 Drive 导出任务: {task_name} -> {folder_name}")
            task = _export_to_drive(
                export_img=export_img,
                task_name=task_name,
                folder=folder_name,
                scale=int(scale),
                geom=geom,
            )
            task_id = task.id

            download_result = _drive_download(
                task_id=task_id,
                task_name=task_name,
                folder=folder_name,
                output_tif=output_tif,
                timeout_sec=int(download_timeout),
                local_drive_path=sync_dir,
            )

            if not download_result.get("success"):
                return {
                    "success": False,
                    "message": download_result.get("message", "Drive 导出后获取文件失败"),
                    "task_id": task_id,
                    "task_name": task_name,
                    "drive_folder": folder_name,
                    "sync_dir": sync_dir,
                    "output_tif": output_tif,
                    "hint": "可以稍后从本地同步目录手动找到 tif，再用 set_current_dataset 设置路径并继续 run_lst",
                }

            download_source = download_result.get("source", "drive")

        if not os.path.exists(output_tif) or os.path.getsize(output_tif) <= 1024:
            return {
                "success": False,
                "message": "下载得到的 tif 无效或文件过小",
            }

        # 同时生成 PNG 预览图
        preview_png = _save_preview_png(output_tif)

        return {
            "success": True,
            "message": f"GEE Landsat SCA 数据下载完成: {Path(output_tif).name}（{count} 景影像合成）",
            "output_tif": output_tif,
            "output_png": preview_png or None,
            "path": output_tif,
            "selected_path": output_tif,
            "bands": ["red", "nir", "bt_raw"],
            "start_date": start_date,
            "end_date": end_date,
            "scale": int(scale),
            "cloud_pct": used_cloud_pct,
            "reducer": reducer,
            "mask_clouds": bool(mask_clouds),
            "image_count": count,
            "task_id": task_id,
            "download_source": download_source,
            "drive_folder": folder_name,
            "sync_dir": sync_dir,
            "metadata": {
                "path": output_tif,
                "name": os.path.basename(output_tif),
                "product_type": "Landsat 热红外产品",
                "ready_for_sca": True,
                "ready_for_thematic_map": False,
                "recommended_band_mapping": {
                    "red": 1,
                    "nir": 2,
                    "brightness_temperature": 3,
                },
                "gee_source": "LANDSAT/LC08+C09 C02 T1 L2",
            },
        }

    except Exception as e:
        return {"success": False, "message": f"GEE Landsat 下载失败: {e}"}


def gee_download_monthly_lst(
    start_date: str,
    end_date: str,
    output_tif: str,
    region: Any = None,
    region_path: Optional[str] = None,
    scale: int = 30,
    project_id: Optional[str] = None,
    drive_folder: str = "",
    local_drive_path: Optional[str] = None,
    download_timeout: int = 900,
) -> Dict[str, Any]:
    """
    月度 LST 智能合成（分级降级策略）。

    自动选择最优方案：
      Level 1: 云<15%, ≥3景 → 分布均匀, 逐景SCA反演 → 均值  质量 A+
      Level 2: 云<20%, ≥2景 → 分布均匀, 逐景SCA反演 → 均值  质量 A
      Level 3: 云<25%, ≥2景 → 逐景SCA反演 → 中值             质量 B+
      Level 4: 云<40%, ≥1景 → 单景SCA反演                    质量 B-
      Level 5: 全部可用     → 逐景SCA反演 → 中值             质量 C

    输出：单波段 LST GeoTIFF（°C）
    """
    from gis.gee_timelapse import _compute_lst_gee

    init_result = init_gee(project_id=project_id)
    if not init_result.get("success"):
        return init_result

    try:
        try:
            geom = _normalize_region(region=region, region_path=region_path)
        except Exception as e:
            return {
                "success": False,
                "message": f"AOI 解析失败: {e}",
                "region_type": type(region).__name__ if region is not None else None,
                "region_path": region_path,
            }

        _ensure_parent(output_tif)

        folder_name = (drive_folder or GEE_DRIVE_FOLDER).strip() or GEE_DRIVE_FOLDER
        sync_dir = local_drive_path or str(GDRIVE_SYNC_DIR)

        # ── 0. 获取整月所有 L8+L9 场景 ─────────────────────
        col8 = (
            ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
            .filterBounds(geom)
            .filterDate(start_date, end_date)
        )
        col9 = (
            ee.ImageCollection("LANDSAT/LC09/C02/T1_L2")
            .filterBounds(geom)
            .filterDate(start_date, end_date)
        )
        all_scenes = col8.merge(col9)
        total_count = all_scenes.size().getInfo()

        if total_count == 0:
            return {
                "success": False,
                "message": f"未找到 {start_date}~{end_date} 内的任何 Landsat 8/9 影像。",
            }

        # ── 1. 分级降级选景 ────────────────────────────────
        # 每级：(云量阈值, 最小场景数, 是否均匀分布, 合成方法, 质量等级)
        levels = [
            (15, 3, True,  "mean",    "A+"),   # Level 1: 理想
            (20, 2, True,  "mean",    "A"),     # Level 2: 次优
            (25, 2, False, "median",  "B+"),    # Level 3: 降级
            (40, 1, False, "single",  "B-"),    # Level 4: 单景
            (100, 1, False, "median", "C"),      # Level 5: 全部
        ]

        selected_col = None
        selected_level = None
        selected_quality = None
        selected_method = None
        selected_count = 0

        for cloud_thresh, min_scenes, distributed, method, quality in levels:
            filtered = all_scenes.filter(ee.Filter.lte("CLOUD_COVER", cloud_thresh))
            cnt = filtered.size().getInfo()

            if cnt < min_scenes:
                continue

            if distributed and cnt >= 3:
                # 均匀分布选景：等分月份，每段取云量最少的 1 景
                from datetime import datetime, timedelta
                sd = datetime.strptime(start_date, "%Y-%m-%d")
                ed = datetime.strptime(end_date, "%Y-%m-%d")
                total_days = (ed - sd).days + 1
                period_days = max(total_days // 3, 1)

                selected = []
                for i in range(3):
                    p_start = sd + timedelta(days=i * period_days)
                    p_end = p_start + timedelta(days=period_days - 1)
                    if i == 2:
                        p_end = ed
                    sub = filtered.filterDate(
                        p_start.strftime("%Y-%m-%d"),
                        (p_end + timedelta(days=1)).strftime("%Y-%m-%d"),
                    )
                    best = sub.sort("CLOUD_COVER").limit(1)
                    selected.append(best)

                merged = selected[0]
                for c in selected[1:]:
                    merged = merged.merge(c)
                actual_cnt = merged.size().getInfo()

                if actual_cnt >= min_scenes:
                    selected_col = merged
                    selected_count = actual_cnt
                else:
                    # 均匀分布不够，回退到按云量取前 N
                    selected_col = filtered.sort("CLOUD_COVER").limit(min(cnt, 3))
                    selected_count = min(cnt, 3)
            else:
                # 按云量排序取前 N 景
                take = min(cnt, 3) if method != "single" else 1
                selected_col = filtered.sort("CLOUD_COVER").limit(take)
                selected_count = take

            selected_level = levels.index((cloud_thresh, min_scenes, distributed, method, quality)) + 1
            selected_quality = quality
            selected_method = method
            break

        if selected_col is None:
            return {
                "success": False,
                "message": f"{start_date}~{end_date} 内无可用 Landsat 8/9 影像。",
            }

        # ── 2. 逐景 QA_PIXEL 去云 + SCA 单通道 LST 反演 ───
        col_masked = selected_col.map(__mask_clouds_qa)
        lst_col = col_masked.map(_compute_lst_gee)

        # ── 3. 合成 ───────────────────────────────────────
        if selected_method == "mean":
            monthly_lst = lst_col.mean().clip(geom)
            method_desc = f"逐景SCA反演→均值（{selected_count}景）"
        elif selected_method == "single":
            monthly_lst = ee.Image(lst_col.first()).clip(geom)
            method_desc = "单景SCA反演"
        else:  # median
            monthly_lst = lst_col.median().clip(geom)
            method_desc = f"逐景SCA反演→中值（{selected_count}景）"

        # ── 4. 填补边缘空洞 ────────────────────────────────
        filled = monthly_lst.focal_mean(radius=3, kernelType="square", units="pixels")
        monthly_lst = monthly_lst.unmask(filled).clip(geom)

        export_img = monthly_lst.rename("LST")

        import time as _time
        _ts = int(_time.time()) % 100000
        task_name = f"gee_monthly_lst_{start_date.replace('-', '')}_{end_date.replace('-', '')}_{_ts}"
        task_id = None
        download_source = "unknown"

        # ── 5. 下载 ────────────────────────────────────────
        direct_result = _download_direct(
            export_img=export_img,
            geom=geom,
            scale=int(scale),
            output_tif=output_tif,
            timeout_sec=min(int(download_timeout), 300),
        )

        result_base = {
            "output_tif": output_tif,
            "path": output_tif,
            "selected_path": output_tif,
            "bands": ["LST"],
            "start_date": start_date,
            "end_date": end_date,
            "scale": int(scale),
            "scene_count": selected_count,
            "total_scenes_in_month": total_count,
            "quality": selected_quality,
            "metadata": {
                "product_type": f"月度 LST 合成 — {method_desc}",
                "unit": "°C",
                "gee_source": "LANDSAT/LC08+C09 C02 T1 L2",
                "method": method_desc,
                "quality_grade": selected_quality,
                "level": selected_level,
                "total_scenes_available": total_count,
            },
        }

        if direct_result.get("success"):
            preview_png = _save_preview_png(output_tif)
            return {
                "success": True,
                "message": f"月度 LST 合成完成 — {method_desc}，质量等级 {selected_quality}（当月共 {total_count} 景，选用 {selected_count} 景）",
                "download_source": "direct_download",
                "output_png": preview_png or None,
                **result_base,
            }

        # 直接下载失败，回退到 Google Drive
        local_path = _wait_drive_file(
            export_img=export_img,
            task_name=task_name,
            folder=folder_name,
            scale=int(scale),
            geom=geom,
            sync_dir=sync_dir,
            timeout_sec=int(download_timeout),
        )
        if local_path:
            _ensure_parent(output_tif)
            shutil.copy2(local_path, output_tif)
            preview_png = _save_preview_png(output_tif)
            return {
                "success": True,
                "message": f"月度 LST 合成完成 — {method_desc}，质量等级 {selected_quality}（当月共 {total_count} 景，选用 {selected_count} 景）",
                "download_source": "drive",
                "output_png": preview_png or None,
                **result_base,
            }

        return {
            "success": False,
            "message": f"月度 LST 已导出到 Google Drive，但本地同步目录未找到文件",
        }

    except Exception as e:
        return {"success": False, "message": f"月度 LST 合成失败: {e}"}


def gee_download_yearly_lst(
    year: int,
    output_dir: str,
    region: Any = None,
    region_path: Optional[str] = None,
    region_name: str = "",
    months: list = None,
    scale: int = 30,
    project_id: Optional[str] = None,
    drive_folder: str = "",
    local_drive_path: Optional[str] = None,
    download_timeout: int = 900,
) -> Dict[str, Any]:
    """
    批量下载全年 12 个月的月度 LST 合成结果。

    对每个月调用 gee_download_monthly_lst 的核心逻辑（分级降级选景 + 逐景 SCA 反演），
    输出 12 个单波段 LST GeoTIFF（°C），文件名格式：{region_name}_{year}_{month:02d}_lst.tif
    """
    from gis.gee_timelapse import _compute_lst_gee
    import calendar

    init_result = init_gee(project_id=project_id)
    if not init_result.get("success"):
        return init_result

    try:
        try:
            geom = _normalize_region(region=region, region_path=region_path)
        except Exception as e:
            return {
                "success": False,
                "message": f"AOI 解析失败: {e}",
            }

        os.makedirs(output_dir, exist_ok=True)

        folder_name = (drive_folder or GEE_DRIVE_FOLDER).strip() or GEE_DRIVE_FOLDER
        sync_dir = local_drive_path or str(GDRIVE_SYNC_DIR)

        # 分级降级策略
        levels = [
            (15, 3, True,  "mean",   "A+"),
            (20, 2, True,  "mean",   "A"),
            (25, 2, False, "median", "B+"),
            (40, 1, False, "single", "B-"),
            (100, 1, False, "median", "C"),
        ]

        results = []
        failed_months = []

        target_months = months if months else list(range(1, 13))
        for month in target_months:
            last_day = calendar.monthrange(year, month)[1]
            start_date = f"{year}-{month:02d}-01"
            end_date = f"{year}-{month:02d}-{last_day:02d}"
            output_tif = os.path.join(output_dir, f"{region_name + '_' if region_name else ''}{year}_{month:02d}_lst.tif")

            try:
                # 获取整月所有场景
                col8 = (
                    ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                    .filterBounds(geom)
                    .filterDate(start_date, end_date)
                )
                col9 = (
                    ee.ImageCollection("LANDSAT/LC09/C02/T1_L2")
                    .filterBounds(geom)
                    .filterDate(start_date, end_date)
                )
                all_scenes = col8.merge(col9)
                total_count = all_scenes.size().getInfo()

                if total_count == 0:
                    failed_months.append({"month": month, "reason": "无可用影像"})
                    continue

                # 分级选景
                selected_col = None
                selected_level = None
                selected_quality = None
                selected_method = None
                selected_count = 0

                for cloud_thresh, min_scenes, distributed, method, quality in levels:
                    filtered = all_scenes.filter(ee.Filter.lte("CLOUD_COVER", cloud_thresh))
                    cnt = filtered.size().getInfo()

                    if cnt < min_scenes:
                        continue

                    if distributed and cnt >= 3:
                        from datetime import datetime, timedelta
                        sd = datetime.strptime(start_date, "%Y-%m-%d")
                        ed = datetime.strptime(end_date, "%Y-%m-%d")
                        total_days = (ed - sd).days + 1
                        period_days = max(total_days // 3, 1)

                        selected = []
                        for i in range(3):
                            p_start = sd + timedelta(days=i * period_days)
                            p_end = p_start + timedelta(days=period_days - 1)
                            if i == 2:
                                p_end = ed
                            sub = filtered.filterDate(
                                p_start.strftime("%Y-%m-%d"),
                                (p_end + timedelta(days=1)).strftime("%Y-%m-%d"),
                            )
                            best = sub.sort("CLOUD_COVER").limit(1)
                            selected.append(best)

                        merged = selected[0]
                        for c in selected[1:]:
                            merged = merged.merge(c)
                        actual_cnt = merged.size().getInfo()

                        if actual_cnt >= min_scenes:
                            selected_col = merged
                            selected_count = actual_cnt
                        else:
                            selected_col = filtered.sort("CLOUD_COVER").limit(min(cnt, 3))
                            selected_count = min(cnt, 3)
                    else:
                        take = min(cnt, 3) if method != "single" else 1
                        selected_col = filtered.sort("CLOUD_COVER").limit(take)
                        selected_count = take

                    selected_level = levels.index((cloud_thresh, min_scenes, distributed, method, quality)) + 1
                    selected_quality = quality
                    selected_method = method
                    break

                if selected_col is None:
                    failed_months.append({"month": month, "reason": "无满足条件的影像"})
                    continue

                # 逐景去云 + SCA 反演 + 合成
                col_masked = selected_col.map(__mask_clouds_qa)
                lst_col = col_masked.map(_compute_lst_gee)

                if selected_method == "mean":
                    monthly_lst = lst_col.mean().clip(geom)
                elif selected_method == "single":
                    monthly_lst = ee.Image(lst_col.first()).clip(geom)
                else:
                    monthly_lst = lst_col.median().clip(geom)

                filled = monthly_lst.focal_mean(radius=3, kernelType="square", units="pixels")
                monthly_lst = monthly_lst.unmask(filled).clip(geom)
                export_img = monthly_lst.rename("LST")

                # 下载
                _ensure_parent(output_tif)
                direct_result = _download_direct(
                    export_img=export_img,
                    geom=geom,
                    scale=int(scale),
                    output_tif=output_tif,
                    timeout_sec=min(int(download_timeout), 300),
                )

                if direct_result.get("success"):
                    method_desc = {"mean": "均值", "median": "中值", "single": "单景"}[selected_method]
                    results.append({
                        "month": month,
                        "output_tif": output_tif,
                        "scene_count": selected_count,
                        "total_scenes": total_count,
                        "quality": selected_quality,
                        "method": f"{selected_count}景{method_desc}",
                    })
                else:
                    # 回退到 Google Drive 导出
                    print(f"[GEE] {start_date}~{end_date} 直接下载失败，回退 Drive: {direct_result.get('message', '')}")
                    import time as _time
                    _ts = int(_time.time()) % 100000
                    drive_task_name = f"gee_yearly_lst_{year}_{month:02d}_{_ts}"
                    local_path = _wait_drive_file(
                        export_img=export_img,
                        task_name=drive_task_name,
                        folder=folder_name,
                        scale=int(scale),
                        geom=geom,
                        sync_dir=sync_dir,
                        timeout_sec=int(download_timeout),
                    )
                    if local_path:
                        shutil.copy2(local_path, output_tif)
                        method_desc = {"mean": "均值", "median": "中值", "single": "单景"}[selected_method]
                        results.append({
                            "month": month,
                            "output_tif": output_tif,
                            "scene_count": selected_count,
                            "total_scenes": total_count,
                            "quality": selected_quality,
                            "method": f"{selected_count}景{method_desc}",
                        })
                    else:
                        failed_months.append({"month": month, "reason": "下载失败（直接+Drive均失败）"})

            except Exception as e:
                failed_months.append({"month": month, "reason": str(e)})

        success_count = len(results)
        if success_count == 0:
            return {
                "success": False,
                "message": f"{year}年 {len(target_months)} 个月均无可用数据",
                "failed_months": failed_months,
            }

        # 质量统计
        quality_counts = {}
        for r in results:
            q = r["quality"]
            quality_counts[q] = quality_counts.get(q, 0) + 1

        return {
            "success": True,
            "message": f"{year}年 LST 批量反演完成：{success_count}/{len(target_months)} 个月成功",
            "output_dir": output_dir,
            "year": year,
            "results": results,
            "failed_months": failed_months,
            "success_count": success_count,
            "quality_summary": quality_counts,
        }

    except Exception as e:
        return {"success": False, "message": f"年度 LST 批量反演失败: {e}"}


def gee_download_multi_year_lst(
    start_year: int,
    end_year: int,
    month: int,
    output_dir: str,
    region: Any = None,
    region_path: Optional[str] = None,
    region_name: str = "",
    scale: int = 30,
    project_id: Optional[str] = None,
    drive_folder: str = "",
    local_drive_path: Optional[str] = None,
    download_timeout: int = 900,
) -> Dict[str, Any]:
    """
    跨多年单月 LST 批量反演。

    对 start_year~end_year 每一年的指定月份，执行分级降级选景 + 逐景 SCA 反演。
    输出 N 个单波段 LST GeoTIFF（°C），文件名格式：{region_name}_{year}_{month:02d}_lst.tif

    典型用法：用户说"2020-2025年每年8月的地表温度"
    """
    from gis.gee_timelapse import _compute_lst_gee
    import calendar

    if not (1 <= month <= 12):
        return {"success": False, "message": f"月份无效：{month}，必须在 1~12 之间"}

    init_result = init_gee(project_id=project_id)
    if not init_result.get("success"):
        return init_result

    try:
        try:
            geom = _normalize_region(region=region, region_path=region_path)
        except Exception as e:
            return {"success": False, "message": f"AOI 解析失败: {e}"}

        os.makedirs(output_dir, exist_ok=True)

        folder_name = (drive_folder or GEE_DRIVE_FOLDER).strip() or GEE_DRIVE_FOLDER
        sync_dir = local_drive_path or str(GDRIVE_SYNC_DIR)

        levels = [
            (15, 3, True,  "mean",   "A+"),
            (20, 2, True,  "mean",   "A"),
            (25, 2, False, "median", "B+"),
            (40, 1, False, "single", "B-"),
            (100, 1, False, "median", "C"),
        ]

        results = []
        failed_years = []

        for year in range(start_year, end_year + 1):
            last_day = calendar.monthrange(year, month)[1]
            start_date = f"{year}-{month:02d}-01"
            end_date = f"{year}-{month:02d}-{last_day:02d}"
            output_tif = os.path.join(output_dir, f"{region_name + '_' if region_name else ''}{year}_{month:02d}_lst.tif")

            try:
                col8 = (
                    ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
                    .filterBounds(geom)
                    .filterDate(start_date, end_date)
                )
                col9 = (
                    ee.ImageCollection("LANDSAT/LC09/C02/T1_L2")
                    .filterBounds(geom)
                    .filterDate(start_date, end_date)
                )
                # L9 2021年底才发射，早期年份无数据是正常的
                all_scenes = col8.merge(col9)
                total_count = all_scenes.size().getInfo()

                if total_count == 0:
                    failed_years.append({"year": year, "reason": "无可用影像"})
                    continue

                # 分级选景
                selected_col = None
                selected_quality = None
                selected_method = None
                selected_count = 0

                for cloud_thresh, min_scenes, distributed, method, quality in levels:
                    filtered = all_scenes.filter(ee.Filter.lte("CLOUD_COVER", cloud_thresh))
                    cnt = filtered.size().getInfo()

                    if cnt < min_scenes:
                        continue

                    if distributed and cnt >= 3:
                        from datetime import datetime, timedelta
                        sd = datetime.strptime(start_date, "%Y-%m-%d")
                        ed = datetime.strptime(end_date, "%Y-%m-%d")
                        total_days = (ed - sd).days + 1
                        period_days = max(total_days // 3, 1)

                        selected = []
                        for i in range(3):
                            p_start = sd + timedelta(days=i * period_days)
                            p_end = p_start + timedelta(days=period_days - 1)
                            if i == 2:
                                p_end = ed
                            sub = filtered.filterDate(
                                p_start.strftime("%Y-%m-%d"),
                                (p_end + timedelta(days=1)).strftime("%Y-%m-%d"),
                            )
                            best = sub.sort("CLOUD_COVER").limit(1)
                            selected.append(best)

                        merged = selected[0]
                        for c in selected[1:]:
                            merged = merged.merge(c)
                        actual_cnt = merged.size().getInfo()

                        if actual_cnt >= min_scenes:
                            selected_col = merged
                            selected_count = actual_cnt
                        else:
                            selected_col = filtered.sort("CLOUD_COVER").limit(min(cnt, 3))
                            selected_count = min(cnt, 3)
                    else:
                        take = min(cnt, 3) if method != "single" else 1
                        selected_col = filtered.sort("CLOUD_COVER").limit(take)
                        selected_count = take

                    selected_quality = quality
                    selected_method = method
                    break

                if selected_col is None:
                    failed_years.append({"year": year, "reason": "无满足条件的影像"})
                    continue

                col_masked = selected_col.map(__mask_clouds_qa)
                lst_col = col_masked.map(_compute_lst_gee)

                if selected_method == "mean":
                    monthly_lst = lst_col.mean().clip(geom)
                elif selected_method == "single":
                    monthly_lst = ee.Image(lst_col.first()).clip(geom)
                else:
                    monthly_lst = lst_col.median().clip(geom)

                filled = monthly_lst.focal_mean(radius=3, kernelType="square", units="pixels")
                monthly_lst = monthly_lst.unmask(filled).clip(geom)
                export_img = monthly_lst.rename("LST")

                _ensure_parent(output_tif)
                direct_result = _download_direct(
                    export_img=export_img,
                    geom=geom,
                    scale=int(scale),
                    output_tif=output_tif,
                    timeout_sec=min(int(download_timeout), 300),
                )

                if direct_result.get("success"):
                    method_desc = {"mean": "均值", "median": "中值", "single": "单景"}[selected_method]
                    results.append({
                        "year": year,
                        "output_tif": output_tif,
                        "scene_count": selected_count,
                        "total_scenes": total_count,
                        "quality": selected_quality,
                        "method": f"{selected_count}景{method_desc}",
                    })
                else:
                    # 回退到 Google Drive 导出
                    print(f"[GEE] {start_date}~{end_date} 直接下载失败，回退 Drive: {direct_result.get('message', '')}")
                    import time as _time
                    _ts = int(_time.time()) % 100000
                    drive_task_name = f"gee_multiyear_lst_{year}_{month:02d}_{_ts}"
                    local_path = _wait_drive_file(
                        export_img=export_img,
                        task_name=drive_task_name,
                        folder=folder_name,
                        scale=int(scale),
                        geom=geom,
                        sync_dir=sync_dir,
                        timeout_sec=int(download_timeout),
                    )
                    if local_path:
                        shutil.copy2(local_path, output_tif)
                        method_desc = {"mean": "均值", "median": "中值", "single": "单景"}[selected_method]
                        results.append({
                            "year": year,
                            "output_tif": output_tif,
                            "scene_count": selected_count,
                            "total_scenes": total_count,
                            "quality": selected_quality,
                            "method": f"{selected_count}景{method_desc}",
                        })
                    else:
                        failed_years.append({"year": year, "reason": "下载失败（直接+Drive均失败）"})

            except Exception as e:
                failed_years.append({"year": year, "reason": str(e)})

        success_count = len(results)
        if success_count == 0:
            return {
                "success": False,
                "message": f"{start_year}-{end_year}年{month}月均无可用数据",
                "failed_years": failed_years,
            }

        quality_counts = {}
        for r in results:
            q = r["quality"]
            quality_counts[q] = quality_counts.get(q, 0) + 1

        return {
            "success": True,
            "message": f"{start_year}-{end_year}年{month}月 LST 批量反演完成：{success_count}/{end_year - start_year + 1} 年成功",
            "output_dir": output_dir,
            "start_year": start_year,
            "end_year": end_year,
            "month": month,
            "results": results,
            "failed_years": failed_years,
            "success_count": success_count,
            "quality_summary": quality_counts,
        }

    except Exception as e:
        return {"success": False, "message": f"跨多年 LST 批量反演失败: {e}"}


# ============================================================
# A5: 增强下载功能
# ============================================================

def gee_download_image_collection(
    image_collection_id: str,
    output_dir: str,
    region: Any = None,
    region_path: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    band_names: Optional[list] = None,
    scale: int = 30,
    crs: str = "EPSG:4326",
    filename_pattern: str = "{id}",
    max_images: int = 50,
) -> Dict[str, Any]:
    """
    下载完整 ImageCollection 中的每景影像到本地目录。

    适用于需要逐景下载数据集的场景（如逐年 Landsat 合成）。

    Args:
        image_collection_id: GEE ImageCollection ID
        output_dir: 输出目录
        region: 研究区（bbox / GeoJSON / ee.Geometry）
        region_path: 研究区 GeoJSON 文件路径
        start_date: 起始日期
        end_date: 结束日期
        band_names: 要选择的波段
        scale: 分辨率（米）
        crs: 坐标参考系统
        filename_pattern: 文件名模式，支持 {id}, {date}, {index}
        max_images: 最大下载影像数

    Returns:
        {"success": bool, "message": str, "output_dir": str, "downloaded_files": list, ...}
    """
    try:
        init_result = init_gee()
        if not init_result.get("success"):
            return {"success": False, "message": f"GEE 初始化失败: {init_result.get('message', '')}",
                    "requires": "gee_init"}

        import geemap

        # ── 构建集合 ──
        collection = ee.ImageCollection(image_collection_id)
        if start_date and end_date:
            collection = collection.filterDate(start_date, end_date)

        if region or region_path:
            geom = _normalize_region(region=region, region_path=region_path)
            collection = collection.filterBounds(geom)
        else:
            geom = None

        if band_names:
            collection = collection.select(band_names)

        count = collection.size().getInfo()
        if count == 0:
            return {"success": False, "message": f"集合 {image_collection_id} 无可用数据"}

        if count > max_images:
            print(f"[GEE Download] 影像数 ({count}) 超过上限 ({max_images})，仅下载前 {max_images} 景")
            collection = collection.limit(max_images)
            count = max_images

        print(f"[GEE Download] 准备下载 {count} 景影像到 {output_dir}...")

        # ── 逐景下载 ──
        os.makedirs(output_dir, exist_ok=True)
        downloaded = []
        failed = []

        # 获取影像列表
        image_list = collection.toList(count)
        for i in range(count):
            try:
                image = ee.Image(image_list.get(i))
                image_id = image.id().getInfo() or f"image_{i}"

                # 构建文件名
                fname = filename_pattern.replace("{id}", str(image_id).replace("/", "_"))
                fname = fname.replace("{index}", f"{i:04d}")
                try:
                    date_str = ee.Date(image.get("system:time_start")).format("YYYY-MM-dd").getInfo()
                    fname = fname.replace("{date}", date_str)
                except Exception:
                    fname = fname.replace("{date}", "unknown")

                if not fname.endswith(".tif"):
                    fname += ".tif"

                out_path = os.path.join(output_dir, fname)

                if os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
                    print(f"[GEE Download] 已存在，跳过: {fname}")
                    downloaded.append(out_path)
                    continue

                print(f"[GEE Download] [{i+1}/{count}] 下载 {fname}...")

                if geom:
                    geemap.download_ee_image(image, out_path, scale=scale, region=geom, crs=crs)
                else:
                    geemap.download_ee_image(image, out_path, scale=scale, crs=crs)

                if os.path.exists(out_path) and os.path.getsize(out_path) > 1024:
                    downloaded.append(out_path)
                else:
                    failed.append(fname)

            except Exception as e:
                print(f"[GEE Download] 第 {i+1} 景下载失败: {e}")
                failed.append(f"image_{i}")

        return {
            "success": len(downloaded) > 0,
            "message": f"下载完成：{len(downloaded)} 成功，{len(failed)} 失败",
            "output_dir": output_dir,
            "downloaded_files": downloaded,
            "failed_files": failed,
            "total_count": count,
            "success_count": len(downloaded),
            "fail_count": len(failed),
        }

    except Exception as e:
        return {"success": False, "message": f"ImageCollection 下载失败: {e}"}


def gee_download_tiled(
    image: Any,
    region: Any,
    output_dir: str,
    scale: int = 30,
    crs: str = "EPSG:4326",
    rows: int = 2,
    cols: int = 2,
    prefix: str = "tile",
    parallel: bool = True,
) -> Dict[str, Any]:
    """
    鱼网分割 + 并行下载大区域影像。

    将大区域分割为网格瓦片，逐片下载后可在本地合并。
    使用 geemap 的 fishnet 和 download_ee_image_tiles_parallel 功能。

    Args:
        image: 待下载的 ee.Image
        region: 研究区（bbox / GeoJSON / ee.Geometry）
        output_dir: 输出目录
        scale: 分辨率（米）
        crs: 坐标参考系统
        rows: 行分割数
        cols: 列分割数
        prefix: 文件名前缀
        parallel: 是否并行下载

    Returns:
        {"success": bool, "message": str, "output_dir": str, "tile_count": int, ...}
    """
    try:
        init_result = init_gee()
        if not init_result.get("success"):
            return {"success": False, "message": f"GEE 初始化失败: {init_result.get('message', '')}",
                    "requires": "gee_init"}

        import geemap

        # ── 解析 region ──
        if isinstance(region, (list, tuple)) and len(region) == 4:
            ee_geom = ee.Geometry.Rectangle(region)
        elif isinstance(region, dict):
            ee_geom = _geojson_to_ee_geometry_local(region)
        elif hasattr(region, "getInfo"):
            ee_geom = region
        else:
            return {"success": False, "message": f"无法识别的 region: {type(region).__name__}"}

        # ── 解析 image ──
        if isinstance(image, str):
            ee_image = ee.Image(image)
        elif hasattr(image, "getInfo"):
            ee_image = image
        else:
            return {"success": False, "message": f"无法识别的 image: {type(image).__name__}"}

        os.makedirs(output_dir, exist_ok=True)

        # ── 创建鱼网 ──
        print(f"[GEE Tiled] 创建 {rows}x{cols} 鱼网...")
        fishnet = geemap.fishnet(ee_geom, rows=rows, cols=cols)
        tile_count = fishnet.size().getInfo()
        print(f"[GEE Tiled] 共 {tile_count} 个瓦片")

        # ── 下载 ──
        if parallel:
            print("[GEE Tiled] 启动并行下载...")
            try:
                geemap.download_ee_image_tiles_parallel(
                    ee_image, fishnet, out_dir=output_dir,
                    scale=scale, crs=crs, prefix=prefix,
                )
            except Exception as e:
                print(f"[GEE Tiled] 并行下载失败，回退到串行: {e}")
                geemap.download_ee_image_tiles(
                    ee_image, fishnet, out_dir=output_dir,
                    scale=scale, crs=crs, prefix=prefix,
                )
        else:
            print("[GEE Tiled] 串行下载...")
            geemap.download_ee_image_tiles(
                ee_image, fishnet, out_dir=output_dir,
                scale=scale, crs=crs, prefix=prefix,
            )

        # ── 检查结果 ──
        import glob
        tif_files = glob.glob(os.path.join(output_dir, "*.tif"))
        total_size = sum(os.path.getsize(f) for f in tif_files) / (1024 * 1024)

        return {
            "success": len(tif_files) > 0,
            "message": f"瓦片下载完成：{len(tif_files)} 个文件，共 {total_size:.1f}MB",
            "output_dir": output_dir,
            "tile_count": tile_count,
            "downloaded_count": len(tif_files),
            "total_size_mb": round(total_size, 1),
            "files": tif_files,
        }

    except Exception as e:
        return {"success": False, "message": f"瓦片下载失败: {e}"}