"""
OpenGIS 4 大核心会话全自动压测
模拟真实用户对话，驱动完整 GIS 工具链
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
    print(f"\n{'='*50}\n💬 {content[:80]}...")
    r = api("POST", f"/api/conversations/{conv_id}/messages/stream",
            json={"content": content}, timeout=timeout, stream=True)
    if r.status_code != 200:
        print(f"  ❌ HTTP {r.status_code}")
        return
    buf = ""
    etype = None
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
                            print(f"  🔧 {d.get('tool')} args={str(d.get('args',{}))[:60]}")
                        elif etype == "tool_result":
                            ok = d.get("result",{}).get("success")
                            msg = str(d.get("result",{}).get("message",""))[:80]
                            print(f"  {'✅' if ok else '❌'} {d.get('tool')} {msg}")
                        elif etype == "final_answer":
                            print(f"  🎯 {str(d.get('content',''))[:120]}")
                        elif etype == "error":
                            print(f"  ❌ {d.get('message','')}")
                    except: pass
    except Exception:
        pass  # 流正常结束

# ═════════════════════════════════════════════════════
print("="*60)
print("OpenGIS 4 大核心会话压测")
print("="*60)

# Session 01: LST专题图与样式定制
print("\n📊 Session 01: LST专题图与样式定制")
c1 = create_conv("温江区LST专题图")
send_msg(c1, "检索本地温江区2026年1月到3月的LST数据，先用coolwarm色调生成1月的温度专题图，添加classic样式的指北针。对图像做高斯去噪增强，最后用自然断点法将温度划分为3类展示。")

# Session 02: 多源数据联动与高级空间分析
print("\n📊 Session 02: 高级空间分析")
c2 = create_conv("温江区空间分析")
send_msg(c2, "基于温江区现有的LST栅格，帮我统计温度直方图。再沿图像中心横向做剖面线分析，最后拉起3D地形可视化叠加温度场。")

# Session 03: GEE云端遥感大屏
print("\n📊 Session 03: GEE云端分析")
c3 = create_conv("温江区GEE分析")
send_msg(c3, "连接Google Earth Engine，对温江区运行Dynamic World地覆分类，并提取2020到2026年的长周期LANDSAT影像生成地表温度时间滑块动态大屏。")

# Session 04: 一键报告
print("\n📊 Session 04: 实验报告")
c4 = create_conv("温江区实验报告")
send_msg(c4, "把本次会话中所有生成的LST专题图、3D渲染图和统计直方图数据全部打包，自动编写并导出一份完整的HTML实验报告。")

# ── 终报 ──
print(f"\n{'='*60}")
print("4 大会话全部执行完毕！")
print(f"  Session 01 (LST专题图): conv_id={c1}")
print(f"  Session 02 (空间分析):   conv_id={c2}")
print(f"  Session 03 (GEE分析):    conv_id={c3}")
print(f"  Session 04 (实验报告):   conv_id={c4}")
print(f"  前端: http://localhost:3000")
print(f"{'='*60}")
