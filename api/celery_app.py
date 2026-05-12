"""
Celery 应用配置
- 使用 Redis 作为消息代理和结果后端
- 配置任务序列化、超时和并发限制
"""

from __future__ import annotations

from celery import Celery

import config

# ── 创建 Celery 实例 ──────────────────────────────────────
celery_app = Celery(
    "opengis_worker",
    broker=config.REDIS_URL,
    backend=config.CELERY_RESULT_BACKEND,
)

# ── Celery 配置 ───────────────────────────────────────────
celery_app.conf.update(
    # 序列化
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # 时区
    timezone="Asia/Shanghai",
    enable_utc=True,

    # 任务结果过期时间（24 小时）
    result_expires=86400,

    # Worker 配置：每个 worker 子进程最多处理 N 个任务后重启（防内存泄漏）
    worker_max_tasks_per_child=config.CELERY_MAX_TASKS_PER_CHILD,

    # 每次只预取 1 个任务，实现公平调度
    worker_prefetch_multiplier=1,

    # 任务超时（30 分钟，GIS 任务可能耗时较长）
    task_soft_time_limit=1800,
    task_time_limit=2400,

    # 任务拒绝时重新入队
    task_reject_on_worker_lost=True,

    # 任务路由（可选，后续可扩展为多队列）
    task_routes={
        "api.tasks_worker.run_gis_task": {"queue": "gis"},
    },

    # 默认队列
    task_default_queue="default",
)

# ── 自动发现任务模块 ──────────────────────────────────────
celery_app.autodiscover_tasks(["api"])
