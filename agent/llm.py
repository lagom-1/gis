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
    """获取 LLM 实例，支持 DeepSeek / Tongyi，失败抛 RuntimeError"""
    provider = os.getenv("LLM_PROVIDER", "tongyi").lower()

    # DeepSeek（OpenAI 兼容接口）
    if provider in ("deepseek", "deepseek-v3", "deepseek-v4"):
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            raise RuntimeError("未配置 DEEPSEEK_API_KEY")
        try:
            from langchain_openai import ChatOpenAI
            model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
            temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))
            return ChatOpenAI(
                model=model,
                api_key=api_key,
                base_url="https://api.deepseek.com",
                temperature=temperature,
                request_timeout=None,  # 无超时限制（GEE 操作中 LLM 可能需要长时间等待）
                max_retries=2,
            )
        except Exception as e:
            print(f"[LLM] DeepSeek 初始化失败: {e}")

    # Tongyi（通义千问）
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if api_key:
        try:
            from langchain_community.chat_models.tongyi import ChatTongyi
            model = os.getenv("QWEN_MODEL", "qwen-plus")
            temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))
            return ChatTongyi(
                model=model,
                api_key=api_key,
                temperature=temperature,
                streaming=False,
            )
        except Exception:
            pass

    raise RuntimeError("LLM 客户端初始化失败：无可用的 LLM 提供商")


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

    # 3. 提取第一个平衡的 { ... } 块
    start = text.find('{')
    if start >= 0:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:i+1])
                except json.JSONDecodeError:
                    break

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

        # 最多尝试 2 次 + 1 次驳回重试，指数退避：1s
        last_text = None
        rejection_used = False
        for attempt in range(3):
            try:
                raw = chain.invoke({"input": input_str})
                text = self._strip_fences(raw)
                last_text = text
                result = _try_parse_json(text)
                if result is not None:
                    # ── 【白卷拦截】第一步就 final 且无输出 → 拒绝（仅一次） ──
                    if (not rejection_used
                            and result.get("type") == "final"
                            and payload.get("output_count", 0) == 0
                            and payload.get("last_result") is None):
                        rejection_used = True
                        print(f"[LLM] ⛔ 检测到开局白卷 final！注入系统驳回消息并强制重试...")
                        payload["rejection_notice"] = (
                            "【系统拒绝】警告！这是当前对话的第一轮，你尚未调用任何 GIS 遥感工具"
                            "（如下载、搜索或分类），严禁直接返回 final 宣称任务完成！"
                            "请立刻给出第一步需要调用的具体工具 JSON！"
                        )
                        input_str = json.dumps(payload, ensure_ascii=False)
                        continue
                    return result
                print(f"[LLM] JSON 解析失败 (attempt {attempt+1}): {text[:200]}...")
            except Exception as e:
                print(f"[LLM] LLM 调用异常 (attempt {attempt+1}): {e}")
                import traceback
                traceback.print_exc()

            if attempt < 2:
                time.sleep(1)

        # JSON 解析失败 → 判断是对话还是任务
        if last_text:
            # 如果已有工具调用历史（output_count > 0），说明是任务中断，抛出错误让引擎重试
            if payload.get("output_count", 0) > 0 or payload.get("last_result") is not None:
                msg = f"LLM 在任务执行中返回了非 JSON 响应: {last_text[:150]}"
                print(f"[LLM] {msg}")
                raise RuntimeError(msg)
            # 否则是对话场景，转为 final
            print(f"[LLM] JSON 解析失败（对话场景），转为 final")
            return {"type": "final", "answer": last_text}
        msg = "LLM 未返回任何响应，请检查 API Key 和网络连接。"
        print(f"[LLM] {msg}")
        raise RuntimeError(msg)

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