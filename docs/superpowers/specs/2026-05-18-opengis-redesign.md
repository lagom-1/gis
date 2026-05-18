# OpenGIS 架构重新设计

**日期**: 2026-05-18
**方案**: B - Clean Plugin 架构
**原则**: 渐进式重构，`gis/` 层不动

---

## 1. 现状问题

| 问题 | 表现 |
|------|------|
| 巨型文件 | `agent/tool.py` 1818行，`agent/core.py` 902行，`Workspace.tsx` 622行 |
| 逻辑重复 | `ConversationalAgent` 复制 `GISAgent` 60% 验证逻辑 |
| 双模式混乱 | 轮询(task) 和 SSE(conversation) 两套执行模式并存 |
| 紧耦合 | Agent 核心混杂工具特定的硬编码检测逻辑 (timelapse/LST/行政区) |
| 前端状态散乱 | 4个 Zustand Store 概念重叠 |
| 工具定义原始 | 元组定义工具，无类型安全，添加工具需改多处 |
| 前端轮询 | 2秒轮询，无实时流式反馈 |
| 不可观测 | Agent 决策链路不透明，难以调试 |

## 2. 设计目标

1. **代码可维护性**: 每个文件 < 300 行，清晰模块边界，新人容易上手
2. **用户交互体验**: 实时 SSE 流式反馈，专业 GIS 可视化界面
3. **架构扩展性**: 插件化工具系统，添加新工具 = 新建一个文件
4. **开发迭代速度**: 减少样板代码，装饰器自动注册，热重载

## 3. 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (React 19 + TypeScript)      │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  │
│  │ ChatPanel│  │ViewerPanel│  │ Sidebar              │  │
│  │ (SSE流式) │  │ (预览/对比)│  │ (会话列表/历史)       │  │
│  └────┬─────┘  └────┬─────┘  └──────────┬───────────┘  │
│       │             │                    │               │
│  ┌────┴─────────────┴────────────────────┴───────────┐  │
│  │  hooks/ (useConversation SSE hook)                 │  │
│  │  stores/ (uiStore - 仅 UI 状态)                    │  │
│  │  api/ (fetch 封装, auth 拦截)                      │  │
│  └────────────────────────┬───────────────────────────┘  │
└───────────────────────────┼──────────────────────────────┘
                            │ SSE (POST /api/conversations/:id/stream)
┌───────────────────────────┼──────────────────────────────┐
│                    Backend (FastAPI)                      │
│  ┌────────────────────────┴───────────────────────────┐  │
│  │  api/routes/conversations.py (SSE StreamingResponse)│  │
│  │  api/models/ (ORM: User, Conversation, Message)     │  │
│  │  api/services/ (auth, file)                        │  │
│  └────────────────────────┬───────────────────────────┘  │
│                           │                               │
│  ┌────────────────────────┴───────────────────────────┐  │
│  │  agent/engine.py     AgentLoop (纯循环, ~150行)     │  │
│  │  agent/llm.py        LLMClient                      │  │
│  │  agent/guard.py      验证规则 + 循环检测             │  │
│  └──────┬──────────────────────────────┬──────────────┘  │
│         │                              │                  │
│  ┌──────┴──────┐              ┌────────┴──────────┐     │
│  │ tools/       │              │  gis/ (完全不动!)  │     │
│  │ ├── base.py  │              │  30+ 纯函数模块    │     │
│  │ ├── gis/     │              └───────────────────┘     │
│  │ ├── gee/     │                                        │
│  │ └── system/  │                                        │
│  │ (每工具1文件) │                                        │
│  └─────────────┘                                         │
└──────────────────────────────────────────────────────────┘
```

## 4. 后端设计

### 4.1 工具系统 (`tools/`)

每个工具一个文件，继承 `BaseTool`，用 `@tool` 装饰器自动注册：

```python
# tools/gis/lst.py
from tools.base import BaseTool, tool

