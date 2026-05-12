import pandas as pd
import matplotlib.pyplot as plt
from langchain_community.chat_models import ChatTongyi
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser
import json
import warnings

# -------------------------- 1. 初始化配置 --------------------------
# 替换为你的通义千问 API Key（从阿里云百炼平台获取）
TONGYI_API_KEY = "sk-e98a4cc8844246d29c05fa4f1e4b96e6"

# 图表默认配置（用于状态管理，记录当前图表参数）
chart_config = {
    "color": "black",  # 默认颜色
    "width_ratio": 1.0,  # 默认宽度比例（1.0=100%）
    "excel_path": r"D:\废物文件\QQ\test_data.xlsx",  # 本地Excel文件路径（请替换为你的文件路径）
    "data_loaded": False,
    "x_data": [],
    "y_data": []
}
# -------------------------- 2. 解决matplotlib中文显示问题 --------------------------
# 关闭字体缺失警告
warnings.filterwarnings('ignore', category=UserWarning, module='matplotlib')

# 设置matplotlib支持中文
plt.rcParams['font.sans-serif'] = ['WenQuanYi Micro Hei', 'SimHei', 'DejaVu Sans']  # 优先使用文泉驿微米黑，兼容不同Linux系统
plt.rcParams['axes.unicode_minus'] = False  # 解决负号显示问题
# -------------------------- 2. 初始化通义千问LLM --------------------------
llm = ChatTongyi(
    api_key=TONGYI_API_KEY,
    model_name="qwen-turbo",  # 通义千问轻量版，也可换qwen-plus/qwen-max
    temperature=0.1  # 低随机性，保证解析指令准确
)

# -------------------------- 3. 定义指令解析提示词（修复核心：转义大括号） --------------------------
prompt_template = ChatPromptTemplate.from_messages([
    ("system", """
    你是一个图表指令解析助手，仅处理以下两类指令：
    1. 绘图指令：用户输入"画图"，返回JSON格式：{{"action": "draw", "params": {{}}}}；
    2. 调整指令：用户输入调整图表颜色/宽度的指令（如"改为蓝色"、"宽度增加2%"），
       解析出调整类型和值，返回JSON格式：
       - 颜色调整：{{"action": "adjust", "params": {{"type": "color", "value": "蓝色"}}}}
       - 宽度调整：{{"action": "adjust", "params": {{"type": "width", "value": 0.02}}}} （增加2%=0.02，减少5%=-0.05）
    仅返回JSON字符串，不要添加任何额外文字！
    """),
    ("user", "{input}")
])

# 构建解析链
parse_chain = prompt_template | llm | StrOutputParser()
# -------------------------- 4. 核心功能函数 --------------------------
def load_excel_data():
    """读取Excel数据，提取折线图的x/y轴数据"""
    try:
        # 假设Excel第一列为x轴（如时间），第二列为y轴（如数值）
        df = pd.read_excel(chart_config["excel_path"])
        chart_config["x_data"] = df.iloc[:, 0].tolist()
        chart_config["y_data"] = df.iloc[:, 1].tolist()
        chart_config["data_loaded"] = True
        print("✅ Excel数据加载成功！")
    except Exception as e:
        print(f"❌ 加载Excel失败：{e}")
        return False
    return True

def draw_line_chart():
    """根据当前配置绘制折线图"""
    # 检查数据是否加载
    if not chart_config["data_loaded"] and not load_excel_data():
        return
    
    # 设置图表尺寸（默认宽度10，高度6，按比例调整）
    fig_width = 10 * chart_config["width_ratio"]
    fig, ax = plt.subplots(figsize=(fig_width, 6))
    
    # 绘制折线图
    ax.plot(
        chart_config["x_data"],
        chart_config["y_data"],
        color=chart_config["color"],
        linewidth=2  # 折线宽度（固定，可根据需求调整）
    )
    
    # 图表美化
    ax.set_xlabel("X轴", fontsize=12)
    ax.set_ylabel("Y轴", fontsize=12)
    ax.set_title("Excel数据折线图", fontsize=14)
    ax.grid(True, alpha=0.3)
    
    # 显示图表
    plt.tight_layout()
    plt.show()

def parse_user_input(user_input):
    """解析用户输入，返回操作类型和参数"""
    try:
        # 调用LLM解析指令
        response = parse_chain.invoke({"input": user_input})
        # 解析JSON结果
        result = json.loads(response)
        return result["action"], result["params"]
    except Exception as e:
        print(f"❌ 解析指令失败：{e}")
        return None, None

def adjust_chart_config(params):
    """根据解析后的参数更新图表配置"""
    adjust_type = params.get("type")
    value = params.get("value")
    
    if adjust_type == "color":
        # 颜色调整（支持中文颜色名/十六进制/英文）
        color_map = {
            "蓝色": "blue", "黑色": "black", "红色": "red",
            "绿色": "green", "黄色": "yellow"
        }
        chart_config["color"] = color_map.get(value, value)  # 兼容自定义颜色
        print(f"✅ 图表颜色已改为：{chart_config['color']}")
    elif adjust_type == "width":
        # 宽度调整（比例增减）
        chart_config["width_ratio"] += value
        # 限制宽度范围，避免异常
        chart_config["width_ratio"] = max(0.5, min(2.0, chart_config["width_ratio"]))
        print(f"✅ 图表宽度比例已更新为：{chart_config['width_ratio']:.2f}（{chart_config['width_ratio']*100:.1f}%）")

# -------------------------- 5. 主交互逻辑 --------------------------
def main():
    print("🤖 AI绘图助手已启动（输入'退出'结束）")
    print("📌 支持指令：")
    print("   - 画图：读取Excel数据绘制折线图")
    print("   - 改为XX颜色：调整折线颜色（如'改为蓝色'）")
    print("   - 宽度增加/减少X%：调整图表宽度（如'宽度增加2%'）")
    
    while True:
        user_input = input("\n请输入指令：").strip()
        if user_input == "退出":
            print("👋 助手已退出")
            break
        
        # 解析用户指令
        action, params = parse_user_input(user_input)
        if not action:
            print("❌ 无法识别的指令，请重新输入")
            continue
        
        # 执行对应操作
        if action == "draw":
            print("🎨 正在绘制折线图...")
            draw_line_chart()
        elif action == "adjust":
            adjust_chart_config(params)
            print("🔄 正在重新绘制调整后的图表...")
            draw_line_chart()

if __name__ == "__main__":
    main()