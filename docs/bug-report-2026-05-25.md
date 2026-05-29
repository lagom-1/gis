# OpenGIS Agent 任务执行 Bug 报告

> 日期：2026-05-25
> 测试环境：Windows 11 / gdal_env conda / DeepSeek v4-flash / SQLite
> 测试场景：同一对话中多轮工具调用（下载数据 → 制图 → 调整样式 → 生成 Web 地图）

---

## 目录

1. [会话状态不持久化](#bug-1-会话状态不持久化)
2. [LLM 重复调用 set_current_dataset 无限循环](#bug-2-llm-重复调用-set_current_dataset-无限循环)
3. [LLM 重复调用 set_map_style 无限循环](#bug-3-llm-重复调用-set_map_style-无限循环)
4. [Guard 变量引用错误](#bug-4-guard-变量引用错误)
5. [Guard 幂等检查包含当前调用自身](#bug-5-guard-幂等检查包含当前调用自身)
6. [SSE 双发 done 事件](#bug-6-sse-双发-done-事件)
7. [连续失败强制终止](#bug-7-连续失败强制终止)
8. [_correct_decision 强制 final 终止](#bug-8-_correct_decision-强制-final-终止)
9. [Guard 强制终止循环](#bug-9-guard-强制终止循环)
10. [DeepSeek 模型返回非 JSON 文本](#bug-10-deepseek-模型返回非-json-文本)
11. [未修复：LLM 仍会循环调用工具](#未修复-llm-仍会循环调用工具)

---

## Bug 1：会话状态不持久化

**严重程度**：P0（阻断性）

**状态**：已修复

**现象**：

在同一对话中，第一条消息成功执行完整工具链（`resolve_admin_region` → `gee_download_monthly_lst` → `set_current_dataset` → `make_thematic_map`），第二条消息发送"把图例放到右边"时，`make_thematic_map` 返回"没有可用栅格"。`current_dataset` 在第二条消息中为 `None`。

**复现步骤**：

1. 创建新会话
2. 发送消息 1："下载温江区2025年8月的LST数据并制作专题图" → 成功
3. 发送消息 2："把图例放到右边" → `make_thematic_map` 失败，报"没有可用栅格"

**根因分析**：

SSE 端点 `send_message_stream` 中，`event_generator` 的事件处理流程存在时序问题：

```
主循环处理事件:
  1. yield "event: final_answer"  → 客户端收到
  2. yield "event: done"          → 客户端收到 done，关闭 SSE 连接
  3. should_break = True，跳出循环

finally 块:
  4. save_conversation_state()    → 永远不执行！客户端已断开
```

客户端收到 `done` 事件后立即关闭 SSE 连接。Python 异步生成器的 `finally` 块在连接关闭后可能不被执行（取决于 GC 时机），导致 `save_conversation_state` 从未调用。

**数据库验证**：

```python
# 查询所有会话状态
from api.services.conversation_service import load_conversation_state
for cid in range(1, 12):
    state = load_conversation_state(db, cid)
    print(f"Conv {cid}: {state}")
# 结果：所有会话返回 None，conversation_states 表为空
```

**修复方案**：

将状态保存移到 `done` 事件发送之前：

```python
def _save_state_and_messages():
    """在 done 事件 yield 之前调用"""
    # 保存工具历史、最终回复、runtime 状态到 DB
    save_conversation_state(db, conv_id, runtime.to_dict())
    conv.status = ConversationStatus.ACTIVE
    db.commit()

# 主循环中：
elif event_type in ("final_answer", "done"):
    _save_state_and_messages()  # 先保存
    should_break = True
    break                        # 再跳出

# finally 仅作兜底
finally:
    if not state_saved:
        _save_state_and_messages()
```

**修改文件**：`api/routers/conversations.py`

**验证结果**：

```
Message 1: set_current_dataset + make_thematic_map → Success, Steps: 2
State saved! current_dataset=D:/opengis/workspace/outputs/温江区_2020_02_lst.tif

Message 2: 把图例放到右边 → Success, Steps: 2
Final state: current_dataset=D:/opengis/workspace/outputs/温江区_2020_02_lst.tif
```

---

## Bug 2：LLM 重复调用 set_current_dataset 无限循环

**严重程度**：P0（阻断性）

**状态**：已修复

**现象**：

LLM 成功调用 `set_current_dataset` 后，反复以相同参数再次调用该工具，直到耗尽所有步骤（25 步）。

**复现步骤**：

1. 发送"请用 set_current_dataset 设置当前数据集为 D:/xxx.tif，然后用 make_thematic_map 制图"
2. 观察 SSE 事件流：`set_current_dataset` 成功 → `make_thematic_map` 成功 → `set_current_dataset` 成功 → 循环...

**根因分析**：

`_correct_decision` 中对 `set_current_dataset` 同路径的处理是 `pass`（放行）：

```python
# 修复前
if tool == "set_current_dataset" and self.runtime.current_dataset:
    target = args.get("path", "")
    if target and target == self.runtime.current_dataset:
        pass  # 允许重复设置，不拦截
```

Guard 的 `_IDEMPOTENT_ONCE` 也不包含 `set_current_dataset`，所以幂等检查不生效。

**修复方案**：

1. `_correct_decision`：同路径时转为 `make_thematic_map`
2. Guard：`set_current_dataset` 加入 `_IDEMPOTENT_ONCE`

```python
# engine.py - _correct_decision
if tool == "set_current_dataset" and self.runtime.current_dataset:
    target = args.get("path", "")
    if target and target == self.runtime.current_dataset:
        return {
            "type": "tool_call",
            "tool": "make_thematic_map",
            "args": {},
            "reason": f"数据集已设置为 {target}，自动生成专题图",
        }

# guard.py
_IDEMPOTENT_ONCE = {"resolve_admin_region", "gee_init", "set_current_dataset", "set_map_style"}
```

**修改文件**：`agent/engine.py`、`agent/guard.py`

---

## Bug 3：LLM 重复调用 set_map_style 无限循环

**严重程度**：P0（阻断性）

**状态**：已修复

**现象**：

用户发送"把图例放到右边"后，LLM 反复调用 `set_map_style` + `make_thematic_map`，50 步不停止。从 DB 消息历史可见：

```
[tool_call] set_map_style step=1 ok=True
[tool_result] make_thematic_map step=2 ok=False
[tool_call] set_map_style step=3 ok=True
[tool_result] make_thematic_map step=4 ok=False
... 重复 25 次 ...
```

**根因分析**：

1. `set_map_style` 不在 Guard 的 `_IDEMPOTENT_ONCE` 中
2. Guard 的 `check()` 方法检查 `history[-1]`，但 `history[-1]` 可能是 `__system_hint__` 条目（引擎在工具成功后注入的提示），不是真实工具调用
3. `__system_hint__` 条目导致 Guard 的幂等检查被跳过

**修复方案**：

1. `set_map_style` 加入 `_IDEMPOTENT_ONCE`
2. Guard 从后往前遍历，跳过 `__system_hint__` 找到最近的真实工具调用

```python
# guard.py
_IDEMPOTENT_ONCE = {"resolve_admin_region", "gee_init", "set_current_dataset", "set_map_style"}

def check(self, history):
    # ...
    # 从后往前找最近的真实工具调用（跳过 __system_hint__）
    last = None
    for h in reversed(history):
        if h.get("tool") and h.get("tool") != "__system_hint__":
            last = h
            break
    if last is None:
        return ""
    last_tool = last.get("tool")
    if last_tool in self._IDEMPOTENT_ONCE:
        prev_success = [
            h for h in history
            if h is not last and h.get("tool") == last_tool and h.get("result", {}).get("success")
        ]
        if prev_success:
            return f"{last_tool} 已成功执行过，请继续下一步。"
```

**修改文件**：`agent/guard.py`

---

## Bug 4：Guard 变量引用错误

**严重程度**：P1（运行时崩溃）

**状态**：已修复

**现象**：

Guard 连续下载检查中，重构后仍引用已删除的 `last_two` 变量，触发 `NameError`。

**根因分析**：

将 `last_two = [h.get("tool") for h in history[-2:]]` 重构为 `real_tools` 列表后，错误信息未更新：

```python
# 修复前（有 bug）
real_tools = [h.get("tool") for h in history if h.get("tool") and h.get("tool") != "__system_hint__"]
if len(real_tools) >= 2 and real_tools[-1] == real_tools[-2] and real_tools[-1] in self._DOWNLOAD_TOOLS:
    return f"{last_two[0]} 已连续调用 2 次..."  # NameError: last_two 未定义
```

**修复方案**：

```python
return f"{real_tools[-1]} 已连续调用 2 次，数据已下载。请使用已有数据继续下一步。"
```

**修改文件**：`agent/guard.py:34`

---

## Bug 5：Guard 幂等检查包含当前调用自身

**严重程度**：P2（逻辑错误）

**状态**：已修复

**现象**：

Guard 的幂等检查可能误判：当 `last` 不是 `history[-1]` 时（因为跳过了 `__system_hint__`），`history[:-1]` 仍包含 `last` 本身，导致"找到 previous success"实际上是当前调用。

**根因分析**：

```python
# 修复前
last = history[-1]  # 可能是 __system_hint__
# ... 但如果 last 被重新查找为 history[-2]，则 history[:-1] 包含 history[-2]
prev_success = [h for h in history[:-1] if h.get("tool") == last_tool ...]
# history[:-1] = [h0, h1, ..., h_{n-2}]，如果 last = h_{n-2}，则包含自身
```

**修复方案**：

使用身份比较 `h is not last` 排除当前调用：

```python
prev_success = [
    h for h in history
    if h is not last and h.get("tool") == last_tool and h.get("result", {}).get("success")
]
```

**修改文件**：`agent/guard.py`

---

## Bug 6：SSE 双发 done 事件

**严重程度**：P2（客户端体验）

**状态**：已修复

**现象**：

客户端收到两个 `done` 事件。

**根因分析**：

主循环处理 `done` 事件时 yield 一次，`finally` 块又 yield 一次：

```python
# 主循环
elif event_type in ("final_answer", "done"):
    yield f"event: done\ndata: {{}}\n\n"  # 第一次
    break

# finally
finally:
    yield f"event: done\ndata: {{}}\n\n"  # 第二次
```

**修复方案**：

移除 `finally` 中的 `yield done`：

```python
finally:
    executor.shutdown(wait=False)
    if not state_saved:
        _save_state_and_messages()
    # done 事件已在主循环中发送，不再重复
```

**修改文件**：`api/routers/conversations.py`

---

## Bug 7：连续失败强制终止

**严重程度**：P1（限制性）

**状态**：已移除

**现象**：

工具连续失败 2 次后，Agent 被强制停止，返回"执行失败"，用户无法继续。

**根因分析**：

```python
# 修复前
if not result.get("success", False):
    failures = sum(1 for r in history[-3:] if not r.get("result", {}).get("success", True))
    if step >= max(5, self.max_steps - 3) and failures >= 2:
        return result.get("message", "执行失败")  # 强制终止
```

**修复方案**：

移除连续失败终止逻辑，改为仅日志记录：

```python
# 连续失败不终止，让 LLM 自行判断
```

**修改文件**：`agent/engine.py`

---

## Bug 8：_correct_decision 强制 final 终止

**严重程度**：P1（限制性）

**状态**：已移除

**现象**：

以下场景会强制返回 `final` 终止任务：
- `resolve_admin_region` 重复调用
- `gee_init` 重复调用
- 下载工具同参数重复调用

**根因分析**：

`_correct_decision` 中多处 `return {"type": "final", "answer": "..."}` 强制终止：

```python
# 场景 1
if tool == "resolve_admin_region":
    for h in history:
        if h.get("tool") == "resolve_admin_region" and h.get("result", {}).get("success"):
            return {"type": "final", "answer": "行政区边界已解析完成..."}

# 场景 2
if tool == "gee_init":
    for h in history:
        if h.get("tool") == "gee_init" and h.get("result", {}).get("success"):
            return {"type": "final", "answer": "GEE 已成功初始化..."}

# 场景 3
if tool in self._DATA_PRODUCERS:
    for h in history:
        if h.get("tool") == tool and h.get("args") == args and h.get("result", {}).get("success"):
            return {"type": "final", "answer": f"{tool} 已用相同参数成功执行过..."}
```

**修复方案**：

移除所有强制 `final`，改为跳过让 LLM 自行判断：

```python
# ── 1. resolve_admin_region 已调用过 → 跳过，让 LLM 自行判断 ──
# ── 2. gee_init 已成功 → 跳过，让 LLM 自行判断 ──
# ── 4. 参数级去重 → 跳过，让 LLM 自行判断 ──
```

**修改文件**：`agent/engine.py`

---

## Bug 9：Guard 强制终止循环

**严重程度**：P1（限制性）

**状态**：已移除

**现象**：

Guard 检测到循环模式时，直接设置 `forced_stop = True` 并强制 `final`，Agent 无法继续执行。

**根因分析**：

```python
# 修复前
loop_warning = self.guard.check(history)
if loop_warning:
    forced_stop = True
    final_answer = f"{loop_warning}\n\n{last_result.get('message', '任务已完成。')}"
    emit("final_answer", {"content": final_answer})
    break  # 强制终止
```

**修复方案**：

改为仅日志警告，不终止：

```python
# 修复后
loop_warning = self.guard.check(history)
if loop_warning:
    logger.info(f"[Guard] 警告: {loop_warning}")
    # 不终止，继续执行
```

**修改文件**：`agent/engine.py`

---

## Bug 10：DeepSeek 模型返回非 JSON 文本

**严重程度**：P1（解析失败）

**状态**：已修复（之前会话）

**现象**：

DeepSeek v4-flash 对简单问候返回 Markdown 文本（"你好！我是 GIS 遥感智能助手..."），而非要求的 JSON 格式，导致 `invoke_json` 解析失败。

**根因分析**：

DeepSeek 模型不严格遵守 system prompt 中的"只输出 JSON"约束，尤其在对话场景（无工具调用历史）中倾向返回自然语言。

**修复方案**：

1. 强化 system prompt：`"你的唯一输出格式是 JSON，严禁输出任何其他文字、Markdown 或解释"`
2. `invoke_json` 中非 JSON 响应在对话场景（`output_count == 0` 且 `last_result is None`）转为 `final`
3. 任务场景（已有工具调用历史）抛出 `RuntimeError` 让引擎重试

```python
if last_text:
    if payload.get("output_count", 0) > 0 or payload.get("last_result") is not None:
        # 任务场景：非 JSON 是错误
        raise RuntimeError(f"LLM 在任务执行中返回了非 JSON 响应: {last_text[:150]}")
    # 对话场景：转为 final
    return {"type": "final", "answer": last_text}
```

**修改文件**：`agent/llm.py`、`agent/prompts/system.py`

---

## 未修复：LLM 仍会循环调用工具

**严重程度**：P2（体验问题）

**状态**：未修复

**现象**：

即使 Guard 和 `_correct_decision` 已修复，DeepSeek 模型在某些场景下仍会反复调用同一工具（如 `set_map_style` 调用 28 次才停止）。

**根因分析**：

1. Guard 的幂等检查只拦截**完全相同**的工具名，LLM 略改参数（如 `legend_position: "right"` vs `legend_position: "lower right"`）就绕过了
2. DeepSeek 模型不充分阅读 `conversation_history` 上下文，不知道工具已成功执行
3. `_correct_decision` 中 `set_map_style` → `make_thematic_map` 的自动渲染如果失败，LLM 会重试 `set_map_style`

**可能的解决方案**：

1. **更强的上下文注入**：在 LLM payload 中明确列出"已成功执行的工具"摘要
2. **工具调用计数限制**：同一工具在 N 步内调用超过 M 次时注入系统警告
3. **LLM 提示词优化**：在 system prompt 中强调"工具成功后不要重复调用"
4. **更换模型**：使用更强的模型（如 DeepSeek v3/v4 正式版）减少循环行为

---

## 修改文件汇总

| 文件 | 修改内容 |
|------|----------|
| `api/routers/conversations.py` | 状态保存移到 done 之前；移除 finally 中的双发 done |
| `agent/engine.py` | max_steps 25→100；移除连续失败终止；移除 _correct_decision 中所有强制 final；Guard 改为仅警告 |
| `agent/guard.py` | set_current_dataset/set_map_style 加入幂等列表；跳过 __system_hint__；修复变量引用和身份比较 |
| `agent/llm.py` | 非 JSON 响应处理：对话场景转 final，任务场景抛异常 |
| `agent/prompts/system.py` | 强化 JSON-only 约束 |
| `tools/runtime.py` | 添加 from_dict 日志（调试用，已清理） |
| `api/services/conversation_service.py` | save/load 添加日志和异常处理 |