@tool(
    name="run_lst",
    description="对当前多波段影像执行地表温度反演（SCA算法）",
    category="analysis",
    parameters={
        "input_tif": "可选，输入栅格路径",
    }
)
class RunLSTTool(BaseTool):
    def execute(self, input_tif=None) -> dict:
        tif = input_tif or self.runtime.current_tif()
        if not tif:
            return {"success": False, "message": "没有可用输入影像"}
        from gis.sca_runner import run_sca
        result = run_sca(input_tif=tif, ...)
        if result.get("success"):
            self.runtime.current_dataset = result["output_tif"]
        return result
```

**注册机制：**
- `tools/__init__.py` 扫描 `tools/gis/`、`tools/gee/`、`tools/system/` 子目录
- `importlib.import_module` 自动导入所有 `.py` 文件
- `@tool` 装饰器自动将类注册到 `ToolRegistry`
- 添加新工具 = 新建文件 + 装饰器，不修改其他代码

### 4.2 Agent 引擎 (`agent/engine.py`)

精简到 ~150 行，纯 Agent 循环，不含任何工具特定逻辑：

```python
class AgentLoop:
    def __init__(self, llm, registry, runtime, guard):
        self.llm = llm
        self.registry = registry
        self.runtime = runtime
        self.guard = guard

    async def run(self, user_input, history, on_event):
        for step in range(1, max_steps + 1):
            # 安全检查
            stop_reason = self.guard.check(history)
            if stop_reason:
                yield Event("stop", reason=stop_reason)
                break

            # LLM 决策
            decision = await self.llm.decide(user_input, step, runtime_state, history)
            yield Event("thinking", decision=decision)

            # 执行
            if decision.type == "final":
                yield Event("final", answer=decision.answer)
                break
            elif decision.type == "tool_call":
                yield Event("tool_start", tool=decision.tool)
                result = self.registry.call(decision.tool, decision.args)
                yield Event("tool_result", tool=decision.tool, result=result)
                history.append(result)
```

### 4.3 验证守卫 (`agent/guard.py`)

所有硬编码的工具特定逻辑集中在这里，每条规则独立函数，易测试：

```python
class SafetyGuard:
    def check(self, history) -> str | None:
        """返回停止原因或None"""
        if self._detect_loop(history):
            return "检测到循环调用"
        if self._detect_repeated_download(history):
            return "重复下载已阻止"
        return None

    def _detect_loop(self, history): ...
    def _detect_repeated_download(self, history): ...
    def should_auto_map(self, history) -> bool: ...
```

### 4.4 API 层

```
api/
├── main.py              # FastAPI app 入口
├── deps.py              # 依赖注入 (get_db, get_current_user)
├── routes/
│   ├── auth.py          # JWT 注册/登录
│   ├── conversations.py # 核心: SSE 流式端点
│   └── files.py         # 文件下载/预览
├── models/
│   ├── user.py          # User ORM
│   ├── conversation.py  # Conversation + Message + State
│   └── task.py          # Task ORM (保留用于历史)
└── services/
    ├── auth_service.py
    └── file_service.py
```

**SSE 事件协议:**
```
event: thinking     → {"step": 1, "reasoning": "正在分析用户意图..."}
event: tool_start   → {"tool": "resolve_admin_region", "args": {...}}
event: tool_result  → {"tool": "resolve_admin_region", "result": {...}}
event: step_start   → {"step": 2, "max": 25}
event: ask_user     → {"question": "..." , "options": [...]}
event: final_answer → {"content": "任务完成，已生成专题图..."}
event: error        → {"message": "..."}
event: done         → {}
```

**唯一执行入口:**
```
POST /api/conversations/:id/stream
Body: {"content": "下载成都市双流区LST并制图"}
→ StreamingResponse (text/event-stream)
```

## 5. 前端设计

### 5.1 组件树

```
Workspace.tsx (thin orchestrator, ~80行)
├── Sidebar.tsx
│   ├── ConversationList.tsx    # 会话列表
│   └── UserMenu.tsx           # 用户信息
├── ChatPanel.tsx
│   ├── MessageList.tsx
│   │   ├── MessageBubble.tsx   # 消息气泡
│   │   ├── StreamingMessage.tsx # 实时流式文本
│   │   └── ToolCallCard.tsx    # 工具调用卡片(展开/折叠)
│   ├── ChatInput.tsx           # 输入框 + 发送按钮
│   └── ExamplePrompts.tsx      # 示例提示
└── ViewerPanel.tsx
    ├── ImageViewer.tsx         # 图片预览(缩放/拖拽)
    ├── GifViewer.tsx           # GIF 播放
    ├── HtmlViewer.tsx          # HTML iframe 预览
    ├── CompareSlider.tsx       # 前后对比滑块
    ├── FileThumbnails.tsx      # 底部缩略图条
    └── FileToolbar.tsx         # 下载/全屏/对比按钮
