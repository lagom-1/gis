"""
下载路由
- GET /api/downloads/{task_id}/preview/{filename}  预览缩略图（免费）
- GET /api/downloads/{task_id}/{filename}          下载完整文件（需付费）
- GET /api/downloads/{task_id}/info                获取任务输出文件信息

付费检查：
- 免费预览：缩略图（200px 宽）
- 付费下载：完整文件，需订单状态为 paid 且层级包含该文件类型
"""

from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import Download, Order, OrderStatus, PaymentRecord, ShareRecord, Task, TaskStatus, User
from api.services.file_service import (
    check_file_type_permission,
    generate_thumbnail,
    get_file_type_for_payment,
    get_task_output_info,
    get_thumbnail_path,
)
from api.services.payment_service import check_download_permission
from api.routers.auth import get_current_user

router = APIRouter(prefix="/api/downloads", tags=["下载"])


class PaymentConfirmRequest(BaseModel):
    """确认支付请求"""
    payment_id: int

from fastapi import Query


@router.get("/serve/{task_id}/{filename}", summary="直接提供文件（用于 iframe）")
async def serve_file(
    task_id: int,
    filename: str,
    token: str = Query(None, description="JWT token（可选）"),
    db: Session = Depends(get_db),
):
    """
    直接提供文件下载，支持通过 query 参数传递 token。
    用于 iframe 等无法携带 Authorization header 的场景。
    """
    from jose import JWTError, jwt
    import config

    # 验证 token
    if not token:
        raise HTTPException(status_code=401, detail="需要认证")

    try:
        payload = jwt.decode(token, config.SECRET_KEY, algorithms=[config.JWT_ALGORITHM])
        user_id = int(payload.get("sub"))
    except (JWTError, ValueError):
        raise HTTPException(status_code=401, detail="无效的 token")

    # 验证任务属于当前用户
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.user_id == user_id,
    ).first()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 查找文件
    if not task.output_files:
        raise HTTPException(status_code=404, detail="任务没有输出文件")

    file_info = None
    if isinstance(task.output_files, dict):
        for name, path in task.output_files.items():
            if name == filename:
                file_info = {"name": name, "path": path}
                break
    elif isinstance(task.output_files, list):
        for f in task.output_files:
            if isinstance(f, dict) and f.get("name") == filename:
                file_info = f
                break

    if file_info is None:
        raise HTTPException(status_code=404, detail=f"文件 {filename} 不存在")

    file_path = Path(file_info["path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件已被删除或移动")

    # 确定 MIME 类型
    media_type, _ = mimetypes.guess_type(str(file_path))
    if media_type is None:
        media_type = "application/octet-stream"

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type=media_type,
    )


# ── 文件路径端点 ─────────────────────────────────────────


