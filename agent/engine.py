"""
Agent 引擎 - 纯 LLM 决策 → 工具执行循环

不含任何工具特定逻辑，所有验证规则在 SafetyGuard 中。
支持两种使用方式：
1. CLI 一次性执行：agent.run(user_input)
2. Web 多轮对话：agent.run(user_input, conversation_history=..., on_event=...)
"""
from __future__ import annotations

import traceback
from typing import Any, Callable, Dict, List, Optional

from agent.context import build_context
from agent.guard import SafetyGuard


class AgentLoop:
    """GIS Agent 主循环引擎"""

    def __init__(
        self,
        llm,
        registry,
        runtime,
        guard: Optional[SafetyGuard] = None,
        max_steps: int = 25,
    ):
        self.llm = llm
        self.registry = registry
        self.runtime = runtime
        self.guard = guard or SafetyGuard()
        self.max_steps = max_steps

    # 数据生产工具：调用成功后表示已有数据可用
    _DATA_PRODUCERS = {
        "run_lst", "gee_compute_lst", "gee_download_monthly_lst",
        "gee_download_yearly_lst", "gee_download_multi_year_lst",
        "gee_download_landsat_sca",
    }

    # 所有数据相关工具（含搜索/查看），在已有数据后禁止调用
    _DATA_TOOLS = _DATA_PRODUCERS | {"search_local_files", "inspect_raster",
                                      "gee_download_lst", "gee_init"}

    def _correct_decision(self, decision: dict, history: list) -> dict:
        """决策校正：防止无意义的重复调用，但不阻止多步骤数据生产（如多月份/多年份 LST）"""
        if decision.get("type") != "tool_call":
            return decision

        tool = decision.get("tool")
        args = decision.get("args") or {}

        # resolve_admin_region 已调用过（无论成功与否），禁止再次调用
        if tool == "resolve_admin_region":
            for h in history:
                if h.get("tool") == "resolve_admin_region":
                    if h.get("result", {}).get("success"):
                        region = self.runtime.last_region_name or "未知区域"
                        return {
                            "type": "final",
                            "answer": f"行政区边界已解析完成（{region}），请使用已解析的研究区继续执行 GEE 数据下载或分析。",
                        }
                    return {
                        "type": "final",
                        "answer": "行政区边界解析失败，请检查区域名称是否正确，或手动提供 GeoJSON 边界文件。",
                    }

        # gee_init 成功后禁止重复调用；失败时允许用户提供新 project ID 重试
        if tool == "gee_init":
            for h in history:
                if h.get("tool") == "gee_init" and h.get("result", {}).get("success"):
                    return {
                        "type": "final",
                        "answer": "GEE 已成功初始化，请直接进行数据下载或分析。",
                    }

        # set_current_dataset 切换到已激活的数据集 → 阻止
        if tool == "set_current_dataset" and self.runtime.current_dataset:
            target = args.get("path", "")
            if target and target == self.runtime.current_dataset:
                return {
                    "type": "final",
                    "answer": "当前数据集已经是目标文件，无需重复切换。如需对此数据制图，请直接调用 make_thematic_map。",
                }

        # set_current_dataset 调用超过 4 次 → 提示制图
        set_calls = [h for h in history if h.get("tool") == "set_current_dataset"]
        if tool == "set_current_dataset" and len(set_calls) >= 4:
            return {
                "type": "final",
                "answer": "已多次切换数据集。请对当前数据集调用 make_thematic_map 生成专题图，不要再继续切换。",
            }
        search_count = sum(1 for h in history if h.get("tool") == "search_local_files")
        inspect_count = sum(1 for h in history if h.get("tool") == "inspect_raster")
        searched_enough = search_count >= 2 and inspect_count >= 1

        if searched_enough:
            if tool in self._DATA_TOOLS:
                return {
                    "type": "final",
                    "answer": "本地文件已找到并检查过，无需继续搜索。请直接对已有数据调用 make_thematic_map 生成专题图，然后输出结果。",
                }

        # 参数级去重：同一工具 + 相同参数 → 拦截（SafetyGuard 也会做，这里提前拦截更高效）
        if tool in self._DATA_PRODUCERS:
            for h in history:
                if h.get("tool") == tool and h.get("args") == args and h.get("result", {}).get("success"):
                    return {
                        "type": "final",
                        "answer": f"{tool} 已用相同参数 {args} 成功执行过。请继续下一步，使用已有数据生成专题图或处理其他月份/年份。",
                    }

        return decision

    def run(
        self,
        user_input: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        """
        执行 Agent 循环

        Args:
            user_input: 用户输入文本
            conversation_history: 之前的对话历史
            on_event: SSE 事件回调 (event_type, data)

        Returns:
            {"success": bool, "type": "final"|"ask_user", "answer": str, "history": list, "state": dict}
        """
        history: List[Dict[str, Any]] = []
        last_result: Optional[Dict[str, Any]] = None
        final_answer = ""
        forced_stop = False

        def emit(event_type: str, data: Dict[str, Any]):
            if on_event:
                try:
                    on_event(event_type, data)
                except Exception:
                    pass

        for step in range(1, self.max_steps + 1):
            # ── 1. 安全检查 ──
            loop_warning = self.guard.check(history)
            if loop_warning:
                forced_stop = True
                if self.guard.should_auto_map(history):
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
                    emit("tool_result", {"tool": "make_thematic_map", "result": map_result})
                final_answer = f"{loop_warning}\n\n{last_result.get('message', '任务已完成。')}"
                emit("final_answer", {"content": final_answer})
                break

            emit("step_start", {"step": step, "max": self.max_steps})

            # ── 2. LLM 决策 ──
            try:
                runtime_state = {
                    "current_dataset": self.runtime.current_dataset,
                    "source_dataset": self.runtime.source_dataset,
                    "last_output": self.runtime.last_output,
                    "last_region_name": self.runtime.last_region_name,
                    "has_last_region_geojson": self.runtime.last_region_geojson is not None,
                    "map_style": self.runtime.map_style,
                }
                payload = build_context(
                    user_input=user_input,
                    step=step,
                    runtime=runtime_state,
                    history=history,
                    tools_manifest=self.registry.manifest(),
                    conversation_history=conversation_history,
                    loop_warning=loop_warning,
                )
                from agent.prompts.system import CONVERSATIONAL_SYSTEM_PROMPT
                decision = self.llm.invoke_json(CONVERSATIONAL_SYSTEM_PROMPT, payload)
                # ── 2.5 决策校正 ──
                decision = self._correct_decision(decision, history)
            except Exception as exc:
                final_answer = f"决策失败: {exc}"
                emit("error", {"message": str(exc)})
                break

            # ── 3. final ──
            if decision.get("type") == "final":
                if self.guard.should_auto_map(history):
                    try:
                        map_result = self.registry.call("make_thematic_map", {})
                        if "success" not in map_result:
                            map_result["success"] = True
                    except Exception as exc:
                        map_result = {"success": False, "message": str(exc)}
                    history.append({
                        "step": step, "tool": "make_thematic_map", "args": {},
                        "reason": "LST 反演完成后自动生成专题图", "result": map_result,
                    })
                    last_result = map_result
                    emit("tool_result", {"tool": "make_thematic_map", "result": map_result})
                final_answer = decision.get("answer", "任务完成。")
                emit("final_answer", {"content": final_answer})
                break

            # ── 4. ask_user ──
            if decision.get("type") == "ask_user":
                emit("ask_user", {
                    "question": decision.get("question", ""),
                    "options": decision.get("options", []),
                })
                return {
                    "success": True,
                    "type": "ask_user",
                    "question": decision.get("question", ""),
                    "options": decision.get("options", []),
                    "history": history,
                    "state": self.runtime.to_dict(),
                }

            # ── 5. tool_call ──
            if decision.get("type") != "tool_call":
                final_answer = f"Agent 返回了无效决策: {decision}"
                emit("error", {"message": final_answer})
                break

            tool = str(decision.get("tool", "")).strip()
            args = decision.get("args") or {}
            reason = str(decision.get("reason", "")).strip()

            emit("tool_start", {"tool": tool, "args": args, "reason": reason})

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

            emit("tool_result", {"tool": tool, "result": result})

            history.append({
                "step": step, "tool": tool, "args": args,
                "reason": reason, "result": result,
            })
            last_result = result

            # GEE 未认证时自动重试
            if not result.get("success") and result.get("requires") == "gee_init":
                try:
                    gee_result = self.registry.call("gee_init", {})
                    if gee_result.get("success"):
                        result = self.registry.call(tool, args)
                        if "success" not in result:
                            result["success"] = False
                        emit("tool_result", {"tool": tool, "result": result})
                        history[-1]["result"] = result
                        last_result = result
                except Exception:
                    pass

            # set_map_style 后自动出图
            if tool == "set_map_style" and result.get("success", False):
                try:
                    render = self.registry.call("make_thematic_map", {})
                    if "success" not in render:
                        render["success"] = False
                except Exception as exc:
                    render = {"success": False, "message": str(exc)}
                history.append({
                    "step": step, "tool": "make_thematic_map", "args": {},
                    "reason": "样式更新后自动重新出图", "result": render,
                })
                last_result = render
                emit("tool_result", {"tool": "make_thematic_map", "result": render})

            # 失败时允许重试，接近 max_steps 且连续失败则终止
            if not result.get("success", False):
                failures = sum(
                    1 for r in history[-3:]
                    if not r.get("result", {}).get("success", True)
                )
                if step >= max(5, self.max_steps - 3) and failures >= 2:
                    final_answer = result.get("message", "执行失败")
                    emit("error", {"message": final_answer})
                    break
        else:
            if history and history[-1].get("result", {}).get("success"):
                last_msg = history[-1]["result"].get("message", "")
                final_answer = f"已完成 {len(history)} 步操作。{last_msg}"
            else:
                final_answer = f"已执行 {len(history)} 步，任务可能需要更多调整。"

        emit("done", {})
        return {
            "success": bool(history) and history[-1].get("result", {}).get("success", False),
            "type": "final",
            "answer": final_answer,
            "history": history,
            "forced_stop": forced_stop,
            "state": self.runtime.to_dict(),
        }
