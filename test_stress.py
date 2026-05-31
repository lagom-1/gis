"""
全自动闭环压测脚本 — 禁止本地寻址，全部走 GEE 真实下载
所有中间输出静默，仅输出最终验证结果
"""
from __future__ import annotations

import json, os, sys, time, traceback
from pathlib import Path

WORKSPACE = Path(__file__).parent / "workspace" / "outputs"

TESTS = [
    ("A",
     "GEE下载→SCA反演→coolwarm→HTML报告",
     "启动 GEE，现场下载四川省成都市温江区 2021 年 1 月的地表温度相关 Landsat 栅格。下载完成后，立刻进行本地 SCA 算法反演，将反演结果配色微调为 coolwarm，最后生成一份包含完整统计图表的 HTML 实验报告。"
    ),
    ("B",
     "GEE时序→3D线框→Timelapse动图",
     "调用 GEE 下载/获取双流区 2024 年 8 月及近年同期的 Landsat 核心数据，本地生成 3D 表面线框图，并现场制作一幅动态时序 Timelapse 动图。"
    ),
    ("C",
     "行政区划→分类→高亮→分区统计",
     "解析成都市县级 GeoJSON，通过 GEE 下载对应的最新地表温度栅格，现场执行自然断点法分类（4类），将温度大于35度的区域进行 RGBA 红框高亮，并结合县级边界计算分区统计直方图。"
    ),
]

def list_output_files():
    files = []
    if WORKSPACE.exists():
        for root, dirs, fns in os.walk(str(WORKSPACE)):
            for fn in fns:
                fp = Path(root) / fn
                files.append((str(fp), fp.stat().st_size))
    return sorted(files, key=lambda x: x[1], reverse=True)

def run_scenario(sid, desc, instruction, run_index=1):
    print(f"\n{'='*70}")
    print(f"  场景 {sid}: {desc} (第{run_index}次)")
    print(f"{'='*70}")

    before = set(list_output_files())

    try:
        from tools import ToolRegistry
        from tools.runtime import GISRuntime
        from agent.llm import LLMClient
        from agent.engine import AgentLoop

        runtime = GISRuntime()
        registry = ToolRegistry(runtime)
        llm = LLMClient()
        agent = AgentLoop(llm, registry, runtime, max_steps=25)

        start = time.time()
        result = agent.run(instruction)
        elapsed = time.time() - start

    except Exception as e:
        print(f"  ❌ 异常: {e}")
        traceback.print_exc()
        return False, {}, str(e), before, set()

    after = set(list_output_files())
    new_files = after - before
    steps = len(result.get("history", []))
    answer = result.get("answer", "")[:500]
    success = result.get("success", False)

    print(f"  耗时: {elapsed:.0f}s | 步数: {steps} | success={success}")

    # 错误详情
    errors = []
    for h in result.get("history", []):
        r = h.get("result", {})
        if not r.get("success", False):
            msg = r.get("message", "")[:200]
            errors.append(f"Step {h.get('step')}: {h.get('tool')} — {msg}")
            print(f"  ❌ Step {h.get('step')}: {h.get('tool')} — {msg}")

    # 新文件
    print(f"  新文件 ({len(new_files)}):")
    for fp, sz in sorted(new_files):
        ok = "✅" if sz > 0 else "⚠️空文件"
        print(f"    {ok} {fp} ({sz:,} bytes)")

    return success, result, "\n".join(errors), before, after

def main():
    scenario_filter = sys.argv[1] if len(sys.argv) > 1 else "all"

    print("=" * 70)
    print("  OpenGIS 全自动闭环压测 — 真实 GEE 下载验证")
    print("  铁律: 禁止本地寻址 | 全部走 GEE 下载 | 自主自愈")
    print("=" * 70)

    all_errors = []
    report = []

    for sid, desc, instr in TESTS:
        if scenario_filter != "all" and scenario_filter != sid:
            continue

        success = False
        errors = ""
        result = {}
        max_retries = 3

        for attempt in range(1, max_retries + 1):
            success, result, errors, before, after = run_scenario(sid, desc, instr, attempt)
            if success:
                break
            if attempt < max_retries:
                print(f"  ⚠️ 第{attempt}次尝试失败，准备第{attempt+1}次重试...")

        report.append({
            "id": sid, "desc": desc, "success": success,
            "steps": len(result.get("history", [])),
            "answer": result.get("answer", "")[:300],
            "errors": errors,
        })
        if not success:
            all_errors.append((sid, desc, errors))

    # ── 最终物理盘审计 ──
    print(f"\n{'='*70}")
    print(f"  物理盘审计 — workspace/outputs/")
    print(f"{'='*70}")
    all_files = list_output_files()
    total = sum(sz for _, sz in all_files)
    print(f"  总文件: {len(all_files)} | 总大小: {total:,} bytes")
    for fp, sz in all_files:
        print(f"    {'✅' if sz > 0 else '⚠️'} {fp} ({sz:,} bytes)")

    # ── 汇总报告 ──
    print(f"\n{'='*70}")
    print(f"  压测汇总")
    print(f"{'='*70}")
    for r in report:
        st = "✅ PASS" if r["success"] else "❌ FAIL"
        print(f"  场景{r['id']} [{st}] {r['desc']} — {r['steps']}步")
        if r["errors"]:
            print(f"    错误: {r['errors'][:200]}")

    if all_errors:
        print(f"\n  ⚠️ {len(all_errors)} 个场景失败")
        return 1
    print(f"\n  🎉 全部通过！")
    return 0

if __name__ == "__main__":
    sys.exit(main())
