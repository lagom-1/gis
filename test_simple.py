"""
简单测试智能体是否正常工作
"""
import sys
sys.stdout.reconfigure(line_buffering=True)  # 确保输出实时刷新

from api.database import SessionLocal
from api.services.conversation_service import load_conversation_state, get_conversation_messages, add_message, save_conversation_state
from api.models import Conversation, ConversationStatus
from tools import ToolRegistry
from tools.runtime import GISRuntime
from agent.llm import LLMClient
from agent.engine import AgentLoop

conv_id = 2
db = SessionLocal()

print(f"[1/5] 加载会话状态 (conv_id={conv_id})...")
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

print("[2/5] 创建运行时和智能体...")
runtime = GISRuntime(conversation_id=conv_id)
if saved_state:
    runtime.from_dict(saved_state)
    print(f"  恢复状态: current_dataset={runtime.current_dataset}, last_region={runtime.last_region_name}")
registry = ToolRegistry(runtime)
llm = LLMClient()
agent = AgentLoop(llm, registry, runtime)

# 简化测试任务 - 只测试解析行政区和下载1个月数据
user_input = "解析北京市朝阳区的行政区边界，然后下载2020年2月的地表温度数据并制图"

print(f"[3/5] 开始执行任务...")
print(f"  任务: {user_input}")

def on_event(event_type, data):
    if event_type == "step_start":
        print(f"  步骤 {data.get('step')}/{data.get('max')}")
    elif event_type == "tool_start":
        print(f"  调用工具: {data.get('tool')}")
    elif event_type == "tool_result":
        result = data.get("result", {})
        print(f"  工具结果: success={result.get('success')}, message={str(result.get('message', ''))[:80]}")
    elif event_type == "final_answer":
        print(f"  最终答案: {str(data.get('content', ''))[:100]}")

result = agent.run(
    user_input=user_input,
    conversation_history=history_messages,
    on_event=on_event,
)

print("\n[4/5] 执行结果:")
print(f"  成功: {result.get('success')}")
print(f"  类型: {result.get('type')}")
print(f"  答案: {str(result.get('answer', ''))[:200]}")

print("\n[5/5] 保存结果...")
# 保存工具调用历史
for h in result.get("history", []):
    tool = h.get("tool", "")
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

print(f"\n输出文件数: {len(runtime.output_files)}")
for f in runtime.output_files:
    print(f"  - {f.get('name')}")

print("\n测试完成！")
