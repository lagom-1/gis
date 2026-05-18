"""
行政区解析模块 - 根据中国市/县/区名称自动匹配本地 GeoJSON 行政边界

重写版：解决文件发现失败、属性名不匹配、名称匹配太严格等问题
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shapely.geometry import shape, mapping


# ============================================================
# 1. 行政区名称提取
# ============================================================

# 明显不是行政区的"区"字结尾词
_FAKE_ADMIN_SUFFIXES = {
    "下载区", "区域", "地区", "城区", "景区", "园区", "社区", "禁区",
    "展区", "产区", "林区", "山区", "牧区", "渔区", "垦区", "矿区",
    "战区", "灾区", "疫区", "特区", "新区", "旧区", "老区", "北区",
    "南区", "东区", "西区", "中区", "内区", "外区", "上区", "下区",
}

# 行政区名不应以这些动词开头
_NON_ADMIN_PREFIXES = (
    "下载", "搜索", "查找", "找到", "打开", "保存", "导出", "上传",
    "加载", "获取", "请求", "调用", "运行", "执行", "生成", "创建",
    "帮我找", "帮我搜", "帮我查",
)


def _strip_verb_prefix(name: str) -> str:
    """去掉行政区名前面的动词前缀，如 '下载旺苍县' → '旺苍县'"""
    for prefix in _NON_ADMIN_PREFIXES:
        if name.startswith(prefix) and len(name) > len(prefix):
            return name[len(prefix):]
    return name


def _normalize_name(text: str) -> str:
    """标准化名称：去空格、去多余字符"""
    text = str(text or "").strip()
    text = re.sub(r"\s+", "", text)
    return text


def extract_admin_region_name(text: str) -> Optional[str]:
    """
    从用户输入中提取中国行政区名称。
    支持：市、县、区、旗、自治县、自治旗、林区
    优先级：组合名（市+县） > 单独县/区 > 单独市
    """
    raw_matches = []

    # 按优先级匹配：市+县组合 > 县 > 区 > 市
    for pattern in [
        r"([\u4e00-\u9fa5]{2,20}?市[\u4e00-\u9fa5]{2,20}?(?:县|区|旗|自治县|自治旗|林区))",
        r"([\u4e00-\u9fa5]{2,20}?(?:县|自治县|自治旗))",
        r"([\u4e00-\u9fa5]{2,20}?(?:区|旗|林区))",
        r"([\u4e00-\u9fa5]{2,20}?市)",
    ]:
        m = re.search(pattern, text)
        if m:
            raw_matches.append(m.group(1))

    seen = set()
    for name in raw_matches:
        if name in _FAKE_ADMIN_SUFFIXES:
            continue
        cleaned = _strip_verb_prefix(name)
        if cleaned in seen:
            continue
        seen.add(cleaned)
        if len(cleaned) >= 2 and cleaned not in _FAKE_ADMIN_SUFFIXES:
            return cleaned

    return None


def _extract_admin_parts(region_name: str) -> Tuple[Optional[str], Optional[str]]:
    """
    解析行政区名称为 市级部分 和 县级部分。
    示例：
      广元市旺苍县 → ("广元市", "旺苍县")
      旺苍县       → (None, "旺苍县")
      广元市       → ("广元市", None)
      温江区       → (None, "温江区")
    """
    text = _normalize_name(region_name)

    city = None
    county = None

    # 先提取市级（非贪婪，到"市"为止）
    m_city = re.search(r"([\u4e00-\u9fa5]{2,20}?市)", text)
    if m_city:
        city = m_city.group(1)

    # 提取县级：不能包含"市"字，避免把"广元市旺苍县"整体匹配为县
    # 排除"市"字的字符类：[\u4e00-\u9fa5&&[^市]]
    m_county = re.search(r"((?:(?!市)[\u4e00-\u9fa5]){2,20}?(?:县|区|旗|自治县|自治旗|林区))", text)
    if m_county:
        county = m_county.group(1)

    # 避免重复：如 "市辖区" 中 "市" 和 "区" 可能重叠
    if city and county == city:
        county = None

    return city, county


# ============================================================
# 2. GeoJSON 文件发现（核心修复：多策略搜索）
# ============================================================

def _find_geojson_files() -> Tuple[Optional[str], Optional[str]]:
    """
    自动查找本地的中国市级和县级行政区 GeoJSON 文件。
    返回 (city_geojson_path, county_geojson_path)

    搜索策略（按优先级）：
    1. 项目 data/ 目录下的已知文件（最高优先级）
    2. 项目 workspace 目录
    3. 脚本所在目录及子目录
    4. 常见用户目录
    """
    city_path = None
    county_path = None

    # 优先检查项目 data/ 目录下的已知文件
    project_root = Path(__file__).resolve().parent.parent  # opengis/
    data_dir = project_root / "data"
    known_city = data_dir / "中国_市.geojson"
    known_county = data_dir / "中国_县.geojson"
    if known_city.exists():
        city_path = str(known_city)
    if known_county.exists():
        county_path = str(known_county)

    # 如果已找到两个文件，直接返回
    if city_path and county_path:
        return city_path, county_path

    # 收集所有搜索根目录
    search_roots = _collect_search_roots()

    # 收集所有 GeoJSON 文件
    all_geojsons: List[str] = []
    for root in search_roots:
        if not os.path.exists(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            # 限制搜索深度：最多往下 4 层
            depth = dirpath.replace(root, "").count(os.sep)
            if depth > 4:
                dirnames.clear()
                continue
            # 跳过隐藏目录和系统目录
            dirnames[:] = [d for d in dirnames if not d.startswith(".") and d not in (
                "node_modules", "__pycache__", ".git", "venv", ".venv",
            )]
            for fname in filenames:
                if fname.lower().endswith(".geojson"):
                    all_geojsons.append(os.path.join(dirpath, fname))

    # 去重
    all_geojsons = list(dict.fromkeys(all_geojsons))

    # 从文件名分类
    for fpath in all_geojsons:
        fname = Path(fpath).name

        # 城市级
        if city_path is None:
            if any(k in fname for k in ["市", "地级市", "市级", "city"]):
                if "县" not in fname and "区划" not in fname:
                    city_path = fpath
                    continue

        # 县级
        if county_path is None:
            if any(k in fname for k in ["县", "区县", "县级", "county", "district"]):
                if "市" not in fname or "区县" in fname:
                    county_path = fpath
                    continue

    # 如果只找到一个，尝试从内容判断是市还是县
    if city_path is None and county_path is None:
        for fpath in all_geojsons:
            level = _guess_geojson_level(fpath)
            if level == "city" and city_path is None:
                city_path = fpath
            elif level == "county" and county_path is None:
                county_path = fpath

    # 如果只找到一个文件且未分类，检查它是否同时包含市和县
    if city_path is None and county_path is None and len(all_geojsons) == 1:
        sole = all_geojsons[0]
        level = _guess_geojson_level(sole)
        if level == "city":
            city_path = sole
        elif level == "county":
            county_path = sole
        else:
            # 无法判断，假设是县级（更常用）
            county_path = sole

    return city_path, county_path


def _collect_search_roots() -> List[str]:
    """收集所有可能包含 GeoJSON 的搜索根目录"""
    roots = []

    # 1. 项目目录（最关键）
    project_root = Path(__file__).resolve().parent.parent  # agent_package/
    workspace = project_root / "workspace"
    roots.extend([
        str(project_root),
        str(workspace),
        str(project_root / "data"),
        str(project_root / "gis"),
        str(project_root / "geojson"),
        str(workspace / "data"),
    ])

    # 2. 当前工作目录
    cwd = os.getcwd()
    roots.extend([
        cwd,
        os.path.join(cwd, "data"),
        os.path.join(cwd, "workspace"),
        os.path.join(cwd, "gis"),
    ])

    # 3. 用户主目录下的常见位置
    home = str(Path.home())
    roots.extend([
        home,
        os.path.join(home, "Desktop"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Downloads"),
        os.path.join(home, "data"),
        os.path.join(home, "gis"),
        os.path.join(home, "geojson"),
        os.path.join(home, "workspace"),
        os.path.join(home, "workspace", "data"),
    ])

    # 4. 项目配置中的额外路径（不扫描系统目录）
    # 去重并过滤不存在的
    seen = set()
    valid = []
    for r in roots:
        r = os.path.normpath(r)
        if r not in seen and os.path.isdir(r):
            seen.add(r)
            valid.append(r)

    return valid


def _guess_geojson_level(filepath: str) -> Optional[str]:
    """
    通过读取文件内容，根据属性特征判断是市级还是县级 GeoJSON。
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        features = data.get("features", [])
        if not features:
            return None

        # 看前 3 个 feature 的属性
        sample_features = features[:3]
        all_prop_keys = set()
        for feat in sample_features:
            props = feat.get("properties", {})
            all_prop_keys.update(props.keys())

        # 常见的市级属性名
        city_keys = {"市", "city", "CITY", "NAME", "name", "地级市", "prefecture"}
        # 常见的县级属性名
        county_keys = {"县", "区", "county", "COUNTY", "district", "DISTRICT"}

        # 检查属性值中是否包含"市"或"县"/"区"
        for feat in sample_features:
            props = feat.get("properties", {})
            for v in props.values():
                if isinstance(v, str):
                    if v.endswith("市") and len(v) <= 8:
                        return "city"
                    if (v.endswith("县") or v.endswith("区")) and len(v) <= 8:
                        return "county"

        # 检查属性名
        if all_prop_keys & city_keys:
            return "city"
        if all_prop_keys & county_keys:
            return "county"

        return None
    except Exception:
        return None


