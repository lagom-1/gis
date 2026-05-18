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

    def _correct_decision(self, decision: dict, history: list) -> dict:
        """简化的决策校正：防止幂等工具重复调用，确保工作流顺序正确"""
        if decision.get("type") != "tool_call":
            return decision

        tool = decision.get("tool")

        # resolve_admin_region 已成功调用过，禁止再次调用
        if tool == "resolve_admin_region":
            for h in history:
                if h.get("tool") == "resolve_admin_region" and h.get("result", {}).get("success"):
                    region = self.runtime.last_region_name or "未知区域"
                    return {
                        "type": "final",
                        "answer": f"行政区边界已解析完成（{region}），请使用已解析的研究区继续执行 GEE 数据下载或分析。",
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
