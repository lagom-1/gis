from dotenv import load_dotenv
from langchain_community.chat_models.tongyi import ChatTongyi
from langchain_core.messages import HumanMessage

load_dotenv()

llm = ChatTongyi(
    model="qwen-plus",
    streaming=False
)

resp = llm.invoke([
    HumanMessage(content="你好，请用一句话介绍你自己。")
])

print(resp.content)