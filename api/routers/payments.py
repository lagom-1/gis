"""
支付路由
- POST /api/payments/create      创建支付订单（Stripe Checkout / 支付宝 / 微信）
- POST /api/payments/notify      Stripe webhook 回调
- GET  /api/payments/{order_id}  查询订单状态
- GET  /api/payments/tiers       获取定价层级信息
- POST /api/payments/cancel/{order_id}  取消待支付订单
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import (
    MessageResponse,
    Order,
    OrderResponse,
    OrderStatus,
    Task,
    TaskStatus,
    User,
)
from api.routers.auth import _get_current_user
from api.services.payment_service import (
    PRICING_TIERS,
    create_alipay_order,
    create_checkout_session,
    create_wechat_order,
    get_order_status,
    get_pricing_tiers,
    get_tier_info,
    handle_webhook_event,
    verify_webhook_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["支付"])


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  请求/响应模型
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class PaymentCreateRequest(BaseModel):
    """创建支付订单请求"""
    task_id: int = Field(..., description="关联的任务 ID")
    tier: str = Field(
        default="basic",
        description="定价层级: free / basic / standard / premium",
    )
    payment_method: str = Field(
        default="stripe",
        description="支付方式: stripe / alipay / wechat",
    )
    success_url: Optional[str] = Field(
        default=None,
        description="支付成功后跳转 URL（可选，默认使用前端地址）",
    )
    cancel_url: Optional[str] = Field(
        default=None,
        description="取消支付后跳转 URL（可选，默认使用前端地址）",
    )


class PaymentCreateResponse(BaseModel):
    """创建支付订单响应"""
    order_id: int
    checkout_url: Optional[str] = None
    session_id: Optional[str] = None
    amount_cents: int
    currency: str
    message: Optional[str] = None


class TierInfo(BaseModel):
    """定价层级信息"""
    name: str
    price_cents: int
    currency: str
    description: str
    includes: list[str]


class TiersResponse(BaseModel):
    """定价层级列表响应"""
    tiers: list[TierInfo]


class WebhookResponse(BaseModel):
    """Webhook 处理响应"""
    success: bool
    message: str
    event_type: Optional[str] = None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  端点
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


@router.get("/tiers", response_model=TiersResponse, summary="获取定价层级信息")
async def list_pricing_tiers():
    """
    返回所有可用的定价层级及其价格、包含内容。

    无需认证即可访问，用于前端展示定价页面。
    """
    tiers = []
    for name, info in PRICING_TIERS.items():
        tiers.append(TierInfo(
            name=name,
            price_cents=info["price_cents"],
            currency=info["currency"],
            description=info["description"],
            includes=info["includes"],
        ))
    return TiersResponse(tiers=tiers)


@router.post("/create", response_model=PaymentCreateResponse, summary="创建支付订单")
async def create_payment(
    request: PaymentCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(_get_current_user),
):
    """
    创建支付订单并返回支付链接。

    流程：
    1. 验证任务存在且属于当前用户
    2. 验证任务状态为 completed
    3. 根据定价层级计算金额
    4. 创建 Stripe Checkout Session（或支付宝/微信订单）
    5. 保存订单到数据库
    6. 返回支付链接
    """
    # 验证层级
    if request.tier == "free":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="免费层级无需支付",
        )

    get_tier_info(request.tier)  # 验证层级是否存在

    # 验证任务
    task = db.query(Task).filter(
        Task.id == request.task_id,
        Task.user_id == current_user.id,
    ).first()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在或无权访问",
        )

    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="任务尚未完成，无法支付",
        )

    # 默认 URL
    frontend_base = "http://localhost:3000"
    success_url = request.success_url or f"{frontend_base}/tasks/{task.id}?payment=success"
    cancel_url = request.cancel_url or f"{frontend_base}/tasks/{task.id}?payment=cancelled"

    # 根据支付方式创建订单
    if request.payment_method == "stripe":
        result = create_checkout_session(
            db=db,
            user=current_user,
            task=task,
            tier=request.tier,
            success_url=success_url,
            cancel_url=cancel_url,
        )
        return PaymentCreateResponse(
            order_id=result["order_id"],
            checkout_url=result["checkout_url"],
            session_id=result["session_id"],
            amount_cents=result["amount_cents"],
            currency=result["currency"],
        )

    elif request.payment_method == "alipay":
        result = create_alipay_order(
            db=db,
            user=current_user,
            task=task,
            tier=request.tier,
            return_url=success_url,
        )
        return PaymentCreateResponse(
            order_id=result["order_id"],
            checkout_url=result["payment_url"],
            amount_cents=result["amount_cents"],
            currency=result["currency"],
            message=result["message"],
        )

    elif request.payment_method == "wechat":
        result = create_wechat_order(
            db=db,
            user=current_user,
            task=task,
            tier=request.tier,
            return_url=success_url,
        )
        return PaymentCreateResponse(
            order_id=result["order_id"],
            checkout_url=result["qrcode_url"],
            amount_cents=result["amount_cents"],
            currency=result["currency"],
            message=result["message"],
        )

    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的支付方式: {request.payment_method}，可选: stripe, alipay, wechat",
        )


@router.post("/webhook/stripe", response_model=WebhookResponse, summary="Stripe Webhook 回调")
async def stripe_webhook(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Stripe Webhook 回调端点。

    处理的事件类型：
    - checkout.session.completed: 支付成功，更新订单状态
    - checkout.session.expired: 会话过期，取消订单
    - payment_intent.payment_failed: 支付失败

    安全性：
    - 使用 stripe.Webhook.construct_event() 验证签名
    - 防止伪造回调
    """
    # 读取原始请求体
    payload = await request.body()
    sig_header = request.headers.get("Stripe-Signature")

    if not sig_header:
        logger.warning("Webhook 请求缺少 Stripe-Signature 头")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="缺少 Stripe-Signature 头",
        )

    # 验证签名并解析事件
    try:
        event = verify_webhook_event(payload, sig_header)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Webhook 签名验证异常: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Webhook 签名验证失败",
        )

    # 处理事件
    try:
        result = handle_webhook_event(db, event)
        return WebhookResponse(
            success=result["success"],
            message=result["message"],
            event_type=event.type,
        )
    except Exception as e:
        logger.error(f"Webhook 事件处理异常: {e}", exc_info=True)
        # 返回 200 避免 Stripe 重试（已记录错误）
        return WebhookResponse(
            success=False,
            message=f"事件处理异常: {str(e)}",
            event_type=event.type,
        )


