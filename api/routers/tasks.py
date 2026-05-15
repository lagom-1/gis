"""
任务路由
- POST   /api/tasks           提交新 GIS 任务
- GET    /api/tasks            列出用户的任务
- GET    /api/tasks/{task_id}  获取任务状态 + 结果
- DELETE /api/tasks/{task_id}  取消任务
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.database import get_db
from api.models import (
    MessageResponse,
    Task,
    TaskCreateRequest,
    TaskListResponse,
    TaskResponse,
    TaskStatus,
    User,
)
from api.routers.auth import get_current_user

logger = logging.getLogger(__name__)

# 全局线程池（限制并发任务数，避免资源竞争）
from concurrent.futures import ThreadPoolExecutor
import threading

_task_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="gis-task")
_running_futures: dict[int, object] = {}  # task_id -> Future
_futures_lock = threading.Lock()

router = APIRouter(prefix="/api/tasks", tags=["任务"])


# ── 端点 ──────────────────────────────────────────────────

@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED, summary="提交新 GIS 任务")
async def create_task(
    request: TaskCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    提交新的 GIS 分析任务。

    任务会被放入后台线程异步执行。可通过轮询 GET /api/tasks/{task_id} 获取状态。
    """
    # 检查是否有正在运行的任务
    with _futures_lock:
        running_count = sum(1 for f in _running_futures.values() if not f.done())

    if running_count >= 2:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="已有 2 个任务正在运行，请稍后再试",
        )

    # 创建数据库记录（状态保持 PENDING，线程启动后才改为 RUNNING）
    task = Task(
        user_id=current_user.id,
        input_text=request.input_text,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    task_id = task.id

    # 在后台线程中执行任务
    from api.tasks_worker import run_gis_task, _update_task_status

    def run_sync():
        # 线程实际开始执行时才改为 RUNNING
        _update_task_status(task_id, "running")
        try:
            run_gis_task(task_id, request.input_text)
        except Exception as e:
            logger.error(f"任务 {task_id} 执行异常: {e}", exc_info=True)
            _update_task_status(task_id, "failed", error_message=f"执行异常: {e}")

    future = _task_executor.submit(run_sync)

    with _futures_lock:
        _running_futures[task_id] = future

    # 清理完成的 future（不设置超时，让任务自然完成）
    def _cleanup_when_done():
        future.result()  # 等待任务自然结束，不设超时
        with _futures_lock:
            _running_futures.pop(task_id, None)

    threading.Thread(target=_cleanup_when_done, daemon=True).start()

    db.refresh(task)
    return task


@router.get("", response_model=TaskListResponse, summary="列出用户的任务")
async def list_tasks(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    status_filter: Optional[TaskStatus] = Query(None, alias="status", description="按状态筛选"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的任务列表，支持分页和状态筛选。"""
    query = db.query(Task).filter(Task.user_id == current_user.id)

    if status_filter:
        query = query.filter(Task.status == status_filter)

    total = query.count()
    tasks = (
        query
        .order_by(Task.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return TaskListResponse(
        tasks=tasks,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{task_id}", response_model=TaskResponse, summary="获取任务状态和结果")
async def get_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取指定任务的详细信息，包括状态、输出文件和错误信息。"""
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    return task


@router.delete("/{task_id}", response_model=MessageResponse, summary="取消任务")
async def cancel_task(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """取消一个待执行或正在运行的任务。已完成的任务无法取消。"""
    task = db.query(Task).filter(Task.id == task_id, Task.user_id == current_user.id).first()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    if task.status in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
        raise HTTPException(
            status_code=400,
            detail=f"任务已处于 {task.status.value} 状态，无法取消",
        )

    # 尝试取消后台 Future
    with _futures_lock:
        future = _running_futures.get(task_id)
        if future and not future.done():
            future.cancel()

    task.status = TaskStatus.CANCELLED
    from datetime import datetime
    task.completed_at = datetime.utcnow()
    db.commit()

    return MessageResponse(success=True, message=f"任务 {task_id} 已取消")
