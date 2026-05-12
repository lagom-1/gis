"""
文件服务层
- 缩略图生成（PNG/JPG/TIF/GIF/HTML）
- 文件元数据提取
- 文件类型映射与权限检查
"""

from __future__ import annotations

import hashlib
import io
import logging
import mimetypes
from pathlib import Path
from typing import Any, Dict, List, Optional

import config

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  常量定义
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 缩略图宽度（像素）
THUMBNAIL_WIDTH = 200

# 缩略图缓存目录
THUMBNAIL_DIR = config.OUTPUTS_DIR / "thumbnails"

# 文件类型映射
FILE_TYPE_MAPPING: Dict[str, str] = {
    "png": "image",
    "jpg": "image",
    "jpeg": "image",
    "gif": "animation",
    "tif": "raster",
    "tiff": "raster",
    "html": "interactive",
    "csv": "data",
    "pdf": "document",
}

# 定价层级对应的可访问文件类型
TIER_FILE_ACCESS: Dict[str, List[str]] = {
    "free": ["preview"],
    "basic": ["png", "jpg", "jpeg"],
    "standard": ["png", "jpg", "jpeg", "html", "pdf"],
    "premium": ["png", "jpg", "jpeg", "gif", "tif", "tiff", "html", "csv", "pdf"],
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  缩略图生成
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_thumbnail_path(file_path: Path) -> Path:
    """
    计算缩略图缓存路径

    使用文件路径的 MD5 哈希作为缩略图文件名，避免路径冲突。
    """
    THUMBNAIL_DIR.mkdir(parents=True, exist_ok=True)

    # 使用文件路径 + 修改时间生成唯一哈希
    file_stat = file_path.stat()
    hash_input = f"{file_path.resolve()}:{file_stat.st_mtime}:{file_stat.st_size}"
    file_hash = hashlib.md5(hash_input.encode()).hexdigest()[:12]

    thumbnail_name = f"{file_hash}_{file_path.stem}.png"
    return THUMBNAIL_DIR / thumbnail_name


def generate_thumbnail(file_path: Path) -> Optional[Path]:
    """
    生成缩略图并缓存到磁盘

    支持的文件类型：
    - PNG/JPG：直接缩放
    - TIF/TIFF：读取第一波段，归一化后转 PNG
    - GIF：提取第一帧
    - HTML：生成占位图
    - 其他：返回 None

    Args:
        file_path: 原始文件路径

    Returns:
        缩略图路径，失败返回 None
    """
    thumbnail_path = get_thumbnail_path(file_path)

    # 检查缓存是否存在且比原文件新
    if thumbnail_path.exists():
        if thumbnail_path.stat().st_mtime >= file_path.stat().st_mtime:
            logger.debug(f"使用缓存缩略图: {thumbnail_path}")
            return thumbnail_path

    ext = file_path.suffix.lower()

    try:
        if ext in (".png", ".jpg", ".jpeg"):
            return _generate_image_thumbnail(file_path, thumbnail_path)
        elif ext == ".gif":
            return _generate_gif_thumbnail(file_path, thumbnail_path)
        elif ext in (".tif", ".tiff"):
            return _generate_raster_thumbnail(file_path, thumbnail_path)
        elif ext in (".html", ".htm"):
            return _generate_html_thumbnail(file_path, thumbnail_path)
        else:
            logger.warning(f"不支持的文件类型生成缩略图: {ext}")
            return None
    except Exception as e:
        logger.error(f"缩略图生成失败: {file_path}, 错误: {e}")
        return None


def _generate_image_thumbnail(file_path: Path, output_path: Path) -> Path:
    """生成 PNG/JPG 缩略图"""
    from PIL import Image

    with Image.open(file_path) as img:
        # 保持比例缩放
        width, height = img.size
        ratio = THUMBNAIL_WIDTH / width
        new_height = int(height * ratio)
        thumbnail = img.resize((THUMBNAIL_WIDTH, new_height), Image.LANCZOS)

        # 转为 RGB（处理 RGBA 和调色板模式）
        if thumbnail.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", thumbnail.size, (255, 255, 255))
            if thumbnail.mode == "P":
                thumbnail = thumbnail.convert("RGBA")
            background.paste(thumbnail, mask=thumbnail.split()[-1] if thumbnail.mode == "RGBA" else None)
            thumbnail = background
        elif thumbnail.mode != "RGB":
            thumbnail = thumbnail.convert("RGB")

        thumbnail.save(output_path, "PNG", optimize=True)

    logger.debug(f"生成图片缩略图: {output_path}")
    return output_path


def _generate_gif_thumbnail(file_path: Path, output_path: Path) -> Path:
    """生成 GIF 缩略图（提取第一帧）"""
    from PIL import Image

    with Image.open(file_path) as img:
        # 提取第一帧
        first_frame = img.copy()
        width, height = first_frame.size
        ratio = THUMBNAIL_WIDTH / width
        new_height = int(height * ratio)
        thumbnail = first_frame.resize((THUMBNAIL_WIDTH, new_height), Image.LANCZOS)

        # 转为 RGB
        if thumbnail.mode in ("RGBA", "P", "LA"):
            background = Image.new("RGB", thumbnail.size, (255, 255, 255))
            if thumbnail.mode == "P":
                thumbnail = thumbnail.convert("RGBA")
            background.paste(thumbnail, mask=thumbnail.split()[-1] if thumbnail.mode == "RGBA" else None)
            thumbnail = background
        elif thumbnail.mode != "RGB":
            thumbnail = thumbnail.convert("RGB")

        thumbnail.save(output_path, "PNG", optimize=True)

    logger.debug(f"生成 GIF 缩略图: {output_path}")
    return output_path


def _generate_raster_thumbnail(file_path: Path, output_path: Path) -> Path:
    """
    生成 TIF 栅格数据缩略图

    读取第一波段，归一化到 0-255，应用伪彩色后保存为 PNG。
    """
    try:
        import numpy as np
        import rasterio
    except ImportError:
        logger.error("rasterio 未安装，无法生成 TIF 缩略图")
        return _generate_placeholder_thumbnail(file_path, output_path, "raster")

    with rasterio.open(file_path) as src:
        # 读取第一波段，降采样以提高性能
        band = src.read(1)

        # 处理 nodata
        nodata = src.nodata
        if nodata is not None:
            mask = band == nodata
        else:
            mask = np.isnan(band) if band.dtype.kind == "f" else np.zeros_like(band, dtype=bool)

        # 归一化到 0-255
        valid_data = band[~mask]
        if len(valid_data) == 0:
            return _generate_placeholder_thumbnail(file_path, output_path, "raster")

        vmin, vmax = np.percentile(valid_data, [2, 98])
        if vmin == vmax:
            vmin, vmax = valid_data.min(), valid_data.max()

        normalized = np.zeros_like(band, dtype=np.uint8)
        if vmax > vmin:
            scaled = (band - vmin) / (vmax - vmin) * 255
            scaled = np.clip(scaled, 0, 255)
            normalized[~mask] = scaled[~mask].astype(np.uint8)

        # 缩放
        from PIL import Image

        img = Image.fromarray(normalized, mode="L")
        width, height = img.size
        ratio = THUMBNAIL_WIDTH / width
        new_height = int(height * ratio)
        thumbnail = img.resize((THUMBNAIL_WIDTH, new_height), Image.LANCZOS)

        # 应用伪彩色（coolwarm）
        import matplotlib.pyplot as plt
        import matplotlib.cm as cm

        fig, ax = plt.subplots(figsize=(THUMBNAIL_WIDTH / 100, new_height / 100), dpi=100)
        ax.imshow(np.array(thumbnail), cmap="coolwarm", vmin=0, vmax=255)
        ax.axis("off")
        fig.tight_layout(pad=0)

        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight", pad_inches=0, dpi=100)
        plt.close(fig)
        buf.seek(0)

        result_img = Image.open(buf)
        result_img.save(output_path, "PNG", optimize=True)

    logger.debug(f"生成栅格缩略图: {output_path}")
    return output_path


def _generate_html_thumbnail(file_path: Path, output_path: Path) -> Path:
    """生成 HTML 占位缩略图"""
    return _generate_placeholder_thumbnail(file_path, output_path, "interactive")


def _generate_placeholder_thumbnail(file_path: Path, output_path: Path, file_type: str) -> Path:
    """
    生成占位缩略图

    对于无法直接预览的文件类型，生成带有文件信息的占位图。
    """
    from PIL import Image, ImageDraw, ImageFont

    # 占位图尺寸
    width, height = THUMBNAIL_WIDTH, 150

    # 创建背景
    if file_type == "interactive":
        bg_color = (240, 248, 255)  # 浅蓝色
        border_color = (70, 130, 180)
        icon_text = "HTML"
    elif file_type == "raster":
        bg_color = (245, 245, 220)  # 米色
        border_color = (139, 119, 101)
        icon_text = "TIF"
    elif file_type == "data":
        bg_color = (240, 255, 240)  # 浅绿色
        border_color = (60, 179, 113)
        icon_text = "CSV"
    elif file_type == "document":
        bg_color = (255, 245, 238)  # 浅橙色
        border_color = (255, 140, 0)
        icon_text = "PDF"
    else:
        bg_color = (245, 245, 245)  # 浅灰色
        border_color = (169, 169, 169)
        icon_text = "FILE"

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    # 绘制边框
    draw.rectangle([(0, 0), (width - 1, height - 1)], outline=border_color, width=2)

    # 绘制图标文字
    try:
        font = ImageFont.truetype("arial.ttf", 24)
    except (OSError, IOError):
        font = ImageFont.load_default()

    bbox = draw.textbbox((0, 0), icon_text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    text_x = (width - text_width) // 2
    text_y = (height - text_height) // 2 - 15
    draw.text((text_x, text_y), icon_text, fill=border_color, font=font)

    # 绘制文件名
    try:
        small_font = ImageFont.truetype("arial.ttf", 10)
    except (OSError, IOError):
        small_font = ImageFont.load_default()

    filename = file_path.name
    if len(filename) > 25:
        filename = filename[:22] + "..."

    bbox = draw.textbbox((0, 0), filename, font=small_font)
    text_width = bbox[2] - bbox[0]
    text_x = (width - text_width) // 2
    draw.text((text_x, height - 30), filename, fill=(100, 100, 100), font=small_font)

    img.save(output_path, "PNG", optimize=True)
    logger.debug(f"生成占位缩略图: {output_path}")
    return output_path


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  文件元数据
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_file_metadata(file_path: Path) -> Dict[str, Any]:
    """
    获取文件元数据

    Args:
        file_path: 文件路径

    Returns:
        包含文件名、大小、类型等信息的字典
    """
    if not file_path.exists():
        return {"exists": False}

    stat = file_path.stat()
    ext = file_path.suffix.lower().lstrip(".")

    metadata = {
        "exists": True,
        "name": file_path.name,
        "path": str(file_path),
        "size_bytes": stat.st_size,
        "size_human": _format_file_size(stat.st_size),
        "extension": ext,
        "file_type": FILE_TYPE_MAPPING.get(ext, "other"),
        "mime_type": mimetypes.guess_type(str(file_path))[0] or "application/octet-stream",
        "modified_at": stat.st_mtime,
    }

    # 尝试获取图片尺寸
    if ext in ("png", "jpg", "jpeg", "gif"):
        try:
            from PIL import Image

            with Image.open(file_path) as img:
                metadata["width"] = img.size[0]
                metadata["height"] = img.size[1]
                metadata["mode"] = img.mode
        except Exception:
            pass

    # 尝试获取栅格信息
    elif ext in ("tif", "tiff"):
        try:
            import rasterio

            with rasterio.open(file_path) as src:
                metadata["width"] = src.width
                metadata["height"] = src.height
                metadata["bands"] = src.count
                metadata["crs"] = str(src.crs) if src.crs else None
                metadata["dtype"] = str(src.dtypes[0]) if src.dtypes else None
                metadata["nodata"] = src.nodata
                metadata["bounds"] = {
                    "left": src.bounds.left,
                    "bottom": src.bounds.bottom,
                    "right": src.bounds.right,
                    "top": src.bounds.top,
                }
        except Exception:
            pass

    return metadata


def get_task_output_info(task_id: int, output_files: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    获取任务输出文件的完整信息

    Args:
        task_id: 任务 ID
        output_files: 输出文件列表（来自 Task.output_files）

    Returns:
        包含文件列表和统计信息的字典
    """
    files_info = []
    total_size = 0
    file_types = set()

    for file_entry in output_files:
        file_path = Path(file_entry.get("path", ""))
        metadata = get_file_metadata(file_path)

        # 生成缩略图 URL
        ext = file_path.suffix.lower().lstrip(".")
        preview_url = f"/api/downloads/{task_id}/preview/{file_path.name}"
        download_url = f"/api/downloads/{task_id}/{file_path.name}"

        file_info = {
            **metadata,
            "preview_url": preview_url,
            "download_url": download_url,
            "requires_payment": ext not in ("json", "txt", "csv"),
            "file_category": FILE_TYPE_MAPPING.get(ext, "other"),
        }
        files_info.append(file_info)

        if metadata.get("exists"):
            total_size += metadata.get("size_bytes", 0)
            file_types.add(ext)

    return {
        "task_id": task_id,
        "files": files_info,
        "total_count": len(files_info),
        "total_size_bytes": total_size,
        "total_size_human": _format_file_size(total_size),
        "file_types": sorted(file_types),
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  工具函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _format_file_size(size_bytes: int) -> str:
    """将字节数转换为人类可读的文件大小"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def check_file_type_permission(file_ext: str, tier: str) -> bool:
    """
    检查指定层级是否有权限访问该文件类型

    Args:
        file_ext: 文件扩展名（如 "png", "tif"）
        tier: 定价层级（如 "basic", "premium"）

    Returns:
        是否有权限
    """
    allowed_types = TIER_FILE_ACCESS.get(tier, [])
    return file_ext.lstrip(".").lower() in allowed_types


def get_file_type_for_payment(file_path: Path) -> str:
    """
    获取文件类型标识（用于付费检查）

    与 payment_service.py 中的 check_download_permission 配合使用。

    Args:
        file_path: 文件路径

    Returns:
        文件类型标识
    """
    ext = file_path.suffix.lower()
    type_mapping = {
        ".png": "png",
        ".jpg": "png",
        ".jpeg": "png",
        ".gif": "gif",
        ".tif": "tif",
        ".tiff": "tif",
        ".html": "html",
        ".htm": "html",
        ".csv": "statistics",
        ".json": "metadata",
        ".txt": "metadata",
        ".pdf": "report",
        ".md": "report",
    }
    return type_mapping.get(ext, "other")
