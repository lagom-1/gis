"""
安全守卫 - 循环检测、自动出图判断、意图检测
所有硬编码的工具特定验证逻辑集中在这里，每条规则独立方法，易测试、易修改。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


class SafetyGuard:
    """Agent 安全守卫：循环检测 + 自动出图判断"""

    def __init__(self, max_map_calls=2, max_style_calls=2, max_consecutive_same=3,
                 max_download_calls=5, max_set_dataset_calls=4):
        self.max_map_calls = max_map_calls
        self.max_style_calls = max_style_calls
        self.max_consecutive_same = max_consecutive_same
        self.max_download_calls = max_download_calls
        self.max_set_dataset_calls = max_set_dataset_calls

    # 所有下载类工具
    _DOWNLOAD_TOOLS = {
        "gee_download_landsat_sca", "gee_download_monthly_lst",
        "gee_download_yearly_lst", "gee_download_multi_year_lst",
        "gee_compute_lst", "gee_download_lst",
    }

    # 幂等工具：一次成功后禁止再调
    _IDEMPOTENT_ONCE = {"resolve_admin_region", "gee_init"}

    def check(self, history: List[Dict[str, Any]]) -> str:
        """检查历史记录，返回停止原因或空字符串"""
        if len(history) < 2:
            return ""

        # ── 单工具总次数限制 ──

        # set_current_dataset 同轮调用超过限制 → 强制制图
        set_calls = [h for h in history if h.get("tool") == "set_current_dataset"]
        if len(set_calls) >= self.max_set_dataset_calls:
            return (
                f"set_current_dataset 已调用 {len(set_calls)} 次。"
                "请停止切换数据集，对当前数据集调用 make_thematic_map 生成专题图。你必须立即返回 final。"
            )

        # set_map_style 同轮调用两次
        style_calls = [h for h in history if h.get("tool") == "set_map_style"]
        if len(style_calls) >= self.max_style_calls:
            return "同一轮对话中 set_map_style 已调用多次。每次用户输入只允许调整一次样式。你必须立即返回 final。"

        # make_thematic_map 同轮调用两次
        map_calls = [h for h in history if h.get("tool") == "make_thematic_map"]
        if len(map_calls) >= self.max_map_calls:
            return "同一轮对话中 make_thematic_map 已调用多次。出图一次就够了。你必须立即返回 final。"

        # 下载工具总次数限制
        for tool_name in self._DOWNLOAD_TOOLS:
            dl_calls = [h for h in history if h.get("tool") == tool_name]
            if len(dl_calls) >= self.max_download_calls:
                return (
                    f"{tool_name} 已调用 {len(dl_calls)} 次。数据下载已超过限制，"
                    "文件要么已存在要么无法获取。你必须立即返回 final，汇总已下载的结果。"
                )

        # ── 连续调用检测 ──

        # download 工具连续调用 2 次
        if len(history) >= 2:
            last_two = [h.get("tool") for h in history[-2:]]
            if last_two[0] == last_two[1] and last_two[0] in self._DOWNLOAD_TOOLS:
                return f"{last_two[0]} 已连续调用 2 次，数据已下载完毕，禁止重复下载。你必须立即返回 final。"

        # 参数级去重：同一工具 + 相同 args → 禁止重复
        last = history[-1]
        last_tool = last.get("tool")
        last_args = last.get("args", {})
        if last_tool and last_args:
            for h in history[:-1]:
                if h.get("tool") == last_tool and h.get("args") == last_args:
                    return (
                        f"{last_tool} 已用相同参数 {last_args} 调用过。"
                        "结果应当已存在，禁止重复调用。你必须立即返回 final。"
                    )

        # 幂等工具：已成功执行过则禁止重复调用；失败时允许用户纠正参数后重试
        if last_tool in self._IDEMPOTENT_ONCE:
            prev_success = [
                h for h in history[:-1]
                if h.get("tool") == last_tool and h.get("result", {}).get("success")
            ]
            if prev_success:
                return f"{last_tool} 已成功执行过，禁止重复调用。请使用已有结果继续下一步。你必须立即返回 final。"

        # 同一工具连续 3 次
        if len(history) >= 3:
            last_tool = history[-1].get("tool")
            if all(h.get("tool") == last_tool for h in history[-3:]):
                return f"{last_tool} 已连续调用 3 次。你必须立即返回 final。"

        # ── 交替循环检测 ──

        # style ↔ map 交替
        if len(history) >= 4:
            recent = [h.get("tool") for h in history[-4:]]
            if recent == ["set_map_style", "make_thematic_map", "set_map_style", "make_thematic_map"]:
                return "set_map_style 和 make_thematic_map 已交替循环。你必须立即返回 final。"

        # 通用交替检测：任意两个工具 A↔B 交替 3 个周期（6 步）
        if len(history) >= 6:
            recent6 = [h.get("tool") for h in history[-6:]]
            a, b = recent6[0], recent6[1]
            if a != b and recent6 == [a, b, a, b, a, b]:
                return (
                    f"{a} 和 {b} 已交替循环 3 轮。"
                    "不要再继续这个循环，使用已有数据进入下一阶段（制图/输出）。你必须立即返回 final。"
                )

        return ""

    def should_auto_map(self, history: List[Dict[str, Any]]) -> bool:
        """判断是否应在 final 前自动生成专题图"""
        if not history:
            return False
        data_producers = {"run_lst", "gee_compute_lst", "gee_download_monthly_lst",
                         "gee_download_yearly_lst", "gee_download_multi_year_lst",
                         "gee_download_landsat_sca"}
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
    if re.search(r"\d{4}\s*[-到至]\s*\d{4}") and any(
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
