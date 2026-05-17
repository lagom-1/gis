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


def _build_result_summary(agent_result: Dict[str, Any]) -> str:
    """从 Agent 执行历史中提取元数据，构建结构化的任务摘要"""
    history = agent_result.get("history", [])
    if not history:
        return ""

    lines = []

    # 提取行政区信息
    for step in history:
        if step.get("tool") == "resolve_admin_region" and step.get("result", {}).get("success"):
            r = step["result"]
            lines.append(f"**研究区**：{r.get('matched_name', '未知')}")
            break

    # 提取数据下载信息
    download_steps = [s for s in history if s.get("tool") in (
        "gee_download_landsat_sca", "gee_download_monthly_lst",
        "gee_download_yearly_lst", "gee_download_multi_year_lst",
        "gee_lst_timelapse", "gee_lst_timelapse_local",
    )]

    for step in download_steps:
        tool = step.get("tool", "")
        result = step.get("result", {})
        if not result.get("success"):
            continue

        if tool == "gee_download_landsat_sca":
            meta = result.get("metadata", {})
            source = meta.get("gee_source", "GEE")
            count = result.get("image_count", "?")
            cloud = result.get("cloud_pct", "?")
            lines.append(f"**数据源**：{source}")
            lines.append(f"**合成方式**：{count} 景 {result.get('reducer', 'median')} 合成（云量阈值 {cloud}%）")

        elif tool == "gee_download_monthly_lst":
            quality = result.get("quality", "?")
            scenes = result.get("scene_count", "?")
            total = result.get("total_scenes_in_month", "?")
            method = result.get("metadata", {}).get("method", "")
            lines.append(f"**数据源**：Landsat 8/9 Collection 2 Level-2 Tier 1")
            lines.append(f"**质量等级**：{quality}（{total} 景中选用 {scenes} 景，{method}）")

        elif tool in ("gee_download_yearly_lst", "gee_download_multi_year_lst"):
            quality_summary = result.get("quality_summary", {})
            success_count = result.get("success_count", 0)
            quality_str = "、".join(f"{k}级: {v}个月" if tool == "gee_download_yearly_lst" else f"{k}级: {v}年"
                                    for k, v in sorted(quality_summary.items()))
            lines.append(f"**数据源**：Landsat 8/9 Collection 2 Level-2 Tier 1")
            lines.append(f"**完成情况**：{success_count} 个时段成功")
            if quality_str:
                lines.append(f"**质量分布**：{quality_str}")

        elif tool == "gee_lst_timelapse_local":
            years_ok = result.get("years_ok", [])
            years_fail = result.get("years_failed", [])
            gif_size = result.get("gif_size_mb", 0)
            lines.append(f"**数据源**：Landsat 8/9 Collection 2 Level-2 Tier 1")
            lines.append(f"**时间跨度**：{years_ok[0]}-{years_ok[-1]}年（{len(years_ok)} 年成功）" if years_ok else "")
            if years_fail:
                lines.append(f"**跳过年份**：{years_fail}（无可用影像）")
            if gif_size:
                lines.append(f"**GIF 大小**：{gif_size} MB")

        elif tool == "gee_lst_timelapse":
            years = result.get("years", [])
            lines.append(f"**数据源**：Landsat 8/9 Collection 2 Level-2 Tier 1")
            lines.append(f"**时间跨度**：{years[0]}-{years[-1]}年" if years else "")

    # 提取 LST 反演信息
    lst_steps = [s for s in history if s.get("tool") == "run_lst" and s.get("result", {}).get("success")]
    if lst_steps:
        lines.append(f"**温度反演**：SCA 单通道算法（已完成）")

    # 统计输出文件
    output_count = sum(1 for s in history if s.get("tool") in (
        "make_thematic_map", "classify_map", "statistics", "generate_web_map",
        "generate_timeslider_map", "gee_lst_split_panel", "gee_lst_trend_chart",
    ) and s.get("result", {}).get("success"))

    if output_count:
        lines.append(f"**生成结果**：{output_count} 个可视化产物")

    # 过滤空行并拼接
    result_text = "\n".join(line for line in lines if line)
    return result_text


def _execute_gis_task(task_id: int, input_text: str, celery_task_id: str = None) -> Dict[str, Any]:
    """实际执行 GIS 任务的核心逻辑"""
    logger.info(f"开始执行任务 {task_id}: {input_text}")

    import time
    import config as app_config
    task_start_timestamp = time.time()

    # 注意：running 状态由调用方设置（tasks.py 的线程函数或 Celery task）
    if celery_task_id:
        _update_task_status(task_id, "running", celery_task_id=celery_task_id)

    # 使用输出目录（加锁避免竞争）
    output_dir = _setup_task_output_dir()
    logger.info(f"任务 {task_id} 输出目录: {output_dir}")

    with _output_dir_lock:
        original_outputs_dir = app_config.OUTPUTS_DIR
        app_config.OUTPUTS_DIR = output_dir

    try:
        # 初始化 GEE（带锁避免并发初始化）
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

        # 构建结构化摘要（数据源、质量、产品类型）
        metadata_summary = _build_result_summary(result)
        llm_answer = result.get("final_answer", "")
        if metadata_summary:
            final_answer = f"{llm_answer}\n\n---\n**任务详情**\n{metadata_summary}"
        else:
            final_answer = llm_answer

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
        with _output_dir_lock:
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
