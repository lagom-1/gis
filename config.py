"""
配置模块 - 路径、默认样式、默认偏好
"""

from __future__ import annotations

import os
from pathlib import Path

# 加载 .env 文件
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
except ImportError:
    pass

# ── 路径 ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
WORKSPACE_DIR = PROJECT_ROOT / "workspace"
RUNS_DIR = WORKSPACE_DIR / "runs"
OUTPUTS_DIR = WORKSPACE_DIR / "outputs"
MEMORY_PATH = WORKSPACE_DIR / "memory.json"
PREFERENCES_PATH = WORKSPACE_DIR / "preferences.json"

# 自动创建目录
for _d in [WORKSPACE_DIR, RUNS_DIR, OUTPUTS_DIR]:
    _d.mkdir(parents=True, exist_ok=True)


def normalize_output_path(absolute_path: str) -> str:
    """将绝对路径标准化为相对于 OUTPUTS_DIR 的 /outputs/ URL 路径"""
    try:
        p = Path(absolute_path).resolve()
        base = OUTPUTS_DIR.resolve()
        rel = p.relative_to(base)
        return "/outputs/" + str(rel).replace("\\", "/")
    except (ValueError, OSError):
        return absolute_path.replace("\\", "/")


# ── 常见搜索根目录 ──────────────────────────────────────
def default_search_roots():
    """返回用户电脑上的常见文件搜索路径"""
    import string
    home = Path.home()
    roots = [
        Path.cwd(),
        home,
        home / "Desktop",
        home / "Documents",
        home / "Downloads",
    ]
    # Windows：扫描所有可用盘符
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            drive = Path(f"{letter}:\\")
            if drive.exists():
                roots.append(drive)
    else:
        roots.extend([Path("/data"), Path("/tmp"), Path("/")])

    seen, out = set(), []
    for p in roots:
        if p.exists():
            s = str(p.resolve())
            if s not in seen:
                seen.add(s)
                out.append(s)
    return out


# ── 栅格文件后缀 ──────────────────────────────────────
RASTER_EXTS = {".tif", ".tiff", ".img", ".jp2", ".vrt", ".asc", ".hdf", ".nc"}


# ── 默认地图样式 ──────────────────────────────────────
DEFAULT_MAP_STYLE = {
    "colormap": "viridis",
    "title": "专题图",
    "show_legend": True,
    "show_scalebar": True,
    "show_north": True,
    "dpi": 300,
    "legend_position": "right",
    "scalebar_position": "lower left",
    "north_position": "upper right",
    "alpha": 1.0,
    "bg_color": "#EFEFEF",
    "title_fontsize": 18,
    "legend_tick_fontsize": 10,
    "legend_label_fontsize": 12,
    "legend_shrink": 0.88,
    "scalebar_fontsize": 10,
    "scalebar_length_ratio": 0.16,
    "north_fontsize": 13,
    "title_color": "#1A1A1A",
    "frame": True,
    "grid": False,
    "map_margin": 0.035,
    "map_frame_scale": 0.94,
}


# ── GEE / Google Drive 配置 ───────────────────────────
GEE_PROJECT = os.getenv("EARTHENGINE_PROJECT") or os.getenv("EE_PROJECT") or ""
GEE_DRIVE_FOLDER = os.getenv("GEE_DRIVE_FOLDER", "GEE_Exports")

GDRIVE_SYNC_DIR = Path(
    os.getenv("GDRIVE_SYNC_DIR", str(PROJECT_ROOT / "workspace" / "gee_exports"))
)

LOCAL_DRIVE_PATH = str(GDRIVE_SYNC_DIR)


def gdrive_is_configured() -> bool:
    return GDRIVE_SYNC_DIR.exists()


def get_gdrive_sync_dir() -> Path:
    return GDRIVE_SYNC_DIR


# ── 数据库配置 ────────────────────────────────────────
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"sqlite:///{(WORKSPACE_DIR / 'opengis.db').as_posix()}",
)

# ── Redis 配置 ────────────────────────────────────────
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# ── JWT 配置 ──────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY", "")
if not SECRET_KEY:
    import secrets
    SECRET_KEY = secrets.token_hex(32)
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = int(os.getenv("JWT_EXPIRE_MINUTES", "1440"))  # 默认 24 小时

# ── CORS 配置 ─────────────────────────────────────────
CORS_ORIGINS = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173").split(",")]

# ── 支付配置 ────────────────────────────────────────────
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# Stripe Price ID（生产环境配置实际的 Price ID）
STRIPE_PRICE_BASIC = os.getenv("STRIPE_PRICE_BASIC", "")
STRIPE_PRICE_STANDARD = os.getenv("STRIPE_PRICE_STANDARD", "")
STRIPE_PRICE_PREMIUM = os.getenv("STRIPE_PRICE_PREMIUM", "")

# 前端地址（用于支付成功/取消回调）
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# ── Celery 配置 ───────────────────────────────────────
CELERY_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
CELERY_MAX_TASKS_PER_CHILD = int(os.getenv("CELERY_MAX_TASKS_PER_CHILD", "10"))

# ── 默认用户偏好 ──────────────────────────────────────
DEFAULT_PREFERENCES = {
    "export_format": "png",
    "colormap": "viridis",
    "classification_method": "natural_breaks",
    "n_classes": 5,
    "legend_position": "right",
    "language": "zh",
    "dpi": 300,
}
