"""
SEBAL (Surface Energy Balance Algorithm for Land) 地表蒸散发反演

基于 Landsat 8/9 影像和 ERA5-Land 再分析数据，在 GEE 云端计算：
- 净辐射 (Rn)
- 土壤热通量 (G)
- 感热通量 (H)
- 潜热通量 (LE)
- 蒸发比 (EF)
- 瞬时蒸散发 (ET_inst, mm/h)
- 日蒸散发 (ET_day, mm/d)

参考文献：
- Bastiaanssen et al. (1998). A remote sensing surface energy balance algorithm for land (SEBAL).
- Allen et al. (2007). Satellite-based energy balance for mapping evapotranspiration with internalized calibration (METRIC).
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

import ee


# ============================================================
# 辅助函数：MOS 稳定度修正
# ============================================================

def psi_m(zeta: ee.Image) -> ee.Image:
    """动量稳定度修正函数 (Paulson, 1970)"""
    x = (1 - 16 * zeta).sqrt()
    psi_unstable = (
        2 * ((1 + x) / 2).log()
        + ((1 + x.sqrt()) / 2).log()
        - 2 * x.atan()
        + math.pi / 2
    )
    psi_stable = -5 * zeta
    return ee.Image(
        ee.Algorithms.If(zeta.lt(0), psi_unstable, psi_stable)
    )


def psi_h(zeta: ee.Image) -> ee.Image:
    """热量稳定度修正函数 (Paulson, 1970)"""
    x = (1 - 16 * zeta).sqrt()
    psi_unstable = 2 * ((1 + x) / 2).log()
    psi_stable = -5 * zeta
    return ee.Image(
        ee.Algorithms.If(zeta.lt(0), psi_unstable, psi_stable)
    )


# ============================================================
# Landsat 预处理
# ============================================================

def preprocess_landsat(image: ee.Image) -> ee.Image:
    """
    Landsat 8/9 Level-2 预处理：
    - 计算地表反照率 (albedo)
    - 计算 NDVI
    - 提取地表温度 (lst, K)
    - 计算地表比辐射率 (emissivity)
    """
    # 地表反射率（Landsat C2 缩放因子）
    blue = image.select("SR_B1").multiply(0.0000275).add(-0.2)
    green = image.select("SR_B2").multiply(0.0000275).add(-0.2)
    red = image.select("SR_B3").multiply(0.0000275).add(-0.2)
    nir = image.select("SR_B4").multiply(0.0000275).add(-0.2)
    swir1 = image.select("SR_B5").multiply(0.0000275).add(-0.2)
    swir2 = image.select("SR_B6").multiply(0.0000275).add(-0.2)

    # NDVI
    ndvi = nir.subtract(red).divide(nir.add(red)).clamp(-1, 1).rename("ndvi")

    # 地表反照率（Tasumi et al., 2008 - Landsat 8 窄波段公式）
    albedo = (
        blue.multiply(0.356)
        .add(green.multiply(0.130)
        .add(red.multiply(0.373)
        .add(nir.multiply(0.085)
        .add(swir1.multiply(0.072)
        .add(swir2.multiply(-0.0018)
    )))))
    ).clamp(0, 1).rename("albedo")

    # 地表温度 (K)
    lst = image.select("ST_B10").multiply(0.00341802).add(149.0).rename("lst")

    # 地表比辐射率（Valor & Caselles, 1996 - NDVI 阈值法）
    pv = ndvi.subtract(0.2).divide(0.3).pow(2).clamp(0, 1)
    emissivity = pv.multiply(0.004).add(0.986).rename("emissivity")

    return ee.Image.cat([albedo, ndvi, lst, emissivity])


# ============================================================
# ERA5-Land 数据获取
# ============================================================

def get_era5_params(
    start_date: str,
    end_date: str,
    geom: ee.Geometry,
    target_hour: int = 10,
) -> Dict[str, ee.Image]:
    """
    获取 ERA5-Land 逐小时风速和气压。

    Args:
        start_date: 开始日期 YYYY-MM-DD
        end_date: 结束日期 YYYY-MM-DD
        geom: 研究区几何
        target_hour: 目标小时（UTC），Landsat 约 10:00 地方时

    Returns:
        {"wind_speed": ee.Image, "pressure": ee.Image}
    """
    era5 = (
        ee.ImageCollection("ECMWF/ERA5_LAND/HOURLY")
        .filterDate(start_date, end_date)
        .filterBounds(geom)
        .filter(ee.Filter.eq("hour", target_hour))
    )

    # 10m 风速分量
    wind_u = era5.select("u_component_of_wind_10m").mean()
    wind_v = era5.select("v_component_of_wind_10m").mean()
    wind_speed = wind_u.pow(2).add(wind_v.pow(2)).sqrt().rename("wind_speed")

    # 地表气压 (Pa)
    pressure = era5.select("surface_pressure").mean().rename("pressure")

    return {"wind_speed": wind_speed, "pressure": pressure}


# ============================================================
# SEBAL 主函数
# ============================================================

def calc_sebal(
    image: ee.Image,
    wind_speed: ee.Image,
    pressure: ee.Image,
    elevation: ee.Image,
    solar_zenith: ee.Number,
    doy: ee.Number,
) -> ee.Image:
    """
    SEBAL 模型核心计算。

    Args:
        image: 预处理后的 Landsat 影像，需包含波段 'albedo', 'ndvi', 'lst', 'emissivity'
        wind_speed: 瞬时风速标量 (m/s)
        pressure: 瞬时气压 (Pa)
        elevation: 海拔 (m)
        solar_zenith: 太阳天顶角 (弧度)
        doy: 儒略日 (整数)

    Returns:
        多波段影像包含 Rn, G, H, LE, EF, ET_inst, ET_day
    """
    # 提取波段
    albedo = image.select("albedo")
    ndvi = image.select("ndvi")
    lst = image.select("lst")  # K
    emiss = image.select("emissivity")

    # 常数
    sigma = 5.67e-8  # Stefan-Boltzmann 常数
    cp = 1005.0      # 空气比热容 J/(kg·K)
    k = 0.41         # von Karman 常数
    rho_w = 1000.0   # 水的密度 kg/m³
    lambda_v = 2.45e6  # 水的汽化潜热 J/kg

    # 空气密度 (kg/m³)
    rho = pressure.divide(287.05 * lst)

    # ========================= 1. 净辐射 Rn =========================
    # 大气透过率（简化公式，基于海拔）
    tau_sw = ee.Image.constant(0.75).add(elevation.multiply(2e-5))

    # 入射短波辐射
    S = 1361.0  # 太阳常数 W/m²
    Rs_down = ee.Image.constant(S).multiply(tau_sw).multiply(solar_zenith.cos())

    # 净短波辐射
    Rn_short = Rs_down.multiply(ee.Image.constant(1).subtract(albedo))

    # 大气下行长波辐射（简化）
    Rl_down = (
        ee.Image.constant(sigma)
        .multiply(lst.pow(4))
        .multiply(ee.Image.constant(0.85).multiply(tau_sw.log().multiply(-1)))
    )

    # 地表上行长波辐射
    Rl_up = emiss.multiply(sigma).multiply(lst.pow(4))

    # 净长波辐射
    Rn_long = Rl_down.subtract(Rl_up)

    # 净辐射
    Rn = Rn_short.add(Rn_long).rename("Rn")

    # ========================= 2. 土壤热通量 G =========================
    # Bastiaanssen (2000) 经验公式
    G = (
        Rn.multiply(
            lst.subtract(273.15)
            .multiply(0.0038 + 0.0074 * albedo)
            .multiply(ee.Image.constant(1).subtract(0.98 * ndvi.pow(4)))
        )
    ).rename("G")

    # ========================= 3. 粗糙度长度 =========================
    # 动量粗糙度长度 (SEBS 方法)
    z0m = (
        ndvi.expression("exp(-5.809 + 5.62 * NDVI)", {"NDVI": ndvi})
        .clamp(0.001, 0.5)
        .rename("z0m")
    )

    # 热量粗糙度长度
    kb1 = 2.5
    z0h = z0m.divide(math.exp(kb1)).rename("z0h")

    # ========================= 4. 冷热点自动标定 =========================
    # 冷点：NDVI 高（前 10%）且 LST 低的像元
    ndvi_cold_pct = ndvi.reduceRegion(
        reducer=ee.Reducer.percentile([90]),
        geometry=image.geometry(),
        scale=100,
        maxPixels=1e9,
        bestEffort=True,
    ).get("ndvi")
    cold_mask = ndvi.gte(ee.Number(ndvi_cold_pct))
    cold_lst = (
        lst.updateMask(cold_mask)
        .reduceRegion(
            reducer=ee.Reducer.percentile([5]),
            geometry=image.geometry(),
            scale=100,
            maxPixels=1e9,
            bestEffort=True,
        )
        .get("lst")
    )
    cold_lst_img = ee.Image.constant(cold_lst)

    # 热点：NDVI 低（后 10%）且 LST 高的像元
    ndvi_hot_pct = ndvi.reduceRegion(
        reducer=ee.Reducer.percentile([10]),
        geometry=image.geometry(),
        scale=100,
        maxPixels=1e9,
        bestEffort=True,
    ).get("ndvi")
    hot_mask = ndvi.lte(ee.Number(ndvi_hot_pct))
    hot_lst = (
        lst.updateMask(hot_mask)
        .reduceRegion(
            reducer=ee.Reducer.percentile([95]),
            geometry=image.geometry(),
            scale=100,
            maxPixels=1e9,
            bestEffort=True,
        )
        .get("lst")
    )
    hot_lst_img = ee.Image.constant(hot_lst)

    # 中性条件下的摩擦速度和空气动力学阻力
    u_star_neutral = wind_speed.multiply(k).divide(ee.Image(10).divide(z0m).log())
    r_ah_cold = (ee.Image(2).divide(z0h).log()).divide(u_star_neutral.multiply(k))
    r_ah_hot = r_ah_cold

    # 冷点 H ≈ 0 -> dT_cold = 0
    # 热点 H = Rn - G -> dT_hot = H_hot * r_ah_hot / (rho * cp)
    Rn_hot = (
        Rn.updateMask(hot_mask)
        .reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=image.geometry(),
            scale=100,
            maxPixels=1e9,
            bestEffort=True,
        )
        .get("Rn")
    )
    G_hot = (
        G.updateMask(hot_mask)
        .reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=image.geometry(),
            scale=100,
            maxPixels=1e9,
            bestEffort=True,
        )
        .get("G")
    )
    H_hot = ee.Image.constant(ee.Number(Rn_hot).subtract(ee.Number(G_hot)))

    rho_hot = (
        rho.updateMask(hot_mask)
        .reduceRegion(
            reducer=ee.Reducer.mean(),
            geometry=image.geometry(),
            scale=100,
            maxPixels=1e9,
            bestEffort=True,
        )
        .get("pressure")
    )
    rho_hot_img = ee.Image.constant(rho_hot).divide(287.05 * hot_lst_img)
    dT_hot = H_hot.multiply(r_ah_hot).divide(rho_hot_img.multiply(cp))

    # 线性回归：dT = a * Ts + b
    a = dT_hot.divide(hot_lst_img.subtract(cold_lst_img).max(1e-6))
    b = ee.Image.constant(0).subtract(a.multiply(cold_lst_img))

    # ========================= 5. MOS 迭代求解 H =========================
    L = ee.Image.constant(1e10)  # 初始中性
    z_ref = ee.Image.constant(2.0)

    # 迭代 4 次
    for _ in range(4):
        psi_m_10 = psi_m(ee.Image.constant(10).divide(L))
        psi_m_z0m = psi_m(z0m.divide(L))
        u_star = wind_speed.multiply(k).divide(
            ee.Image(10).divide(z0m).log().subtract(psi_m_10).add(psi_m_z0m)
        )

        psi_h_2 = psi_h(z_ref.divide(L))
        psi_h_z0h = psi_h(z0h.divide(L))
        r_ah = (
            z_ref.divide(z0h).log().subtract(psi_h_z0h).add(psi_h_2)
        ).divide(u_star.multiply(k))

        dT = a.multiply(lst).add(b)
        H = dT.multiply(rho).multiply(cp).divide(r_ah).rename("H")
        H = H.min(Rn.subtract(G)).max(0)  # 物理约束

        # 更新 L
        L = (
            u_star.pow(3).multiply(lst.multiply(rho).multiply(cp))
            .divide(ee.Image.constant(k * 9.81).multiply(H.add(1e-9)))
            .rename("L")
        )
        L = L.where(L.abs().lt(0.1), ee.Image.constant(0.1).multiply(L.signum()))

    # ========================= 6. LE, EF, ET =========================
    LE = Rn.subtract(G).subtract(H).max(0).rename("LE")
    EF = LE.divide(Rn.subtract(G).add(1e-6)).rename("EF")

    # 瞬时 ET (mm/h) = LE / lambda * 3600 / rho_w
    # 简化：ET_inst ≈ LE / 28.34
    ET_inst = LE.divide(28.34).rename("ET_inst")

    # 日 ET (mm/d) = ET_inst * 24（假设蒸发比白天恒定）
    ET_day = ET_inst.multiply(24).rename("ET_day")

    return ee.Image.cat([Rn, G, H, LE, EF, ET_inst, ET_day])
