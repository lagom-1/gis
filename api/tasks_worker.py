"""
任务执行器
- run_gis_task: 执行 GIS 分析任务，封装 GISAgent.run()
- 支持 Celery 异步模式和同步模式
- 任务状态流转: pending -> running -> completed / failed
"""

from __future__ import annotations

import json
import os
import re
import threading
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
    """更新数据库中的任务状态，同时检查任务是否已被取消"""
    from api.database import SessionLocal
    from api.models import Task, TaskStatus

    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if task is None:
            logger.error(f"任务 {task_id} 不存在")
            return

        # 防止已取消的任务被覆盖为 completed/failed
        if task.status == TaskStatus.CANCELLED and status in ("completed", "failed"):
            logger.warning(f"任务 {task_id} 已被用户取消，忽略状态更新为 {status}")
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
        if "current_step" in kwargs:
            task.current_step = kwargs["current_step"]
        if "step_description" in kwargs:
            task.step_description = kwargs["step_description"]

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


def _natural_sort_key(name: str) -> tuple:
    """自然排序键：数字零位补齐，确保 1月 < 2月 < 10月，全部保持字符串避免类型比较错误"""
    parts = []
    for text, num in re.findall(r"(\D*)(\d+)", name):
        if text:
            parts.append(text)
        if num:
            parts.append(num.zfill(10))
    # 处理末尾非数字部分
    last = re.split(r"\d+", name)[-1]
    if last:
        parts.append(last)
    return tuple(parts)


def _collect_output_files(task_id: int, start_timestamp: float = None) -> list:
    """收集任务产出的文件列表，按文件名自然排序，不再限制数量"""
    from config import OUTPUTS_DIR

    output_dir = OUTPUTS_DIR
    files = []

    if not output_dir.exists():
        return files

    # 递归搜索所有文件
    all_files = sorted(
        [p for p in output_dir.rglob("*") if p.is_file()],
        key=lambda p: _natural_sort_key(p.name),
    )

    # 将当前任务的直接输出排在前面（不在子目录中的文件 + 最新子目录中的文件）
    root_files = []
    sub_files = []

    for f in all_files:
        if f.suffix.lower() not in {".png", ".tif", ".tiff", ".jpg", ".jpeg", ".html", ".csv", ".gif"}:
            continue

        stat = f.stat()
        # 只收集任务开始后生成的文件
        if start_timestamp and stat.st_mtime < start_timestamp:
            continue

        modified = datetime.fromtimestamp(stat.st_mtime)
        relative_path = f.relative_to(OUTPUTS_DIR)
        entry = {
            "name": f.name,
            "path": str(f),
            "relative_path": str(relative_path),
            "size": stat.st_size,
            "modified": modified.isoformat(),
        }

        if str(relative_path) == f.name:
            root_files.append(entry)
        else:
            sub_files.append(entry)

    # 按名称自然排序：根目录文件在前，子目录文件在后
    root_files.sort(key=lambda x: _natural_sort_key(x["name"]))
    sub_files.sort(key=lambda x: _natural_sort_key(x["relative_path"]))

    return root_files + sub_files


_output_dir_lock = threading.Lock()


def _execute_gis_task(task_id: int, input_text: str, celery_task_id: str = None) -> Dict[str, Any]:
    """实际执行 GIS 任务的核心逻辑"""
    logger.info(f"开始执行任务 {task_id}: {input_text}")

    import time
    task_start_timestamp = time.time()

    if celery_task_id:
        _update_task_status(task_id, "running", celery_task_id=celery_task_id)

    output_dir = _setup_task_output_dir()
    logger.info(f"任务 {task_id} 输出目录: {output_dir}")

    try:
        # 初始化 GEE（带锁避免并发初始化）
        from agent.gee_client import init_gee
        gee_result = init_gee()
        if not gee_result.get("success"):
            raise RuntimeError(f"GEE 初始化失败: {gee_result.get('message')}")

        import config as app_config

        from agent.core import GISAgent

        agent = GISAgent(max_steps=25)

        def _on_progress(step: int, tool: str):
            _update_task_status(task_id, "running", current_step=step, step_description=tool)

        result = agent.run(input_text, progress_callback=_on_progress)

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
            error_msg = result.get("error", "未知错误")
            # 检查是否为可重试的网络/超时错误
            if any(err_type in error_msg for err_type in ("ConnectionError", "TimeoutError", "ConnectTimeout", "Max retries")):
                try:
                    self.retry(exc=Exception(error_msg))
                except self.MaxRetriesExceededError:
                    logger.error(f"任务 {task_id} 达到最大重试次数")

        return result
else:
    # 同步模式：直接执行任务
    def run_gis_task(task_id: int, input_text: str) -> Dict[str, Any]:
        """同步执行 GIS 任务（无 Celery 时使用）"""
        return _execute_gis_task(task_id, input_text)
