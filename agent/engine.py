"""
Agent 引擎 - 纯 LLM 决策 → 工具执行循环

不含任何工具特定逻辑，所有验证规则在 SafetyGuard 中。
支持两种使用方式：
1. CLI 一次性执行：agent.run(user_input)
2. Web 多轮对话：agent.run(user_input, conversation_history=..., on_event=...)
"""
from __future__ import annotations

import os
import re
import traceback
from typing import Any, Callable, Dict, List, Optional

from agent.context import build_context
from agent.guard import SafetyGuard

# ── 错误分类 ──────────────────────────────────────────

def classify_error(error: Exception, tool: str) -> Dict[str, Any]:
    """将异常分类为可操作的结构化错误"""
    msg = str(error)
    # 可重试的网络错误
    if any(k in msg for k in ("Connection", "Timeout", "ConnectTimeout", "Max retries")):
        return {
            "error_type": "RETRYABLE",
            "suggestion": f"网络连接失败，可以重试 {tool}。如果持续失败，请检查网络或 GEE 服务状态。",
        }
    # GEE 认证错误
    if any(k in msg for k in ("认证", "auth", "credentials", "ee.Initialize")):
        return {
            "error_type": "AUTH_REQUIRED",
            "suggestion": "GEE 未认证，请调用 gee_init 进行认证，或提供正确的 project_id。",
        }
    # 文件/路径错误
    if any(k in msg for k in ("文件不存在", "No such file", "FileNotFound", "没有可用栅格")):
        return {
            "error_type": "FILE_NOT_FOUND",
            "suggestion": "文件未找到，请先搜索本地文件或检查文件路径是否正确。",
        }
    # OOM 错误
    if any(k in msg for k in ("MemoryError", "OOM", "内存")):
        return {
            "error_type": "OOM",
            "suggestion": "内存不足，建议缩小研究区范围或降低分辨率。",
        }
    # 默认
    return {
        "error_type": "UNKNOWN",
        "suggestion": f"{tool} 执行失败，请检查参数是否正确。如果问题持续，请换一种方式描述需求。",
    }


# ── UI 渲染协议 ───────────────────────────────────────

# 工具 → 渲染类型映射
_TOOL_UI_ACTIONS: Dict[str, str] = {
    "make_thematic_map": "RENDER_IMAGE",
    "classify_map": "RENDER_IMAGE",
    "view_3d": "RENDER_IMAGE",
    "threshold_highlight": "RENDER_IMAGE",
    "enhance_raster": "RENDER_IMAGE",
    "compare_views": "RENDER_COMPARISON",
    "profile_analysis": "RENDER_CHART",
    "statistics": "RENDER_CHART",
    "gee_lst_timelapse": "RENDER_ANIMATION",
    "gee_lst_timelapse_local": "RENDER_ANIMATION",
    "gee_lst_split_panel": "RENDER_COMPARISON",
    "gee_lst_trend_chart": "RENDER_CHART",
    "generate_web_map": "RENDER_MAP",
    "generate_timeslider_map": "RENDER_MAP",
    "generate_report": "RENDER_HTML",
    "dynamic_world_landcover": "RENDER_IMAGE",
}


