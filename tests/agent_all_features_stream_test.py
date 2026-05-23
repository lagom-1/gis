"""
Agent 多轮对话 4 连招黑盒流式压测
通过真实 SSE API 测试 35 个工具的 Agent 决策流
"""
import requests, json, time, sys, os, re

BASE = "http://localhost:8000"
HEADERS = {"Content-Type": "application/json"}
FAILED = []
PASSED = []
TOOL_TRACE = []


def log(emoji, msg):
    ts = time.strftime("%H:%M:%S")
    line = f"[{ts}] {emoji} {msg}"
    print(line)
    TOOL_TRACE.append(line)


def create_conversation(initial_msg=""):
    r = requests.post(f"{BASE}/api/conversations", json={"initial_message": initial_msg}, headers=HEADERS)
    if r.status_code == 201:
        cid = r.json()["id"]
        log("📝", f"创建会话 id={cid}")
        return cid
    raise RuntimeError(f"创建会话失败: {r.status_code} {r.text}")


def send_message_stream(conv_id, content, timeout=180):
    """发送消息并解析 SSE 流，返回所有事件"""
    log("💬", f"发送: {content[:60]}...")
    r = requests.post(
        f"{BASE}/api/conversations/{conv_id}/messages/stream",
        json={"content": content},
        headers={**HEADERS, "Accept": "text/event-stream"},
        stream=True,
        timeout=timeout,
    )
    if r.status_code != 200:
        log("❌", f"SSE HTTP {r.status_code}: {r.text[:200]}")
        return {"error": True, "status": r.status_code, "body": r.text[:200]}

    events = []
    current_type = None
    buffer = ""
    try:
        for chunk in r.iter_content(chunk_size=None):
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                if line.startswith("event: "):
                    current_type = line[7:].strip()
                elif line.startswith("data: "):
                    data_str = line[6:].strip()
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        data = {"raw": data_str}
                    events.append({"type": current_type, "data": data})

                    # 日志关键事件
                    if current_type == "tool_start":
                        log("🔧", f"调用: {data.get('tool','?')} args={str(data.get('args',{}))[:80]}")
                    elif current_type == "tool_result":
                        ok = data.get("result", {}).get("success", False)
                        ui = data.get("ui_action", "NONE")
                        icon = "✅" if ok else "❌"
                        msg = str(data.get("result", {}).get("message", ""))[:80]
                        log(icon, f"结果: {data.get('tool','?')} ui={ui} msg={msg}")
                    elif current_type == "final_answer":
                        log("🎯", f"最终回答: {str(data.get('content',''))[:100]}")
                    elif current_type == "error":
                        log("❌", f"错误: {data.get('message','')}")
                    elif current_type == "step_start":
                        log("📍", f"步骤 {data.get('step','?')}/{data.get('max','?')}")
                    elif current_type == "ask_user":
                        log("❓", f"反问: {data.get('question','')}")

                    # done 事件后安全退出
                    if current_type == "done" or current_type == "final_answer":
                        break
    except (requests.exceptions.ChunkedEncodingError, requests.exceptions.ConnectionError) as e:
        # 流正常结束（Agent 完成或连接关闭）
        pass
    except Exception as e:
        log("⚠️", f"流中断 (非致命): {e}")

    return {"events": events, "count": len(events)}


def assert_event_has(events, ev_type, check_fn, desc):
    """断言: 存在类型为 ev_type 且 check_fn(data) 为 True 的事件"""
    matches = [e for e in events if e["type"] == ev_type and check_fn(e["data"])]
    if matches:
        PASSED.append(desc)
        log("✅", f"断言通过: {desc}")
    else:
        FAILED.append(desc)
        log("❌", f"断言失败: {desc} (共 {len(events)} 事件, 匹配类型 {ev_type}: {len([e for e in events if e['type']==ev_type])})")


def assert_tool_called(events, tool_name, desc):
    """断言: 某个工具被调用过"""
    called = any(e["type"] == "tool_start" and e["data"].get("tool") == tool_name for e in events)
    if called:
        PASSED.append(desc)
        log("✅", f"断言通过: {desc}")
    else:
        FAILED.append(desc)
        log("❌", f"断言失败: {desc} (工具 {tool_name} 未被调用)")


def assert_tool_success(events, tool_name, desc):
    """断言: 某个工具调用成功"""
    ok = any(
        e["type"] == "tool_result" and e["data"].get("tool") == tool_name
        and e["data"].get("result", {}).get("success") == True
        for e in events
    )
    if ok:
        PASSED.append(desc)
        log("✅", f"断言通过: {desc}")
    else:
        FAILED.append(desc)
        log("❌", f"断言失败: {desc}")


