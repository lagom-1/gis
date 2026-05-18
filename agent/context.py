"""
上下文构建器 - 为 LLM 构建决策上下文
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_context(
    user_input: str,
    step: int,
    runtime: Dict[str, Any],
    history: List[Dict[str, Any]],
    tools_manifest: List[Dict[str, Any]],
    conversation_history: Optional[List[Dict[str, Any]]] = None,
    loop_warning: str = "",
) -> Dict[str, Any]:
    """构建发送给 LLM 的决策 payload"""
    context_text = ""
    if conversation_history:
        context_text = _format_history(conversation_history, user_input)

    return {
        "user_input": user_input,
        "conversation_history": context_text,
        "step": step,
        "tools": tools_manifest,
        "runtime": runtime,
        "last_result": history[-1].get("result") if history else None,
        "loop_warning": loop_warning,
    }


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
