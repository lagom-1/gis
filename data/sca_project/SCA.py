import rasterio
import numpy as np
import os

# 输入路径（ST_B10, SR_B4, SR_B5 三波段）
path = r"D:\python大数据\Beijing_South_30km_lower.tif"
output_path = r"D:/python大数据/SCA/LST_SCA_Python_fixed.tif"

with rasterio.open(path) as src:
    red = src.read(1).astype('float32')   # SR_B4
    nir = src.read(2).astype('float32')   # SR_B5
    bt = src.read(3).astype('float32')    # ST_B10
    profile = src.profile

# 1️⃣ BT 计算（Kelvin）
bt = bt * 0.00341802 + 149

# 2️⃣ NDVI（不要再乘 SR 比例因子）
ndvi = np.where((nir + red) == 0, np.nan, (nir - red) / (nir + red))
ndvi = np.clip(ndvi, 0, 1)

# 3️⃣ 发射率 ε
NDVImin, NDVImax = 0.2, 0.5
Pv = ((ndvi - NDVImin) / (NDVImax - NDVImin)) ** 2
Pv = np.clip(Pv, 0, 1)
emissivity = 0.986 + 0.004 * Pv
emissivity[emissivity <= 0] = np.nan

# 4️⃣ SCA 地表温度
lambda_ = 10.895e-6
rho = 1.438e-2
LST = bt / (1 + (lambda_ * bt / rho) * np.log(emissivity)) - 273.15

# 5️⃣ 输出
if os.path.exists(output_path):
    os.remove(output_path)
profile.update(dtype=rasterio.float32, count=1)
with rasterio.open(output_path, 'w', **profile) as dst:
    dst.write(LST.astype('float32'), 1)

print("✅ 修正后的 LST 范围：", np.nanmin(LST), "–", np.nanmax(LST))
