"""
FastAPI 应用入口

启动方式：
    uvicorn api.app:app --reload --host 0.0.0.0 --port 8000

API 文档：
    http://localhost:8000/docs      (Swagger UI)
    http://localhost:8000/redoc     (ReDoc)
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import config
from api.database import create_tables

logger = logging.getLogger(__name__)


# ── 应用生命周期 ──────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """应用启动和关闭时执行的逻辑"""
    # 启动时：创建数据库表
    logger.info("正在创建数据库表...")
    create_tables()
    logger.info("数据库表创建完成")

    yield

    # 关闭时：清理资源（如有需要）
    logger.info("应用关闭")


# ── 创建 FastAPI 实例 ─────────────────────────────────────

app = FastAPI(
    title="OpenGIS API",
    description=(
        "AI 驱动的 GIS 遥感分析平台 API。\n\n"
        "支持自然语言提交 GIS 分析任务，后台异步执行，结果付费下载。"
    ),
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# ── CORS 中间件 ───────────────────────────────────────────

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 全局异常处理 ──────────────────────────────────────────

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """捕获所有未处理的异常，返回统一错误格式"""
    logger.error(f"未处理的异常: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "服务器内部错误",
            "detail": str(exc) if config.SECRET_KEY == "opengis-dev-secret-key-change-in-production" else "请联系管理员",
        },
    )


# ── 注册路由 ──────────────────────────────────────────────

from api.routers import auth, downloads, payments, tasks

app.include_router(auth.router)
app.include_router(tasks.router)
app.include_router(payments.router)
app.include_router(downloads.router)


# ── 静态文件服务（开发模式）──────────────────────────────────────

from fastapi.staticfiles import StaticFiles
from pathlib import Path

# 挂载输出目录为静态文件
outputs_dir = Path(__file__).parent.parent / "workspace" / "outputs"
if outputs_dir.exists():
    app.mount("/outputs", StaticFiles(directory=str(outputs_dir)), name="outputs")


# ── 健康检查 ──────────────────────────────────────────────

@app.get("/health", tags=["系统"], summary="健康检查")
async def health_check():
    """健康检查端点，用于负载均衡和监控。"""
    return {"status": "ok", "service": "opengis-api", "version": "0.1.0"}


@app.get("/", tags=["系统"], summary="根路径")
async def root():
    """API 根路径，返回基本信息。"""
    return {
        "service": "OpenGIS API",
        "version": "0.1.0",
        "docs": "/docs",
        "health": "/health",
    }
