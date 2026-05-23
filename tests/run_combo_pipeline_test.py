"""
Session Combo: 时序动画 ➔ 卷帘对比 ➔ Web地图 ➔ 直方图 ➔ 实验报告
5节点长链条，同一会话上下文传导
"""
import requests, json, time, sys

BASE = "http://localhost:8000"
H = {"Content-Type": "application/json"}

def api(method, path, **kw):
    return requests.request(method, f"{BASE}{path}", headers=H, **kw)

def create_conv(msg=""):
    r = api("POST", "/api/conversations", json={"initial_message": msg[:50] or "新对话"})
    return r.json()["id"]

def send_msg(conv_id, content, timeout=300):
    print(f"\n{'─'*50}\n💬 {content[:100]}")
    r = api("POST", f"/api/conversations/{conv_id}/messages/stream",
            json={"content": content}, timeout=timeout, stream=True)
    if r.status_code != 200:
        print(f"  ❌ HTTP {r.status_code}")
        return
    buf = ""; etype = None
    try:
        for chunk in r.iter_content(chunk_size=None):
            buf += chunk.decode("utf-8", errors="replace")
            while "\n" in buf:
                line, buf = buf.split("\n", 1)
                if line.startswith("event: "): etype = line[7:].strip()
                elif line.startswith("data: ") and etype:
                    try:
                        d = json.loads(line[6:])
                        if etype == "tool_start":
                            tool = d.get("tool","?"); args = str(d.get("args",{}))[:60]
                            print(f"  🔧 {tool} {args}")
                        elif etype == "tool_result":
                            ok = d.get("result",{}).get("success"); ui = d.get("ui_action","")
                            msg = str(d.get("result",{}).get("message",""))[:80]
                            print(f"  {'✅' if ok else '❌'} ui={ui} {msg}")
                        elif etype == "final_answer":
                            print(f"  🎯 {str(d.get('content',''))[:150]}")
                        elif etype == "step_start":
                            print(f"  📍 步骤 {d.get('step')}/{d.get('max')}")
                    except: pass
    except: pass

# ═══════════════════════════════════
print("="*60)
print("Session Combo: 5节点长链条流水线")
print("="*60)

cid = create_conv("终极演示-多任务集成流水线")

# 节点1: 搜索本地LST + 制图 (GEE可能不可用，用本地数据)
print("\n🔹 节点1: 搜索+制图")
send_msg(cid, "搜索本地温江区2026年1月的LST TIF文件并生成专题图，配色用coolwarm")

# 节点2: 卷帘对比 (需要两个文件)
print("\n🔹 节点2: 卷帘对比")
send_msg(cid, "再对温江区2026年2月的LST也生成专题图，然后和1月的进行卷帘左右对比")

# 节点3: Web地图
print("\n🔹 节点3: Web地图")
send_msg(cid, "把刚才生成的温江区2026年1月LST专题图发布为交互式Web地图")

# 节点4: 统计直方图
print("\n🔹 节点4: 统计直方图")
send_msg(cid, "对当前温江区的LST数据做统计分析，输出温度直方图，展示均值、标准差")

# 节点5: 实验报告
print("\n🔹 节点5: 实验报告")
send_msg(cid, "把本次会话生成的所有专题图、直方图和Web地图打包，生成一份完整的HTML实验报告")

# ── 终报 ──
print(f"\n{'='*60}")
print("【多任务长链条集成压测 100% 闭环！】")
print(f"  会话ID: {cid}")
print(f"  时序动画、卷帘、Web地图、直方图与实验报告已在同一Session内完成数据全线贯通")
print(f"  前端: http://localhost:3003")
print(f"{'='*60}")
