"""
GEE 云端单通道地表温度反演
输入: Landsat 8/9 L2 影像 (SR_B4, SR_B5, ST_B10)
输出: 单波段 LST (°C)
"""

from __future__ import annotations

import ee


def compute_lst(image: ee.Image) -> ee.Image:
    """
    单通道算法反演 LST。
    NDVI → 植被覆盖度 Pv → 比辐射率 ε → 普朗克公式 → LST (°C)
    """
    # 缩放反射率和亮温
    red = image.select("SR_B4").multiply(0.0000275).add(-0.2)
    nir = image.select("SR_B5").multiply(0.0000275).add(-0.2)
    bt = image.select("ST_B10").multiply(0.00341802).add(149.0)  # Kelvin

    # NDVI
    ndvi = nir.subtract(red).divide(nir.add(red)).clamp(-1, 1)

    # 植被覆盖度 Pv
    ndvi_min, ndvi_max = 0.2, 0.5
    pv = ndvi.subtract(ndvi_min).divide(ndvi_max - ndvi_min).pow(2).clamp(0, 1)

    # 比辐射率 ε
    emissivity = pv.multiply(0.004).add(0.986)

    # 单通道 LST 反演
    lambda_ = 10.895e-6     # Landsat 8 TIRS Band 10 中心波长
    rho = 0.01438           # h*c/k

    lst = bt.divide(
        ee.Image(1).add(
            bt.multiply(lambda_).divide(rho).multiply(emissivity.log())
        )
    ).subtract(273.15)  # Kelvin → °C

    return lst.rename("LST").copyProperties(image, ["system:time_start"])