def get_ui_action(tool: str, result: Dict[str, Any]) -> str:
    """根据工具和执行结果，确定前端应有的渲染行为"""
    if not result.get("success"):
        return "NONE"
    # 显式映射
    if tool in _TOOL_UI_ACTIONS:
        return _TOOL_UI_ACTIONS[tool]
    # 根据输出文件类型推断
    for key in ("output_gif",):
        if result.get(key):
            return "RENDER_ANIMATION"
    for key in ("output_html",):
        if result.get(key):
            return "RENDER_HTML"
    for key in ("output_png", "output_tif"):
        if result.get(key):
            return "RENDER_IMAGE"
    return "NONE"


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
    # 注意：search_local_files 是只读检索工具，不应被拦截（文件目录动态变化）
    _DATA_TOOLS = _DATA_PRODUCERS | {"inspect_raster",
                                      "gee_download_lst", "gee_init"}

    # GEE 工具链依赖顺序
    _GEE_TOOLS = _DATA_PRODUCERS | {"gee_compute_lst", "gee_lst_timelapse",
                                     "gee_lst_timelapse_local", "gee_lst_split_panel",
                                     "gee_lst_trend_chart"}

    def _correct_decision(self, decision: dict, history: list, user_input: str = "") -> dict:
        """决策校正：GEE 工作流顺序 + 去重 + 循环防护"""
        if decision.get("type") != "tool_call":
            return decision

        tool = decision.get("tool")
        args = decision.get("args") or {}

        # ── 0. GEE 工具链强制顺序：resolve_admin_region 必须先行 ──
        if tool in self._GEE_TOOLS:
            admin_resolved = any(
                h.get("tool") == "resolve_admin_region"
                and h.get("result", {}).get("success")
                for h in history
            )
            if not admin_resolved:
                # 尝试从用户输入中提取行政区名称
                from gis.admin_region import extract_admin_region_name
                region_name = extract_admin_region_name(user_input)
                if region_name:
                    return {
                        "type": "tool_call",
                        "tool": "resolve_admin_region",
                        "args": {"region_name": region_name},
                        "reason": f"[强制校正] GEE 操作前必须先解析行政区: {region_name}",
                    }

        # ── 1. resolve_admin_region 已调用过 → 禁止再次调用 ──
        if tool == "resolve_admin_region":
            for h in history:
                if h.get("tool") == "resolve_admin_region":
                    if h.get("result", {}).get("success"):
                        region = self.runtime.last_region_name or "未知区域"
                        # 如果有 GEE 工具失败过，不要强制 final——允许 Agent 重试其他工具
                        last_gee_failed = any(
                            h2.get("tool") in self._GEE_TOOLS and not h2.get("result", {}).get("success")
                            for h2 in history
                        )
                        if not last_gee_failed:
                            return {
                                "type": "final",
                                "answer": f"行政区边界已解析完成（{region}），请使用已解析的研究区继续执行 GEE 数据下载或分析。",
                            }
                    else:
                        return {
                            "type": "final",
                            "answer": "行政区边界解析失败，请检查区域名称是否正确，或手动提供 GeoJSON 边界文件。",
                        }

        # ── 2. gee_init 成功后禁止重复调用 ──
        if tool == "gee_init":
            for h in history:
                if h.get("tool") == "gee_init" and h.get("result", {}).get("success"):
                    return {
                        "type": "final",
                        "answer": "GEE 已成功初始化，请直接进行数据下载或分析。",
                    }

        # ── 3. set_current_dataset 同路径 → 自动转制图（不拦截，不跳转）──
        if tool == "set_current_dataset" and self.runtime.current_dataset:
            target = args.get("path", "")
            if target and target == self.runtime.current_dataset:
                pass  # 允许重复设置，不拦截

        # ── 4. 参数级去重：仅下载工具的相同参数拦截 ──
        if tool in self._DATA_PRODUCERS:
            for h in history:
                if h.get("tool") == tool and h.get("args") == args and h.get("result", {}).get("success"):
                    return {
                        "type": "final",
                        "answer": f"{tool} 已用相同参数 {args} 成功执行过。请继续下一步，使用已有数据生成专题图或处理其他月份/年份。",
                    }

        return decision

    # ── 复合指令动词→工具映射 ──
    _VERB_TOOL_MAP = {
        "分类": "classify_map", "classify": "classify_map",
        "增强": "enhance_raster", "去噪": "enhance_raster", "降噪": "enhance_raster",
        "统计": "statistics", "直方图": "statistics",
        "剖面": "profile_analysis", "剖面线": "profile_analysis",
        "3d": "view_3d", "三维": "view_3d", "地形": "view_3d",
        "对比": "compare_views",
        "报告": "generate_report", "导出": "export_result",
        "制图": "make_thematic_map", "出图": "make_thematic_map",
        "动画": "gee_lst_timelapse_local", "gif": "gee_lst_timelapse_local",
        "趋势": "gee_lst_trend_chart",
        "卷帘": "compare_views",
        "换配色": "set_map_style", "改配色": "set_map_style", "调色": "set_map_style",
        "指北针": "set_map_style", "标题": "set_map_style",
        "配色": "set_map_style", "调色盘": "set_map_style",
    }

    def _parse_pending_subtasks(self, user_input: str) -> list:
        """从用户输入中提取复合动作，返回待执行的工具名列表（保持出现顺序）"""
        seen = set()
        tasks = []
        for verb, tool in self._VERB_TOOL_MAP.items():
            if verb in user_input and tool not in seen:
                seen.add(tool)
                tasks.append(tool)
        return tasks

    def _get_pending_subtasks(self, history: list, user_input: str) -> list:
        """返回尚未成功执行的子任务"""
        all_needed = self._parse_pending_subtasks(user_input)
        if len(all_needed) <= 1:
            return []  # 只有0或1个任务，不需监工
        # 查找已成功执行的工具
        executed_ok = {
            h.get("tool") for h in history
            if h.get("tool") and h.get("tool") != "__system_hint__"
            and h.get("result", {}).get("success") is not False
        }
        return [t for t in all_needed if t not in executed_ok]

    def _get_next_unmapped_file(self, history: list) -> str | None:
        """找到批量下载产生但尚未制图的文件列表中的下一个待处理 TIF"""
        # 1. 找到最近的数据生产工具调用，提取其 output_files
        all_output_tifs = []
        for h in history:
            if h.get("tool") in self._DATA_PRODUCERS and h.get("result", {}).get("success"):
                of = h["result"].get("output_files", [])
                for f in of:
                    tif_path = f.get("path", "")
                    if tif_path and tif_path.endswith(".tif"):
                        if tif_path not in all_output_tifs:
                            all_output_tifs.append(tif_path)

        if len(all_output_tifs) <= 1:
            return None  # 只有 0 或 1 个文件，无需批量处理

        # 2. 找到已被 make_thematic_map 处理过的 TIF
        mapped_tifs = set()
        for h in history:
            if h.get("tool") == "set_current_dataset":
                tif_path = h.get("args", {}).get("path", "")
                if tif_path:
                    # 检查这个 set_current_dataset 之后是否有 make_thematic_map
                    step_idx = history.index(h)
                    for later_h in history[step_idx:]:
                        if later_h.get("tool") == "make_thematic_map" and later_h.get("result", {}).get("success"):
                            mapped_tifs.add(tif_path)
                            break

        # 也检查直接传 tif_path 给 make_thematic_map 的情况
        for h in history:
            if h.get("tool") == "make_thematic_map" and h.get("result", {}).get("success"):
                tif_path = h.get("args", {}).get("tif_path", "")
                if tif_path:
                    mapped_tifs.add(tif_path)

        # 3. 返回第一个未制图的 TIF
        for tif_path in all_output_tifs:
            if tif_path not in mapped_tifs:
                return tif_path

        return None

    def run(
        self,
        user_input: str,
        conversation_history: Optional[List[Dict[str, Any]]] = None,
        on_event: Optional[Callable[[str, Dict[str, Any]], None]] = None,
        progress_callback: Optional[Callable[[int, str, str], None]] = None,
    ) -> Dict[str, Any]:
        """
        执行 Agent 循环

        Args:
            user_input: 用户输入文本
            conversation_history: 之前的对话历史
            on_event: SSE 事件回调 (event_type, data)
            progress_callback: 进度回调 (step, tool_name, detail)，用于任务系统

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
                    emit("tool_result", {"tool": "make_thematic_map", "result": map_result, "ui_action": "RENDER_IMAGE"})
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
                pending = self._get_pending_subtasks(history, user_input)
                payload = build_context(
                    user_input=user_input,
                    step=step,
                    runtime=runtime_state,
                    history=history,
                    tools_manifest=self.registry.manifest(),
                    conversation_history=conversation_history,
                    loop_warning=loop_warning,
                    pending_tasks=pending if pending else None,
                )
                from agent.prompts.system import CONVERSATIONAL_SYSTEM_PROMPT
                decision = self.llm.invoke_json(CONVERSATIONAL_SYSTEM_PROMPT, payload)
                # ── 2.5 决策校正 ──
                decision = self._correct_decision(decision, history, user_input)
            except Exception as exc:
                final_answer = f"决策失败: {exc}"
                emit("error", {"message": str(exc)})
                break

            # ── 3. final ──
            if decision.get("type") == "final":
                # 自动出图检查
                if self.guard.should_auto_map(history):
                    try:
                        map_result = self.registry.call("make_thematic_map", {})
                        if "success" not in map_result:
                            map_result["success"] = True
                    except Exception as exc:
                        map_result = {"success": False, "message": str(exc)}
                    history.append({
                        "step": step, "tool": "make_thematic_map", "args": {},
                        "reason": "自动出图", "result": map_result,
                    })
                    last_result = map_result
                    emit("tool_result", {"tool": "make_thematic_map", "result": map_result, "ui_action": "RENDER_IMAGE"})

                # 批量制图检查
                next_unmapped = self._get_next_unmapped_file(history)
                if next_unmapped and step < self.max_steps - 3:
                        fname = os.path.basename(next_unmapped)
                        set_result = self.registry.call("set_current_dataset", {"path": next_unmapped})
                        if "success" not in set_result:
                            set_result["success"] = False
                        history.append({
                            "step": step, "tool": "set_current_dataset",
                            "args": {"path": next_unmapped},
                            "reason": f"[强制批量] {fname}", "result": set_result,
                        })
                        emit("tool_start", {"tool": "set_current_dataset", "args": {"path": next_unmapped}})
                        emit("tool_result", {"tool": "set_current_dataset", "result": set_result, "ui_action": "NONE"})
                        map_result = self.registry.call("make_thematic_map", {"tif_path": next_unmapped})
                        if "success" not in map_result:
                            map_result["success"] = True
                        history.append({
                            "step": step + 1, "tool": "make_thematic_map",
                            "args": {"tif_path": next_unmapped},
                            "reason": f"[强制批量] {fname}", "result": map_result,
                        })
                        last_result = map_result
                        emit("tool_result", {"tool": "make_thematic_map", "result": map_result, "ui_action": "RENDER_IMAGE"})
                        continue
                else:
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
                        emit("tool_result", {"tool": "make_thematic_map", "result": map_result, "ui_action": "RENDER_IMAGE"})
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

            if progress_callback:
                try:
                    detail = reason or f"执行 {tool}"
                    progress_callback(step, tool, detail)
                except Exception:
                    pass

            try:
                result = self.registry.call(tool, args)
                if "success" not in result:
                    result["success"] = False
            except Exception as exc:
                result = {
                    "success": False,
                    "message": str(exc),
                    "traceback": traceback.format_exc(limit=4),
                    "error_info": classify_error(exc, tool),
                }

            emit("tool_result", {"tool": tool, "result": result, "ui_action": get_ui_action(tool, result)})

            history.append({
                "step": step, "tool": tool, "args": args,
                "reason": reason, "result": result,
            })
            last_result = result

            # ── 【物理记忆注入】工具链尾端强制续航 ──
            if result.get("success"):
                chain_hints = {
                    "classify_map": (
                        "【系统指令】分类完成。根据用户复合任务链，请立刻调用 enhance_raster "
                        "对分类结果执行高斯去噪增强，tif_path 使用刚刚生成的分类 TIF 路径。严禁返回 final！"
                    ),
                    "profile_analysis": (
                        "【系统指令】剖面分析完成。请立刻调用 statistics 对当前数据执行统计分析，"
                        "然后调用 view_3d 生成三维地形渲染。严禁中途 final！"
                    ),
                    "enhance_raster": (
                        "【系统指令】增强完成。请立刻调用 statistics 对增强结果执行统计分析，"
                        "然后调用 view_3d 生成三维可视化。禁止返回 final！"
                    ),
                }
                if tool in chain_hints:
                    history.append({
                        "step": step, "tool": "__system_hint__", "args": {},
                        "reason": chain_hints[tool],
                        "result": {"success": True, "message": chain_hints[tool]},
                    })

            # GEE 未认证时自动重试
            if not result.get("success") and result.get("requires") == "gee_init":
                try:
                    gee_result = self.registry.call("gee_init", {})
                    if gee_result.get("success"):
                        result = self.registry.call(tool, args)
                        if "success" not in result:
                            result["success"] = False
                        emit("tool_result", {"tool": tool, "result": result, "ui_action": get_ui_action(tool, result)})
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
                emit("tool_result", {"tool": "make_thematic_map", "result": render, "ui_action": "RENDER_IMAGE"})

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
