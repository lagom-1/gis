"""
多轮对话式 GIS 智能体

与 GISAgent（一次性执行）的区别：
- handle_message() 逐轮执行，而非 run() 全自动跑完
- 注入完整对话历史到 LLM 上下文
- 支持 ask_user 决策类型（反问用户）
- 通过 event_callback 推送实时事件（SSE 用）
- 状态持久化到 DB conversation_states 表
"""
from __future__ import annotations

import re
import traceback
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional

from agent.core import (
    GISAgent,
    _has_timelapse_intent,
    _extract_month,
    _extract_year_range,
    _pick_timelapse_tool,
    _has_monthly_lst_intent,
    _has_yearly_lst_intent,
    _has_multi_year_lst_intent,
    _extract_multi_year_range,
    _should_auto_make_map,
    _args_similar,
)
from agent.memory import MemoryStore
from agent.tool_registry import ToolRegistry
from agent.tool import GISRuntime  # V2 GISRuntime（有 to_dict/from_dict）
from agent.prompts.system import CONVERSATIONAL_SYSTEM_PROMPT
from gis.admin_region import extract_admin_region_name


class ConversationalAgent:
    """
    多轮对话式 GIS 智能体。

    每个 handle_message() 调用对应一轮对话：
    1. 加载会话状态和消息历史
    2. 构建含完整历史上下文的 LLM prompt
    3. 决策循环 (max 15 步/轮)
    4. 通过 event_callback 推送实时事件
    5. 持久化状态和消息
    """

    def __init__(
        self,
        conversation_id: int,
        max_steps_per_turn: int = 15,
        state: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.conversation_id = conversation_id
        self.max_steps_per_turn = max_steps_per_turn
        self.runtime = GISRuntime()
        self.registry = ToolRegistry(self.runtime)
        self.memory = MemoryStore()
        self._llm = None
        self._llm_available = False

        from agent.llm_client import LLMClient
        self._llm = LLMClient()
        self._llm_available = True

        # 注册工具
        from agent.tool import register_tools as _register_all
        _register_all(self.registry, self.runtime, self.memory.preferences)

        # 恢复之前保存的会话状态
        if state:
            self._restore_state(state)

    # ── 状态序列化 ─────────────────────────────────────

    def _restore_state(self, state: Dict[str, Any]) -> None:
        """从 DB 加载的 dict 恢复运行时状态。"""
        self.runtime.from_dict(state)
        self.memory.from_dict(state)

    def get_state(self) -> Dict[str, Any]:
        """获取当前运行时状态的 dict 形式（用于持久化到 DB）。"""
        runtime_state = self.runtime.to_dict()
        memory_state = self.memory.to_dict()
        return {**runtime_state, **memory_state}

    # ── Agent 核心流程（逐轮执行）─────────────────────

    def handle_message(
        self,
        user_message: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        event_callback: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        处理一条用户消息，返回最终结果。

        Args:
            user_message: 用户的输入文本
            conversation_history: 之前的消息列表 [{role, content, tool_name, ...}, ...]
            event_callback: SSE 事件回调函数 (event_type, data)

        Returns:
            {
                "success": bool,
                "type": "final" | "ask_user",   # 本轮结束原因
                "answer": str,                   # final 时的回复文本
                "question": str,                 # ask_user 时的问题
                "options": List[str],            # ask_user 时的选项
                "history": List[dict],           # 本轮工具调用历史
                "state": dict,                   # 持久化的 runtime 状态
            }
        """
        history: List[Dict[str, Any]] = []
        last_result: Optional[Dict[str, Any]] = None
        final_answer = ""
        forced_stop = False

        def _emit(event_type: str, data: Dict[str, Any]) -> None:
            if event_callback:
                try:
                    event_callback(event_type, data)
                except Exception:
                    pass  # 忽略回调异常

        for step in range(1, self.max_steps_per_turn + 1):
            loop_warning = self._detect_loop(history)

            if loop_warning:
                forced_stop = True
                if _should_auto_make_map(history):
                    try:
                        map_result = self.registry.call("make_thematic_map", {})
                        if "success" not in map_result:
                            map_result["success"] = True
                    except Exception as exc:
                        map_result = {"success": False, "message": str(exc)}
                    history.append({
                        "step": step, "tool": "make_thematic_map", "args": {},
                        "reason": "循环检测触发前自动生成专题图", "result": map_result,
                    })
                    last_result = map_result
                final_answer = f"{loop_warning}\n\n{last_result.get('message', '任务已完成。')}"
                _emit("final_answer", {"content": final_answer})
                break

            try:
                decision = self._decide(
                    user_message=user_message,
                    step=step,
                    last_result=last_result,
                    history=history,
                    conversation_history=conversation_history or [],
                    loop_warning=loop_warning,
                )
            except Exception as exc:
                final_answer = f"决策失败: {exc}"
                _emit("error", {"message": str(exc)})
                break

            _emit("step_start", {"step": step, "max": self.max_steps_per_turn})

            # ── final ──
            if decision.get("type") == "final":
                if _should_auto_make_map(history):
                    try:
                        map_result = self.registry.call("make_thematic_map", {})
                        if "success" not in map_result:
                            map_result["success"] = True
                    except Exception as exc:
                        map_result = {"success": False, "message": str(exc)}
                    history.append({
                        "step": step, "tool": "make_thematic_map", "args": {},
                        "reason": "自动生成专题图", "result": map_result,
                    })
                    last_result = map_result
                    _emit("tool_result", {"tool": "make_thematic_map", "result": map_result})
                final_answer = decision.get("answer", "任务完成。")
                _emit("final_answer", {"content": final_answer})
                break

            # ── ask_user ──
            if decision.get("type") == "ask_user":
                _emit("ask_user", {
                    "question": decision.get("question", ""),
                    "options": decision.get("options", []),
                })
                return {
                    "success": True,
                    "type": "ask_user",
                    "question": decision.get("question", ""),
                    "options": decision.get("options", []),
                    "history": history,
                    "state": self.get_state(),
                }

            # ── tool_call ──
            if decision.get("type") != "tool_call":
                final_answer = f"Agent 返回了无效决策: {decision}"
                _emit("error", {"message": final_answer})
                break

            tool = str(decision.get("tool", "")).strip()
            args = decision.get("args") or {}
            reason = str(decision.get("reason", "")).strip()

            _emit("tool_start", {"tool": tool, "args": args, "reason": reason})

            # 执行工具
            try:
                result = self.registry.call(tool, args)
                if "success" not in result:
                    result["success"] = False
            except Exception as exc:
                result = {
                    "success": False,
                    "message": str(exc),
                    "traceback": traceback.format_exc(limit=4),
                }

            _emit("tool_result", {"tool": tool, "result": result})

            history.append({
                "step": step, "tool": tool, "args": args,
                "reason": reason, "result": result,
            })
            last_result = result

            # set_map_style 成功后自动出图
            if tool == "set_map_style" and result.get("success", False):
                try:
                    render_result = self.registry.call("make_thematic_map", {})
                    if "success" not in render_result:
                        render_result["success"] = False
                except Exception as exc:
                    render_result = {"success": False, "message": str(exc)}

                history.append({
                    "step": step, "tool": "make_thematic_map", "args": {},
                    "reason": "样式更新后自动重新出图", "result": render_result,
                })
                last_result = render_result
                _emit("tool_result", {"tool": "make_thematic_map", "result": render_result})

            # 失败时允许重试
            if not result.get("success", False):
                consecutive_failures = sum(
                    1 for r in history[-3:]
                    if not r.get("result", {}).get("success", True)
                )
                if step >= max(5, self.max_steps_per_turn - 3) and consecutive_failures >= 2:
                    final_answer = result.get("message", "执行失败")
                    _emit("error", {"message": final_answer})
                    break
        else:
            if history and history[-1]["result"].get("success"):
                last_msg = history[-1]["result"].get("message", "")
                final_answer = f"已完成 {len(history)} 步操作。{last_msg}"
            else:
                final_answer = f"已执行 {len(history)} 步，任务可能需要更多调整。"

        return {
            "success": bool(history) and history[-1]["result"].get("success", False),
            "type": "final",
            "answer": final_answer,
            "history": history,
            "forced_stop": forced_stop,
            "state": self.get_state(),
        }

    # ── LLM 决策 ─────────────────────────────────────

    def _decide(
        self,
        user_message: str,
        step: int,
        last_result: Optional[Dict[str, Any]],
        history: List[Dict[str, Any]],
        conversation_history: List[Dict[str, Any]],
        loop_warning: str = "",
    ) -> Dict[str, Any]:
        if not self._llm_available:
            raise RuntimeError("LLM 不可用")

        # 构建含对话历史的 prompt
        conversation_text = _format_conversation_history(conversation_history, user_message)

        payload = {
            "user_input": user_message,
            "conversation_history": conversation_text,
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

        try:
            decision = self._llm.invoke_json(CONVERSATIONAL_SYSTEM_PROMPT, payload)
            return self._validate_decision(decision, user_message, history)
        except Exception as e:
            raise RuntimeError(f"LLM 决策失败: {e}")

    # ── 决策验证（复用 GISAgent 的逻辑）──────────────

    def _validate_decision(
        self,
        decision: Dict[str, Any],
        user_input: str,
        history: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        从 GISAgent._validate_decision 提取的逻辑，适配 ConversationalAgent。
        关键检查：GEE 工作流顺序、行政区解析前置、timelapse 流程校正、图例微调。
        """
        if decision.get("type") != "tool_call":
            return decision

        text = user_input
        admin_name = extract_admin_region_name(text)
        has_remote_sensing = any(k in text.lower() for k in ["gee", "earth engine", "landsat", "下载", "从gee"])
        has_lst = any(k in text for k in ["地表温度", "温度反演", "反演", "单通道", "热红外", "lst"])
        has_gee_intent = has_remote_sensing or has_lst
        has_timelapse = _has_timelapse_intent(text)
        bbox_match = re.search(
            r"\[\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*\]",
            text,
        )
        date_matches = re.findall(r"\d{4}-\d{2}-\d{2}", text)
        has_gee_kw = any(k in text.lower() for k in ["gee", "earth engine", "从gee", "landsat"])

        already_resolved = self._admin_region_done_in_history(history)
        already_downloaded = self._gee_download_done_in_history(history)

        # ── 时间序列流程校正 ──
        if has_timelapse and admin_name:
            timelapse_tools = {
                "gee_lst_timelapse", "gee_lst_timelapse_local",
                "gee_lst_split_panel", "gee_lst_trend_chart",
            }
            if not already_resolved and decision.get("tool") != "resolve_admin_region":
                return {
                    "type": "tool_call",
                    "tool": "resolve_admin_region",
                    "args": {"region_name": admin_name},
                    "reason": f"[强制校正] 时间序列分析需要研究区，先解析：{admin_name}",
                }
            if already_resolved and decision.get("tool") not in timelapse_tools:
                timelapse_tool = _pick_timelapse_tool(text)
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
                    "reason": f"[强制校正] 行政区已解析，执行时间序列：{start_year}-{end_year}年{month}月",
                }

        # ── bbox 研究区 ──
        need_gee_download = bool(
            bbox_match and len(date_matches) >= 1 and (has_gee_kw or len(date_matches) >= 2)
        )
        if need_gee_download and not already_downloaded:
            has_monthly = _has_monthly_lst_intent(text)
            target_tool = "gee_download_monthly_lst" if has_monthly else "gee_compute_lst"
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
                    "reason": f"[强制校正] bbox=[{xmin},{ymin},{xmax},{ymax}]",
                }

        # ── 行政区研究区（无 bbox、无 timelapse）──
        if admin_name and has_gee_intent and not bbox_match and not has_timelapse:
            if not already_resolved and decision.get("tool") != "resolve_admin_region":
                return {
                    "type": "tool_call",
                    "tool": "resolve_admin_region",
                    "args": {"region_name": admin_name},
                    "reason": f"[强制校正] 先解析行政区边界：{admin_name}",
                }
            if already_resolved and not already_downloaded:
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
                            "reason": f"[强制校正] 执行 {sy}-{ey} 年每年 {mon} 月 LST",
                        }
                elif has_yearly:
                    import re as _re2
                    year_match = _re2.search(r"(\d{4})\s*年", text)
                    year = int(year_match.group(1)) if year_match else 2025
                    if decision.get("tool") != "gee_download_yearly_lst":
                        return {
                            "type": "tool_call",
                            "tool": "gee_download_yearly_lst",
                            "args": {"year": year},
                            "reason": f"[强制校正] 执行 {year} 年全年月度 LST",
                        }
                elif has_monthly:
                    if decision.get("tool") != "gee_download_monthly_lst":
                        start_date, end_date = self._extract_date_range_or_default(text)
                        return {
                            "type": "tool_call",
                            "tool": "gee_download_monthly_lst",
                            "args": {"start_date": start_date, "end_date": end_date},
                            "reason": f"[强制校正] 月度 LST 合成 {start_date}~{end_date}",
                        }
                else:
                    if decision.get("tool") != "gee_compute_lst":
                        start_date, end_date = self._extract_date_range_or_default(text)
                        return {
                            "type": "tool_call",
                            "tool": "gee_compute_lst",
                            "args": {"start_date": start_date, "end_date": end_date},
                            "reason": f"[强制校正] GEE 云端反演 LST {start_date}~{end_date}",
                        }

        # ── 图例微调 vs 绝对位置 ──
        if decision.get("tool") == "set_map_style":
            args = decision.get("args") or {}
            if "legend_position" in args:
                shift_match = re.search(r"往\s*(左|右|上|下)\s*(?:边|侧)?\s*(移|挪|推|动)", text)
                nudge_match = re.search(r"(?:稍微|稍)\s*往\s*(左|右|上|下)", text)
                if shift_match or nudge_match:
                    direction = (shift_match or nudge_match).group(1)
                    delta = 0.02 if nudge_match and not shift_match else 0.03
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

        return decision

    # ── 辅助方法 ─────────────────────────────────────

    def _detect_loop(self, history: List[Dict[str, Any]]) -> str:
        """循环检测（复用 GISAgent 逻辑）。"""
        if len(history) < 2:
            return ""

        style_calls = [h for h in history if h["tool"] == "set_map_style"]
        if len(style_calls) >= 2:
            return "警告：同一轮对话中 set_map_style 已调用多次。你必须立即返回 final。"

        map_calls = [h for h in history if h["tool"] == "make_thematic_map"]
        if len(map_calls) >= 15:
            return "警告：同一轮对话中 make_thematic_map 已调用超过 15 次。你必须立即返回 final。"

        set_calls = [h for h in history if h.get("tool") == "set_current_dataset"]
        if len(set_calls) >= 15:
            return "警告：同一轮对话中 set_current_dataset 已调用超过 15 次。请对当前数据集制图后 final。"

        _download_tools = {
            "gee_download_landsat_sca", "gee_download_monthly_lst",
            "gee_download_yearly_lst", "gee_download_multi_year_lst",
        }
        if len(history) >= 2:
            last_two = [h["tool"] for h in history[-2:]]
            if last_two[0] == last_two[1] and last_two[0] in _download_tools:
                return f"警告：{last_two[0]} 已连续调用 2 次。你必须立即返回 final。"

        if len(history) >= 3:
            last_tool = history[-1]["tool"]
            if all(h["tool"] == last_tool for h in history[-3:]):
                return f"警告：{last_tool} 已连续调用 3 次。你必须立即返回 final。"

        if len(history) >= 4:
            recent = [h["tool"] for h in history[-4:]]
            if recent == ["set_map_style", "make_thematic_map", "set_map_style", "make_thematic_map"]:
                return "警告：set_map_style 和 make_thematic_map 已交替循环。你必须立即返回 final。"

        return ""

    def _admin_region_done_in_history(self, history: List[Dict[str, Any]]) -> bool:
        for h in history:
            if h.get("tool") == "resolve_admin_region" and h.get("result", {}).get("success", False):
                return True
        return False

    def _gee_download_done_in_history(self, history: List[Dict[str, Any]]) -> bool:
        for h in history:
            if h.get("tool") in (
                "gee_download_landsat_sca", "gee_compute_lst",
                "gee_download_monthly_lst", "gee_download_yearly_lst",
                "gee_download_multi_year_lst",
            ) and h.get("result", {}).get("success", False):
                return True
        return False

    def _extract_date_range_or_default(self, text: str) -> tuple[str, str]:
        today = date.today()
        first_day_this_month = today.replace(day=1)
        last_day_prev_month = first_day_this_month - timedelta(days=1)
        first_day_prev_month = last_day_prev_month.replace(day=1)

        dates = re.findall(r"\d{4}-\d{2}-\d{2}", text)
        if dates:
            dates = sorted(dates)
            return dates[0], dates[-1] if len(dates) >= 2 else dates[0]
        m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", text)
        if m:
            import calendar
            year, month = int(m.group(1)), int(m.group(2))
            if 1 <= month <= 12:
                last_day = calendar.monthrange(year, month)[1]
                return f"{year}-{month:02d}-01", f"{year}-{month:02d}-{last_day:02d}"
        return first_day_prev_month.isoformat(), last_day_prev_month.isoformat()


