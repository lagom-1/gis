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

    # 关系
    user = relationship("User", back_populates="tasks")
    orders = relationship("Order", back_populates="task", lazy="dynamic")
    downloads = relationship("Download", back_populates="task", lazy="dynamic")


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
