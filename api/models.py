"""
数据模型定义
- SQLAlchemy ORM 模型（数据库表结构）
- Pydantic 模型（请求/响应验证）
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from api.database import Base


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  枚举类型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TaskStatus(str, enum.Enum):
    """任务状态"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class OrderStatus(str, enum.Enum):
    """订单状态"""
    PENDING = "pending"
    PAID = "paid"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


class ConversationStatus(str, enum.Enum):
    """会话状态"""
    ACTIVE = "active"
    PROCESSING = "processing"
    ARCHIVED = "archived"


class MessageRole(str, enum.Enum):
    """消息角色"""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ASK_USER = "ask_user"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  SQLAlchemy ORM 模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class User(Base):
    """用户表"""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(128), unique=True, nullable=False, index=True)
    password_hash = Column(String(128), nullable=False)
    credits = Column(Integer, default=0, nullable=False, comment="用户积分/余额（分）")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # 关系
    tasks = relationship("Task", back_populates="user", lazy="dynamic")
    conversations = relationship("Conversation", back_populates="user", lazy="dynamic")
    orders = relationship("Order", back_populates="user", lazy="dynamic")
    downloads = relationship("Download", back_populates="user", lazy="dynamic")


class Task(Base):
    """GIS 任务表"""
    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    celery_task_id = Column(String(128), unique=True, nullable=True, index=True, comment="Celery 任务 ID")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    input_text = Column(Text, nullable=False, comment="用户输入的自然语言指令")
    status = Column(
        Enum(TaskStatus),
        default=TaskStatus.PENDING,
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    started_at = Column(DateTime, nullable=True, comment="任务开始执行时间")
    completed_at = Column(DateTime, nullable=True, comment="任务完成/失败时间")
    output_files = Column(JSON, nullable=True, comment="输出文件列表 [{name, path, size}]")
    final_answer = Column(Text, nullable=True, comment="Agent 的最终回复文本")
    error_message = Column(Text, nullable=True, comment="失败时的错误信息")
    run_log_path = Column(String(512), nullable=True, comment="运行日志文件路径")
    current_step = Column(Integer, nullable=True, default=0, comment="当前执行步骤编号")
    step_description = Column(Text, nullable=True, comment="当前步骤描述（工具名+参数摘要）")
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True, index=True, comment="所属会话 ID")
    turn_index = Column(Integer, nullable=True, default=0, comment="会话中的第几轮")

    # 关系
    user = relationship("User", back_populates="tasks")
    conversation = relationship("Conversation", back_populates="tasks")
    orders = relationship("Order", back_populates="task", lazy="dynamic")
    downloads = relationship("Download", back_populates="task", lazy="dynamic")


