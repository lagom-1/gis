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
    msg_count = db.query(MessageResponse).count() if False else None  # lazy

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
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权操作此会话")

    # 1. 保存用户消息
    user_msg = add_message(db, conv_id, role="user", content=request.content)

    # 2. 加载会话状态
    from api.services.conversation_service import load_conversation_state
    saved_state = load_conversation_state(db, conv_id)

    # 3. 加载之前的对话历史
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

    # 4. 执行 ConversationalAgent
    from tools import ToolRegistry
    from tools.runtime import GISRuntime
    from agent.llm import LLMClient
    from agent.engine import AgentLoop

    runtime = GISRuntime()
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
        raise HTTPException(status_code=404, detail="会话不存在")
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

    runtime = GISRuntime()
    if saved_state:
        runtime.from_dict(saved_state)
    registry = ToolRegistry(runtime)
    llm = LLMClient()
    agent = AgentLoop(llm, registry, runtime)

    # 存储工具调用历史，用于最终保存
    tool_history: list = []
    final_result: dict = {}

    async def event_generator() -> AsyncGenerator[str, None]:
        nonlocal tool_history, final_result

        # 用队列桥接同步 event_callback 和异步 generator
        queue: asyncio.Queue = asyncio.Queue()

        def sync_callback(event_type: str, data: dict):
            """同步回调：将事件放入异步队列"""
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            loop.call_soon_threadsafe(
                queue.put_nowait, (event_type, data)
            )

        # 在后台线程中运行 Agent
        import threading

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
            except Exception as exc:
                logger.error(f"Agent SSE 执行失败: {exc}", exc_info=True)
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                loop.call_soon_threadsafe(
                    queue.put_nowait, ("error", {"message": str(exc)})
                )

        thread = threading.Thread(target=run_agent, daemon=True)
        thread.start()

        # 心跳定时器
        async def heartbeat_sender():
            while thread.is_alive():
                await asyncio.sleep(15)
                if thread.is_alive():
                    yield "event: heartbeat\ndata: {}\n\n"

        hb_task = asyncio.ensure_future(_consume_heartbeat(heartbeat_sender))

        try:
            while thread.is_alive() or not queue.empty():
                try:
                    event_type, data = await asyncio.wait_for(queue.get(), timeout=0.5)
                    yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                    if event_type in ("final_answer", "ask_user", "error"):
                        break
                except asyncio.TimeoutError:
                    continue
        finally:
            hb_task.cancel()
            thread.join(timeout=5)

        # 保存工具调用到 DB
        for h in tool_history:
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

        # 保存最终回复
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

        # 保存状态
        save_conversation_state(db, conv_id, runtime.to_dict())

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


async def _consume_heartbeat(generator):
    """消费心跳事件"""
    async for _ in generator:
        pass
