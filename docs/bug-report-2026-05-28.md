# Bug 报告：Agent 循环调用与前端显示问题

**日期**：2026-05-28
**测试场景**：下载旺苍县2025年2月LST → 制图 → 调整配色
**严重程度**：高（核心功能异常）

---

## 问题概述

用户测试"调整配色"功能时，发现以下问题：
1. `set_map_style` 和 `make_thematic_map` 被重复调用 15+ 次
2. 前端显示多个重复的专题图文件
3. 原始配色的图片在前端丢失
4. 新生成的文件名没有包含配色方案信息

---

## Bug #1：LLM 重复调用 set_map_style

### 现象
- 数据库消息记录显示 `set_map_style` 和 `make_thematic_map` 交替调用 15+ 次
- 任务执行时间过长（约1分钟）

### 根本原因
**`__system_hint__` 对 LLM 不可见**

#### 数据流分析
```
engine.py._execute_tool_call()
  ↓ set_map_style 成功后自动调用 make_thematic_map
  ↓ 注入 __system_hint__ 到 history
build_context()
  ↓ 构建 payload，但没有包含 history
invoke_json(payload)
  ↓ payload 转 JSON 作为 user message
LLM
  ↓ 看不到 __system_hint__，继续调用 set_map_style
```

#### LLM 实际看到的 payload
```json
{
  "user_input": "调整配色",
  "step": 3,
  "runtime": {
    "current_dataset": "...",
    "output_files": [...]
  },
  "output_count": 1,
  "last_result": {...},
  "success_tools": ["set_map_style", "make_thematic_map"],
  "loop_warning": ""
}
```

**问题**：没有 `history` 字段，LLM 无法看到 `__system_hint__` 中的"严禁再次调用"指令。

### 相关代码
- `agent/engine.py:436-454` — `__system_hint__` 注入逻辑
- `agent/context.py:113-126` — `build_context` 返回的 payload 缺少 history

---

## Bug #2：文件名没有包含配色方案

### 现象
- 生成的文件名：`旺苍县_2025年2月_LST_LST专题图.png`
- 预期文件名：`旺苍县_2025年2月_LST_viridis_专题图.png`

### 根本原因
**后端代码修改未生效**

#### 代码修改
```python
# tools/visualization.py:190-192
# 文件名包含配色方案，不同配色生成不同文件，方便用户比较
colormap_name = style.get("colormap", "coolwarm")
output_path = kwargs.get("output_path") or str(self._out_dir() / f"{_stem(tif)}_{colormap_name}_专题图.png")
```

#### 可能原因
1. 后端 `--reload` 模式未检测到文件变化
2. `make_thematic_map` 被系统自动调用时，`colormap` 参数未正确传递
3. `style.get("colormap")` 返回 `None`，使用了默认值 `"coolwarm"`

### 相关代码
- `tools/visualization.py:190-192` — 输出路径生成逻辑
- `agent/engine.py:439` — 自动调用 `make_thematic_map` 时未传递 colormap 参数

---

## Bug #3：前端显示多个重复文件

### 现象
- 文件夹中只有 1 个专题图文件
- 前端显示多个相同的文件

### 根本原因
**前端从多个 tool_result 消息中提取文件时，内部去重逻辑可能未生效**

#### 前端代码分析
```typescript
// Conversations.tsx:148-160
const files: OutputFile[] = []
const seenNames = new Set<string>()
for (const msg of result.messages) {
  if (msg.tool_result) {
    for (const f of extractFilesFromResult(msg.tool_result as Record<string, unknown>)) {
      if (!seenNames.has(f.name)) {
        seenNames.add(f.name)
        files.push(f)
      }
    }
  }
}
```

#### 问题分析
- `set_map_style` 被调用 15 次
- 每次都返回相同的 `output_png` 路径
- 去重逻辑应该生效，但可能因为：
  1. 文件名在不同消息中不完全一致（路径分隔符差异）
  2. `extractFilesFromResult` 提取的文件名不一致

### 相关代码
- `frontend/src/pages/Conversations.tsx:148-160` — 文件提取和去重逻辑
- `frontend/src/utils/workspace.ts:16-41` — `extractFilesFromResult` 函数

---

## Bug #4：原始配色图片丢失

### 现象
- 第一次制图生成的 `旺苍县_2025年2月_LST_map.png` 在前端不显示
- 只显示新配色的专题图

### 根本原因
**前端只显示最后一次提取到的文件**

#### 分析
- 前端 `outputFiles` 状态是累积的
- 但如果 `extractFilesFromResult` 从最新的 tool_result 中提取文件，可能会覆盖之前的文件
- 或者前端只显示最新的图片，没有保留历史图片

### 相关代码
- `frontend/src/pages/Conversations.tsx:152` — `setOutputFiles` 更新逻辑

---

## 问题关联图

```
用户说"调整配色"
  ↓
LLM 调用 set_map_style
  ↓
系统自动调用 make_thematic_map
  ↓
注入 __system_hint__ 到 history
  ↓
LLM 看不到 __system_hint__（Bug #1）
  ↓
LLM 继续调用 set_map_style（循环 15+ 次）
  ↓
每次生成相同的文件名（Bug #2）
  ↓
前端从 15 个 tool_result 中提取文件
  ↓
去重逻辑可能失效（Bug #3）
  ↓
前端显示多个重复文件
  ↓
原始配色图片被覆盖或丢失（Bug #4）
```

---

## 修复建议

### Bug #1：让 LLM 看到 __system_hint__

**方案 A**：在 payload 中添加最近的 system_hint
```python
# agent/context.py
recent_hints = [
    h for h in history[-5:]
    if h.get("tool") == "__system_hint__"
]
return {
    ...
    "system_hints": [h.get("reason") for h in recent_hints],
}
```

**方案 B**：在 payload 中添加完整 history
```python
return {
    ...
    "history": history[-10:],  # 最近 10 条记录
}
```

**推荐方案 A**（payload 更小，信息更精准）

### Bug #2：确保文件名包含配色方案

1. 重启后端，确保代码修改生效
2. 检查 `make_thematic_map` 自动调用时是否传递了 `colormap` 参数
3. 添加日志验证输出路径

### Bug #3：修复前端去重逻辑

1. 检查 `extractFilesFromResult` 返回的文件名格式
2. 确保路径分隔符一致（统一使用 `/`）
3. 添加更严格的去重逻辑（基于完整路径）

### Bug #4：保留所有历史图片

1. 前端应累积所有图片，不覆盖
2. 或者在文件名中加入时间戳/序号

---

## 测试验证步骤

修复后需要验证：

1. **单文件场景**
   - 下载旺苍县2025年2月LST
   - 制图
   - 调整配色
   - 验证：只调用 1 次 set_map_style
   - 验证：生成 2 个不同配色的文件
   - 验证：前端显示 2 个文件

2. **多文件场景**
   - 下载 3 个年份的 LST
   - 批量调整配色
   - 验证：调用 3 次 set_map_style
   - 验证：生成 3 个新配色文件
   - 验证：前端显示所有文件

---

## 状态

| Bug | 状态 | 优先级 |
|-----|------|--------|
| #1 LLM 看不到 __system_hint__ | 待修复 | P0 |
| #2 文件名缺少配色方案 | 待修复 | P1 |
| #3 前端显示重复文件 | 待修复 | P1 |
| #4 原始图片丢失 | 待修复 | P2 |
