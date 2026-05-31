"""测试完整GIS链路API"""
import requests
import json
import time
from dotenv import load_dotenv
load_dotenv()

BASE = "http://localhost:8000"

# 1. 创建会话
print("=" * 60)
print("1. 创建会话")
resp = requests.post(f"{BASE}/api/conversations", json={"title": "朝阳区LST完整链路测试"})
print(f"   状态: {resp.status_code}")
conv = resp.json()
conv_id = conv.get("id")
print(f"   会话ID: {conv_id}")

# 2. 发送测试消息
print("\n2. 发送测试消息（完整链路）")
test_message = "下载北京市朝阳区2020-2023年每年2月的地表温度反演结果并进行制图，然后将这四张专题地图的指北针换个样式，然后修改这四张专题地图的配色，然后生成web地图，然后进行数据统计，然后再生成报告"
print(f"   消息: {test_message[:50]}...")

# 使用流式接口
resp = requests.post(
    f"{BASE}/api/conversations/{conv_id}/messages/stream",
    json={"content": test_message},
    stream=True,
    headers={"Accept": "text/event-stream"}
)

print("\n3. 执行过程:")
print("-" * 60)

step_count = 0
tools_executed = []

for line in resp.iter_lines(decode_unicode=True):
    if not line:
        continue

    if line.startswith("event:"):
        event_type = line[6:].strip()
    elif line.startswith("data:"):
        data_str = line[5:].strip()
        try:
            data = json.loads(data_str)
        except:
            data = {}

        if event_type == "step_start":
            step_count += 1
            print(f"\n--- 步骤 {data.get('step')}/{data.get('max')} ---")

        elif event_type == "tool_start":
            tool = data.get("tool", "")
            reason = data.get("reason", "")
            print(f"  调用工具: {tool}")
            if reason:
                print(f"  原因: {reason[:80]}")

        elif event_type == "tool_result":
            tool = data.get("tool", "")
            result = data.get("result", {})
            success = result.get("success", False)
            msg = result.get("message", "")[:100]
            tools_executed.append(tool)
            status = "✓" if success else "✗"
            print(f"  结果: {status} {msg}")

        elif event_type == "final_answer":
            content = data.get("content", "")
            print(f"\n{'=' * 60}")
            print("最终回复:")
            print(content[:500])

        elif event_type == "error":
            print(f"\n错误: {data.get('message', '')}")

        elif event_type == "done":
            print("\n执行完成")

print(f"\n{'=' * 60}")
print(f"总共执行了 {len(tools_executed)} 个工具调用:")
for i, tool in enumerate(tools_executed, 1):
    print(f"  {i}. {tool}")
