"""
Agent 核心引擎 - 完整的 GIS 智能体
系统架构：
  用户输入 → LLM决策 → 工具执行 → 状态更新 → 循环/结束

【修改】
1. _validate_decision 新增时间序列流程校正
2. _has_timelapse_intent 新增
3. 移除规则回退模式，LLM 为唯一决策路径
4. 【修复】添加 region 一致性校验，防止跨任务区域污染
"""

from __future__ import annotations

import re
import traceback
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from agent.memory import MemoryStore
from agent.prompts import DECISION_SYSTEM_PROMPT
from agent.tool_registry import ToolRegistry
from agent.tool import GISRuntime, register_tools
from gis.admin_region import extract_admin_region_name


def _args_similar(a: Dict, b: Dict, keys: List[str] = None) -> bool:
    """判断两组参数是否相似（用于循环检测）"""
    if not a and not b:
        return True
    if keys:
        a = {k: a.get(k) for k in keys if k in a}
        b = {k: b.get(k) for k in keys if k in b}
    common = set(a.keys()) & set(b.keys())
    if not common:
        return False
    return all(a[k] == b[k] for k in common)


# ── 时间序列意图检测（新增）─────────────────────────────

_TIMELAPSE_KEYWORDS = [
    "时间序列", "timelapse", "time lapse", "time-lapse",
    "连续", "多年", "年际", "逐年", "历年",
    "gif", "GIF", "动画", "动图",
    "分屏", "首年", "末年",
    "趋势", "折线", "变化曲线",
]


def _has_timelapse_intent(text: str) -> bool:
    """判断用户是否有时间序列分析意图"""
    for kw in _TIMELAPSE_KEYWORDS:
        if kw in text:
            return True
    # "对比XX年和XX年" 模式
    if re.search(r"对比.*\d{4}.*\d{4}", text):
        return True
    # "XX年到/至XX年" + 可视化/变化
    if re.search(r"\d{4}\s*[-到至]\s*\d{4}", text) and any(k in text for k in ["变化", "可视化", "分析"]):
        return True
    return False


def _pick_timelapse_tool(text: str) -> str:
    """根据用户意图选择具体的 timelapse 工具"""
    t = text.lower()
    if any(k in t for k in ["分屏", "左右", "首年", "末年", "split"]):
        return "gee_lst_split_panel"
    if any(k in t for k in ["趋势", "折线", "曲线", "均值", "变化图", "trend"]):
        return "gee_lst_trend_chart"
    # 默认用本地版（更稳定）
    return "gee_lst_timelapse_local"


def _extract_year_range(text: str) -> tuple[int, int]:
    """从文本中提取年份范围"""
    m = re.search(r"(\d{4})\s*[-到至~]\s*(\d{4})", text)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"连续\s*(\d+)\s*年", text)
    if m:
        n = int(m.group(1))
        end_year = date.today().year - 1
        return end_year - n + 1, end_year
    m = re.search(r"近\s*(\d+)\s*年", text)
    if m:
        n = int(m.group(1))
        end_year = date.today().year - 1
        return end_year - n + 1, end_year
    years = re.findall(r"\b(20\d{2})\b", text)
    if len(years) >= 2:
        y = sorted(int(y) for y in years)
        return y[0], y[-1]
    return 2015, 2024


def _extract_month(text: str) -> int:
    """从文本中提取月份"""
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


def _has_monthly_lst_intent(text: str) -> bool:
    """检测用户是否有月度 LST 合成意图（月份 + 温度/LST 关键词）"""
    t = text.lower()
    has_lst_kw = any(k in t for k in ["地表温度", "lst", "温度反演", "热红外", "地温"])
    has_month_kw = any(k in t for k in ["月度", "月均", "每月", "月平均"])
    has_month_pattern = bool(re.search(r"\d{1,2}\s*月", t)) or bool(re.search(r"年\s*\d{1,2}\s*月", t))
    return has_lst_kw and (has_month_kw or has_month_pattern)