@router.get("/by-path", summary="通过文件路径获取下载权限")
async def get_permission_by_path(
    file_path: str = Query(..., description="文件路径"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """通过文件路径查找任务并返回下载权限"""
    # 查找包含该文件的任务
    tasks = db.query(Task).filter(
        Task.user_id == current_user.id,
        Task.status == TaskStatus.COMPLETED,
    ).all()

    found_task = None
    for task in tasks:
        if not task.output_files:
            continue
        if isinstance(task.output_files, dict):
            for name, path in task.output_files.items():
                if path == file_path or path.endswith(file_path):
                    found_task = task
                    break
        elif isinstance(task.output_files, list):
            for f in task.output_files:
                if isinstance(f, dict):
                    p = f.get("path", "")
                    if p == file_path or p.endswith(file_path):
                        found_task = task
                        break
        if found_task:
            break

    if not found_task:
        raise HTTPException(status_code=404, detail="未找到包含该文件的任务")

    from api.services.payment_service import check_download_permission
    result = check_download_permission(db, current_user.id, found_task.id)
    result["task_id"] = found_task.id
    return result


@router.post("/by-path/share", summary="通过文件路径记录分享")
async def share_by_path(
    file_path: str = Query(..., description="文件路径"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """通过文件路径查找任务并记录分享"""
    from datetime import datetime
    from api.services.payment_service import check_download_permission

    tasks = db.query(Task).filter(
        Task.user_id == current_user.id,
        Task.status == TaskStatus.COMPLETED,
    ).all()

    found_task = None
    for task in tasks:
        if not task.output_files:
            continue
        if isinstance(task.output_files, dict):
            for name, path in task.output_files.items():
                if path == file_path or path.endswith(file_path):
                    found_task = task
                    break
        elif isinstance(task.output_files, list):
            for f in task.output_files:
                if isinstance(f, dict):
                    p = f.get("path", "")
                    if p == file_path or p.endswith(file_path):
                        found_task = task
                        break
        if found_task:
            break

    if not found_task:
        raise HTTPException(status_code=404, detail="未找到包含该文件的任务")

    permission = check_download_permission(db, current_user.id, found_task.id)
    if not permission["can_download"] or permission["download_type"] != "share":
        raise HTTPException(status_code=403, detail="本周免费下载次数已用完")

    now = datetime.now()
    share_record = ShareRecord(
        user_id=current_user.id,
        task_id=found_task.id,
        week_number=now.isocalendar()[1],
        year=now.year,
    )
    db.add(share_record)
    db.commit()

    return {
        "success": True,
        "message": "分享成功，开始下载",
        "task_id": found_task.id,
        "share_remaining": permission["share_remaining"] - 1,
    }


@router.post("/by-path/payment", summary="通过文件路径创建支付")
async def create_payment_by_path(
    file_path: str = Query(..., description="文件路径"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """通过文件路径查找任务并创建支付记录"""
    from api.services.payment_service import calculate_price

    tasks = db.query(Task).filter(
        Task.user_id == current_user.id,
        Task.status == TaskStatus.COMPLETED,
    ).all()

    found_task = None
    for task in tasks:
        if not task.output_files:
            continue
        if isinstance(task.output_files, dict):
            for name, path in task.output_files.items():
                if path == file_path or path.endswith(file_path):
                    found_task = task
                    break
        elif isinstance(task.output_files, list):
            for f in task.output_files:
                if isinstance(f, dict):
                    p = f.get("path", "")
                    if p == file_path or p.endswith(file_path):
                        found_task = task
                        break
        if found_task:
            break

    if not found_task:
        raise HTTPException(status_code=404, detail="未找到包含该文件的任务")

    existing = db.query(PaymentRecord).filter(
        PaymentRecord.user_id == current_user.id,
        PaymentRecord.task_id == found_task.id,
        PaymentRecord.status == "pending",
    ).first()

    if existing:
        return {
            "success": True,
            "payment_id": existing.id,
            "amount_yuan": existing.amount_yuan,
            "task_id": found_task.id,
            "message": "请扫码支付后点击「我已支付」",
        }

    price = calculate_price(found_task)
    payment = PaymentRecord(
        user_id=current_user.id,
        task_id=found_task.id,
        amount_yuan=price,
        status="pending",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    return {
        "success": True,
        "payment_id": payment.id,
        "amount_yuan": price,
        "task_id": found_task.id,
        "message": "请扫码支付后点击「我已支付」",
    }


# ── 文件信息端点 ─────────────────────────────────────────


@router.get("/{task_id}/info", summary="获取任务输出文件信息")
async def get_task_files_info(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """
    获取任务输出文件的元数据和预览信息。
    """
    # 验证任务属于当前用户
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.user_id == current_user.id,
    ).first()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="任务尚未完成")

    if not task.output_files:
        raise HTTPException(status_code=404, detail="任务没有输出文件")

    # 获取文件信息
    file_info = get_task_output_info(task_id, task.output_files)

    # 检查用户是否有已支付的订单
    paid_order = db.query(Order).filter(
        Order.task_id == task_id,
        Order.user_id == current_user.id,
        Order.status == OrderStatus.PAID,
    ).first()

    file_info["has_paid_order"] = paid_order is not None
    if paid_order:
        from api.services.payment_service import _infer_tier_from_amount
        file_info["paid_tier"] = _infer_tier_from_amount(
            paid_order.amount_cents, paid_order.currency
        )

    return file_info


# ── 预览端点（免费）──────────────────────────────────────────


@router.get("/{task_id}/preview/{filename}", summary="预览输出文件缩略图（免费）")
async def preview_file(
    task_id: int,
    filename: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    预览输出文件的缩略图（免费）。
    """
    # 验证任务属于当前用户
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.user_id == current_user.id,
    ).first()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="任务尚未完成")

    # 查找文件
    if not task.output_files:
        raise HTTPException(status_code=404, detail="任务没有输出文件")

    file_info = None
    if isinstance(task.output_files, dict):
        # 字典格式：{filename: filepath}
        for name, path in task.output_files.items():
            if name == filename:
                file_info = {"name": name, "path": path}
                break
    elif isinstance(task.output_files, list):
        # 列表格式：[{"name": ..., "path": ...}, ...]
        for f in task.output_files:
            if isinstance(f, dict) and f.get("name") == filename:
                file_info = f
                break

    if file_info is None:
        raise HTTPException(status_code=404, detail=f"文件 {filename} 不存在")

    file_path = Path(file_info["path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件已被删除或移动")

    # 生成缩略图
    thumbnail_path = generate_thumbnail(file_path)
    if thumbnail_path is None:
        raise HTTPException(
            status_code=400,
            detail=f"无法为 {file_path.suffix} 类型文件生成缩略图",
        )

    return FileResponse(
        path=str(thumbnail_path),
        filename=f"preview_{file_path.stem}.png",
        media_type="image/png",
    )


# ── 下载端点（需付费）────────────────────────────────────────


@router.get("/{task_id}/{filename}", summary="下载输出文件（需付费）")
async def download_file(
    task_id: int,
    filename: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    下载指定任务的完整输出文件（需付费）。
    """
    # 验证任务属于当前用户
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.user_id == current_user.id,
    ).first()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="任务尚未完成")

    # 查找文件
    if not task.output_files:
        raise HTTPException(status_code=404, detail="任务没有输出文件")

    file_info = None
    if isinstance(task.output_files, dict):
        # 字典格式：{filename: filepath}
        for name, path in task.output_files.items():
            if name == filename:
                file_info = {"name": name, "path": path}
                break
    elif isinstance(task.output_files, list):
        # 列表格式：[{"name": ..., "path": ...}, ...]
        for f in task.output_files:
            if isinstance(f, dict) and f.get("name") == filename:
                file_info = f
                break

    if file_info is None:
        raise HTTPException(status_code=404, detail=f"文件 {filename} 不存在")

    file_path = Path(file_info["path"])
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件已被删除或移动")

    # 确定文件类型（用于付费检查）
    file_type = get_file_type_for_payment(file_path)

    # 免费文件类型：metadata 和 statistics 无需付费
    free_types = {"metadata", "statistics"}
    if file_type not in free_types:
        # 需要付费的文件类型，检查订单状态
        order = check_download_permission(
            db=db,
            task_id=task_id,
            user_id=current_user.id,
            file_type=file_type,
        )

        # 记录下载行为
        download_record = Download(
            user_id=current_user.id,
            order_id=order.id,
            task_id=task_id,
            file_path=str(file_path),
        )
        db.add(download_record)
        db.commit()

    # 确定 MIME 类型
    media_type, _ = mimetypes.guess_type(str(file_path))
    if media_type is None:
        media_type = "application/octet-stream"

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type=media_type,
    )


@router.get("/{task_id}/check-permission", summary="检查下载权限")
async def check_permission(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """检查用户是否有下载权限"""
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.user_id == current_user.id,
    ).first()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    from api.services.payment_service import check_download_permission
    result = check_download_permission(db, current_user.id, task_id)
    return result


@router.post("/{task_id}/share", summary="记录分享")
async def record_share(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录用户分享并返回下载链接"""
    from datetime import datetime
    from api.services.payment_service import check_download_permission

    task = db.query(Task).filter(
        Task.id == task_id,
        Task.user_id == current_user.id,
    ).first()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    permission = check_download_permission(db, current_user.id, task_id)
    if not permission["can_download"] or permission["download_type"] != "share":
        raise HTTPException(status_code=403, detail="本周免费下载次数已用完")

    now = datetime.now()
    share_record = ShareRecord(
        user_id=current_user.id,
        task_id=task_id,
        week_number=now.isocalendar()[1],
        year=now.year,
    )
    db.add(share_record)
    db.commit()

    return {
        "success": True,
        "message": "分享成功，开始下载",
        "share_remaining": permission["share_remaining"] - 1,
    }


@router.post("/{task_id}/payment", summary="创建支付记录")
async def create_payment(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建支付记录"""
    from api.services.payment_service import calculate_price

    task = db.query(Task).filter(
        Task.id == task_id,
        Task.user_id == current_user.id,
    ).first()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    existing = db.query(PaymentRecord).filter(
        PaymentRecord.user_id == current_user.id,
        PaymentRecord.task_id == task_id,
        PaymentRecord.status == "pending",
    ).first()

    if existing:
        return {
            "success": True,
            "payment_id": existing.id,
            "amount_yuan": existing.amount_yuan,
            "message": "请扫码支付后点击「我已支付」",
        }

    price = calculate_price(task)
    payment = PaymentRecord(
        user_id=current_user.id,
        task_id=task_id,
        amount_yuan=price,
        status="pending",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    return {
        "success": True,
        "payment_id": payment.id,
        "amount_yuan": price,
        "message": "请扫码支付后点击「我已支付」",
    }


@router.post("/confirm-payment", summary="确认支付（管理员）")
async def confirm_payment(
    request: PaymentConfirmRequest,
    db: Session = Depends(get_db),
):
    """管理员确认支付"""
    payment = db.query(PaymentRecord).filter(
        PaymentRecord.id == request.payment_id,
    ).first()

    if payment is None:
        raise HTTPException(status_code=404, detail="支付记录不存在")

    if payment.status != "pending":
        raise HTTPException(status_code=400, detail="支付状态异常")

    from datetime import datetime
    payment.status = "paid"
    payment.paid_at = datetime.now()
    payment.confirmed_at = datetime.now()
    db.commit()

    return {
        "success": True,
        "message": "支付已确认，可以下载",
    }