# ============================================================
# 3. GeoJSON 加载与名称匹配（核心修复：检查所有属性字段）
# ============================================================

def _load_geojson(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _get_feature_name(props: Dict[str, Any]) -> str:
    """
    从 feature 的 properties 中提取名称。
    不硬编码字段名，而是按优先级检查所有常见字段。
    """
    # 优先级：精确的中文行政名字段 > 通用 name 字段 > 第一个字符串值
    priority_keys = [
        "市", "县", "区", "name", "NAME", "Name",
        "NAME_CHN", "name_chn", "市名", "县名", "区名",
        "CITY", "city", "COUNTY", "county", "DISTRICT", "district",
        "fullname", "FULLNAME", "ADMIN_NAME", "admin_name",
        "GB", "gb", "adcode", "ADCODE",
    ]

    for key in priority_keys:
        val = props.get(key)
        if val and isinstance(val, str) and len(val.strip()) >= 2:
            return val.strip()

    # 兜底：取第一个字符串类型的值
    for val in props.values():
        if isinstance(val, str) and len(val.strip()) >= 2:
            return val.strip()

    return ""


def _pick_best_match(
    features: List[Dict[str, Any]],
    target_name: str,
) -> Optional[Dict[str, Any]]:
    """
    在 feature 列表中找到最匹配 target_name 的 feature。
    策略：
    1. 精确匹配（所有属性值）
    2. 去掉"市/县/区"后缀后匹配
    3. 包含匹配
    4. 模糊匹配（编辑距离）
    """
    target = _normalize_name(target_name)
    target_core = re.sub(r"[市县区旗]$", "", target)  # 去后缀

    # ---- 第 1 轮：精确匹配 ----
    for feat in features:
        props = feat.get("properties", {})
        # 检查所有属性值
        for val in props.values():
            if isinstance(val, str) and _normalize_name(val) == target:
                return feat

    # ---- 第 2 轮：去后缀匹配 ----
    for feat in features:
        props = feat.get("properties", {})
        for val in props.values():
            if isinstance(val, str):
                val_norm = _normalize_name(val)
                val_core = re.sub(r"[市县区旗]$", "", val_norm)
                if val_norm == target or val_core == target_core:
                    return feat

    # ---- 第 3 轮：包含匹配 ----
    for feat in features:
        props = feat.get("properties", {})
        name = _get_feature_name(props)
        name_norm = _normalize_name(name)
        if target in name_norm or name_norm in target:
            return feat
        # 也检查所有属性值
        for val in props.values():
            if isinstance(val, str):
                val_norm = _normalize_name(val)
                if target in val_norm or val_norm in target:
                    return feat

    # ---- 第 4 轮：宽松匹配（目标核心词在属性值中）----
    if len(target_core) >= 2:
        for feat in features:
            props = feat.get("properties", {})
            for val in props.values():
                if isinstance(val, str) and target_core in _normalize_name(val):
                    return feat

    return None


def _bbox_of_geometry(geom: Dict[str, Any]) -> List[float]:
    g = shape(geom)
    minx, miny, maxx, maxy = g.bounds
    return [float(minx), float(miny), float(maxx), float(maxy)]


# ============================================================
# 4. 主入口
# ============================================================

def resolve_admin_region(region_name: str) -> Dict[str, Any]:
    """
    根据行政区名称，自动查找本地 GeoJSON 并返回匹配的行政边界。

    流程：
    1. 提取并验证行政区名称
    2. 自动发现本地 GeoJSON 文件
    3. 在 GeoJSON 属性中匹配名称
    4. 返回 GeoJSON Feature + bbox

    Args:
        region_name: 行政区名称，如 "温江区" / "旺苍县" / "广元市旺苍县"

    Returns:
        成功：{"success": True, "region_geojson": {...}, "bbox": [...], ...}
        失败：{"success": False, "message": "原因", ...}
    """
    if not region_name or not str(region_name).strip():
        return {"success": False, "message": "region_name 不能为空"}

    region_name = str(region_name).strip()
    city_name, county_name = _extract_admin_parts(region_name)

    # ---- 步骤 1：发现 GeoJSON 文件 ----
    city_path, county_path = _find_geojson_files()

    if not city_path and not county_path:
        return {
            "success": False,
            "message": (
                f"未找到本地行政区 GeoJSON 文件。"
                f"请确保本地存在中国_市.geojson 和/或 中国_县.geojson 文件，"
                f"并放在项目目录或用户主目录下。"
            ),
            "searched_locations": _collect_search_roots()[:10],
            "hint": "可以将 GeoJSON 文件放在项目根目录的 data/ 子目录下",
        }

    # ---- 步骤 2：加载 GeoJSON ----
    city_features = []
    county_features = []

    if city_path:
        try:
            city_data = _load_geojson(city_path)
            city_features = city_data.get("features", [])
        except Exception as e:
            print(f"[AdminRegion] 加载市级 GeoJSON 失败: {city_path} -> {e}")

    if county_path:
        try:
            county_data = _load_geojson(county_path)
            county_features = county_data.get("features", [])
        except Exception as e:
            print(f"[AdminRegion] 加载县级 GeoJSON 失败: {county_path} -> {e}")

    if not city_features and not county_features:
        return {
            "success": False,
            "message": f"GeoJSON 文件已找到但内容为空或解析失败",
            "city_path": city_path,
            "county_path": county_path,
        }

    # ---- 步骤 3：匹配行政区 ----
    matched_feat = None
    matched_level = None
    matched_name = None

    # 优先县级匹配
    if county_name and county_features:
        matched_feat = _pick_best_match(county_features, county_name)
        if matched_feat:
            matched_level = "county"
            matched_name = _get_feature_name(matched_feat.get("properties", {}))

    # 再查市级
    if not matched_feat and city_name and city_features:
        matched_feat = _pick_best_match(city_features, city_name)
        if matched_feat:
            matched_level = "city"
            matched_name = _get_feature_name(matched_feat.get("properties", {}))

    # 兜底：用完整名称在所有 feature 中搜索
    if not matched_feat:
        # 先搜县级
        if county_features:
            matched_feat = _pick_best_match(county_features, region_name)
            if matched_feat:
                matched_level = "county"
                matched_name = _get_feature_name(matched_feat.get("properties", {}))

        # 再搜市级
        if not matched_feat and city_features:
            matched_feat = _pick_best_match(city_features, region_name)
            if matched_feat:
                matched_level = "city"
                matched_name = _get_feature_name(matched_feat.get("properties", {}))

    # ---- 步骤 4：返回结果 ----
    if not matched_feat:
        # 生成诊断信息
        sample_names = []
        all_features = county_features + city_features
        for feat in all_features[:5]:
            props = feat.get("properties", {})
            name = _get_feature_name(props)
            if name:
                sample_names.append(name)

        return {
            "success": False,
            "message": f"未在 GeoJSON 中找到行政区: {region_name}",
            "query": region_name,
            "parsed_city": city_name,
            "parsed_county": county_name,
            "city_features_count": len(city_features),
            "county_features_count": len(county_features),
            "sample_names": sample_names,
            "city_path": city_path,
            "county_path": county_path,
            "hint": (
                f"GeoJSON 中有 {len(all_features)} 个 feature，"
                f"前几个名称为: {sample_names[:3]}。"
                f"请检查行政区名称是否与 GeoJSON 属性中的名称一致。"
            ),
        }

    props = matched_feat.get("properties", {})
    geom = matched_feat.get("geometry")

    if not geom:
        return {
            "success": False,
            "message": f"匹配到 {matched_name} 但缺少 geometry 字段",
            "properties": props,
        }

    return {
        "success": True,
        "query": region_name,
        "level": matched_level,
        "matched_name": matched_name,
        "properties": dict(props),
        "source_layer": county_path if matched_level == "county" else city_path,
        "bbox": _bbox_of_geometry(geom),
        "region_geojson": {
            "type": "Feature",
            "properties": dict(props),
            "geometry": geom,
        },
    }