def _has_yearly_lst_intent(text: str) -> bool:
    """检测用户是否有年度批量 LST 意图（全年/12个月 + 温度/LST）"""
    t = text.lower()
    has_lst_kw = any(k in t for k in ["地表温度", "lst", "温度反演", "热红外", "地温"])
    has_yearly_kw = any(k in t for k in ["全年", "12个月", "十二个月", "一年", "逐月", "每个月", "各月", "每月"])
    return has_lst_kw and has_yearly_kw


def _has_multi_year_lst_intent(text: str) -> bool:
    """检测用户是否有跨多年单月 LST 意图（如"2020-2025年每年8月"）"""
    t = text.lower()
    has_lst_kw = any(k in t for k in ["地表温度", "lst", "温度反演", "热红外", "地温"])
    # 匹配 "YYYY-YYYY年每年M月" 或 "YYYY到YYYY年每年M月"
    has_multi_year = bool(re.search(r"\d{4}\s*[-到~]\s*\d{4}\s*年.*每年\s*\d{1,2}\s*月", t))
    # 匹配 "连续N年M月"
    has_consecutive = bool(re.search(r"连续\s*\d+\s*年.*\d{1,2}\s*月", t))
    return has_lst_kw and (has_multi_year or has_consecutive)


def _extract_multi_year_range(text: str) -> tuple[int, int, int]:
    """从文本中提取跨多年范围和月份，如 '2020-2025年每年8月' → (2020, 2025, 8)"""
    # "YYYY-YYYY年每年M月"
    m = re.search(r"(\d{4})\s*[-到~]\s*(\d{4})\s*年.*每年\s*(\d{1,2})\s*月", text)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    # "连续N年M月" → 从当前年往前推
    m = re.search(r"连续\s*(\d+)\s*年.*(\d{1,2})\s*月", text)
    if m:
        n = int(m.group(1))
        month = int(m.group(2))
        from datetime import date
        cur_year = date.today().year
        return cur_year - n + 1, cur_year, month
    return 2020, 2025, 8


# ── 需要研究区的 GEE 工具集合 ──
_GEE_TOOLS_NEEDING_REGION = {
    "gee_download_landsat_sca",
    "gee_download_monthly_lst",
    "gee_download_yearly_lst",
    "gee_download_multi_year_lst",
    "gee_lst_timelapse",
    "gee_lst_timelapse_local",
    "gee_lst_split_panel",
    "gee_lst_trend_chart",
    "gee_timeseries_inspector",
    "gee_chart_timeseries",
    "gee_chart_by_region",
    "gee_chart_phenology",
    "dynamic_world_landcover",
    "gee_download_collection",
    "gee_download_tiled",
    "generate_timeslider_map",
    "ee_unsupervised_classify",
    "ee_supervised_classify",
    "gee_zonal_statistics",
}


def _should_auto_make_map(history: List[Dict[str, Any]]) -> bool:
    """判断是否应在 final 前自动生成专题图"""
    if not history:
        return False
    # 1. 是否有 LST 数据产出
    data_producers = {"run_lst", "gee_download_monthly_lst"}
    map_tools = {"make_thematic_map", "generate_web_map", "classify_map",
                 "gee_lst_timelapse", "gee_lst_timelapse_local", "gee_lst_split_panel",
                 "generate_timeslider_map"}
    last_data_idx = -1
    for i, h in enumerate(history):
        if h.get("tool") in data_producers and h.get("result", {}).get("success"):
            last_data_idx = i
    if last_data_idx < 0:
        return False
    # 2. 数据产出后是否已经制过图
    for h in history[last_data_idx + 1:]:
        if h.get("tool") in map_tools:
            return False
    return True