# ── 对话历史格式化 ──────────────────────────────────────────

def _format_conversation_history(
    messages: List[Dict[str, Any]],
    current_user_message: str,
    max_messages: int = 30,
) -> str:
    """将对话历史格式化为 LLM 可读的文本。"""
    if not messages:
        return f"[用户]: {current_user_message}"

    # 截断到最近 N 条
    truncated = messages[-max_messages:] if len(messages) > max_messages else messages

    lines = []
    for msg in truncated:
        role = msg.get("role", "")
        content = msg.get("content", "")
        tool_name = msg.get("tool_name", "")
        tool_result = msg.get("tool_result")

        if role == "user":
            lines.append(f"[用户]: {content}")
        elif role == "assistant":
            lines.append(f"[助手]: {content}")
        elif role == "tool_call":
            lines.append(f"[助手]: (调用 {tool_name})")
        elif role == "tool_result":
            if isinstance(tool_result, dict):
                ok = tool_result.get("success", False)
                msg_text = tool_result.get("message", "")[:80]
                lines.append(f"[系统]: {tool_name} {'成功' if ok else '失败'} - {msg_text}")
        elif role == "system":
            lines.append(f"[系统]: {content}")

    # 加上当前消息
    lines.append(f"\n[用户]（当前消息）: {current_user_message}")

    return "\n".join(lines)
