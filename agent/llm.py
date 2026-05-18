"""
LLM 统一适配层
支持 Tongyi (通义千问) / OpenAI 兼容接口
配置失败时抛出异常，由调用方处理
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


def get_llm():
    """获取 LLM 实例，优先 Tongyi，失败抛 RuntimeError"""
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise RuntimeError("未配置 DASHSCOPE_API_KEY，LLM 客户端初始化失败")

    # 尝试 Tongyi
    try:
        from langchain_community.chat_models.tongyi import ChatTongyi
        model = os.getenv("QWEN_MODEL", "qwen-plus")
        temperature = float(os.getenv("QWEN_TEMPERATURE", "0.1"))
        return ChatTongyi(
            model=model,
            api_key=api_key,
            temperature=temperature,
            streaming=False,
        )
    except Exception:
        pass


def _try_parse_json(text: str) -> Optional[Dict[str, Any]]:
    """尝试多种方式解析 JSON，容错 LLM 常见格式问题"""
    if not text or not text.strip():
        return None

    text = text.strip()

    # 1. 直接解析
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # 2. 提取 ```json ... ``` 代码块
    m = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass

    # 3. 提取第一个 { ... } 块（贪心匹配最外层）
    m = re.search(r'\{.*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            pass

    # 4. 修复常见问题：截断的 JSON → 尝试补括号
    for closer in ['}', '}]', '}}', '"]}}', '"}}']:
        try:
            return json.loads(text + closer)
        except json.JSONDecodeError:
            continue

    # 5. 修复常见问题：尾部多余逗号
    fixed = re.sub(r',\s*([}\]])', r'\1', text)
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    return None


class LLMClient:
    """带 JSON 解析和错误恢复的 LLM 客户端"""

    def __init__(self) -> None:
        self._llm = get_llm()
        if self._llm is None:
            raise RuntimeError(
                "LLM 客户端初始化失败：无法连接到 DashScope API。"
                "请检查 DASHSCOPE_API_KEY 环境变量和网络连接。"
            )

    @staticmethod
    def _strip_fences(text: str) -> str:
        text = (text or "").strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        return text.strip()

    def invoke_json(self, system_prompt: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """调用 LLM 并解析 JSON 响应，带指数退避重试和容错"""
        import time
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("user", "{input}"),
        ])
        chain = prompt | self._llm | StrOutputParser()

        input_str = json.dumps(payload, ensure_ascii=False)

        # 最多尝试 3 次，指数退避：1s, 5s
        # LLM 调用设置 120 秒超时，防止永久阻塞
        last_error = None
        for attempt in range(3):
            try:
                raw = chain.invoke({"input": input_str}, config={"timeout": 120})
                text = self._strip_fences(raw)
                result = _try_parse_json(text)
                if result is not None:
                    return result
                last_error = f"JSON 解析失败 (attempt {attempt+1}): {text[:200]}..."
                print(f"[LLM] {last_error}")
            except Exception as e:
                last_error = f"LLM 调用失败 (attempt {attempt+1}): {e}"
                print(f"[LLM] {last_error}")

            # 指数退避：第1次重试等1秒，第2次重试等5秒
            if attempt < 2:
                wait_time = 1 if attempt == 0 else 5
                print(f"[LLM] 等待 {wait_time} 秒后重试...")
                time.sleep(wait_time)

        raise RuntimeError(f"LLM 调用失败（已重试 3 次）: {last_error}")

    def invoke_text(self, system_prompt: str, user_msg: str) -> str:
        """调用 LLM 返回纯文本"""
        from langchain_core.output_parsers import StrOutputParser
        from langchain_core.prompts import ChatPromptTemplate

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("user", "{input}"),
        ])
        chain = prompt | self._llm | StrOutputParser()
        return chain.invoke({"input": user_msg}).strip()

    def health_check(self) -> bool:
        """测试 LLM 连接性，返回 True 表示可用"""
        try:
            from langchain_core.output_parsers import StrOutputParser
            from langchain_core.prompts import ChatPromptTemplate

            prompt = ChatPromptTemplate.from_messages([
                ("system", "你好"),
                ("user", "请回复'OK'"),
            ])
            chain = prompt | self._llm | StrOutputParser()
            result = chain.invoke({"input": ""}).strip()
            return len(result) > 0
        except Exception as e:
            print(f"[LLM] 健康检查失败: {e}")
            return False