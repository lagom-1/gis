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


def _mask_clouds_qa(image: ee.Image) -> ee.Image:
    """
    Landsat Collection 2 QA_PIXEL 云掩膜：
      Bit 3: Cloud
      Bit 4: Cloud Shadow
    """
    qa = image.select("QA_PIXEL")
    cloud_bit = 1 << 3
    shadow_bit = 1 << 4
    mask = qa.bitwiseAnd(cloud_bit).eq(0).And(qa.bitwiseAnd(shadow_bit).eq(0))
    return image.updateMask(mask)


def _landsat89_l2_collection(region_geom, start_date: str, end_date: str, cloud_pct: float = 30):
    """
    合并 Landsat 8/9 Collection 2 Level-2 Tier 1。
    不硬性过滤云量，而是按云量排序取最优影像。
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

    # 按云量升序排序，取前 20 景最优影像
    # 这样即使没有低于 cloud_pct 的影像，也能取到最好的
    merged = merged.sort("CLOUD_COVER").limit(20)

    return merged


def _reduce_collection(col, reducer: str = "median", mask_clouds: bool = True) -> ee.Image:
    if mask_clouds:
        col = col.map(_mask_clouds_qa)

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

        col = _landsat89_l2_collection(
            region_geom=geom,
            start_date=start_date,
            end_date=end_date,
            cloud_pct=float(cloud_pct),
        )

        count = col.size().getInfo()
        if count == 0:
            return {
                "success": False,
                "message": f"未找到 {start_date}~{end_date} 内的 Landsat 8/9 影像。请尝试扩大日期范围或检查研究区。",
            }

        image = _reduce_collection(col, reducer=reducer, mask_clouds=mask_clouds).clip(geom)

        # ── 填补边缘小空洞 ──────────────────────────────────
        # 去云 + 中值合成后，县边缘只被 1-2 景覆盖的区域可能残留 NoData
        # 用 1 像素半径的 focal_mean 均值填补，保留原始有效值
        filled_bands = []
        for band_name in ["SR_B4", "SR_B5", "ST_B10"]:
            band = image.select(band_name)
            filled = band.focal_mean(radius=1, kernelType="square", units="pixels")
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

        return {
            "success": True,
            "message": f"GEE Landsat SCA 数据下载完成: {Path(output_tif).name}（{count} 景影像合成）",
            "output_tif": output_tif,
            "path": output_tif,
            "selected_path": output_tif,
            "bands": ["red", "nir", "bt_raw"],
            "start_date": start_date,
            "end_date": end_date,
            "scale": int(scale),
            "cloud_pct": float(cloud_pct),
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