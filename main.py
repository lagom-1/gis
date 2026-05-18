"""
GIS 智能体 - 主入口
用法：
  python main.py                          # 交互模式
  python main.py "帮我找XX影像，做温度反演"   # 单命令模式
"""
from __future__ import annotations

import json
import sys


def main() -> None:
    try:
        from tools import ToolRegistry
        from tools.runtime import GISRuntime
        from agent.llm import LLMClient
        from agent.engine import AgentLoop

        runtime = GISRuntime()
        registry = ToolRegistry(runtime)
        llm = LLMClient()
        agent = AgentLoop(llm, registry, runtime)
    except RuntimeError as e:
        print(f"错误：{e}")
        print("请确保已配置 DASHSCOPE_API_KEY 环境变量。")
        sys.exit(1)
    except Exception as e:
        print(f"初始化失败：{e}")
        sys.exit(1)

    # 单命令模式
    if len(sys.argv) > 1:
        user_input = " ".join(sys.argv[1:]).strip()
        try:
            result = agent.run(user_input)
            print(json.dumps(result, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"执行失败：{e}")
            sys.exit(1)
        return

    # 交互模式
    print("=" * 60)
    print("  GIS 遥感智能体已启动")
    print(f"  已加载 {len(registry.manifest())} 个工具")
    print("  支持：文件搜索 → 数据检查 → 温度反演 → 制图 → 样式调整 → 导出")
    print("  输入 quit 退出")
    print("=" * 60)

    while True:
        try:
            user_input = input("\n你> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n已退出。")
            return
        if not user_input:
            continue
        if user_input.lower() in {"quit", "exit", "q"}:
            print("已退出。")
            return

        try:
            result = agent.run(user_input)
        except Exception as e:
            print(f"\n执行失败：{e}")
            continue

        print(f"\nAgent> {result.get('answer', '无结果')}")

        if result.get("history"):
            print(f"\n--- 执行了 {len(result['history'])} 步 ---")
            for h in result["history"]:
                status = "✓" if h["result"].get("success") else "✗"
                print(f"  {status} Step {h['step']}: {h['tool']} — {h.get('reason', '')}")

        state = result.get("state", {})
        if state.get("last_output"):
            print(f"  输出文件: {state['last_output']}")


if __name__ == "__main__":
    main()
