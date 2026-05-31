"""
完整测试链路：北京市朝阳区2020-2023年每年2月LST
1. 下载4年数据
2. 修改指北针样式
3. 修改配色
4. 生成web地图
5. 数据统计
6. 生成报告
"""
import sys
sys.stdout.reconfigure(line_buffering=True)

from api.database import SessionLocal
from api.services.conversation_service import load_conversation_state, get_conversation_messages, add_message, save_conversation_state
from api.models import Conversation, ConversationStatus
from tools import ToolRegistry
from tools.runtime import GISRuntime
from agent.llm import LLMClient
from agent.engine import AgentLoop

conv_id = 2
db = SessionLocal()

print("=" * 60)
print("完整测试链路：北京市朝阳区2020-2023年每年2月LST")
print("=" * 60)

# 加载会话状态
print("\n[1/7] 加载会话状态...")
saved_state = load_conversation_state(db, conv_id)
history_messages = [
    {
        "role": m.role,
        "content": m.content,
        "tool_name": m.tool_name,
        "tool_result": m.tool_result,
    }
    for m in get_conversation_messages(db, conv_id, limit=100)
]
print(f"  历史消息数: {len(history_messages)}")

# 创建运行时和智能体
print("\n[2/7] 创建运行时和智能体...")
runtime = GISRuntime(conversation_id=conv_id)
if saved_state:
    runtime.from_dict(saved_state)
    print(f"  恢复状态: current_dataset={runtime.current_dataset}")
registry = ToolRegistry(runtime)
llm = LLMClient()
agent = AgentLoop(llm, registry, runtime)

# 完整测试任务
user_input = """请帮我完成以下完整任务：

1. 下载北京市朝阳区2020-2023年每年2月的地表温度反演结果（共4年数据）
2. 对生成的4张专题地图，将指北针样式改为"circle"圆形样式
3. 将4张专题地图的配色方案改为"RdYlBu_r"（红蓝反转配色）
4. 为这4年数据生成一个交互式web地图
5. 对这4年的温度数据进行统计分析
6. 生成一份完整的实验报告"""

print(f"\n[3/7] 开始执行完整任务...")
print(f"任务内容:")
print(f"  - 下载2020-2023年每年2月LST")
print(f"  - 修改指北针样式为circle")
print(f"  - 修改配色为RdYlBu_r")
print(f"  - 生成web地图")
print(f"  - 数据统计")
print(f"  - 生成报告")

def on_event(event_type, data):
    if event_type == "step_start":
        print(f"\n--- 步骤 {data.get('step')}/{data.get('max')} ---")
    elif event_type == "tool_start":
        tool = data.get('tool')
        args = data.get('args', {})
        print(f"  调用工具: {tool}")
        if args:
            print(f"    参数: {str(args)[:100]}")
    elif event_type == "tool_result":
        result = data.get("result", {})
        success = result.get('success')
        msg = str(result.get('message', ''))[:100]
        print(f"  结果: success={success}, {msg}")
    elif event_type == "final_answer":
        print(f"\n[4/7] 最终答案:")
        print(f"  {data.get('content', '')[:300]}")

result = agent.run(
    user_input=user_input,
    conversation_history=history_messages,
    on_event=on_event,
)

print("\n" + "=" * 60)
print("[5/7] 执行结果汇总:")
print(f"  成功: {result.get('success')}")
print(f"  类型: {result.get('type')}")
print(f"  答案: {str(result.get('answer', ''))[:500]}")

print("\n[6/7] 保存结果...")
# 保存工具调用历史
for h in result.get("history", []):
    tool = h.get("tool", "")
    if tool == "__system_hint__":
        continue
    tool_result = h.get("result", {})
    add_message(db, conv_id, role="tool_call", content=f"调用工具: {tool}",
                tool_name=tool, tool_args=h.get("args", {}), step_number=h.get("step", 0))
    add_message(db, conv_id, role="tool_result", content=tool_result.get("message", ""),
                tool_name=tool, tool_result=tool_result, step_number=h.get("step", 0))

# 保存最终回复
add_message(db, conv_id, role="assistant", content=result.get("answer", "任务完成。"))

# 保存运行时状态
save_conversation_state(db, conv_id, runtime.to_dict())

# 更新会话状态
conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
if conv:
    conv.status = ConversationStatus.ACTIVE
    db.commit()

print("\n[7/7] 输出文件列表:")
print(f"  总文件数: {len(runtime.output_files)}")
for i, f in enumerate(runtime.output_files, 1):
    print(f"  {i}. {f.get('name')}")

print("\n" + "=" * 60)
print("测试完成！")
print("=" * 60)
