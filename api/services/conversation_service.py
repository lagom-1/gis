"""
会话业务逻辑层
- 会话 CRUD（创建、列表、详情、删除）
- 消息管理（添加消息、获取历史消息）
- 会话状态持久化（GISRuntime 状态读写）
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import desc
from sqlalchemy.orm import Session

from api.models import (
    Conversation,
    ConversationState,
    Message,
    MessageRole,
)

logger = logging.getLogger(__name__)


def create_conversation(
    db: Session,
    user_id: int,
    title: Optional[str] = None,
) -> Conversation:
    """创建新会话。"""
    conv = Conversation(
        user_id=user_id,
        title=title or "新对话",
    )
    db.add(conv)
    db.commit()
    db.refresh(conv)
    return conv


def add_message(
    db: Session,
    conversation_id: int,
    role: str,
    content: str,
    tool_name: Optional[str] = None,
    tool_args: Optional[Dict[str, Any]] = None,
    tool_result: Optional[Dict[str, Any]] = None,
    step_number: Optional[int] = None,
    output_files: Optional[List[Dict[str, Any]]] = None,
) -> Message:
    """向会话添加一条消息。"""
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        tool_name=tool_name,
        tool_args=tool_args,
        tool_result=tool_result,
        step_number=step_number,
        output_files=output_files,
    )
    db.add(msg)

    # 更新会话的 updated_at
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if conv:
        conv.updated_at = datetime.utcnow()
        # 自动用首条用户消息作为标题
        if conv.title == "新对话" and role == "user" and content:
            conv.title = content[:50] + ("..." if len(content) > 50 else "")

    db.commit()
    db.refresh(msg)
    return msg


def get_conversation(db: Session, conversation_id: int) -> Optional[Conversation]:
    """获取单个会话。"""
    return db.query(Conversation).filter(Conversation.id == conversation_id).first()


def get_last_message(db: Session, conversation_id: int) -> Optional[Message]:
    """获取会话的最后一条消息。"""
    return (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(desc(Message.created_at))
        .first()
    )


def list_conversations(
    db: Session,
    user_id: int,
    page: int = 1,
    page_size: int = 20,
) -> tuple[List[Conversation], int]:
    """列出用户的会话列表（分页）。"""
    query = (
        db.query(Conversation)
        .filter(Conversation.user_id == user_id)
    )
    total = query.count()
    conversations = (
        query
        .order_by(desc(Conversation.updated_at))
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    return conversations, total


def get_conversation_messages(
    db: Session,
    conversation_id: int,
    before_id: Optional[int] = None,
    limit: int = 50,
) -> List[Message]:
    """获取会话的消息历史。"""
    query = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
    )
    if before_id:
        query = query.filter(Message.id < before_id)
    return (
        query
        .order_by(Message.created_at)
        .limit(limit)
        .all()
    )


def delete_conversation(db: Session, conversation_id: int) -> bool:
    """删除会话（级联删除消息和状态）。"""
    conv = db.query(Conversation).filter(Conversation.id == conversation_id).first()
    if not conv:
        return False
    db.delete(conv)
    db.commit()
    return True


# ── 会话状态持久化 ──────────────────────────────────────────

def save_conversation_state(
    db: Session,
    conversation_id: int,
    state: Dict[str, Any],
) -> None:
    """保存 GISRuntime 状态到 conversation_states 表。"""
    existing = (
        db.query(ConversationState)
        .filter(ConversationState.conversation_id == conversation_id)
        .first()
    )

    # 将复杂类型序列化为 JSON 字符串
    prepared = dict(state)
    if "last_region_geojson" in prepared and isinstance(prepared["last_region_geojson"], dict):
        prepared["last_region_geojson"] = json.dumps(
            prepared["last_region_geojson"], ensure_ascii=False
        )

    if existing:
        for key, value in prepared.items():
            if hasattr(existing, key):
                setattr(existing, key, value)
    else:
        prepared["conversation_id"] = conversation_id
        new_state = ConversationState(**prepared)
        db.add(new_state)

    db.commit()


def load_conversation_state(
    db: Session,
    conversation_id: int,
) -> Optional[Dict[str, Any]]:
    """从 conversation_states 表加载 GISRuntime 状态。"""
    state = (
        db.query(ConversationState)
        .filter(ConversationState.conversation_id == conversation_id)
        .first()
    )
    if not state:
        return None

    result = {
        "current_dataset": state.current_dataset,
        "source_dataset": state.source_dataset,
        "last_output": state.last_output,
        "last_tif_output": state.last_tif_output,
        "product_type": state.product_type,
        "last_region_name": state.last_region_name,
        "map_style": state.map_style or {},
        "known_facts": state.known_facts or {},
        "preferences": state.preferences or {},
    }

    # 反序列化 GeoJSON
    if state.last_region_geojson:
        try:
            result["last_region_geojson"] = json.loads(state.last_region_geojson)
        except (json.JSONDecodeError, TypeError):
            result["last_region_geojson"] = None
    else:
        result["last_region_geojson"] = None

    return result
