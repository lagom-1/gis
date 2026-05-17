"""
GEE 客户端初始化 + 认证
"""

from __future__ import annotations

import os
import time
from typing import Dict, Any, Optional

import ee


def init_gee(project_id: Optional[str] = None, force_auth: bool = False,
             max_retries: int = 3) -> Dict[str, Any]:
    """初始化 Earth Engine，带重试和自动认证"""
    project = project_id or os.getenv("EE_PROJECT") or os.getenv("EARTHENGINE_PROJECT") or ""

    for attempt in range(max_retries):
        try:
            if force_auth:
                ee.Authenticate()
            ee.Initialize(project=project)
            return {"success": True, "message": "GEE 初始化成功", "project": project}
        except Exception as e:
            err = str(e)
            if "credentials" in err.lower() or "auth" in err.lower() or "token" in err.lower():
                try:
                    ee.Authenticate()
                    ee.Initialize(project=project)
                    return {"success": True, "message": "GEE 认证并初始化成功", "project": project}
                except Exception as auth_err:
                    if attempt < max_retries - 1:
                        time.sleep(2 ** attempt)
                        continue
                    return {"success": False, "message": f"GEE 认证失败: {auth_err}"}
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            return {"success": False, "message": f"GEE 初始化失败: {e}"}

    return {"success": False, "message": "GEE 初始化失败（已达最大重试次数）"}
