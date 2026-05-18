"""
工具基类和装饰器

每个工具继承 BaseTool，用 @tool 装饰器标记，
在导入时自动注册到全局注册表，由 ToolRegistry 发现。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type


@dataclass
class ToolSpec:
    """工具规格定义"""
    name: str
    description: str
    input_schema: Dict[str, str]
    category: str = "general"
    handler: Optional[Type] = None


# 全局注册表，由 @tool 装饰器在模块导入时填充
_registry: List[tuple] = []


def tool(
    name: str,
    description: str,
    parameters: Dict[str, str],
    category: str = "general",
):
    """装饰器：将类注册为工具

    用法:
        @tool(name="my_tool", description="...", parameters={"arg1": "说明"}, category="analysis")
        class MyTool(BaseTool):
            def execute(self, arg1=None) -> dict:
                ...
    """
    spec = ToolSpec(
        name=name,
        description=description,
        input_schema=parameters,
        category=category,
    )

    def decorator(cls):
        spec.handler = cls
        _registry.append((cls, spec))
        return cls

    return decorator


def get_registered_tools() -> List[tuple]:
    """获取所有 @tool 装饰器注册的工具"""
    return list(_registry)


class BaseTool:
    """工具基类，提供 runtime 访问。

    子类必须实现 execute(**kwargs) -> dict 方法。
    """

    def __init__(self, runtime):
        self.runtime = runtime

    def execute(self, **kwargs) -> Dict[str, Any]:
        raise NotImplementedError("子类必须实现 execute 方法")
