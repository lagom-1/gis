"""
会话路由
- POST   /api/conversations              创建新会话
- GET    /api/conversations              列出用户会话
- GET    /api/conversations/{id}         获取会话详情
- DELETE /api/conversations/{id}         删除会话
- POST   /api/conversations/{id}/messages 发送消息并获取 Agent 响应
- GET    /api/conversations/{id}/messages 获取历史消息
"""
from __future__ import annotations

import logging
import asyncio
import json
from typing import AsyncGenerator, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import (
    ConversationCreateRequest,
    ConversationListResponse,
    ConversationMessageResponse,
    ConversationResponse,
    ConversationStatus,
    MessageCreateRequest,
    MessageResponse,
    User,
)
from api.routers.auth import get_current_user
from api.services.conversation_service import (
    add_message,
    create_conversation,
    delete_conversation,
    get_conversation,
    get_conversation_messages,
    get_last_message,
    list_conversations,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/conversations", tags=["会话"])


# ── 会话 CRUD ──────────────────────────────────────────────────

@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED, summary="创建新会话")
async def create_conv(
    request: ConversationCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建新的对话会话，可选地同时发送第一条消息。"""
    conv = create_conversation(
        db=db,
        user_id=current_user.id,
        title=request.title,
    )

    if request.initial_message:
        add_message(
            db=db,
            conversation_id=conv.id,
            role="user",
            content=request.initial_message,
        )

    last_msg = get_last_message(db, conv.id)
    # msg_count is computed below

    return ConversationResponse(
        id=conv.id,
        user_id=conv.user_id,
        title=conv.title,
        status=conv.status,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        last_message=ConversationMessageResponse.model_validate(last_msg) if last_msg else None,
        message_count=None,
    )


@router.get("", response_model=ConversationListResponse, summary="列出用户会话")
async def list_convs(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的所有会话，按最近更新排序。"""
    conversations, total = list_conversations(db, current_user.id, page, page_size)

    # 为每个会话附上最后一条消息
    response_convs = []
    for conv in conversations:
        last_msg = get_last_message(db, conv.id)
        from api.models import Message as MsgModel
        msg_count = (
            db.query(MsgModel)
            .filter(MsgModel.conversation_id == conv.id)
            .count()
        )
        response_convs.append(
            ConversationResponse(
                id=conv.id,
                user_id=conv.user_id,
                title=conv.title,
                status=conv.status,
                created_at=conv.created_at,
                updated_at=conv.updated_at,
                last_message=ConversationMessageResponse.model_validate(last_msg) if last_msg else None,
                message_count=msg_count,
            )
        )

    return ConversationListResponse(
        conversations=response_convs,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{conv_id}", response_model=ConversationResponse, summary="获取会话详情")
async def get_conv(
    conv_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取指定会话的详细信息。"""
    conv = get_conversation(db, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此会话")

    last_msg = get_last_message(db, conv.id)
    from api.models import Message as MsgModel
    msg_count = (
        db.query(MsgModel)
        .filter(MsgModel.conversation_id == conv.id)
        .count()
    )

    return ConversationResponse(
        id=conv.id,
        user_id=conv.user_id,
        title=conv.title,
        status=conv.status,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        last_message=ConversationMessageResponse.model_validate(last_msg) if last_msg else None,
        message_count=msg_count,
    )


@router.delete("/{conv_id}", response_model=MessageResponse, summary="删除会话")
async def delete_conv(
    conv_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除指定会话，级联删除所有消息和状态。"""
    conv = get_conversation(db, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作此会话")

    delete_conversation(db, conv_id)
    return MessageResponse(success=True, message=f"会话 {conv_id} 已删除")


# ── 消息 ──────────────────────────────────────────────────────

@router.get("/{conv_id}/messages", summary="获取会话历史消息")
async def list_messages(
    conv_id: int,
    before: Optional[int] = Query(None, description="获取此 ID 之前的消息"),
    limit: int = Query(50, ge=1, le=200, description="返回数量"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取指定会话的消息历史，按时间正序排列。"""
    conv = get_conversation(db, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此会话")

    messages = get_conversation_messages(db, conv_id, before_id=before, limit=limit)
    return {
        "messages": [ConversationMessageResponse.model_validate(m) for m in messages],
        "has_more": len(messages) >= limit,
    }


@router.post("/{conv_id}/messages", summary="发送消息并获取 Agent 响应")
async def send_message(
    conv_id: int,
    request: MessageCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    在会话中发送一条用户消息并获取 Agent 响应。

    当前为同步模式：Agent 执行完毕后返回完整结果。
    SSE 流式模式将在 Phase 4 中实现。
    """
    conv = get_conversation(db, conv_id)
    if not conv:
        from api.services.conversation_service import create_conversation
        conv = create_conversation(db, current_user.id, request.content[:50])
        conv_id = conv.id
    if conv.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作此会话")

    # 1. 保存用户消息
    user_msg = add_message(db, conv_id, role="user", content=request.content)

    # 2. 加载会话状态
    from api.services.conversation_service import load_conversation_state

    saved_state = load_conversation_state(db, conv_id)
    history_messages = [
        {
            "role": m.role,
            "content": m.content,
            "tool_name": m.tool_name,
            "tool_result": m.tool_result,
        }
        for m in get_conversation_messages(db, conv_id, limit=100)
    ]

    # 4. 执行 Agent
    from tools import ToolRegistry
    from tools.runtime import GISRuntime
    from agent.llm import LLMClient
    from agent.engine import AgentLoop

    runtime = GISRuntime(conversation_id=conv_id)
    if saved_state:
        runtime.from_dict(saved_state)
    registry = ToolRegistry(runtime)
    llm = LLMClient()
    agent = AgentLoop(llm, registry, runtime)

    try:
        result = agent.run(
            user_input=request.content,
            conversation_history=history_messages,
        )
    except Exception as exc:
        logger.error(f"Agent 执行失败: {exc}", exc_info=True)
        add_message(
            db, conv_id,
            role="assistant",
            content=f"抱歉，执行失败: {exc}",
        )
        return {
            "success": False,
            "message": str(exc),
            "answer": f"执行失败: {exc}",
        }

    # 5. 保存工具调用消息
    history = result.get("history", [])
    for h in history:
        step = h.get("step", 0)
        tool = h.get("tool", "")
        args = h.get("args", {})
        tool_result = h.get("result", {})
        reason = h.get("reason", "")

        add_message(
            db, conv_id,
            role="tool_call",
            content=reason or f"调用工具: {tool}",
            tool_name=tool,
            tool_args=args,
            step_number=step,
        )
        add_message(
            db, conv_id,
            role="tool_result",
            content=tool_result.get("message", ""),
            tool_name=tool,
            tool_result=tool_result,
            step_number=step,
        )

    # 6. 保存最终回复
    result_type = result.get("type", "final")
    if result_type == "ask_user":
        assistant_content = result.get("question", "")
    else:
        assistant_content = result.get("answer", "任务完成。")

    assistant_msg = add_message(
        db, conv_id,
        role="assistant",
        content=assistant_content,
        output_files=None,
    )

    # 7. 保存会话状态
    from api.services.conversation_service import save_conversation_state
    save_conversation_state(db, conv_id, runtime.to_dict())

    return {
        "success": result.get("success", True),
        "message_id": assistant_msg.id,
        "type": result_type,
        "answer": result.get("answer", ""),
        "question": result.get("question", "") if result_type == "ask_user" else None,
        "options": result.get("options", []) if result_type == "ask_user" else None,
        "steps": len(history),
    }


# ── SSE 流式端点 ──────────────────────────────────────────────

@router.post("/{conv_id}/messages/stream", summary="发送消息并获取 SSE 流式 Agent 响应")
async def send_message_stream(
    conv_id: int,
    request: MessageCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    在会话中发送一条用户消息，通过 Server-Sent Events 流式返回 Agent 执行过程。

    事件类型：
    - event: step_start    → {"step": 1, "max": 15}
    - event: tool_start    → {"tool": "...", "args": {...}, "reason": "..."}
    - event: tool_result   → {"tool": "...", "result": {...}}
    - event: ask_user      → {"question": "...", "options": [...]}
    - event: final_answer  → {"content": "..."}
    - event: heartbeat     → {}
    - event: error         → {"message": "..."}
    """
    conv = get_conversation(db, conv_id)
    if not conv:
        # 会话不存在 → 自动创建新会话（服务重启后前端可能持有旧 ID）
        from api.services.conversation_service import create_conversation
        conv = create_conversation(db, current_user.id, request.content[:50])
        conv_id = conv.id
    if conv.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作此会话")

    # 保存用户消息
    add_message(db, conv_id, role="user", content=request.content)

    # 加载状态和历史
    from api.services.conversation_service import load_conversation_state, save_conversation_state
    saved_state = load_conversation_state(db, conv_id)
    history_messages = [
        {
            "role": m.role,
            "content": m.content,
            "tool_name": m.tool_name,
            "tool_result": m.tool_result,
        }
        for m in get_conversation_messages(db, conv_id, limit=100)
    ]

    from tools import ToolRegistry
    from tools.runtime import GISRuntime
    from agent.llm import LLMClient
    from agent.engine import AgentLoop

    runtime = GISRuntime(conversation_id=conv_id)
    if saved_state:
        runtime.from_dict(saved_state)
    registry = ToolRegistry(runtime)
    llm = LLMClient()
    agent = AgentLoop(llm, registry, runtime)

    # 存储工具调用历史，用于最终保存
    tool_history: list = []
    final_result: dict = {}

    import concurrent.futures
    from collections import deque

    # 标记执行状态：用于前端轮询检测
    from api.models import ConversationStatus
    conv.status = ConversationStatus.PROCESSING
    db.commit()

    async def event_generator() -> AsyncGenerator[str, None]:
        nonlocal tool_history, final_result

        events: deque = deque()
        import threading
        lock = threading.Lock()

        # 跟踪已保存到 DB 的工具步骤，避免重复
        saved_steps: set = set()
        # 错误跟踪
        error_occurred = False
        error_message = ""

        def sync_callback(event_type: str, data: dict):
            with lock:
                events.append((event_type, data))

        loop = asyncio.get_running_loop()

        def run_agent():
            nonlocal tool_history, final_result
            try:
                result = agent.run(
                    user_input=request.content,
                    conversation_history=history_messages,
                    on_event=sync_callback,
                )
                tool_history = result.get("history", [])
                final_result = result
                sync_callback("done", {})
            except Exception as exc:
                logger.error(f"Agent SSE 执行失败: {exc}", exc_info=True)
                sync_callback("error", {"message": str(exc)})

        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = loop.run_in_executor(executor, run_agent)

        # 当前正在执行的工具名和步骤号（用于增量保存）
        current_tool_name = ""
        current_tool_args = {}
        current_step = 0

        # 轮询事件直到完成，同时增量保存工具结果到 DB
        # 不设硬性超时——Agent 自身有 max_steps 和循环检测保护
        should_break = False
        import time
        last_heartbeat = time.time()

        while not future.done() or events:
            # 每 15 秒发送心跳，防止代理/网关因长时间无数据断开连接
            now = time.time()
            if now - last_heartbeat > 15:
                last_heartbeat = now
                yield f": heartbeat\n\n"

            with lock:
                batch = list(events)
                events.clear()
            for event_type, data in batch:
                yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

                if event_type == "step_start":
                    current_step = int(data.get("step", 0))

                elif event_type == "tool_start":
                    current_tool_name = str(data.get("tool", ""))
                    current_tool_args = data.get("args") or {}

                elif event_type == "tool_result":
                    # 增量保存：优先使用事件中的 tool 名，回退到上一个 tool_start
                    tool_name = str(data.get("tool", "") or current_tool_name)
                    result_data = data.get("result") or {}
                    step_key = f"{tool_name}-{current_step}"
                    if step_key not in saved_steps:
                        saved_steps.add(step_key)
                        step_num = len(saved_steps)
                        # 保存 tool_call
                        add_message(
                            db, conv_id,
                            role="tool_call",
                            content=f"调用工具: {tool_name}",
                            tool_name=tool_name,
                            tool_args=current_tool_args,
                            step_number=step_num,
                        )
                        # 保存 tool_result
                        add_message(
                            db, conv_id,
                            role="tool_result",
                            content=result_data.get("message", ""),
                            tool_name=tool_name,
                            tool_result=result_data,
                            step_number=step_num,
                        )

                elif event_type == "error":
                    error_occurred = True
                    error_message = str(data.get("message", ""))
                    should_break = True
                    break
                elif event_type in ("final_answer", "ask_user", "done"):
                    should_break = True
                    break

            if should_break:
                break
            if batch:
                continue
            await asyncio.sleep(0.2)

        executor.shutdown(wait=False)

        # ── 智能补齐：如果 TIF 已下载但未生成专题图，自动生成 ──
        tif_path = runtime.current_tif()
        has_map = any(h.get("tool") == "make_thematic_map" for h in tool_history)
        if tif_path and not has_map:
            try:
                logger.info(f"自动生成专题图: {tif_path}")
                from gis.cartographic_map import generate_cartographic_map
                from pathlib import Path
                region_name = runtime.last_region_name or "研究区"
                stem = Path(tif_path).stem
                map_path = str(Path(tif_path).parent / f"{stem}_map.png")
                map_result = generate_cartographic_map(
                    tif_path=tif_path,
                    output_path=map_path,
                    title=f"地表温度 - {region_name}",
                    colormap="coolwarm",
                )
                if map_result.get("success"):
                    runtime.last_output = map_result.get("output_png")
                    # 追加到 tool_history 供后续保存
                    tool_history.append({
                        "step": len(tool_history) + 1,
                        "tool": "make_thematic_map",
                        "args": {},
                        "reason": "超时/出错后自动生成专题图",
                        "result": map_result,
                    })
                    logger.info(f"专题图已自动生成: {map_result.get('output_png')}")
            except Exception as e:
                logger.error(f"自动生成专题图失败: {e}")

        # 保存尚未保存的工具调用（兜底），使用与增量保存一致的 step_key
        for i, h in enumerate(tool_history):
            tool = h.get("tool", "")
            h_step = h.get("step", 0)
            step_key = f"{tool}-{h_step}"
            if step_key in saved_steps:
                continue
            saved_steps.add(step_key)
            args = h.get("args", {})
            tool_result = h.get("result", {})
            reason = h.get("reason", "")

            add_message(
                db, conv_id,
                role="tool_call",
                content=f"调用工具: {tool}",
                tool_name=tool,
                tool_args=args,
                step_number=step,
            )
            add_message(
                db, conv_id,
                role="tool_result",
                content=tool_result.get("message", ""),
                tool_name=tool,
                tool_result=tool_result,
                step_number=step,
            )

        # 保存最终回复
        if error_occurred:
            assistant_content = error_message or "执行失败"
        else:
            result_type = final_result.get("type", "final")
            if result_type == "ask_user":
                assistant_content = final_result.get("question", "")
            else:
                assistant_content = final_result.get("answer", "任务完成。")

        add_message(
            db, conv_id,
            role="assistant",
            content=assistant_content,
            output_files=None,
        )

        # 保存状态并恢复会话状态
        save_conversation_state(db, conv_id, runtime.to_dict())
        conv.status = ConversationStatus.ACTIVE
        db.commit()

        # 发送完成信号
        yield f"event: done\ndata: {{}}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        },
    )


# ── 文件预览 ────────────────────────────────────────────────────

@router.get("/{conv_id}/preview/{filename}", summary="预览会话产出文件")
async def preview_conversation_file(
    conv_id: int,
    filename: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """通过会话 ID 预览输出文件（缩略图）。"""
    from pathlib import Path
    from fastapi.responses import FileResponse

    conv = get_conversation(db, conv_id)
    if not conv:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此会话")

    # 从该会话的 tool_result 消息中查找文件路径
    messages = get_conversation_messages(db, conv_id, limit=200)
    file_path = None
    for msg in messages:
        if not msg.tool_result or not isinstance(msg.tool_result, dict):
            continue
        # 检查 output_files 数组
        for f in (msg.tool_result.get("output_files") or []):
            if isinstance(f, dict) and f.get("name") == filename:
                file_path = Path(f["path"])
                break
        if file_path:
            break
        # 检查单文件输出字段
        for key in ["output_png", "output_tif", "output_gif", "output_html", "output_csv"]:
            val = msg.tool_result.get(key)
            if isinstance(val, str) and (val.endswith(filename) or val.split("/")[-1].split("\\")[-1] == filename):
                file_path = Path(val)
                break
        if file_path:
            break

    if not file_path or not file_path.exists():
        # 尝试在 workspace/outputs 目录中查找
        outputs_dir = Path("workspace/outputs")
        candidate = outputs_dir / filename
        if candidate.exists():
            file_path = candidate
        else:
            raise HTTPException(status_code=404, detail="文件不存在")

    # 对于图片文件直接返回，对于 TIF 生成缩略图
    if file_path.suffix.lower() in ('.png', '.jpg', '.jpeg', '.gif'):
        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type=f"image/{file_path.suffix[1:].replace('jpg', 'jpeg')}",
        )

    # TIF 等其他格式生成缩略图
    from api.services.file_service import generate_thumbnail
    thumbnail_path = generate_thumbnail(file_path)
    if not thumbnail_path:
        # 如果无法生成缩略图，返回原文件
        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type="application/octet-stream",
        )

    return FileResponse(
        path=str(thumbnail_path),
        filename=f"preview_{file_path.stem}.png",
        media_type="image/png",
    )
