"""
任务执行器
- run_gis_task: 执行 GIS 分析任务，封装 GISAgent.run()
- 支持 Celery 异步模式和同步模式
- 任务状态流转: pending -> running -> completed / failed
"""

from __future__ import annotations

import json
import os
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

# 尝试导入 Celery，如果不可用则使用同步模式
try:
    from celery import current_task
    from celery.utils.log import get_task_logger
    from api.celery_app import celery_app
    HAS_CELERY = True
    logger = get_task_logger(__name__)
except ImportError:
    HAS_CELERY = False
    import logging
    logger = logging.getLogger(__name__)


def _update_task_status(task_id: int, status: str, **kwargs) -> None:
    """更新数据库中的任务状态"""
    from api.database import SessionLocal
    from api.models import Task, TaskStatus

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if task is None:
            logger.error(f"任务 {task_id} 不存在")
            return

        task.status = TaskStatus(status)

        if status == "running":
            task.started_at = datetime.utcnow()
        elif status in ("completed", "failed", "cancelled"):
            task.completed_at = datetime.utcnow()

        if "output_files" in kwargs:
            task.output_files = kwargs["output_files"]
        if "final_answer" in kwargs:
            task.final_answer = kwargs["final_answer"]
        if "error_message" in kwargs:
            task.error_message = kwargs["error_message"]
        if "run_log_path" in kwargs:
            task.run_log_path = kwargs["run_log_path"]
        if "celery_task_id" in kwargs:
            task.celery_task_id = kwargs["celery_task_id"]

        db.commit()
        logger.info(f"任务 {task_id} 状态更新为 {status}")
    except Exception as exc:
        db.rollback()
        logger.error(f"更新任务状态失败: {exc}")
    finally:
        db.close()


def _setup_task_output_dir() -> Path:
    """创建输出目录"""
    from config import OUTPUTS_DIR
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    return OUTPUTS_DIR


def _collect_output_files(task_id: int, start_timestamp: float = None) -> list:
    """收集任务产出的文件列表"""
    from config import OUTPUTS_DIR

    output_dir = OUTPUTS_DIR
    files = []

    if not output_dir.exists():
        return files

    # 递归搜索所有文件，按修改时间倒序
    all_files = sorted(output_dir.rglob("*"), key=lambda p: p.stat().st_mtime, reverse=True)

    for f in all_files:
        if f.is_file() and f.suffix.lower() in {".png", ".tif", ".tiff", ".jpg", ".html", ".csv", ".gif"}:
            stat = f.stat()
            modified = datetime.fromtimestamp(stat.st_mtime)

            # 只收集任务开始后生成的文件
            if start_timestamp and stat.st_mtime < start_timestamp:
                continue

            # 使用相对于 OUTPUTS_DIR 的路径（前端代理需要）
            relative_path = f.relative_to(OUTPUTS_DIR)
            files.append({
                "name": f.name,
                "path": str(f),
                "relative_path": str(relative_path),
                "size": stat.st_size,
                "modified": modified.isoformat(),
            })
        if len(files) >= 20:
            break

    return files


def _execute_gis_task(task_id: int, input_text: str, celery_task_id: str = None) -> Dict[str, Any]:
    """实际执行 GIS 任务的核心逻辑"""
    logger.info(f"开始执行任务 {task_id}: {input_text}")

    import time
    import config as app_config
    task_start_timestamp = time.time()

    _update_task_status(task_id, "running", celery_task_id=celery_task_id)

    # 使用输出目录
    output_dir = _setup_task_output_dir()
    original_outputs_dir = app_config.OUTPUTS_DIR
    app_config.OUTPUTS_DIR = output_dir
    logger.info(f"任务 {task_id} 输出目录: {output_dir}")

    try:
        # 初始化 GEE
        from agent.gee_client import init_gee
        gee_result = init_gee()
        if not gee_result.get("success"):
            raise RuntimeError(f"GEE 初始化失败: {gee_result.get('message')}")

        from agent.core import GISAgent

        agent = GISAgent(max_steps=25)
        result = agent.run(input_text)

        # 收集任务输出文件
        output_files = _collect_output_files(task_id, start_timestamp=task_start_timestamp)
        run_log_path = result.get("run_log", {}).get("log_path") if isinstance(result.get("run_log"), dict) else None
        final_answer = result.get("final_answer", "")

        _update_task_status(
            task_id,
            "completed",
            output_files=output_files,
            final_answer=final_answer,
            run_log_path=run_log_path,
        )

        logger.info(f"任务 {task_id} 执行完成，共 {len(output_files)} 个输出文件")

        return {
            "success": True,
            "task_id": task_id,
            "final_answer": result.get("final_answer", ""),
            "output_files": output_files,
            "steps": len(result.get("history", [])),
        }

    except Exception as exc:
        error_msg = f"{type(exc).__name__}: {exc}"
        tb = traceback.format_exc()
        logger.error(f"任务 {task_id} 执行失败: {error_msg}\n{tb}")

        _update_task_status(task_id, "failed", error_message=error_msg)

        return {
            "success": False,
            "task_id": task_id,
            "error": error_msg,
        }
    finally:
        # 恢复原始输出目录
        app_config.OUTPUTS_DIR = original_outputs_dir


if HAS_CELERY:
    # Celery 模式：使用装饰器定义异步任务
    @celery_app.task(
        bind=True,
        name="api.tasks_worker.run_gis_task",
        max_retries=1,
        default_retry_delay=30,
        acks_late=True,
    )
    def run_gis_task(self, task_id: int, input_text: str) -> Dict[str, Any]:
        """Celery 异步执行 GIS 任务"""
        result = _execute_gis_task(task_id, input_text, celery_task_id=self.request.id)

        if not result.get("success"):
            exc = Exception(result.get("error", "未知错误"))
            if isinstance(exc, (ConnectionError, TimeoutError)):
                try:
                    self.retry(exc=exc)
                except self.MaxRetriesExceededError:
                    logger.error(f"任务 {task_id} 达到最大重试次数")

        return result
else:
    # 同步模式：直接执行任务
    def run_gis_task(task_id: int, input_text: str) -> Dict[str, Any]:
        """同步执行 GIS 任务（无 Celery 时使用）"""
        return _execute_gis_task(task_id, input_text)