```

### 5.2 状态管理（双层分离）

**服务端状态 → TanStack Query:**
```typescript
// 会话列表
useQuery({ queryKey: ['conversations'], queryFn: api.getConversations })
// 消息历史
useQuery({ queryKey: ['messages', convId], queryFn: () => api.getMessages(convId) })
```

**客户端状态 → Zustand (仅 UI):**
```typescript
interface UIState {
  sidebarOpen: boolean
  viewerMode: 'preview' | 'compare' | 'fullscreen'
  activeFile: OutputFile | null
}
```

### 5.3 SSE Hook

```typescript
function useConversation(convId: number) {
  const [phase, setPhase] = useState<'idle' | 'thinking' | 'executing' | 'done'>('idle')
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([])
  const [answer, setAnswer] = useState('')

  const send = async (content: string) => {
    const res = await fetch(`/api/conversations/${convId}/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content }),
    })
    // 逐帧解析 SSE 事件，更新 phase/toolCalls/answer
  }

  return { phase, toolCalls, answer, send }
}
```

### 5.4 文件结构

```
frontend/src/
├── api/              # API 调用（纯函数，无状态）
│   ├── client.ts     # fetch 封装
│   ├── auth.ts
│   ├── conversations.ts
│   └── files.ts
├── hooks/            # React Hooks
│   ├── useConversation.ts
│   ├── useConversations.ts
│   └── useMessages.ts
├── stores/
│   └── uiStore.ts    # Zustand (仅UI状态)
├── components/
│   ├── layout/       # AppShell, Sidebar, Header
│   ├── chat/         # ChatPanel, MessageList, ChatInput, ToolCallCard
│   ├── viewer/       # ViewerPanel, ImageViewer, CompareSlider
│   └── shared/       # StatusBadge, LoadingSpinner, EmptyState
├── pages/
│   ├── Workspace.tsx
│   ├── Home.tsx
│   └── Login.tsx
└── types/
    ├── conversation.ts
    ├── tool.ts
    └── index.ts
```

## 6. 实施计划

| 阶段 | 内容 | 产出 | 可验证方式 |
|------|------|------|-----------|
| 1. 工具系统重构 | `BaseTool` + `@tool` 装饰器 + 迁移工具 | 新工具系统可运行 | CLI: `python main.py "下载成都LST"` |
| 2. Agent 引擎重写 | `engine.py` + `guard.py` + `llm.py` | 纯 Agent 循环 | CLI 验证 |
| 3. API 层重写 | SSE 流式端点 + ORM 模型 | SSE API | `curl` 验证 SSE 流 |
| 4. 前端重写 | 组件树 + TanStack Query + Zustand + SSE | 新前端 | 浏览器完整交互 |
| 5. 清理 | 删除旧代码，更新文档 | 干净代码库 | — |

**关键约束:**
- `gis/` 层 30+ 模块完全不动
- 每阶段独立可验证
- 阶段 1-3 不影响前端
- 阶段 4 一次性切换

## 7. 设计原则

- 每个文件 < 300 行，单一职责
- 工具通过装饰器自动注册，添加工具 = 新建文件
- Agent 引擎不含任何工具特定逻辑
- 验证规则独立函数，易测试、易修改
- 前端 SSE 统一流式，废弃轮询
- TanStack Query 管服务端数据，Zustand 管 UI 状态
- 组件职责单一，每个 < 200 行
