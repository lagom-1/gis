"""
数据库配置 - SQLAlchemy 引擎、会话管理、依赖注入
"""

from __future__ import annotations

import logging
from typing import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

import config

logger = logging.getLogger(__name__)


# ── SQLAlchemy 基类 ──────────────────────────────────────
class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""
    pass


# ── 引擎和会话工厂 ────────────────────────────────────────
# SQLite 需要 check_same_thread=False 以支持多线程
connect_args = {}
if config.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    config.DATABASE_URL,
    connect_args=connect_args,
    echo=False,
)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# ── 创建所有表 + 自动迁移 ──────────────────────────────────
def create_tables() -> None:
    """在应用启动时创建所有表，并自动添加缺失的列"""
    from api import models  # noqa: F401
    Base.metadata.create_all(bind=engine)
    _auto_migrate_columns()


def _auto_migrate_columns() -> None:
    """自动为已有表添加新列（SQLite ALTER TABLE ADD COLUMN）"""
    conn = engine.connect()
    try:
        db_inspect = inspect(engine)
        existing_tables = db_inspect.get_table_names()

        if "tasks" in existing_tables:
            existing_cols = {col["name"] for col in db_inspect.get_columns("tasks")}
            # 需要添加的列: (列名, SQL 类型)
            missing_cols = [
                ("final_answer", "TEXT"),
                ("current_step", "INTEGER DEFAULT 0"),
                ("step_description", "TEXT"),
                ("conversation_id", "INTEGER REFERENCES conversations(id)"),
                ("turn_index", "INTEGER DEFAULT 0"),
            ]
            for col_name, col_type in missing_cols:
                if col_name not in existing_cols:
                    conn.execute(text(f"ALTER TABLE tasks ADD COLUMN {col_name} {col_type}"))
                    logger.info(f"自动迁移: tasks 表添加列 {col_name}")
            conn.commit()
    except Exception as exc:
        logger.warning(f"自动迁移跳过: {exc}")
    finally:
        conn.close()


# ── FastAPI 依赖注入 ──────────────────────────────────────
def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖项：为每个请求提供数据库会话"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
