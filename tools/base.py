"""
工具基类和装饰器

每个工具继承 BaseTool，用 @tool 装饰器标记，
在导入时自动注册到全局注册表，由 ToolRegistry 发现。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple, Type


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


def ensure_gee_and_roi(runtime) -> Tuple[Any, Optional[Dict[str, Any]]]:
    """GEE 工具公共前置检查：初始化 GEE + 解析研究区。

    返回 (ee_geom, None) 成功，或 (None, error_dict) 失败。
    所有 GEE 工具应统一使用此函数，避免重复逻辑。
    """
    from gis.gee.client import init_gee
    init_result = init_gee()
    if not init_result.get("success"):
        return None, {
            "success": False,
            "message": f"GEE 未认证：{init_result.get('message', '')}。请先执行 gee_init 完成授权。",
            "requires": "gee_init",
        }
    roi = runtime.last_region_geojson
    if roi is None:
        return None, {
            "success": False,
            "message": "缺少研究区。请先用 resolve_admin_region 解析行政区边界。",
        }
    try:
        from gis.gee_tools import _normalize_region
        return _normalize_region(region=roi), None
    except Exception as e:
        return None, {"success": False, "message": f"研究区转换失败: {e}"}
