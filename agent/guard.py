"""
安全守卫 - 只拦截真正的危险模式（数据重复下载、幂等重调）
已移除所有频次/次数限制，允许 Agent 自由调用工具
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class SafetyGuard:
    """Agent 安全守卫：仅拦截危险操作，不限制调用频次"""

    def __init__(self, max_download_calls=5, **_kwargs):
        self.max_download_calls = max_download_calls

    _DOWNLOAD_TOOLS = {
        "gee_download_landsat_sca", "gee_download_monthly_lst",
        "gee_download_yearly_lst", "gee_download_multi_year_lst",
        "gee_compute_lst", "gee_download_lst",
    }

    _IDEMPOTENT_ONCE = {"resolve_admin_region", "gee_init"}

    def check(self, history: List[Dict[str, Any]]) -> str:
        if len(history) < 2:
            return ""

        # ── 下载工具连续 2 次 → 拦截（防止无限重下）──
        if len(history) >= 2:
            last_two = [h.get("tool") for h in history[-2:]]
            if last_two[0] == last_two[1] and last_two[0] in self._DOWNLOAD_TOOLS:
                return f"{last_two[0]} 已连续调用 2 次，数据已下载。请使用已有数据继续下一步。"

        # ── 下载工具总次数限制 ──
        for tool_name in self._DOWNLOAD_TOOLS:
            dl_calls = [h for h in history if h.get("tool") == tool_name]
            if len(dl_calls) >= self.max_download_calls:
                return f"{tool_name} 已调用 {len(dl_calls)} 次，已达上限。请使用已有数据。"

        # ── 幂等工具：成功后禁止重调 ──
        last = history[-1]
        last_tool = last.get("tool")
        if last_tool in self._IDEMPOTENT_ONCE:
            prev_success = [
                h for h in history[:-1]
                if h.get("tool") == last_tool and h.get("result", {}).get("success")
            ]
            if prev_success:
                return f"{last_tool} 已成功执行过，请继续下一步。"

        # ── 参数去重：同一工具+相同参数且已成功 → 拦截（仅下载工具）──
        last_args = last.get("args", {})
        if last_tool and last_args and last_tool in self._DOWNLOAD_TOOLS:
            for h in history[:-1]:
                if h.get("tool") == last_tool and h.get("args") == last_args and h.get("result", {}).get("success"):
                    return f"{last_tool} 已用相同参数成功执行，请继续下一步。"

        return ""

    def should_auto_map(self, history: List[Dict[str, Any]]) -> bool:
        if not history:
            return False
        data_producers = {"run_lst", "gee_compute_lst", "gee_download_monthly_lst",
                         "gee_download_yearly_lst", "gee_download_multi_year_lst",
                         "gee_download_landsat_sca"}
        map_tools = {"make_thematic_map", "generate_web_map", "classify_map",
                     "gee_lst_timelapse", "gee_lst_timelapse_local",
                     "gee_lst_split_panel", "generate_timeslider_map"}
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


# ── 意图检测工具函数（不变） ──

_TIMELAPSE_KEYWORDS = [
    "时间序列", "timelapse", "time lapse", "time-lapse",
    "连续", "多年", "年际", "逐年", "历年",
    "gif", "GIF", "动画", "动图", "分屏", "首年", "末年", "趋势", "折线", "变化曲线",
]

def has_timelapse_intent(text: str) -> bool:
    for kw in _TIMELAPSE_KEYWORDS:
        if kw in text: return True
    if re.search(r"对比.*\d{4}.*\d{4}", text): return True
    if re.search(r"\d{4}\s*[-到至]\s*\d{4}") and any(k in text for k in ["变化", "可视化", "分析"]): return True
    return False

def has_monthly_lst_intent(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in ["地表温度", "lst", "温度反演", "热红外", "地温"]) and (
        any(k in t for k in ["月度", "月均", "每月", "月平均"]) or bool(re.search(r"\d{1,2}\s*月", t))
    )

def has_yearly_lst_intent(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in ["地表温度", "lst", "温度反演", "热红外", "地温"]) and (
        any(k in t for k in ["全年", "12个月", "十二个月", "一年", "逐月", "每个月", "各月", "每月"])
    )

def has_multi_year_lst_intent(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in ["地表温度", "lst", "温度反演", "热红外", "地温"]) and (
        bool(re.search(r"\d{4}\s*[-到~]\s*\d{4}\s*年.*?\d{1,2}\s*月", t)) or
        bool(re.search(r"连续\s*\d+\s*年.*\d{1,2}\s*月", t))
    )

def extract_year_range(text: str) -> tuple:
    m = re.search(r"(\d{4})\s*[-到至~]\s*(\d{4})", text)
    if m: return int(m.group(1)), int(m.group(2))
    years = re.findall(r"\b(20\d{2})\b", text)
    if len(years) >= 2:
        y = sorted(int(y) for y in years)
        return y[0], y[-1]
    return 2015, 2024

def extract_month(text: str) -> int:
    for zh, val in {"一月":1, "二月":2, "三月":3, "四月":4, "五月":5, "六月":6, "七月":7, "八月":8, "九月":9, "十月":10, "十一月":11, "十二月":12}.items():
        if zh in text: return val
    m = re.search(r"(\d{1,2})\s*月", text)
    if m:
        v = int(m.group(1))
        if 1 <= v <= 12: return v
    if "夏季" in text: return 7
    if "冬季" in text: return 1
    return 7

def extract_multi_year_range(text: str) -> tuple:
    m = re.search(r"(\d{4})\s*[-到~]\s*(\d{4})\s*年.*?(\d{1,2})\s*月", text)
    if m: return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return 2020, 2025, 8

def pick_timelapse_tool(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ["分屏", "左右", "首年", "末年", "split"]): return "gee_lst_split_panel"
    if any(k in t for k in ["趋势", "折线", "曲线", "均值", "变化图", "trend"]): return "gee_lst_trend_chart"
    return "gee_lst_timelapse_local"