class Conversation(Base):
    """会话表：多轮对话的顶层容器"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(256), default="", nullable=False, comment="会话标题")
    status = Column(
        Enum(ConversationStatus),
        default=ConversationStatus.ACTIVE,
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # 关系
    user = relationship("User", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation", lazy="dynamic", cascade="all, delete-orphan")
    tasks = relationship("Task", back_populates="conversation", lazy="dynamic")
    state = relationship("ConversationState", back_populates="conversation", uselist=False, cascade="all, delete-orphan")


class Message(Base):
    """消息表：会话中的每条消息（用户输入、助手回复、工具调用等）"""
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String(16), nullable=False, comment="user/assistant/system/tool_call/tool_result/ask_user")
    content = Column(Text, nullable=False, comment="消息文本或 JSON")
    tool_name = Column(String(64), nullable=True, comment="调用的工具名（tool_call/tool_result）")
    tool_args = Column(JSON, nullable=True, comment="工具参数（tool_call）")
    tool_result = Column(JSON, nullable=True, comment="工具执行结果（tool_result）")
    step_number = Column(Integer, nullable=True, comment="当前轮内的步骤编号")
    output_files = Column(JSON, nullable=True, comment="本轮产出的文件列表")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)

    # 关系
    conversation = relationship("Conversation", back_populates="messages")


class ConversationState(Base):
    """会话状态表：持久化 GISRuntime 运行时状态，跨轮次保留"""
    __tablename__ = "conversation_states"

    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), primary_key=True)
    current_dataset = Column(Text, nullable=True, comment="当前工作数据集路径")
    source_dataset = Column(Text, nullable=True, comment="原始源数据集路径")
    last_output = Column(Text, nullable=True, comment="最后输出文件路径")
    last_tif_output = Column(Text, nullable=True, comment="最后 TIFF 输出路径")
    product_type = Column(String(32), nullable=True, comment="推断的产品类型")
    last_region_geojson = Column(Text, nullable=True, comment="最近解析的行政区 GeoJSON（JSON 字符串）")
    last_region_name = Column(String(256), nullable=True, comment="最近解析的行政区名称")
    map_style = Column(JSON, nullable=True, comment="地图样式参数")
    known_facts = Column(JSON, nullable=True, comment="累积的已知事实")
    preferences = Column(JSON, nullable=True, comment="用户偏好")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)

    # 关系
    conversation = relationship("Conversation", back_populates="state")


class Order(Base):
    """支付订单表"""
    __tablename__ = "orders"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    amount_cents = Column(Integer, nullable=False, comment="金额（分）")
    currency = Column(String(8), default="CNY", nullable=False)
    status = Column(
        Enum(OrderStatus),
        default=OrderStatus.PENDING,
        nullable=False,
        index=True,
    )
    payment_method = Column(String(32), nullable=True, comment="支付方式：stripe/alipay/wechat")
    payment_id = Column(String(128), nullable=True, comment="第三方支付平台订单号")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    paid_at = Column(DateTime, nullable=True, comment="支付完成时间")

    # 关系
    user = relationship("User", back_populates="orders")
    task = relationship("Task", back_populates="orders")
    downloads = relationship("Download", back_populates="order", lazy="dynamic")


class Download(Base):
    """下载记录表"""
    __tablename__ = "downloads"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=True, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=True, index=True)
    file_path = Column(String(512), nullable=False, comment="下载文件路径")
    downloaded_at = Column(DateTime, server_default=func.now(), nullable=False)

    # 关系
    user = relationship("User", back_populates="downloads")
    order = relationship("Order", back_populates="downloads")
    task = relationship("Task", back_populates="downloads")


class ShareRecord(Base):
    """分享记录表"""
    __tablename__ = "share_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    shared_at = Column(DateTime, server_default=func.now(), nullable=False)
    week_number = Column(Integer, nullable=False, comment="ISO 周数")
    year = Column(Integer, nullable=False, comment="年份")

    # 关系
    user = relationship("User")
    task = relationship("Task")


class PaymentRecord(Base):
    """支付记录表"""
    __tablename__ = "payment_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    amount_yuan = Column(Float, nullable=False, comment="金额（元）")
    status = Column(String(20), default="pending", nullable=False, comment="pending/paid/cancelled")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    paid_at = Column(DateTime, nullable=True, comment="支付时间")
    confirmed_at = Column(DateTime, nullable=True, comment="确认时间")

    # 关系
    user = relationship("User")
    task = relationship("Task")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Pydantic 模型（请求 / 响应）
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


# ── 认证 ──────────────────────────────────────────────────

class UserRegisterRequest(BaseModel):
    """用户注册请求"""
    username: str = Field(..., min_length=2, max_length=64, description="用户名")
    email: EmailStr = Field(..., description="邮箱地址")
    password: str = Field(..., min_length=6, max_length=128, description="密码")


class UserLoginRequest(BaseModel):
    """用户登录请求"""
    username: str = Field(..., description="用户名或邮箱")
    password: str = Field(..., description="密码")


class TokenResponse(BaseModel):
    """JWT Token 响应"""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(..., description="过期时间（秒）")


class UserResponse(BaseModel):
    """用户信息响应"""
    id: int
    username: str
    email: str
    credits: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 任务 ──────────────────────────────────────────────────

class TaskCreateRequest(BaseModel):
    """创建任务请求"""
    input_text: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="自然语言 GIS 指令，如 '找到北京的 TIF，做温度反演并制图'",
    )


class TaskResponse(BaseModel):
    """任务信息响应"""
    id: int
    celery_task_id: Optional[str] = None
    user_id: int
    input_text: str
    status: TaskStatus
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    output_files: Optional[List[Dict[str, Any]]] = None
    final_answer: Optional[str] = None
    error_message: Optional[str] = None
    run_log_path: Optional[str] = None
    current_step: Optional[int] = None
    step_description: Optional[str] = None

    model_config = {"from_attributes": True}


class TaskListResponse(BaseModel):
    """任务列表响应"""
    tasks: List[TaskResponse]
    total: int
    page: int
    page_size: int


# ── 支付 ──────────────────────────────────────────────────


class OrderResponse(BaseModel):
    """订单信息响应"""
    id: int
    user_id: int
    task_id: Optional[int] = None
    amount_cents: int
    currency: str
    status: OrderStatus
    payment_method: Optional[str] = None
    payment_id: Optional[str] = None
    created_at: datetime
    paid_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


# ── 通用 ──────────────────────────────────────────────────

class MessageResponse(BaseModel):
    """通用消息响应"""
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None


# ── 会话 ──────────────────────────────────────────────────

class ConversationCreateRequest(BaseModel):
    """创建会话请求"""
    title: Optional[str] = Field(None, max_length=256, description="会话标题，不填则从首条消息自动生成")
    initial_message: Optional[str] = Field(None, max_length=2000, description="首条用户消息")


class MessageCreateRequest(BaseModel):
    """发送消息请求"""
    content: str = Field(..., min_length=1, max_length=2000, description="消息文本")


class ConversationMessageResponse(BaseModel):
    """会话消息响应"""
    id: int
    conversation_id: int
    role: str
    content: str
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    tool_result: Optional[Dict[str, Any]] = None
    step_number: Optional[int] = None
    output_files: Optional[List[Dict[str, Any]]] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationResponse(BaseModel):
    """会话信息响应"""
    id: int
    user_id: int
    title: str
    status: ConversationStatus
    created_at: datetime
    updated_at: datetime
    last_message: Optional[ConversationMessageResponse] = None
    message_count: Optional[int] = None

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    """会话列表响应"""
    conversations: List[ConversationResponse]
    total: int
    page: int
    page_size: int


class ConversationStateResponse(BaseModel):
    """会话状态响应"""
    conversation_id: int
    current_dataset: Optional[str] = None
    last_region_name: Optional[str] = None
    map_style: Optional[Dict[str, Any]] = None

    model_config = {"from_attributes": True}


class SendCodeRequest(BaseModel):
    email: str

class LoginWithCodeRequest(BaseModel):
    email: str
    code: str


# ── 分享 / 下载权限 ──────────────────────────────────────


class ShareRecordResponse(BaseModel):
    """分享记录响应"""
    id: int
    user_id: int
    task_id: int
    shared_at: datetime
    week_number: int
    year: int

    model_config = {"from_attributes": True}


class PaymentRecordResponse(BaseModel):
    """支付记录响应"""
    id: int
    user_id: int
    task_id: int
    amount_yuan: float
    status: str
    created_at: datetime
    paid_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DownloadPermissionResponse(BaseModel):
    """下载权限响应"""
    can_download: bool
    download_type: Optional[str] = None
    share_remaining: int
    price_yuan: float
    payment_status: Optional[str] = None


class ShareRequest(BaseModel):
    """分享请求"""
    task_id: int


class PaymentCreateRequest(BaseModel):
    """创建支付请求"""
    task_id: int


class PaymentConfirmRequest(BaseModel):
    """确认支付请求"""
    payment_id: int
