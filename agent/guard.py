"""
安全守卫 - 循环检测、自动出图判断、意图检测
所有硬编码的工具特定验证逻辑集中在这里，每条规则独立方法，易测试、易修改。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class SafetyGuard:
    """Agent 安全守卫：循环检测 + 自动出图判断"""

    def __init__(self, max_map_calls=2, max_style_calls=2, max_consecutive_same=3):
        self.max_map_calls = max_map_calls
        self.max_style_calls = max_style_calls
        self.max_consecutive_same = max_consecutive_same

    def check(self, history: List[Dict[str, Any]]) -> str:
        """检查历史记录，返回停止原因或空字符串"""
        if len(history) < 2:
            return ""

        # set_map_style 同轮调用两次
        style_calls = [h for h in history if h.get("tool") == "set_map_style"]
        if len(style_calls) >= self.max_style_calls:
            return "同一轮对话中 set_map_style 已调用多次。每次用户输入只允许调整一次样式。你必须立即返回 final。"

        # make_thematic_map 同轮调用两次
        map_calls = [h for h in history if h.get("tool") == "make_thematic_map"]
        if len(map_calls) >= self.max_map_calls:
            return "同一轮对话中 make_thematic_map 已调用多次。出图一次就够了。你必须立即返回 final。"

        # 下载工具连续调用 2 次
        _download_tools = {
            "gee_download_landsat_sca", "gee_download_monthly_lst",
            "gee_download_yearly_lst", "gee_download_multi_year_lst",
        }
        if len(history) >= 2:
            last_two = [h.get("tool") for h in history[-2:]]
            if last_two[0] == last_two[1] and last_two[0] in _download_tools:
                return f"{last_two[0]} 已连续调用 2 次，数据已下载完毕，禁止重复下载。你必须立即返回 final。"

        # 同一工具连续 3 次
        if len(history) >= 3:
            last_tool = history[-1].get("tool")
            if all(h.get("tool") == last_tool for h in history[-3:]):
                return f"{last_tool} 已连续调用 3 次。你必须立即返回 final。"

        # set_map_style ↔ make_thematic_map 交替循环
        if len(history) >= 4:
            recent = [h.get("tool") for h in history[-4:]]
            if recent == ["set_map_style", "make_thematic_map", "set_map_style", "make_thematic_map"]:
                return "set_map_style 和 make_thematic_map 已交替循环。你必须立即返回 final。"

        return ""

    def should_auto_map(self, history: List[Dict[str, Any]]) -> bool:
        """判断是否应在 final 前自动生成专题图"""
        if not history:
            return False
        data_producers = {"run_lst", "gee_compute_lst", "gee_download_monthly_lst"}
        map_tools = {
            "make_thematic_map", "generate_web_map", "classify_map",
            "gee_lst_timelapse", "gee_lst_timelapse_local",
            "gee_lst_split_panel", "generate_timeslider_map",
        }
        last_data_idx = -1
        for i, h in enumerate(history):
            if h.get("tool") in data_producers and h.get("result", {}).get("success"):
                last_data_idx = i
        if last_data_idx < 0:
            return False
        for h in history[last_data_idx + 1:]:
            if h.get("tool") in map_tools:
                return False
        return True


# ── 意图检测工具函数 ───────────────────────────────

_TIMELAPSE_KEYWORDS = [
    "时间序列", "timelapse", "time lapse", "time-lapse",
    "连续", "多年", "年际", "逐年", "历年",
    "gif", "GIF", "动画", "动图",
    "分屏", "首年", "末年",
    "趋势", "折线", "变化曲线",
]


def has_timelapse_intent(text: str) -> bool:
    for kw in _TIMELAPSE_KEYWORDS:
        if kw in text:
            return True
    if re.search(r"对比.*\d{4}.*\d{4}", text):
        return True
    if re.search(r"\d{4}\s*[-到至]\s*\d{4}", text) and any(
        k in text for k in ["变化", "可视化", "分析"]
    ):
        return True
    return False


def has_monthly_lst_intent(text: str) -> bool:
    t = text.lower()
    has_lst = any(k in t for k in ["地表温度", "lst", "温度反演", "热红外", "地温"])
    has_month = any(k in t for k in ["月度", "月均", "每月", "月平均"])
    has_month_pattern = bool(re.search(r"\d{1,2}\s*月", t)) or bool(re.search(r"年\s*\d{1,2}\s*月", t))
    return has_lst and (has_month or has_month_pattern)


def has_yearly_lst_intent(text: str) -> bool:
    t = text.lower()
    has_lst = any(k in t for k in ["地表温度", "lst", "温度反演", "热红外", "地温"])
    has_yearly = any(k in t for k in ["全年", "12个月", "十二个月", "一年", "逐月", "每个月", "各月", "每月"])
    return has_lst and has_yearly


def has_multi_year_lst_intent(text: str) -> bool:
    t = text.lower()
    has_lst = any(k in t for k in ["地表温度", "lst", "温度反演", "热红外", "地温"])
    has_multi = bool(re.search(r"\d{4}\s*[-到~]\s*\d{4}\s*年.*?\d{1,2}\s*月", t))
    has_consecutive = bool(re.search(r"连续\s*\d+\s*年.*\d{1,2}\s*月", t))
    return has_lst and (has_multi or has_consecutive)


def extract_year_range(text: str) -> tuple:
    m = re.search(r"(\d{4})\s*[-到至~]\s*(\d{4})", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"连续\s*(\d+)\s*年", text)
    if m:
        from datetime import date
        n = int(m.group(1))
        end_year = date.today().year - 1
        return end_year - n + 1, end_year
    years = re.findall(r"\b(20\d{2})\b", text)
    if len(years) >= 2:
        y = sorted(int(y) for y in years)
        return y[0], y[-1]
    return 2015, 2024


def extract_month(text: str) -> int:
    month_map = {
        "一月": 1, "二月": 2, "三月": 3, "四月": 4,
        "五月": 5, "六月": 6, "七月": 7, "八月": 8,
        "九月": 9, "十月": 10, "十一月": 11, "十二月": 12,
    }
    for zh, val in month_map.items():
        if zh in text:
            return val
    m = re.search(r"(\d{1,2})\s*月", text)
    if m:
        v = int(m.group(1))
        if 1 <= v <= 12:
            return v
    if any(k in text for k in ["夏季", "夏天"]):
        return 7
    if any(k in text for k in ["冬季", "冬天"]):
        return 1
    if any(k in text for k in ["春季", "春天"]):
        return 4
    if any(k in text for k in ["秋季", "秋天"]):
        return 10
    return 7


def extract_multi_year_range(text: str) -> tuple:
    m = re.search(r"(\d{4})\s*[-到~]\s*(\d{4})\s*年.*?(\d{1,2})\s*月", text)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    m = re.search(r"连续\s*(\d+)\s*年.*(\d{1,2})\s*月", text)
    if m:
        from datetime import date
        n = int(m.group(1))
        month = int(m.group(2))
        cur_year = date.today().year
        return cur_year - n + 1, cur_year, month
    return 2020, 2025, 8


def pick_timelapse_tool(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["分屏", "左右", "首年", "末年", "split"]):
        return "gee_lst_split_panel"
    if any(k in t for k in ["趋势", "折线", "曲线", "均值", "变化图", "trend"]):
        return "gee_lst_trend_chart"
    return "gee_lst_timelapse_local"
