"""
运行时状态管理 - 当前数据集、上次输出、地图样式
从 agent/tool.py 迁移，保持原有逻辑不变
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List

from config import DEFAULT_MAP_STYLE, OUTPUTS_DIR


class GISRuntime:
    """运行时状态：当前数据集、上次输出、地图样式、最近解析的行政区"""

    def __init__(self, conversation_id: int = 0) -> None:
        self.conversation_id = conversation_id
        self.current_dataset: str | None = None
        self.source_dataset: str | None = None
        self.last_output: str | None = None
        self.last_tif_output: str | None = None
        self.last_region_geojson: Dict[str, Any] | None = None
        self.last_region_name: str | None = None
        self.map_style: Dict[str, Any] = dict(DEFAULT_MAP_STYLE)
        self.preferences: Dict[str, Any] = {}
        self.output_files: List[Dict[str, Any]] = []

    @property
    def session_dir(self) -> Path:
        """当前会话的沙箱子目录：outputs/session_{id}/"""
        d = Path(OUTPUTS_DIR) / f"session_{self.conversation_id}"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def reset_for_new_task(self) -> None:
        """新任务开始时重置跨任务易污染的状态"""
        self.current_dataset = None
        self.source_dataset = None
        self.last_region_geojson = None
        self.last_region_name = None

    def current_tif(self) -> str | None:
        """获取当前可用的 TIF 文件路径"""
        if self.current_dataset and os.path.exists(self.current_dataset):
            return self.current_dataset
        if self.last_tif_output and os.path.exists(self.last_tif_output):
            return self.last_tif_output
        return None

    def register_output(self, file_path: str, file_type: str = "image") -> None:
        """注册一个输出文件，累积到 output_files 列表（去重）"""
        name = os.path.basename(file_path)
        existing = [f for f in self.output_files if f.get('path') == file_path or f.get('name') == name]
        if not existing:
            self.output_files.append({
                "name": name,
                "path": file_path,
                "type": file_type,
                "modified": str(os.path.getmtime(file_path)) if os.path.exists(file_path) else "",
            })

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 dict，用于持久化到 conversation_states 表"""
        region = self.last_region_geojson
        if region is not None and not isinstance(region, dict):
            region = None  # ee.Geometry 不可序列化
        return {
            "conversation_id": self.conversation_id,
            "current_dataset": self.current_dataset,
            "source_dataset": self.source_dataset,
            "last_output": self.last_output,
            "last_tif_output": self.last_tif_output,
            "last_region_geojson": region,
            "last_region_name": self.last_region_name,
            "map_style": dict(self.map_style),
            "preferences": dict(self.preferences),
            "output_files": list(self.output_files),
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """从 dict 恢复状态"""
        if not data:
            return
        self.conversation_id = data.get("conversation_id", self.conversation_id)
        self.current_dataset = data.get("current_dataset") or self.current_dataset
        self.source_dataset = data.get("source_dataset") or self.source_dataset
        self.last_output = data.get("last_output") or self.last_output
        self.last_tif_output = data.get("last_tif_output") or self.last_tif_output
        self.last_region_geojson = data.get("last_region_geojson") or self.last_region_geojson
        self.last_region_name = data.get("last_region_name") or self.last_region_name
        if data.get("map_style"):
            self.map_style.update(data["map_style"])
        if data.get("preferences"):
            self.preferences.update(data["preferences"])
        if data.get("output_files"):
            self.output_files = list(data["output_files"])