def assert_no_error(events, desc):
    errors = [e for e in events if e["type"] == "error"]
    if not errors:
        PASSED.append(desc)
        log("✅", f"断言通过: {desc}")
    else:
        FAILED.append(desc)
        log("❌", f"断言失败: {desc} (错误数: {len(errors)})")


# ═══════════════════════════════════════════════════════════
# 连招 1：多月下载 → 样式定制 → 卷帘注册
# ═══════════════════════════════════════════════════════════
def test_chain_1():
    log("="*50, "")
    log("🚀", "连招 1: 多月下载 → 样式定制 → 对比")

    cid = create_conversation("温江区LST测试")
    all_events = []

    # 第1轮: 下载 → 这里用本地已有文件替代（GEE 耗时太长）
    # 由于已有本地 TIF，直接搜索 + 制图
    r1 = send_message_stream(cid, "搜索本地温江区2026年1月和2月的LST TIF文件，然后分别制图，标题格式为 温江区2026年X月LST专题图")
    all_events.extend(r1.get("events", []))
    assert_no_error(r1.get("events", []), "连招1-轮1: 无 SSE 错误")
    assert_tool_called(r1.get("events", []), "make_thematic_map", "连招1-轮1: make_thematic_map 被调用")

    # 第2轮: 改样式 → 调色盘 + 指北针 + 重命名
    r2 = send_message_stream(cid, "把这两张专题图的配色改为 coolwarm，指北针改成 classic 样式，标题保持 温江区2026年X月LST专题图 不变，重新出图")
    all_events.extend(r2.get("events", []))
    assert_no_error(r2.get("events", []), "连招1-轮2: 无 SSE 错误")
    assert_tool_called(r2.get("events", []), "set_map_style", "连招1-轮2: set_map_style 被调用")

    # 第3轮: 卷帘对比
    r3 = send_message_stream(cid, "把这两个月的专题图进行卷帘对比")
    all_events.extend(r3.get("events", []))
    assert_no_error(r3.get("events", []), "连招1-轮3: 无 SSE 错误")

    return all_events


# ═══════════════════════════════════════════════════════════
# 连招 2：空间分析 → 分类/增强 → 剖面/统计/3D
# ═══════════════════════════════════════════════════════════
def test_chain_2():
    log("="*50, "")
    log("🚀", "连招 2: 分析层 -> 分类 -> 增强 -> 剖面 -> 统计 -> 3D (逐轮拆分)")

    cid = create_conversation("温江区空间分析")
    all_events = []

    # 轮1: 搜索文件
    r0 = send_message_stream(cid, "找到温江区2026年1月的LST TIF文件")
    all_events.extend(r0.get("events", []))
    assert_no_error(r0.get("events", []), "连招2-轮1: 无 SSE 错误")

    # 轮2: 分类 (单独一轮)
    r1 = send_message_stream(cid, "对当前TIF用自然断点法分3类")
    all_events.extend(r1.get("events", []))
    assert_no_error(r1.get("events", []), "连招2-轮2: 无 SSE 错误")
    assert_tool_called(r1.get("events", []), "classify_map", "连招2-轮2: classify_map 被调用")

    # 轮3: 增强 (单独一轮，指定用当前数据集)
    r2 = send_message_stream(cid, "对当前数据集做高斯去噪增强处理，tif_path直接用当前数据集路径")
    all_events.extend(r2.get("events", []))
    assert_no_error(r2.get("events", []), "连招2-轮3: 无 SSE 错误")
    assert_tool_called(r2.get("events", []), "enhance_raster", "连招2-轮3: enhance_raster 被调用")

    # 轮4: 剖面 (单独一轮)
    r3 = send_message_stream(cid, "对增强后的数据做剖面线分析，沿中心横向采样")
    all_events.extend(r3.get("events", []))
    assert_no_error(r3.get("events", []), "连招2-轮4: 无 SSE 错误")
    assert_tool_called(r3.get("events", []), "profile_analysis", "连招2-轮4: profile_analysis 被调用")

    # 轮5: 统计 (单独一轮)
    r4 = send_message_stream(cid, "对当前数据做统计分析输出直方图")
    all_events.extend(r4.get("events", []))
    assert_no_error(r4.get("events", []), "连招2-轮5: 无 SSE 错误")
    assert_tool_called(r4.get("events", []), "statistics", "连招2-轮5: statistics 被调用")

    # 轮6: 3D (单独一轮，用当前数据集)
    r5 = send_message_stream(cid, "对当前数据生成3D地形可视化，使用当前数据集路径")
    all_events.extend(r5.get("events", []))
    assert_no_error(r5.get("events", []), "连招2-轮6: 无 SSE 错误")
    assert_tool_called(r5.get("events", []), "view_3d", "连招2-轮6: view_3d 被调用")

    return all_events