@router.get("/{order_id}", response_model=OrderResponse, summary="查询订单状态")
async def get_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_get_current_user),
):
    """
    查询指定订单的状态。

    仅返回属于当前用户的订单。
    """
    order = get_order_status(db, order_id, current_user.id)
    return order


@router.post("/cancel/{order_id}", response_model=MessageResponse, summary="取消待支付订单")
async def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_get_current_user),
):
    """
    取消待支付的订单。

    只能取消状态为 pending 的订单。
    """
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == current_user.id,
    ).first()

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="订单不存在",
        )

    if order.status != OrderStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"只能取消待支付订单，当前状态: {order.status.value}",
        )

    order.status = OrderStatus.CANCELLED
    db.commit()

    logger.info(f"订单已取消: order_id={order_id}, user={current_user.id}")

    return MessageResponse(success=True, message="订单已取消")


@router.get("/task/{task_id}", response_model=list[OrderResponse], summary="查询任务关联的订单")
async def get_orders_by_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(_get_current_user),
):
    """
    查询指定任务关联的所有订单。

    返回该任务的所有订单记录（包括已取消的）。
    """
    # 验证任务属于当前用户
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.user_id == current_user.id,
    ).first()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在或无权访问",
        )

    orders = db.query(Order).filter(
        Order.task_id == task_id,
        Order.user_id == current_user.id,
    ).order_by(Order.created_at.desc()).all()

    return orders
