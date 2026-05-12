"""
支付服务层
- Stripe Checkout Session 创建与管理
- Webhook 签名验证
- 定价层级定义
- 支付宝/微信支付占位
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional

import stripe
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

import config
from api.models import Order, OrderStatus, Task, TaskStatus, User

logger = logging.getLogger(__name__)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  定价层级
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

PRICING_TIERS: Dict[str, Dict[str, Any]] = {
    "free": {
        "price_cents": 0,
        "currency": "CNY",
        "description": "仅预览（缩略图、元数据、统计摘要）",
        "includes": ["preview", "metadata", "statistics"],
    },
    "basic": {
        "price_cents": 990,
        "currency": "CNY",
        "stripe_price_cents": 150,  # $1.50 USD
        "description": "PNG 输出（专题图、图表、趋势图）",
        "includes": ["preview", "metadata", "statistics", "png"],
    },
    "standard": {
        "price_cents": 2990,
        "currency": "CNY",
        "stripe_price_cents": 450,  # $4.50 USD
        "description": "所有图像输出 + HTML 交互地图 + 报告",
        "includes": ["preview", "metadata", "statistics", "png", "html", "report"],
    },
    "premium": {
        "price_cents": 4990,
        "currency": "CNY",
        "stripe_price_cents": 750,  # $7.50 USD
        "description": "所有输出 + 原始 TIF 数据 + GIF 动画",
        "includes": ["preview", "metadata", "statistics", "png", "html", "report", "tif", "gif"],
    },
}

# 定价层级对应的 Stripe 价格 ID（生产环境应配置实际的 Price ID）
STRIPE_PRICE_IDS: Dict[str, str] = {
    "basic": config.STRIPE_PRICE_BASIC if hasattr(config, "STRIPE_PRICE_BASIC") else "",
    "standard": config.STRIPE_PRICE_STANDARD if hasattr(config, "STRIPE_PRICE_STANDARD") else "",
    "premium": config.STRIPE_PRICE_PREMIUM if hasattr(config, "STRIPE_PRICE_PREMIUM") else "",
}


def get_pricing_tiers() -> Dict[str, Dict[str, Any]]:
    """返回所有定价层级信息"""
    return PRICING_TIERS


def get_tier_info(tier: str) -> Dict[str, Any]:
    """获取指定层级信息，不存在则抛出异常"""
    if tier not in PRICING_TIERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"无效的定价层级: {tier}，可选值: {', '.join(PRICING_TIERS.keys())}",
        )
    return PRICING_TIERS[tier]


def calculate_amount(tier: str, payment_method: str = "stripe") -> int:
    """
    根据层级和支付方式计算金额（分）

    Args:
        tier: 定价层级名称
        payment_method: 支付方式 (stripe/alipay/wechat)

    Returns:
        金额（分）
    """
    tier_info = get_tier_info(tier)

    if payment_method == "stripe":
        # Stripe 使用美元价格
        return tier_info.get("stripe_price_cents", tier_info["price_cents"])
    else:
        # 支付宝/微信使用人民币价格
        return tier_info["price_cents"]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Stripe 支付服务
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _init_stripe() -> None:
    """初始化 Stripe API 密钥"""
    if not config.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe 支付服务未配置，请联系管理员",
        )
    stripe.api_key = config.STRIPE_SECRET_KEY


def create_checkout_session(
    db: Session,
    user: User,
    task: Task,
    tier: str,
    success_url: str,
    cancel_url: str,
) -> Dict[str, Any]:
    """
    创建 Stripe Checkout Session

    Args:
        db: 数据库会话
        user: 当前用户
        task: 关联任务
        tier: 定价层级
        success_url: 支付成功后跳转 URL
        cancel_url: 取消支付后跳转 URL

    Returns:
        包含 order_id, checkout_url, session_id 的字典
    """
    _init_stripe()

    # 验证任务状态
    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="任务尚未完成，无法支付",
        )

    # 检查是否已有已支付的订单（同一任务不能重复购买）
    paid_order = db.query(Order).filter(
        Order.task_id == task.id,
        Order.user_id == user.id,
        Order.status == OrderStatus.PAID,
    ).first()
    if paid_order:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该任务已支付，无需重复购买",
        )

    # 取消同一任务的待支付订单（允许重新下单）
    pending_orders = db.query(Order).filter(
        Order.task_id == task.id,
        Order.user_id == user.id,
        Order.status == OrderStatus.PENDING,
    ).all()
    for pending_order in pending_orders:
        pending_order.status = OrderStatus.CANCELLED

    # 计算金额
    tier_info = get_tier_info(tier)
    amount_cents = calculate_amount(tier, "stripe")
    currency = "usd"  # Stripe Checkout 使用小写货币代码

    # 创建订单记录
    order = Order(
        user_id=user.id,
        task_id=task.id,
        amount_cents=amount_cents,
        currency=currency.upper(),
        status=OrderStatus.PENDING,
        payment_method="stripe",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    try:
        # 创建 Stripe Checkout Session
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price_data": {
                    "currency": currency,
                    "product_data": {
                        "name": f"OpenGIS - {tier_info['description']}",
                        "description": f"任务 #{task.id}: {task.input_text[:100]}",
                        "metadata": {
                            "task_id": str(task.id),
                            "order_id": str(order.id),
                            "tier": tier,
                        },
                    },
                    "unit_amount": amount_cents,
                },
                "quantity": 1,
            }],
            mode="payment",
            success_url=f"{success_url}?session_id={{CHECKOUT_SESSION_ID}}&order_id={order.id}",
            cancel_url=f"{cancel_url}?order_id={order.id}",
            client_reference_id=str(order.id),
            customer_email=user.email,
            metadata={
                "order_id": str(order.id),
                "task_id": str(task.id),
                "user_id": str(user.id),
                "tier": tier,
            },
            expires_in=1800,  # 30 分钟过期
        )

        # 更新订单的支付 ID
        order.payment_id = session.id
        db.commit()

        logger.info(
            f"Stripe Checkout Session 创建成功: session={session.id}, "
            f"order={order.id}, user={user.id}, tier={tier}, amount={amount_cents}"
        )

        return {
            "order_id": order.id,
            "checkout_url": session.url,
            "session_id": session.id,
            "amount_cents": amount_cents,
            "currency": currency.upper(),
            "expires_at": session.expires_at,
        }

    except stripe.error.StripeError as e:
        # Stripe 调用失败，将订单标记为取消
        order.status = OrderStatus.CANCELLED
        db.commit()
        logger.error(f"Stripe Checkout Session 创建失败: {e}")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"支付服务异常: {str(e)}",
        )


def verify_webhook_event(payload: bytes, sig_header: str) -> stripe.Event:
    """
    验证 Stripe Webhook 签名并解析事件

    Args:
        payload: 原始请求体（bytes）
        sig_header: Stripe-Signature 头部值

    Returns:
        解析后的 Stripe Event 对象

    Raises:
        HTTPException: 签名验证失败或事件类型无效
    """
    _init_stripe()

    if not config.STRIPE_WEBHOOK_SECRET:
        logger.warning("STRIPE_WEBHOOK_SECRET 未配置，跳过签名验证（仅限开发环境）")
        # 开发环境：不验证签名，直接解析
        try:
            import json
            event_data = json.loads(payload)
            return stripe.Event.construct_from(event_data, stripe.api_key)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"无效的 webhook 负载: {str(e)}",
            )

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, config.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="无效的 webhook 负载",
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="webhook 签名验证失败",
        )

    return event


def handle_checkout_completed(db: Session, event_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    处理 checkout.session.completed 事件

    Args:
        db: 数据库会话
        event_data: Stripe 事件数据

    Returns:
        处理结果字典
    """
    session = event_data.get("object", {})
    session_id = session.get("id")
    payment_status = session.get("payment_status")
    client_reference_id = session.get("client_reference_id")
    metadata = session.get("metadata", {})

    order_id = metadata.get("order_id") or client_reference_id

    if not order_id:
        logger.error(f"Webhook 缺少 order_id: session={session_id}")
        return {"success": False, "message": "缺少 order_id"}

    order = db.query(Order).filter(Order.id == int(order_id)).first()
    if order is None:
        logger.error(f"订单不存在: order_id={order_id}")
        return {"success": False, "message": "订单不存在"}

    if order.status == OrderStatus.PAID:
        logger.info(f"订单已处理，跳过: order_id={order_id}")
        return {"success": True, "message": "订单已处理"}

    if payment_status == "paid":
        order.status = OrderStatus.PAID
        order.payment_id = session_id
        order.paid_at = datetime.utcnow()
        db.commit()

        logger.info(f"订单支付成功: order_id={order_id}, session={session_id}")
        return {
            "success": True,
            "message": "支付成功",
            "order_id": order.id,
            "task_id": order.task_id,
        }
    else:
        logger.warning(
            f"Webhook 支付状态异常: order_id={order_id}, "
            f"payment_status={payment_status}"
        )
        return {"success": False, "message": f"支付状态: {payment_status}"}