# ═══════════════════════════════════════════════════════════
# 连招 3：GEE 智能分类 → 地覆分析 → 时间滑块
# ═══════════════════════════════════════════════════════════
def test_chain_3():
    log("="*50, "")
    log("🚀", "连招 3: GEE 分类 -> 地覆分析 -> 时间滑块")

    cid = create_conversation("温江区GEE分析")
    all_events = []

    # 第1轮: Dynamic World + K-Means
    r1 = send_message_stream(cid, "对温江区运行 Dynamic World 9类地覆分类和 K-Means 无监督聚类分析")
    all_events.extend(r1.get("events", []))
    assert_no_error(r1.get("events", []), "连招3-轮1: 无 SSE 错误")
    # 至少一个 GEE 分类工具被调用
    assert_event_has(r1.get("events", []), "tool_start",
        lambda d: d.get("tool") in ["dynamic_world_landcover", "ee_unsupervised_classify"],
        "连招3-轮1: GEE 分类工具被调用")

    # 第2轮: 时序提取 + 时间滑块
    r2 = send_message_stream(cid, "在温江区中心位置提取2020-2026年地温时序，生成时间滑块交互地图")
    all_events.extend(r2.get("events", []))
    assert_no_error(r2.get("events", []), "连招3-轮2: 无 SSE 错误")
    assert_event_has(r2.get("events", []), "tool_start",
        lambda d: d.get("tool") in ["extract_timeseries_to_point", "generate_timeslider_map"],
        "连招3-轮2: 时序/时间滑块工具被调用")

    return all_events


# ═══════════════════════════════════════════════════════════
# 连招 4：GIF 序列动画 → 趋势图 → 报告导出
# ═══════════════════════════════════════════════════════════
def test_chain_4():
    log("="*50, "")
    log("🚀", "连招 4: GIF 序列 -> 趋势图 -> 报告")

    cid = create_conversation("温江区时空演变")
    all_events = []

    # 第1轮: 趋势图 + GIF 合成
    r1 = send_message_stream(cid, "分析温江区2026年1月到3月温度变化趋势，绘制趋势折线图，将这三个月的专题图合成GIF动画")
    all_events.extend(r1.get("events", []))
    assert_no_error(r1.get("events", []), "连招4-轮1: 无 SSE 错误")
    assert_event_has(r1.get("events", []), "tool_start",
        lambda d: d.get("tool") in ["gee_lst_timelapse_local", "gee_lst_timelapse", "gee_lst_trend_chart"],
        "连招4-轮1: 时序可视化工具被调用")

    # 第2轮: 报告
    r2 = send_message_stream(cid, "将本次会话所有成果打包生成HTML实验报告")
    all_events.extend(r2.get("events", []))
    assert_no_error(r2.get("events", []), "连招4-轮2: 无 SSE 错误")
    assert_tool_called(r2.get("events", []), "generate_report", "连招4-轮2: generate_report 被调用")

    return all_events


# ═══════════════════════════════════════════════════════════
# 执行
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("="*60)
    print("Agent 多轮对话 4 连招流式压测")
    print(f"后端: {BASE}")
    print("="*60)

    for name, fn in [
        ("连招1: 多月下载→样式→卷帘", test_chain_1),
        ("连招2: 分析→分类→剖面→3D", test_chain_2),
        ("连招3: GEE分类→地覆→时间滑块", test_chain_3),
        ("连招4: GIF→趋势→报告", test_chain_4),
    ]:
        try:
            fn()
        except Exception as e:
            FAILED.append(f"{name}: 异常 - {e}")
            log("💥", f"{name} 崩溃: {e}")

    # ── 终报 ──
    print("\n" + "="*60)
    print(f"📊 压测终报: {len(PASSED)} 通过 / {len(FAILED)} 失败")
    print("="*60)
    if FAILED:
        print("❌ 失败项:")
        for f in FAILED:
            print(f"  - {f}")
        sys.exit(1)
    else:
        print("✅ 全部通过!")
        sys.exit(0)
