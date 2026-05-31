"""
gis/export.py - 导出/格式转换模块
"""

import os
from PIL import Image


def export_image(
    input_path: str,
    output_path: str = None,
    format: str = "png",
    dpi: int = 300,
) -> dict:
    """
    图像格式转换

    Args:
        format: "png" / "jpg" / "pdf" / "svg" / "tif"
    """
    try:
        if not os.path.exists(input_path):
            return {"success": False, "message": f"输入文件不存在: {input_path}"}

        if output_path is None:
            base = os.path.splitext(input_path)[0]
            output_path = f"{base}_export.{format}"

        with Image.open(input_path) as img:
            if format in ("jpg", "jpeg"):
                if img.mode in ("RGBA", "P"):
                    img = img.convert("RGB")
                img.save(output_path, "JPEG", quality=95, dpi=(dpi, dpi))
            elif format == "png":
                img.save(output_path, "PNG", dpi=(dpi, dpi))
            elif format == "pdf":
                img.save(output_path, "PDF", resolution=dpi)
            elif format == "tif" or format == "tiff":
                img.save(output_path, "TIFF", dpi=(dpi, dpi))
            elif format == "svg":
                return {
                    "success": False,
                    "message": "SVG 格式需要在出图时指定，请使用 matplotlib 的 savefig(svg) 功能",
                }
            else:
                return {"success": False, "message": f"不支持的格式: {format}"}

        return {
            "success": True,
            "message": f"已导出为 {format.upper()}",
            "output_path": output_path,
            "format": format,
            "dpi": dpi,
        }

    except Exception as e:
        return {"success": False, "message": str(e)}