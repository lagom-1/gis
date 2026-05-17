"""
GEE 共用工具函数
供 gee_tools.py 和 gee_timelapse.py 共享，避免循环导入
"""

from __future__ import annotations

import ee


def mask_clouds_qa(image: ee.Image) -> ee.Image:
    """Landsat Collection 2 QA_PIXEL 云掩膜：屏蔽 Cloud (Bit 3) 和 Cloud Shadow (Bit 4)"""
    qa = image.select("QA_PIXEL")
    cloud_bit = 1 << 3
    shadow_bit = 1 << 4
    mask = qa.bitwiseAnd(cloud_bit).eq(0).And(qa.bitwiseAnd(shadow_bit).eq(0))
    return image.updateMask(mask)