def handle_webhook_event(db: Session, event: stripe.Event) -> Dict[str, Any]:
    """
    分发处理不同类型的 Stripe Webhook 事件

    Args:
        db: 数据库会话
        event: Stripe Event 对象

    Returns:
        处理结果字典
    """
    event_type = event.type
    event_data = event.data.object if hasattr(event, "data") else {}

    logger.info(f"收到 Stripe webhook 事件: type={event_type}, id={event.id}")

    if event_type == "checkout.session.completed":
        return handle_checkout_completed(db, {"object": event_data})

    elif event_type == "checkout.session.expired":
        # 会话过期，取消订单
        metadata = event_data.get("metadata", {})
        order_id = metadata.get("order_id")
        if order_id:
            order = db.query(Order).filter(Order.id == int(order_id)).first()
            if order and order.status == OrderStatus.PENDING:
                order.status = OrderStatus.CANCELLED
                db.commit()
                logger.info(f"订单因会话过期已取消: order_id={order_id}")
        return {"success": True, "message": "会话已过期"}

    elif event_type == "payment_intent.payment_failed":
        logger.warning(f"支付失败: {event_data.get('id')}")
        return {"success": True, "message": "支付失败已记录"}

    else:
        logger.info(f"未处理的 webhook 事件类型: {event_type}")
        return {"success": True, "message": f"事件 {event_type} 已接收"}


