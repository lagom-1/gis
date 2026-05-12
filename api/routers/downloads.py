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
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import Download, Order, OrderStatus, Task, TaskStatus
from api.services.file_service import (
    check_file_type_permission,
    generate_thumbnail,
    get_file_type_for_payment,
    get_task_output_info,
    get_thumbnail_path,
)
from api.services.payment_service import check_download_permission

# 默认用户 ID，无需认证
DEFAULT_USER_ID = 1

router = APIRouter(prefix="/api/downloads", tags=["下载"])


# ── 文件信息端点 ─────────────────────────────────────────


@router.get("/{task_id}/info", summary="获取任务输出文件信息")
async def get_task_files_info(
    task_id: int,
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """
    获取任务输出文件的元数据和预览信息。

    返回：
    - 文件列表（名称、大小、类型、预览 URL、下载 URL）
    - 文件总数和总大小
    - 包含的文件类型
    """
    # 验证任务
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.user_id == DEFAULT_USER_ID,
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
        Order.user_id == DEFAULT_USER_ID,
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
):
    """
    预览输出文件的缩略图（免费）。

    - PNG/JPG：缩放到 200px 宽，保持比例
    - TIF：读取第一波段，归一化后转为 PNG 缩略图
    - GIF：提取第一帧生成缩略图
    - HTML：生成占位图

    缩略图会缓存到 workspace/outputs/thumbnails/ 目录。
    """
    # 验证任务
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.user_id == DEFAULT_USER_ID,
    ).first()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="任务尚未完成")

    # 查找文件
    if not task.output_files:
        raise HTTPException(status_code=404, detail="任务没有输出文件")

    file_info = None
    for f in task.output_files:
        if f.get("name") == filename:
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
        # 无法生成缩略图，返回 400
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
):
    """
    下载指定任务的完整输出文件（需付费）。

    流程：
    1. 验证任务存在且属于当前用户
    2. 验证文件存在
    3. 检查文件类型是否需要付费
    4. 检查用户是否有已支付的订单
    5. 验证订单层级是否包含该文件类型
    6. 返回完整文件并记录下载

    免费文件类型：metadata（json/txt）、statistics（csv）
    需付费文件类型：png/jpg/gif/tif/html/pdf
    """
    # 验证任务
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.user_id == DEFAULT_USER_ID,
    ).first()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status != TaskStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="任务尚未完成")

    # 查找文件
    if not task.output_files:
        raise HTTPException(status_code=404, detail="任务没有输出文件")

    file_info = None
    for f in task.output_files:
        if f.get("name") == filename:
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
            user_id=DEFAULT_USER_ID,
            file_type=file_type,
        )

        # 记录下载行为
        download_record = Download(
            user_id=DEFAULT_USER_ID,
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
