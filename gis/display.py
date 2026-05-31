"""
gis/display.py - 图像展示
"""

import os
from PIL import Image


def show_image(image_path: str) -> dict:
    if not os.path.exists(image_path):
        return {"success": False, "message": f"图片不存在: {image_path}"}

    try:
        img = Image.open(image_path)
        img.show()
        return {"success": True, "message": f"已打开图片: {image_path}", "path": image_path}
    except Exception as e:
        return {"success": False, "message": f"打开图片失败: {e}"}