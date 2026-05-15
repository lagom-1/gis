"""
工具注册中心 - 统一管理所有 GIS 工具的规格与处理器

【修复】添加参数校验、调用日志和超时机制
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List

# 工具调用日志
logger = logging.getLogger("opengis.tool_registry")

# 工具执行超时（秒），GEE 操作可能较慢，给 600 秒
TOOL_CALL_TIMEOUT = 600


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
        """
        调用指定工具，带参数校验、日志记录和超时保护。

        参数校验：检查工具是否存在，参数类型基本合法。
        日志记录：记录每次工具调用的名称、参数和耗时。
        超时机制：防止 GEE 等外部服务阻塞过久。
        """
        # ── 工具存在性检查 ──
        if name not in self.handlers:
            logger.warning("工具不存在: %s", name)
            return {"success": False, "message": f"未找到工具: {name}"}

        spec = self.specs.get(name)

        # ── 参数基本校验 ──
        args = args or {}
        if spec and spec.input_schema:
            # 检查必填参数（schema 中定义了但 args 中缺失且无默认值说明的参数）
            # 由于 schema 是描述性 dict，这里只做类型安全检查
            for key, value in args.items():
                if value is None:
                    continue
                # 确保参数值是可序列化的基本类型
                if not isinstance(value, (str, int, float, bool, list, dict, type(None))):
                    args[key] = str(value)
                    logger.debug("参数 %s 类型已转换为 str: %s", key, type(value).__name__)

        # ── 记录调用开始 ──
        start_time = time.time()
        logger.info(
            "工具调用开始: %s | 参数: %s",
            name,
            {k: v for k, v in args.items() if k != "password"},  # 避免日志泄露敏感信息
        )

        # ── 带超时执行 ──
        try:
            # 使用线程池执行，设置超时
            with ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(self.handlers[name], args)
                result = future.result(timeout=TOOL_CALL_TIMEOUT)
        except FutureTimeout:
            elapsed = time.time() - start_time
            logger.error("工具调用超时: %s (%.1f秒)", name, elapsed)
            return {
                "success": False,
                "message": f"工具 {name} 执行超时（{TOOL_CALL_TIMEOUT}秒）。如果是 GEE 操作，请检查网络连接或稍后重试。",
            }
        except Exception as exc:
            elapsed = time.time() - start_time
            logger.error("工具调用异常: %s | 耗时: %.1f秒 | 错误: %s", name, elapsed, exc)
            raise  # 重新抛出，让调用方处理

        # ── 记录调用结果 ──
        elapsed = time.time() - start_time
        success = result.get("success", True) if isinstance(result, dict) else False
        if success:
            logger.info("工具调用成功: %s | 耗时: %.1f秒", name, elapsed)
        else:
            msg = result.get("message", "") if isinstance(result, dict) else str(result)
            logger.warning("工具调用失败: %s | 耗时: %.1f秒 | 原因: %s", name, elapsed, msg[:200])

        return result
