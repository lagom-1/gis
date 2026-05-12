#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
从 NOAA isd-history.txt 中筛选指定范围内或附近的站点，
并生成 2023 年 ISD-Lite 下载链接。

用法：
    python find_noaa_stations.py

输出：
    - bbox 内站点列表
    - 若 bbox 内无站点，则输出最近站点
    - 对应 2023 年 ISD-Lite 文件下载链接
    - 可选自动下载 .gz 并解压为 .txt
"""

from __future__ import annotations

import csv
import gzip
import math
import os
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


# =========================
# 1. 研究区范围
# =========================
MIN_LON = 116.205807
MAX_LON = 116.591626
MIN_LAT = 39.603377
MAX_LAT = 39.746813

# 矩形中心点，用于找最近站
CENTER_LON = (MIN_LON + MAX_LON) / 2
CENTER_LAT = (MIN_LAT + MAX_LAT) / 2

# 年份
YEAR = 2023

# 是否自动下载对应 ISD-Lite 文件
AUTO_DOWNLOAD = False

# 若 bbox 内没有站点，则输出最近 N 个
TOP_N_NEAREST = 5

# 输出目录
OUT_DIR = Path("noaa_isd_output")
OUT_DIR.mkdir(exist_ok=True)

# NOAA 官方文本文件
ISD_HISTORY_URL = "https://www.ncei.noaa.gov/pub/data/noaa/isd-history.txt"
ISD_LITE_BASE = "https://www.ncei.noaa.gov/pub/data/noaa/isd-lite"


@dataclass
class Station:
    usaf: str
    wban: str
    name: str
    country: str
    state: str
    icao: str
    lat: float
    lon: float
    begin: str
    end: str

    @property
    def station_id(self) -> str:
        return f"{self.usaf}-{self.wban}"

    @property
    def lite_filename(self) -> str:
        return f"{self.station_id}-{YEAR}.gz"

    @property
    def lite_url(self) -> str:
        return f"{ISD_LITE_BASE}/{YEAR}/{self.lite_filename}"


def download_file(url: str, out_path: Path) -> None:
    print(f"下载: {url}")
    urllib.request.urlretrieve(url, out_path)


def haversine_km(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """计算球面距离（千米）"""
    r = 6371.0
    lon1, lat1, lon2, lat2 = map(math.radians, [lon1, lat1, lon2, lat2])
    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    c = 2 * math.asin(math.sqrt(a))
    return r * c


def parse_float_safe(s: str) -> Optional[float]:
    s = s.strip()
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_isd_history(file_path: Path) -> List[Station]:
    """
    解析 NOAA isd-history.txt
    固定宽度字段参考 NOAA 文档，常用字段大致如下：
    USAF(1-6), WBAN(8-12), NAME(14-42), CTRY(44-45), STATE(47-48),
    ICAO(52-56), LAT(58-64), LON(66-73), BEGIN(83-90), END(92-99)
    """
    stations: List[Station] = []

    with file_path.open("r", encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()

    # 跳过表头
    for line in lines[22:]:
        if not line.strip():
            continue

        usaf = line[0:6].strip()
        wban = line[7:12].strip()
        name = line[13:43].strip()
        country = line[43:46].strip()
        state = line[46:49].strip()
        icao = line[51:56].strip()
        lat = parse_float_safe(line[57:64])
        lon = parse_float_safe(line[65:73])
        begin = line[82:90].strip()
        end = line[91:99].strip()

        if not usaf or not wban:
            continue
        if lat is None or lon is None:
            continue

        stations.append(
            Station(
                usaf=usaf,
                wban=wban,
                name=name,
                country=country,
                state=state,
                icao=icao,
                lat=lat,
                lon=lon,
                begin=begin,
                end=end,
            )
        )

    return stations


def filter_bbox(stations: List[Station]) -> List[Station]:
    result = []
    for s in stations:
        if MIN_LON <= s.lon <= MAX_LON and MIN_LAT <= s.lat <= MAX_LAT:
            result.append(s)
    return result


def filter_has_year(stations: List[Station], year: int) -> List[Station]:
    """根据 begin/end 粗筛该年可能有数据"""
    result = []
    for s in stations:
        try:
            begin_year = int(s.begin[:4])
            end_year = int(s.end[:4])
        except Exception:
            continue
        if begin_year <= year <= end_year:
            result.append(s)
    return result


def nearest_stations(stations: List[Station], top_n: int = 5) -> List[tuple[Station, float]]:
    items = []
    for s in stations:
        d = haversine_km(CENTER_LON, CENTER_LAT, s.lon, s.lat)
        items.append((s, d))
    items.sort(key=lambda x: x[1])
    return items[:top_n]


def save_csv(stations: List[Station], path: Path, with_distance: bool = False) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        header = [
            "usaf",
            "wban",
            "station_id",
            "name",
            "country",
            "state",
            "icao",
            "lat",
            "lon",
            "begin",
            "end",
            "isd_lite_url",
        ]
        if with_distance:
            header.append("distance_km")
        writer.writerow(header)

        for row in stations:
            if with_distance:
                s, d = row  # type: ignore
                writer.writerow([
                    s.usaf, s.wban, s.station_id, s.name, s.country, s.state, s.icao,
                    s.lat, s.lon, s.begin, s.end, s.lite_url, round(d, 3)
                ])
            else:
                s = row  # type: ignore
                writer.writerow([
                    s.usaf, s.wban, s.station_id, s.name, s.country, s.state, s.icao,
                    s.lat, s.lon, s.begin, s.end, s.lite_url
                ])


def try_download_and_unzip(station: Station, out_dir: Path) -> None:
    gz_path = out_dir / station.lite_filename
    txt_path = out_dir / f"{station.station_id}-{YEAR}.txt"

    try:
        download_file(station.lite_url, gz_path)
    except Exception as e:
        print(f"[跳过] 下载失败: {station.lite_url} -> {e}")
        return

    try:
        with gzip.open(gz_path, "rb") as f_in, txt_path.open("wb") as f_out:
            f_out.write(f_in.read())
        print(f"[完成] 已解压到: {txt_path}")
    except Exception as e:
        print(f"[跳过] 解压失败: {gz_path} -> {e}")


def main() -> None:
    history_path = OUT_DIR / "isd-history.txt"

    if not history_path.exists():
        try:
            download_file(ISD_HISTORY_URL, history_path)
        except Exception as e:
            print(f"下载 isd-history.txt 失败: {e}")
            sys.exit(1)

    stations = parse_isd_history(history_path)
    print(f"共解析到站点数: {len(stations)}")

    stations_2023 = filter_has_year(stations, YEAR)
    print(f"可能覆盖 {YEAR} 年的站点数: {len(stations_2023)}")

    inside = filter_bbox(stations_2023)

    if inside:
        print(f"\nbbox 内找到 {len(inside)} 个站点：")
        for s in inside:
            print(
                f"- {s.station_id} | {s.name} | ({s.lat}, {s.lon}) | "
                f"{s.begin}-{s.end}\n  {s.lite_url}"
            )
        save_csv(inside, OUT_DIR / f"stations_in_bbox_{YEAR}.csv")
        print(f"\n已保存: {OUT_DIR / f'stations_in_bbox_{YEAR}.csv'}")

        if AUTO_DOWNLOAD:
            data_dir = OUT_DIR / f"isd_lite_{YEAR}"
            data_dir.mkdir(exist_ok=True)
            for s in inside:
                try_download_and_unzip(s, data_dir)

    else:
        print("\nbbox 内没有找到站点，开始查找最近站点...")
        nearest = nearest_stations(stations_2023, TOP_N_NEAREST)
        for s, d in nearest:
            print(
                f"- {s.station_id} | {s.name} | ({s.lat}, {s.lon}) | "
                f"距离中心约 {d:.2f} km\n  {s.lite_url}"
            )

        save_csv(nearest, OUT_DIR / f"nearest_stations_{YEAR}.csv", with_distance=True)
        print(f"\n已保存: {OUT_DIR / f'nearest_stations_{YEAR}.csv'}")

        if AUTO_DOWNLOAD:
            data_dir = OUT_DIR / f"isd_lite_{YEAR}"
            data_dir.mkdir(exist_ok=True)
            for s, _ in nearest:
                try_download_and_unzip(s, data_dir)


if __name__ == "__main__":
    main()