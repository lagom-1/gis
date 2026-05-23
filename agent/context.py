"""
上下文构建器 - 为 LLM 构建决策上下文
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _infer_stage(runtime: Dict[str, Any], history: List[Dict[str, Any]]) -> str:
    """推断当前执行阶段，帮助 LLM 正确决策下一步"""
    has_data = bool(runtime.get("current_dataset") or runtime.get("last_output"))
    has_region = bool(runtime.get("last_region_name") and runtime.get("has_last_region_geojson"))

    # 检查是否已有输出文件
    has_output = any(
        h.get("tool") in ("make_thematic_map", "classify_map", "generate_web_map",
                          "gee_lst_timelapse", "gee_lst_timelapse_local")
        and h.get("result", {}).get("success")
        for h in history
    )

    # 检查是否刚完成数据下载/生产
    data_produced = any(
        h.get("tool") in ("gee_compute_lst", "gee_download_monthly_lst",
                          "gee_download_yearly_lst", "gee_download_multi_year_lst",
                          "gee_download_landsat_sca", "run_lst")
        and h.get("result", {}).get("success")
        for h in history
    )

    if has_output:
        return "has_output"       # 已有专题图，用户可能是要修改/追加
    elif data_produced:
        return "ready_to_map"     # 数据已就绪，应制图或分析
    elif has_data:
        return "has_data"         # 有当前数据集，可分析/制图
    elif has_region:
        return "has_region"       # 行政区已解析，应下载数据
    else:
        return "idle"             # 初始状态，需要搜索/解析


def build_context(
    user_input: str,
    step: int,
    runtime: Dict[str, Any],
    history: List[Dict[str, Any]],
    tools_manifest: List[Dict[str, Any]],
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    loop_warning: str = "",
    pending_tasks: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """构建发送给 LLM 的决策 payload"""
    context_text = ""
    if conversation_history:
        context_text = _format_history(conversation_history, user_input)

    # ── DAG驱动指令：置顶在上下文最末尾 ──
    dag_directive = ""
    if pending_tasks:
        dag_directive = (
            f"\n\n【系统核心驱动】检测到未完成的复合任务: {', '.join(pending_tasks)}。"
            f"你必须立刻调用 {pending_tasks[0]} 工具继续执行！"
            f"严禁返回 final，严禁搜索文件，严禁调用 summarize_context。"
        )

    stage = _infer_stage(runtime, history)

    output_files = [
        h for h in history
        if h.get("result", {}).get("success") and any(
            h["result"].get(k) for k in ("output_png", "output_gif", "output_html")
        )
    ]

    return {
        "user_input": user_input,
        "conversation_history": context_text,
        "step": step,
        "tools": tools_manifest,
        "runtime": runtime,
        "stage": stage,
        "stage_hint": _stage_hint(stage),
        "output_count": len(output_files),
        "last_result": history[-1].get("result") if history else None,
        "loop_warning": loop_warning,
        "dag_directive": dag_directive,
    }


def _stage_hint(stage: str) -> str:
    """根据阶段给 LLM 提示（idle 阶段不推送任何暗示，防止幻觉）"""
    if stage == "idle":
        return ""  # 初始阶段不推送任何环境暗示
    hints = {
        "has_region": "行政区已解析，可以进行 GEE 数据下载",
        "has_data": "有当前数据集，可以进行分析或制图",
        "ready_to_map": "数据下载完成，可以对文件生成专题图",
        "has_output": "已有输出文件，可以进行样式修改或进一步分析",
    }
    return hints.get(stage, "")


def _format_history(
    messages: List[Dict[str, Any]],
    current_msg: str,
    max_msgs: int = 30,
) -> str:
    """将对话历史格式化为 LLM 可读的文本"""
    truncated = messages[-max_msgs:] if len(messages) > max_msgs else messages

    lines = []
    for msg in truncated:
        role = msg.get("role", "")
        content = msg.get("content", "")
        tool = msg.get("tool_name", "")
        tool_result = msg.get("tool_result")

        if role == "user":
            lines.append(f"[用户]: {content}")
        elif role == "assistant":
            lines.append(f"[助手]: {content}")
        elif role == "tool_call":
            lines.append(f"[助手]: (调用 {tool})")
        elif role == "tool_result":
            if isinstance(tool_result, dict):
                ok = tool_result.get("success", False)
                msg_text = tool_result.get("message", "")[:80]
                lines.append(f"[系统]: {tool} {'成功' if ok else '失败'} - {msg_text}")
        elif role == "system":
            lines.append(f"[系统]: {content}")

    lines.append(f"\n[用户]（当前消息）: {current_msg}")
    return "\n".join(lines)
