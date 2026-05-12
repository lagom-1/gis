from __future__ import annotations

import os
import time
from typing import Optional

import ee

import config


def init_gee(project_id: Optional[str] = None, force_auth: bool = False, max_retries: int = 3) -> dict:
    """
    初始化 Google Earth Engine。
    优先使用已有本地凭证；失败时尝试认证。支持自动重试（应对网络波动）。
    """
    project = project_id or config.GEE_PROJECT or os.getenv("EARTHENGINE_PROJECT") or os.getenv("EE_PROJECT")

    last_error = None
    for attempt in range(max_retries):
        try:
            if force_auth and attempt == 0:
                ee.Authenticate()
            ee.Initialize(project=project)
            return {
                "success": True,
                "message": f"GEE 初始化成功（project={project or 'default'}）",
                "project_id": project,
            }
        except Exception as exc:
            last_error = exc
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))  # 递增等待: 2s, 4s

    # 所有重试失败，尝试认证后再初始化
    try:
        ee.Authenticate()
        ee.Initialize(project=project)
        return {
            "success": True,
            "message": f"GEE 认证并初始化成功（project={project or 'default'}）",
            "project_id": project,
        }
    except Exception as second_exc:
        return {
            "success": False,
            "message": f"GEE 初始化失败（重试{max_retries}次后）: {second_exc}",
            "project_id": project,
            "traceback_hint": str(last_error),
        }