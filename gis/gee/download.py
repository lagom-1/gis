"""
GEE 影像下载：HTTP 直接下载 + Google Drive 回退
"""

from __future__ import annotations

import os
import time
import urllib.request
from typing import Any, Dict

import ee

from .client import init_gee


def _ensure_parent(path: str):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)


def download_tif(
    image: ee.Image,
    region_geom: Any,
    output_path: str,
    scale: int = 30,
    crs: str = "EPSG:4326",
    timeout_sec: int = 900,
    project_id: str = None,
) -> Dict[str, Any]:
    """
    HTTP 直接下载 GEE Image 为 GeoTIFF。
    适合小区域（< 50MB），超大区域自动回退 Drive。
    """
    init = init_gee(project_id=project_id)
    if not init.get("success"):
        return init

    try:
        url = image.getDownloadURL({
            "scale": scale,
            "region": region_geom,
            "format": "GeoTIFF",
            "crs": crs,
        })

        _ensure_parent(output_path)
        tmp_path = output_path + ".downloading"

        print(f"[GEE] 下载中... scale={scale}m")
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            content_length = resp.headers.get("Content-Length")
            total = int(content_length) if content_length else None
            downloaded = 0
            with open(tmp_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total:
                        pct = int(downloaded * 100 / total)
                        bar = "#" * (pct // 5) + " " * (20 - pct // 5)
                        print(f"\r[GEE] [{bar}] {pct}%", end="", flush=True)
            if total:
                print(f"\r[GEE] [{'#' * 20}] 100%", flush=True)

        os.replace(tmp_path, output_path)
        size_mb = os.path.getsize(output_path) / (1024 * 1024)

        return {
            "success": True,
            "message": f"下载完成 {size_mb:.1f}MB",
            "output_path": output_path,
            "size_mb": round(size_mb, 1),
        }

    except Exception as e:
        err = str(e)
        tmp = output_path + ".downloading"
        if os.path.exists(tmp):
            os.remove(tmp)

        # 文件太大 → 回退 Drive
        if any(k in err.lower() for k in ["too large", "memory", "limit", "50331648"]):
            return download_to_drive(image, region_geom, output_path, scale)

        return {"success": False, "message": f"下载失败: {err}"}


def download_to_drive(
    image: ee.Image,
    region_geom: Any,
    output_path: str,
    scale: int = 30,
    drive_folder: str = "GEE_Exports",
) -> Dict[str, Any]:
    """Google Drive 导出 + 本地同步回退"""
    import glob as _glob
    import shutil

    task = ee.batch.Export.image.toDrive(
        image=image,
        description=os.path.splitext(os.path.basename(output_path))[0],
        folder=drive_folder,
        scale=scale,
        region=region_geom,
        crs="EPSG:4326",
        maxPixels=1e13,
    )
    task.start()

    print(f"[GEE] Drive 导出已启动: {task.id}，等待完成...")
    timeout = 1800
    start = time.time()
    while task.active():
        if time.time() - start > timeout:
            return {"success": False, "message": "Drive 导出超时"}
        time.sleep(10)

    if task.status()["state"] != "COMPLETED":
        return {"success": False, "message": f"Drive 导出失败: {task.status()}",
                "requires": "gee_init"}

    # 尝试从本地 Google Drive 同步目录复制
    drive_sync = os.getenv("GDRIVE_SYNC_DIR", r"G:\我的云端硬盘\GEE_Exports")
    task_name = os.path.splitext(os.path.basename(output_path))[0]
    candidates = _glob.glob(os.path.join(drive_sync, f"{task_name}*.tif"))

    if candidates:
        shutil.copy2(candidates[0], output_path)
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        return {"success": True, "message": f"Drive 导出完成 {size_mb:.1f}MB",
                "output_path": output_path, "size_mb": round(size_mb, 1)}

    return {"success": True, "message": f"Drive 导出完成，请手动下载到 {output_path}",
            "drive_task_id": task.id, "output_path": output_path}