class GISAgent:
    """
    GIS 智能体

    使用 LLM 进行自主决策，规划并执行 GIS 工作流。
    """

    def __init__(self, max_steps: int = 25, memory_path=None, prefs_path=None) -> None:
        self.max_steps = max_steps
        self.memory = MemoryStore(memory_path=memory_path, preferences_path=prefs_path)
        self.runtime = GISRuntime()
        self.registry = ToolRegistry()
        self._llm = None
        self._llm_available = False

        from agent.llm_client import LLMClient
        self._llm = LLMClient()
        self._llm_available = True

        self._restore_runtime_from_memory()
        register_tools(self.registry, self.runtime, self.memory.preferences)

    def _restore_runtime_from_memory(self) -> None:
        session = self.memory.session
        self.runtime.current_dataset = session.current_dataset
        self.runtime.source_dataset = session.source_dataset
        self.runtime.last_output = session.current_output
        if session.map_style:
            self.runtime.map_style.update(session.map_style)

    # ── 日期 / 行政区辅助 ─────────────────────────────────

    def _default_last_full_month(self) -> tuple[str, str]:
        today = date.today()
        first_day_this_month = today.replace(day=1)
        last_day_prev_month = first_day_this_month - timedelta(days=1)
        first_day_prev_month = last_day_prev_month.replace(day=1)
        return first_day_prev_month.isoformat(), last_day_prev_month.isoformat()

    def _extract_date_range_or_default(self, text: str) -> tuple[str, str]:
        dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
        if dates:
            dates = sorted(dates)
            start_date = dates[0]
            end_date = dates[-1] if len(dates) >= 2 else dates[0]
            return start_date, end_date
        # "YYYY年M月" 模式 → 展开为该月首日~末日
        m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", text)
        if m:
            import calendar
            year, month = int(m.group(1)), int(m.group(2))
            if 1 <= month <= 12:
                last_day = calendar.monthrange(year, month)[1]
                return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day:02d}"
        return self._default_last_full_month()

    def _extract_admin_region_name(self, text: str) -> Optional[str]:
        """调用共享的行政区名称提取函数（避免重复逻辑）"""
        return extract_admin_region_name(text)

    def _has_remote_sensing_download_intent(self, text: str) -> bool:
        t = text.lower()
        has_download = any(k in t for k in ["gee", "earth engine", "landsat", "下载", "从gee"])
        has_lst = any(k in text for k in ["地表温度", "温度反演", "反演", "单通道", "热红外", "lst"])
        return has_download or has_lst

    # ── LLM 决策 ─────────────────────────────────────

    def _decide_llm(
        self,
        user_input: str,
        step: int,
        last_result: Dict[str, Any] | None,
        loop_warning: str = "",
    ) -> Dict[str, Any]:
        payload = {
            "user_input": user_input,
            "step": step,
            "tools": self.registry.manifest(),
            "memory": self.memory.task_context(),
            "runtime": {
                "current_dataset": self.runtime.current_dataset,
                "source_dataset": self.runtime.source_dataset,
                "last_output": self.runtime.last_output,
                "last_region_name": self.runtime.last_region_name,
                "has_last_region_geojson": self.runtime.last_region_geojson is not None,
                "map_style": self.runtime.map_style,
            },
            "last_result": last_result,
            "loop_warning": loop_warning,
        }
        return self._llm.invoke_json(DECISION_SYSTEM_PROMPT, payload)

    # ── 决策后验证：修正 LLM 常见错误 ─────────────────

    def _gee_download_done_in_history(self, history: List[Dict[str, Any]]) -> bool:
        for h in history:
            if h.get("tool") == "gee_download_landsat_sca" and h.get("result", {}).get("success", False):
                return True
        return False

    def _admin_region_done_in_history(self, history: List[Dict[str, Any]]) -> bool:
        for h in history:
            if h.get("tool") == "resolve_admin_region" and h.get("result", {}).get("success", False):
                return True
        return False

    def _validate_decision(
        self,
        decision: Dict[str, Any],
        user_input: str,
        history: List[Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        """
        在 LLM 返回决策后进行校正。
        1) 中国行政区名称研究区：先 resolve_admin_region，再 gee_download_landsat_sca
        2) bbox + 日期：优先 gee_download_landsat_sca
        3) 图例微调 vs 绝对位置
        4) 【新增】时间序列流程：先 resolve_admin_region，再 timelapse 工具
        """
        history = history or []

        if decision.get("type") == "tool_call":
            text = user_input
            admin_name = self._extract_admin_region_name(text)
            has_remote_sensing_intent = self._has_remote_sensing_download_intent(text)
            has_timelapse = _has_timelapse_intent(text)
            bbox_match = re.search(
                r"\[\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*\]",
                text,
            )
            date_matches = re.findall(r"\d{4}-\d{2}-\d{2}", text)
            has_gee_kw = any(k in text.lower() for k in ["gee", "earth engine", "从gee", "landsat"])

            already_resolved = self._admin_region_done_in_history(history)
            already_downloaded = self._gee_download_done_in_history(history)

            # ── 【新增】时间序列流程校正 ──
            # 如果用户有意图做 timelapse 且用了行政区名称，强制先 resolve_admin_region
            if has_timelapse and admin_name:
                timelapse_tools = {"gee_lst_timelapse", "gee_lst_timelapse_local", "gee_lst_split_panel", "gee_lst_trend_chart"}

                # 如果行政区还没解析，强制先解析
                if not already_resolved and decision.get("tool") != "resolve_admin_region":
                    return {
                        "type": "tool_call",
                        "tool": "resolve_admin_region",
                        "args": {"region_name": admin_name},
                        "reason": f"[强制校正] 时间序列分析需要研究区，先解析行政区边界：{admin_name}",
                    }

                # 如果行政区已解析但 LLM 返回的不是 timelapse 工具，强制选择
                if already_resolved and decision.get("tool") not in timelapse_tools:
                    timelapse_tool = _pick_timelapse_tool(text)
                    # 保留 LLM 已提取的参数（LLM 可能已经正确解析了月份/年份）
                    llm_args = decision.get("args") or {}
                    start_year = llm_args.get("start_year")
                    end_year = llm_args.get("end_year")
                    month = llm_args.get("month")
                    if start_year is None or end_year is None:
                        s, e = _extract_year_range(text)
                        start_year = start_year or s
                        end_year = end_year or e
                    if month is None:
                        month = _extract_month(text)
                    return {
                        "type": "tool_call",
                        "tool": timelapse_tool,
                        "args": {
                            "start_year": int(start_year),
                            "end_year": int(end_year),
                            "month": int(month),
                        },
                        "reason": f"[强制校正] 行政区已解析，执行时间序列分析：{start_year}-{end_year}年{month}月",
                    }

            # ── bbox 研究区（优先级最高：有坐标就不走行政区）──
            need_gee_download = bool(
                bbox_match and len(date_matches) >= 1 and (has_gee_kw or len(date_matches) >= 2)
            )
            if need_gee_download and not already_downloaded:
                has_monthly_lst = _has_monthly_lst_intent(text)
                target_tool = "gee_download_monthly_lst" if has_monthly_lst else "gee_download_landsat_sca"
                if decision.get("tool") != target_tool:
                    xmin = float(bbox_match.group(1))
                    ymin = float(bbox_match.group(2))
                    xmax = float(bbox_match.group(3))
                    ymax = float(bbox_match.group(4))
                    start_date, end_date = self._extract_date_range_or_default(text)

                    return {
                        "type": "tool_call",
                        "tool": target_tool,
                        "args": {
                            "region": [xmin, ymin, xmax, ymax],
                            "start_date": start_date,
                            "end_date": end_date,
                        },
                    "reason": f"[强制校正] 本轮尚未执行 GEE 下载，先下载 bbox=[{xmin},{ymin},{xmax},{ymax}] {start_date}~{end_date} 的 Landsat 数据。",
                }

            # ── 行政区名称研究区（仅在无 bbox、无 timelapse 时触发）──
            if admin_name and has_remote_sensing_intent and not bbox_match and not has_timelapse:
                if not already_resolved and decision.get("tool") != "resolve_admin_region":
                    return {
                        "type": "tool_call",
                        "tool": "resolve_admin_region",
                        "args": {"region_name": admin_name},
                        "reason": f"[强制校正] 用户使用行政区名称作为研究区，先解析边界：{admin_name}",
                    }

                if already_resolved and not already_downloaded:
                    # 跨多年单月 > 年度批量 > 月度单月 > 普通下载
                    has_multi_year = _has_multi_year_lst_intent(text)
                    has_yearly = _has_yearly_lst_intent(text)
                    has_monthly = _has_monthly_lst_intent(text)

                    if has_multi_year:
                        sy, ey, mon = _extract_multi_year_range(text)
                        if decision.get("tool") != "gee_download_multi_year_lst":
                            return {
                                "type": "tool_call",
                                "tool": "gee_download_multi_year_lst",
                                "args": {"start_year": sy, "end_year": ey, "month": mon},
                                "reason": f"[强制校正] 行政区边界已解析，执行 {sy}-{ey} 年每年 {mon} 月 LST 批量反演。",
                            }
                    elif has_yearly:
                        import re as _re
                        year_match = _re.search(r"(\d{4})\s*年", text)
                        year = int(year_match.group(1)) if year_match else 2025
                        if decision.get("tool") != "gee_download_yearly_lst":
                            return {
                                "type": "tool_call",
                                "tool": "gee_download_yearly_lst",
                                "args": {"year": year},
                                "reason": f"[强制校正] 行政区边界已解析，执行 {year} 年全年月度 LST 批量反演。",
                            }
                    elif has_monthly:
                        target_tool = "gee_download_monthly_lst"
                        if decision.get("tool") != target_tool:
                            start_date, end_date = self._extract_date_range_or_default(text)
                            return {
                                "type": "tool_call",
                                "tool": target_tool,
                                "args": {
                                    "start_date": start_date,
                                    "end_date": end_date,
                                },
                                "reason": f"[强制校正] 行政区边界已解析，执行月度 LST 合成 {start_date}~{end_date}。",
                            }
                    else:
                        if decision.get("tool") != "gee_download_landsat_sca":
                            start_date, end_date = self._extract_date_range_or_default(text)
                            return {
                                "type": "tool_call",
                                "tool": "gee_download_landsat_sca",
                                "args": {
                                    "start_date": start_date,
                                    "end_date": end_date,
                                },
                                "reason": f"[强制校正] 行政区边界已解析，继续从 GEE 下载 {start_date}~{end_date} 数据。",
                            }

        # ── 图例微调 vs 绝对位置 ──
        if decision.get("type") != "tool_call" or decision.get("tool") != "set_map_style":
            return decision

        args = decision.get("args") or {}
        if "legend_position" not in args:
            return decision

        text = user_input
        shift_match = re.search(r"往\s*(左|右|上|下)\s*(?:边|侧)?\s*(移|挪|推|动)", text)
        nudge_match = re.search(r"(?:稍微|稍)\s*往\s*(左|右|上|下)", text)
        nudge_match2 = re.search(r"往\s*(左|右|上|下)\s*(?:边|侧)?\s*(?:一\s*点|一些|少许)", text)

        if shift_match or nudge_match or nudge_match2:
            direction = (shift_match or nudge_match or nudge_match2).group(1)
            delta = 0.02 if (nudge_match or nudge_match2) and not shift_match else 0.03

            cur_xoff = float(self.runtime.map_style.get("legend_xoffset", 0.0))
            cur_yoff = float(self.runtime.map_style.get("legend_yoffset", 0.0))

            new_args = {k: v for k, v in args.items() if k != "legend_position"}
            if direction == "左":
                new_args["legend_xoffset"] = round(cur_xoff - delta, 4)
            elif direction == "右":
                new_args["legend_xoffset"] = round(cur_xoff + delta, 4)
            elif direction == "上":
                new_args["legend_yoffset"] = round(cur_yoff + delta, 4)
            elif direction == "下":
                new_args["legend_yoffset"] = round(cur_yoff - delta, 4)

            decision["args"] = new_args
            decision["reason"] = decision.get("reason", "") + " [已校正：微调偏移而非绝对位置]"

        return decision

    # ── region 一致性校验 ─────────────────────────────

    def _check_region_consistency(
        self,
        tool: str,
        args: Dict[str, Any],
        user_input: str,
        history: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """
        工具执行前的 region 一致性校验。

        修复：跨任务状态污染的第二道防线。
        如果当前任务的用户输入中提到了行政区名称，但 runtime 中的
        last_region_name 与之不匹配，说明可能存在状态污染，
        强制重新解析行政区边界。

        返回 None 表示一致性检查通过，返回 dict 表示需要替换为该决策。
        """
        # 仅对需要研究区的 GEE 工具做检查
        if tool not in _GEE_TOOLS_NEEDING_REGION:
            return None

        # 如果 args 中已经显式传了 region，不需要检查
        if args.get("region"):
            return None

        # 如果用户输入中没有行政区名称，不需要检查
        admin_name = self._extract_admin_region_name(user_input)
        if not admin_name:
            return None

        # 如果当前任务中已经成功解析了行政区，检查是否匹配
        if self._admin_region_done_in_history(history):
            # 当前任务已有解析结果，检查 runtime 中的名称是否匹配用户输入
            current_region = self.runtime.last_region_name or ""
            # 简单子串匹配：用户输入的行政区名应出现在已解析的名称中
            if admin_name in current_region or current_region in admin_name:
                return None  # 一致，继续执行
            # 不一致，强制重新解析
            return {
                "type": "tool_call",
                "tool": "resolve_admin_region",
                "args": {"region_name": admin_name},
                "reason": f"[region 一致性校验] 用户输入行政区'{admin_name}'与当前研究区'{current_region}'不匹配，重新解析。",
            }

        # 当前任务尚未解析行政区，但用户提到了行政区名称
        # 如果 runtime 中有旧的 region_name，且与当前不匹配，需要重新解析
        if self.runtime.last_region_name and admin_name not in self.runtime.last_region_name:
            return {
                "type": "tool_call",
                "tool": "resolve_admin_region",
                "args": {"region_name": admin_name},
                "reason": f"[region 一致性校验] 用户输入行政区'{admin_name}'与 runtime 中的'{self.runtime.last_region_name}'不匹配，重新解析。",
            }

        return None

    # ── 统一决策 ─────────────────────────────────────

    def _decide(
        self,
        user_input: str,
        step: int,
        last_result: Dict[str, Any] | None,
        history: List[Dict[str, Any]] | None = None,
        loop_warning: str = "",
    ) -> Dict[str, Any]:
        if not self._llm_available:
            raise RuntimeError("LLM 不可用，无法进行决策")

        # ── 前置拦截：GEE/行政区意图时，第一步必须走正确流程 ──
        history = history or []
        if step == 1 and not history:
            forced = self._force_first_step(user_input)
            if forced:
                return forced

        try:
            decision = self._decide_llm(user_input, step, last_result, loop_warning)
            return self._validate_decision(decision, user_input, history)
        except Exception as e:
            raise RuntimeError(f"LLM 决策失败: {e}")

    def _force_first_step(self, user_input: str) -> Optional[Dict[str, Any]]:
        """
        在第一步时强制拦截：如果用户明确要求 GEE 下载/温度反演/时间序列，
        但 LLM 可能错误选择 search_local_files，在这里强制校正。
        """
        text = user_input
        admin_name = self._extract_admin_region_name(text)
        has_gee_kw = any(k in text.lower() for k in ["gee", "earth engine", "从gee", "landsat"])
        has_download = any(k in text for k in ["下载", "获取", "拉取"])
        has_lst = any(k in text for k in ["地表温度", "温度反演", "反演", "单通道", "热红外", "lst"])
        has_timelapse = _has_timelapse_intent(text)
        bbox_match = re.search(
            r"\[\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*\]",
            text,
        )

        # 情况 A：行政区名称 + (下载/温度反演/时间序列) → 先解析行政区
        if admin_name and (has_download or has_lst or has_timelapse or has_gee_kw):
            if has_timelapse:
                return {
                    "type": "tool_call",
                    "tool": "resolve_admin_region",
                    "args": {"region_name": admin_name},
                    "reason": f"[前置拦截] 时间序列分析需要研究区，先解析：{admin_name}",
                }
            # 非时间序列的 GEE 下载流程
            if has_download or has_lst or has_gee_kw:
                return {
                    "type": "tool_call",
                    "tool": "resolve_admin_region",
                    "args": {"region_name": admin_name},
                    "reason": f"[前置拦截] GEE 下载需要研究区，先解析行政区边界：{admin_name}",
                }

        # 情况 B：bbox + 日期 + (下载/温度反演) → 直接 GEE 下载
        if bbox_match and (has_download or has_lst or has_gee_kw):
            start_date, end_date = self._extract_date_range_or_default(text)
            xmin, ymin, xmax, ymax = (
                float(bbox_match.group(1)),
                float(bbox_match.group(2)),
                float(bbox_match.group(3)),
                float(bbox_match.group(4)),
            )
            has_monthly_lst = _has_monthly_lst_intent(text)
            target_tool = "gee_download_monthly_lst" if has_monthly_lst else "gee_download_landsat_sca"
            return {
                "type": "tool_call",
                "tool": target_tool,
                "args": {
                    "region": [xmin, ymin, xmax, ymax],
                    "start_date": start_date,
                    "end_date": end_date,
                },
                "reason": f"[前置拦截] 用户要求从 GEE 下载，直接执行：bbox=[{xmin},{ymin},{xmax},{ymax}] {start_date}~{end_date}",
            }

        return None

    # ── 循环检测 ─────────────────────────────────────

    def _detect_loop(self, history: List[Dict[str, Any]]) -> str:
        if len(history) < 2:
            return ""

        style_calls = [h for h in history if h["tool"] == "set_map_style"]
        if len(style_calls) >= 2:
            return (
                "警告：同一轮对话中 set_map_style 已调用多次。"
                "每次用户输入只允许调整一次样式。"
                "你必须立即返回 final，把当前结果告诉用户。"
            )

        map_calls = [h for h in history if h["tool"] == "make_thematic_map"]
        if len(map_calls) >= 2:
            return (
                "警告：同一轮对话中 make_thematic_map 已调用多次。"
                "出图一次就够了。"
                "你必须立即返回 final，把当前结果告诉用户。"
            )

        if len(history) >= 3:
            last_tool = history[-1]["tool"]
            if all(h["tool"] == last_tool for h in history[-3:]):
                return f"警告：{last_tool} 已连续调用 3 次。你必须立即返回 final。"

        if len(history) >= 4:
            recent = [h["tool"] for h in history[-4:]]
            if recent == ["set_map_style", "make_thematic_map", "set_map_style", "make_thematic_map"]:
                return "警告：set_map_style 和 make_thematic_map 已交替循环。你必须立即返回 final。"

        return ""

    # ── 主执行流程 ───────────────────────────────────

    def run(self, user_input: str) -> Dict[str, Any]:
        self.memory.start_new_task(user_input)
        self.runtime.reset_for_new_task()  # 重置运行时状态，防止跨任务污染
        history: List[Dict[str, Any]] = []
        last_result: Dict[str, Any] | None = None
        final_answer = ""
        forced_stop = False

        for step in range(1, self.max_steps + 1):
            loop_warning = self._detect_loop(history)

            try:
                decision = self._decide(
                    user_input=user_input,
                    step=step,
                    last_result=last_result,
                    history=history,
                    loop_warning=loop_warning,
                )
            except Exception as exc:
                final_answer = f"决策失败: {exc}"
                break

            if decision.get("type") == "final":
                # 如果已产出 LST 数据但还没制专题图，自动补一张
                if _should_auto_make_map(history):
                    try:
                        map_result = self.registry.call("make_thematic_map", {})
                        if "success" not in map_result:
                            map_result["success"] = True
                    except Exception as exc:
                        map_result = {"success": False, "message": str(exc)}
                    self.memory.append_event(
                        step=step, tool="make_thematic_map", args={},
                        result=map_result, reason="LST 反演完成后自动生成专题图",
                    )
                    self.memory.mark_completed("make_thematic_map")
                    self.memory.session.map_style = dict(self.runtime.map_style)
                    self.memory.save()
                    history.append({
                        "step": step, "tool": "make_thematic_map", "args": {},
                        "reason": "LST 反演完成后自动生成专题图", "result": map_result,
                    })
                    last_result = map_result
                final_answer = decision.get("answer", "任务完成。")
                break

            if decision.get("type") != "tool_call":
                final_answer = f"Agent 返回了无效决策: {decision}"
                break

            tool = str(decision.get("tool", "")).strip()
            args = decision.get("args") or {}
            reason = str(decision.get("reason", "")).strip()

            # ── 【修复】region 一致性校验（第二道防线）──
            region_fix = self._check_region_consistency(tool, args, user_input, history)
            if region_fix:
                # region 不一致，强制重新解析行政区
                tool = region_fix["tool"]
                args = region_fix["args"]
                reason = region_fix["reason"]

            if history and history[-1]["tool"] == "set_map_style" and tool != "make_thematic_map":
                tool = "make_thematic_map"
                args = {}
                reason = "自动触发：样式更新后必须重新出图"

            try:
                result = self.registry.call(tool, args)
                if "success" not in result:
                    result["success"] = True
            except Exception as exc:
                result = {
                    "success": False,
                    "message": str(exc),
                    "traceback": traceback.format_exc(limit=4),
                }

            self.memory.append_event(step=step, tool=tool, args=args, result=result, reason=reason)
            self.memory.mark_completed(tool)
            self.memory.session.map_style = dict(self.runtime.map_style)
            self.memory.save()

            record = {"step": step, "tool": tool, "args": args, "reason": reason, "result": result}
            history.append(record)
            last_result = result

            # ── 【新增】GEE 未认证时自动调用 gee_init ──
            if not result.get("success") and result.get("requires") == "gee_init":
                print("[Agent] GEE 未认证，自动执行 gee_init...")
                try:
                    gee_result = self.registry.call("gee_init", {})
                    gee_record = {
                        "step": step,
                        "tool": "gee_init",
                        "args": {},
                        "reason": "GEE 未认证，自动初始化",
                        "result": gee_result,
                    }
                    history.append(gee_record)
                    self.memory.append_event(
                        step=step, tool="gee_init", args={},
                        result=gee_result, reason="自动 GEE 初始化",
                    )
                    if not gee_result.get("success"):
                        final_answer = (
                            f"GEE 认证失败：{gee_result.get('message', '')}。"
                            "请手动执行 gee_init（输入'初始化GEE'）完成 Google 账号授权。"
                        )
                        break
                    # 认证成功，下一步会重新调用原工具
                except Exception as gee_exc:
                    final_answer = f"GEE 初始化异常: {gee_exc}。请手动输入'初始化GEE'完成授权。"
                    break

            if tool == "set_map_style" and result.get("success", False):
                try:
                    render_result = self.registry.call("make_thematic_map", {})
                    if "success" not in render_result:
                        render_result["success"] = True
                except Exception as exc:
                    render_result = {"success": False, "message": str(exc)}

                self.memory.append_event(
                    step=step,
                    tool="make_thematic_map",
                    args={},
                    result=render_result,
                    reason="样式更新后自动重新出图",
                )
                self.memory.mark_completed("make_thematic_map")
                self.memory.session.map_style = dict(self.runtime.map_style)
                self.memory.save()

                render_record = {
                    "step": step,
                    "tool": "make_thematic_map",
                    "args": {},
                    "reason": "样式更新后自动重新出图",
                    "result": render_result,
                }
                history.append(render_record)
                last_result = render_result

            if loop_warning and len(history) >= 2:
                forced_stop = True
                final_answer = f"检测到执行循环，自动终止。{result.get('message', '已完成，请查看输出文件。')}"
                break

            if not result.get("success", False) and step >= max(3, self.max_steps - 2):
                final_answer = result.get("message", "执行失败")
                break
        else:
            if history and history[-1]["result"].get("success"):
                last_msg = history[-1]["result"].get("message", "")
                final_answer = f"已完成 {len(history)} 步操作。{last_msg}"
            else:
                final_answer = f"已执行 {len(history)} 步，任务可能需要更多调整。"

        mode_info = "LLM模式"
        agent_result = {
            "success": bool(history) and history[-1]["result"].get("success", False),
            "goal": user_input,
            "mode": mode_info,
            "history": history,
            "final_answer": final_answer,
            "forced_stop": forced_stop,
            "memory": self.memory.task_context(),
            "runtime": {
                "current_dataset": self.runtime.current_dataset,
                "source_dataset": self.runtime.source_dataset,
                "last_output": self.runtime.last_output,
                "last_region_name": self.runtime.last_region_name,
                "map_style": self.runtime.map_style,
            },
        }
        run_log = self.memory.write_run_log(agent_result)
        agent_result["run_log"] = run_log
        return agent_result
