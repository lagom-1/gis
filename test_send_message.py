"""
发送测试任务给智能体
"""
import json
from api.database import SessionLocal
from api.services.conversation_service import load_conversation_state, get_conversation_messages
from api.models import Conversation
from tools import ToolRegistry
from tools.runtime import GISRuntime
from agent.llm import LLMClient
from agent.engine import AgentLoop

conv_id = 2
db = SessionLocal()

# 加载会话状态
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

# 创建运行时和智能体
runtime = GISRuntime(conversation_id=conv_id)
if saved_state:
    runtime.from_dict(saved_state)
registry = ToolRegistry(runtime)
llm = LLMClient()
agent = AgentLoop(llm, registry, runtime)

# 测试任务
user_input = """下载北京市朝阳区2020-2023年每年2月的地表温度反演结果并进行制图，
然后将这四张专题地图的指北针换个样式，然后修改这四张专题地图的配色，
然后生成web地图，然后进行数据统计，然后再生成报告。"""

print(f"开始执行任务: {user_input[:50]}...")
print(f"会话ID: {conv_id}")
print(f"历史消息数: {len(history_messages)}")

# 执行智能体
result = agent.run(
    user_input=user_input,
    conversation_history=history_messages,
)

print("\n=== 执行结果 ===")
print(f"成功: {result.get('success')}")
print(f"类型: {result.get('type')}")
print(f"答案: {result.get('answer', '')[:200]}...")
print(f"历史记录数: {len(result.get('history', []))}")

# 保存结果
from api.services.conversation_service import add_message, save_conversation_state
from api.models import ConversationStatus

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

print("\n任务执行完成！")
print(f"输出文件数: {len(runtime.output_files)}")
for f in runtime.output_files:
    print(f"  - {f.get('name')}")
