"""
工具注册中心 - 统一管理所有 GIS 工具的规格与处理器
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, str] = field(default_factory=dict)
    category: str = "general"  # 工具分类：data / analysis / visualization / export / system


class ToolRegistry:
    def __init__(self) -> None:
        self.specs: Dict[str, ToolSpec] = {}
        self.handlers: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {}

    def register(self, spec: ToolSpec, handler: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
        self.specs[spec.name] = spec
        self.handlers[spec.name] = handler

    def manifest(self) -> List[Dict[str, Any]]:
        return [
            {"name": s.name, "description": s.description,
             "input_schema": s.input_schema, "category": s.category}
            for s in self.specs.values()
        ]

    def call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        if name not in self.handlers:
            return {"success": False, "message": f"未找到工具: {name}"}
        return self.handlers[name](args or {})