def get_order_status(db: Session, order_id: int, user_id: int) -> Order:
    """
    查询订单状态

    Args:
        db: 数据库会话
        order_id: 订单 ID
        user_id: 当前用户 ID

    Returns:
        Order 对象

    Raises:
        HTTPException: 订单不存在或无权访问
    """
    order = db.query(Order).filter(
        Order.id == order_id,
        Order.user_id == user_id,
    ).first()

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="订单不存在",
        )

    return order


def check_download_permission(db: Session, task_id: int, user_id: int, file_type: str = "png") -> Order:
    """
    检查用户是否有权限下载指定类型的文件

    Args:
        db: 数据库会话
        task_id: 任务 ID
        user_id: 用户 ID
        file_type: 文件类型 (png/html/tif/gif/report)

    Returns:
        已支付的 Order 对象

    Raises:
        HTTPException: 无权下载
    """
    # 查找已支付的订单
    order = db.query(Order).filter(
        Order.task_id == task_id,
        Order.user_id == user_id,
        Order.status == OrderStatus.PAID,
    ).first()

    if order is None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="请先支付后再下载",
        )

    # 检查层级是否包含该文件类型
    # 根据订单金额反推层级
    tier = _infer_tier_from_amount(order.amount_cents, order.currency)
    if tier and file_type not in PRICING_TIERS.get(tier, {}).get("includes", []):
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"当前套餐不包含 {file_type} 类型文件，请升级套餐",
        )

    return order


def _infer_tier_from_amount(amount_cents: int, currency: str) -> Optional[str]:
    """根据金额反推定价层级"""
    for tier_name, tier_info in PRICING_TIERS.items():
        if tier_name == "free":
            continue
        if currency == "USD":
            if tier_info.get("stripe_price_cents") == amount_cents:
                return tier_name
        else:
            if tier_info["price_cents"] == amount_cents:
                return tier_name
    return None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  支付宝/微信支付占位
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def create_alipay_order(
    db: Session,
    user: User,
    task: Task,
    tier: str,
    return_url: str,
) -> Dict[str, Any]:
    """
    创建支付宝订单（占位实现）

    TODO: 集成 python-alipay-sdk
    - from alipay.aop.api.AlipayClientConfig import AlipayClientConfig
    - from alipay.aop.api.domain.AlipayTradePagePayModel import AlipayTradePagePayModel
    """
    tier_info = get_tier_info(tier)
    amount_cents = calculate_amount(tier, "alipay")

    # 创建订单记录
    order = Order(
        user_id=user.id,
        task_id=task.id,
        amount_cents=amount_cents,
        currency="CNY",
        status=OrderStatus.PENDING,
        payment_method="alipay",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    logger.info(f"支付宝订单创建（占位）: order={order.id}, amount={amount_cents}")

    return {
        "order_id": order.id,
        "payment_url": f"https://openapi.alipay.com/gateway.do?placeholder=true&order_id={order.id}",
        "amount_cents": amount_cents,
        "currency": "CNY",
        "message": "支付宝支付暂未开放，请使用 Stripe 支付",
    }


def create_wechat_order(
    db: Session,
    user: User,
    task: Task,
    tier: str,
    return_url: str,
) -> Dict[str, Any]:
    """
    创建微信支付订单（占位实现）

    TODO: 集成 wechatpay-python 或 wxpay-sdk
    """
    tier_info = get_tier_info(tier)
    amount_cents = calculate_amount(tier, "wechat")

    # 创建订单记录
    order = Order(
        user_id=user.id,
        task_id=task.id,
        amount_cents=amount_cents,
        currency="CNY",
        status=OrderStatus.PENDING,
        payment_method="wechat",
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    logger.info(f"微信支付订单创建（占位）: order={order.id}, amount={amount_cents}")

    return {
        "order_id": order.id,
        "qrcode_url": f"weixin://wxpay/bizpayurl?placeholder=true&order_id={order.id}",
        "amount_cents": amount_cents,
        "currency": "CNY",
        "message": "微信支付暂未开放，请使用 Stripe 支付",
    }
