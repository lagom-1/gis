"""
安全守卫 - 仅防止 GEE 配额耗尽（下载次数上限）
不限制任何工具的调用次数，依赖 LLM 决策 + max_steps 兜底
"""
from __future__ import annotations

from typing import Any, Dict, List


class SafetyGuard:
    """Agent 安全守卫：下载次数上限检查"""

    def __init__(self, max_download_calls=10, **_kwargs):
        self.max_download_calls = max_download_calls

    _DOWNLOAD_TOOLS = {
        "gee_download_landsat_sca", "gee_download_monthly_lst",
        "gee_download_yearly_lst", "gee_download_multi_year_lst",
        "gee_compute_lst", "gee_download_lst",
    }

    def check(self, history: List[Dict[str, Any]]) -> str:
        """安全检查：仅保留下载次数上限，防止 GEE 配额耗尽"""
        # 统计下载工具调用次数
        download_count = sum(
            1 for h in history
            if h.get("tool") in self._DOWNLOAD_TOOLS
            and h.get("result", {}).get("success")
        )
        if download_count >= self.max_download_calls:
            return f"【系统警告】下载工具已调用 {download_count} 次，接近 GEE 配额上限。请停止下载，使用已有数据进行分析。"

        return ""

    def should_auto_map(self, history: List[Dict[str, Any]]) -> bool:
        """不再自动出图，让 LLM 自行判断"""
        return False


# ── 意图检测工具函数 ──

_WEB_MAP_KEYWORDS = [
    "web地图", "web 地图", "web map", "webmap",
    "交互式地图", "交互地图", "在线地图", "可缩放地图",
    "能看坐标", "leaflet", "openstreetmap",
]

def has_web_map_intent(text: str) -> bool:
    t = text.lower()
    return any(kw.lower() in t for kw in _WEB_MAP_KEYWORDS)
