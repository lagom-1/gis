"""
任务路由
- POST   /api/tasks           提交新 GIS 任务
- GET    /api/tasks            列出用户的任务
- GET    /api/tasks/{task_id}  获取任务状态 + 结果
- DELETE /api/tasks/{task_id}  取消任务
"""

from __future__ import annotations

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
from api.routers.auth import _get_current_user

router = APIRouter(prefix="/api/tasks", tags=["任务"])


# ── 端点 ──────────────────────────────────────────────────

@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED, summary="提交新 GIS 任务")
async def create_task(
    request: TaskCreateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(_get_current_user),
):
    """
    提交新的 GIS 分析任务。

    任务会被放入 Celery 队列异步执行。可通过轮询 GET /api/tasks/{task_id} 获取状态。
    """
    # 创建数据库记录
    task = Task(
        user_id=current_user.id,
        input_text=request.input_text,
        status=TaskStatus.PENDING,
    )
    db.add(task)
    db.commit()
    db.refresh(task)

    # 提交任务执行（优先 Celery，回退到同步）
    try:
        from api.tasks_worker import run_gis_task

        try:
            # 尝试使用 Celery 异步执行
            celery_result = run_gis_task.delay(task.id, request.input_text)
            task.celery_task_id = celery_result.id
            db.commit()
            db.refresh(task)
        except Exception:
            # Celery 不可用，使用同步模式执行
            task.status = TaskStatus.RUNNING
            db.commit()

            # 在后台线程中同步执行任务
            from concurrent.futures import ThreadPoolExecutor
            executor = ThreadPoolExecutor(max_workers=1)

            def run_sync():
                try:
                    run_gis_task(task.id, request.input_text)
                except Exception as e:
                    task.status = TaskStatus.FAILED
                    task.error_message = str(e)
                    db.commit()

            executor.submit(run_sync)
            db.refresh(task)
    except Exception as exc:
        task.status = TaskStatus.FAILED
        task.error_message = f"任务执行失败: {exc}"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"任务执行失败: {exc}",
        )

    return task


@router.get("", response_model=TaskListResponse, summary="列出用户的任务")
async def list_tasks(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    status_filter: Optional[TaskStatus] = Query(None, alias="status", description="按状态筛选"),
    db: Session = Depends(get_db),
    current_user: User = Depends(_get_current_user),
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
    current_user: User = Depends(_get_current_user),
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
    current_user: User = Depends(_get_current_user),
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

    # 尝试撤销 Celery 任务
    if task.celery_task_id:
        try:
            from api.celery_app import celery_app
            celery_app.control.revoke(task.celery_task_id, terminate=True)
        except Exception:
            pass  # 撤销失败不影响状态更新

    task.status = TaskStatus.CANCELLED
    from datetime import datetime
    task.completed_at = datetime.utcnow()
    db.commit()

    return MessageResponse(success=True, message=f"任务 {task_id} 已取消")
