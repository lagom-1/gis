"""
工具系统入口 - ToolRegistry + 自动发现

ToolRegistry 会在初始化时自动扫描 tools 目录下所有子模块，
将 @tool 装饰器注册的工具类收集到注册表中。

使用:
    from tools import ToolRegistry
    from tools.runtime import GISRuntime

    runtime = GISRuntime()
    registry = ToolRegistry(runtime)
    result = registry.call("search_local_files", {"query": "北京"})
"""
from __future__ import annotations

import importlib
import os
import pkgutil
from typing import Any, Dict, List, Optional

from tools.base import BaseTool, ToolSpec, get_registered_tools
from tools.runtime import GISRuntime


class ToolRegistry:
    """工具注册表，管理所有可用工具的定义和实例"""

    def __init__(self, runtime: Optional[GISRuntime] = None):
        self.runtime = runtime or GISRuntime()
        self._tools: Dict[str, ToolSpec] = {}
        self._instances: Dict[str, BaseTool] = {}
        self._auto_discover()

    def _auto_discover(self):
        """自动扫描 tools 包下所有子模块，导入以触发 @tool 装饰器注册"""
        import tools as pkg
        pkg_path = os.path.dirname(__file__)

        for _, name, is_pkg in pkgutil.iter_modules([pkg_path]):
            if name.startswith('_') or name in ('base', 'runtime'):
                continue
            try:
                importlib.import_module(f'tools.{name}')
            except ImportError as e:
                # 某些模块可能依赖 GEE 等可选依赖，跳过导入错误
                import sys
                print(f"[tools] 跳过模块 {name}（导入失败: {e}）", file=sys.stderr)

        # 收集所有 @tool 装饰的类
        for cls, spec in get_registered_tools():
            self._tools[spec.name] = spec

    def register(self, spec: ToolSpec, handler_cls: type):
        """手动注册工具（用于不需要自动发现的场景）"""
        self._tools[spec.name] = spec
        spec.handler = handler_cls

    def manifest(self) -> List[Dict[str, Any]]:
        """返回所有工具的可读清单，用于 LLM prompt"""
        return [
            {
                "name": s.name,
                "description": s.description,
                "parameters": s.input_schema,
                "category": s.category,
            }
            for s in self._tools.values()
        ]

    def call(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """调用指定工具

        Args:
            name: 工具名称
            args: 参数字典

        Returns:
            {"success": bool, "message": str, ...}
        """
        spec = self._tools.get(name)
        if not spec:
            return {"success": False, "message": f"未知工具: {name}"}

        # 懒初始化：首次调用时实例化
        if name not in self._instances:
            if not spec.handler:
                return {"success": False, "message": f"工具 {name} 无处理器"}
            self._instances[name] = spec.handler(self.runtime)

        instance = self._instances[name]
        try:
            return instance.execute(**args)
        except TypeError as e:
            return {"success": False, "message": f"参数错误: {e}"}
        except Exception as e:
            import traceback
            return {
                "success": False,
                "message": str(e),
                "traceback": traceback.format_exc(limit=4),
            }
