"""
gis/display.py - 图像展示
"""

import os
from PIL import Image


def show_image(image_path: str):
    if not os.path.exists(image_path):
        print(f"图片不存在: {image_path}")
        return

    img = Image.open(image_path)
    img.show()