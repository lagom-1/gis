# 登录页面实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 OpenGIS 实现企业级左右分栏登录页面，支持密码登录、邮箱验证码登录、微信登录

**Architecture:** 前端重构 Login.tsx 为左右分栏布局，新增 BrandPanel 和 LoginForm 组件；后端新增验证码发送和验证端点；第三方登录通过重定向方式实现

**Tech Stack:** React, TypeScript, TailwindCSS, Zustand, FastAPI, SQLAlchemy

---

## 文件结构

### 前端文件

| 文件 | 职责 |
|------|------|
| `frontend/src/types/index.ts` | 添加新类型：`SendCodeRequest`、`LoginWithCodeRequest` |
| `frontend/src/services/auth.ts` | 添加 `sendCode()`、`loginWithCode()`、`getWechatAuthUrl()` |
| `frontend/src/pages/Login.tsx` | 重构为左右分栏布局，整合 BrandPanel + LoginForm |
| `frontend/src/components/auth/BrandPanel.tsx` | 左侧品牌展示区（绿色渐变 + 功能特色） |
| `frontend/src/components/auth/LoginForm.tsx` | 右侧登录表单（密码/验证码切换 + 微信登录） |
| `frontend/src/components/auth/TabSwitcher.tsx` | 登录方式切换标签 |
| `frontend/src/components/auth/PasswordForm.tsx` | 密码登录表单 |
| `frontend/src/components/auth/CodeForm.tsx` | 验证码登录表单 |
| `frontend/src/components/auth/ThirdPartyLogin.tsx` | 第三方登录按钮组 |
| `frontend/src/App.tsx` | 添加 `/login` 和 `/register` 路由 |

### 后端文件

| 文件 | 职责 |
|------|------|
| `api/models.py` | 添加 `SendCodeRequest`、`LoginWithCodeRequest` Pydantic 模型 |
| `api/routers/auth.py` | 添加 `POST /api/auth/send-code`、`POST /api/auth/login-with-code` 端点 |
| `api/services/auth_service.py` | 验证码生成、存储、发送逻辑 |

---

### Task 1: 前端类型和认证服务扩展

**Files:**
- Modify: `frontend/src/types/index.ts`
- Modify: `frontend/src/services/auth.ts`

- [ ] **Step 1: 添加新类型定义**

在 `frontend/src/types/index.ts` 中添加：

```typescript
export interface SendCodeRequest {
  email: string
}

export interface LoginWithCodeRequest {
  email: string
  code: string
}

export interface WechatAuthResponse {
  auth_url: string
}
```

- [ ] **Step 2: 扩展认证服务**

在 `frontend/src/services/auth.ts` 中添加新方法：

```typescript
import type { SendCodeRequest, LoginWithCodeRequest, WechatAuthResponse } from '../types'

export const authService = {
  // ... 现有方法保持不变 ...

  async sendCode(data: SendCodeRequest): Promise<{ message: string }> {
    const response = await api.post('/auth/send-code', data)
    return response.data
  },

  async loginWithCode(data: LoginWithCodeRequest): Promise<AuthResponse> {
    const response = await api.post<AuthResponse>('/auth/login-with-code', data)
    return response.data
  },

  async getWechatAuthUrl(): Promise<WechatAuthResponse> {
    const response = await api.get<WechatAuthResponse>('/auth/wechat')
    return response.data
  },
}
```

- [ ] **Step 3: 验证类型无报错**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 无类型错误

- [ ] **Step 4: 提交**

```bash
git add frontend/src/types/index.ts frontend/src/services/auth.ts
git commit -m "feat: 添加验证码登录和微信登录的类型及服务方法"
```

---

### Task 2: 后端验证码服务和端点

**Files:**
- Create: `api/services/__init__.py`
- Create: `api/services/auth_service.py`
- Modify: `api/models.py`
- Modify: `api/routers/auth.py`

- [ ] **Step 1: 创建验证码服务**

创建 `api/services/__init__.py`（空文件）。

创建 `api/services/auth_service.py`：

```python
"""
验证码服务
- 生成 6 位数字验证码
- 存储到内存（生产环境应使用 Redis）
- 发送邮件（当前仅打印日志）
"""

import random
import time
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 验证码存储（生产环境应使用 Redis）
_code_store: dict[str, tuple[str, float]] = {}

CODE_EXPIRE_SECONDS = 300  # 5 分钟过期


def generate_code(email: str) -> str:
    """生成并存储验证码"""
    code = f"{random.randint(0, 999999):06d}"
    _code_store[email] = (code, time.time() + CODE_EXPIRE_SECONDS)
    logger.info(f"验证码已生成: {email} -> {code}")
    return code


def verify_code(email: str, code: str) -> bool:
    """验证验证码"""
    stored = _code_store.get(email)
    if not stored:
        return False

    stored_code, expire_time = stored
    if time.time() > expire_time:
        del _code_store[email]
        return False

    if stored_code != code:
        return False

    del _code_store[email]
    return True
```

- [ ] **Step 2: 添加 Pydantic 模型**

在 `api/models.py` 中添加：

```python
from pydantic import BaseModel, EmailStr

class SendCodeRequest(BaseModel):
    email: EmailStr

class LoginWithCodeRequest(BaseModel):
    email: EmailStr
    code: str
```

- [ ] **Step 3: 添加验证码端点**

在 `api/routers/auth.py` 中添加：

```python
from api.services.auth_service import generate_code, verify_code
from api.models import SendCodeRequest, LoginWithCodeRequest

@router.post("/send-code", response_model=MessageResponse, summary="发送验证码")
async def send_code(request: SendCodeRequest, db: Session = Depends(get_db)):
    """发送邮箱验证码"""
    # 检查邮箱是否已注册
    user = db.query(User).filter(User.email == request.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="该邮箱未注册")

    code = generate_code(request.email)
    # TODO: 实际发送邮件，当前仅返回成功
    logger.info(f"验证码发送至 {request.email}: {code}")
    return MessageResponse(success=True, message="验证码已发送")


@router.post("/login-with-code", response_model=TokenResponse, summary="验证码登录")
async def login_with_code(request: LoginWithCodeRequest, db: Session = Depends(get_db)):
    """使用邮箱验证码登录"""
    if not verify_code(request.email, request.code):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="验证码无效或已过期",
        )

    user = db.query(User).filter(User.email == request.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="该邮箱未注册")

    access_token = create_access_token(
        data={"sub": str(user.id), "username": user.username},
        expires_delta=timedelta(minutes=config.JWT_EXPIRE_MINUTES),
    )

    return TokenResponse(
        access_token=access_token,
        expires_in=config.JWT_EXPIRE_MINUTES * 60,
    )
```

- [ ] **Step 4: 验证后端启动**

```bash
cd D:\opengis
python -c "from api.services.auth_service import generate_code, verify_code; print('OK')"
```

Expected: `OK`

- [ ] **Step 5: 提交**

```bash
git add api/services/ api/models.py api/routers/auth.py
git commit -m "feat: 添加验证码登录端点和验证码服务"
```

---

### Task 3: BrandPanel 组件

**Files:**
- Create: `frontend/src/components/auth/BrandPanel.tsx`

- [ ] **Step 1: 创建 BrandPanel 组件**

```tsx
/**
 * 登录页左侧品牌展示区
 * 绿色渐变背景 + OpenGIS 品牌 + 功能特色
 */
export default function BrandPanel() {
  const features = [
    '智能温度反演与热岛分析',
    '多时相变化检测',
    '自然语言交互式分析',
  ]

  return (
    <div className="hidden lg:flex flex-col justify-center px-12 py-16 bg-gradient-to-br from-emerald-600 to-emerald-500 text-white relative overflow-hidden">
      {/* 装饰性光晕 */}
      <div className="absolute top-0 right-0 w-64 h-64 bg-white/10 rounded-full -translate-y-1/3 translate-x-1/3" />
      <div className="absolute bottom-0 left-0 w-48 h-48 bg-white/5 rounded-full translate-y-1/3 -translate-x-1/4" />

      <div className="relative z-10">
        <h1 className="text-3xl font-bold mb-4">OpenGIS</h1>
        <p className="text-lg text-emerald-100 mb-10 leading-relaxed">
          从卫星影像到决策洞察
          <br />
          只需一句自然语言
        </p>

        <div className="space-y-4">
          {features.map((feature) => (
            <div key={feature} className="flex items-center gap-3">
              <div className="w-6 h-6 bg-white/20 rounded-full flex items-center justify-center text-xs">
                ✓
              </div>
              <span className="text-sm text-emerald-50">{feature}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: 验证组件无类型错误**

```bash
cd frontend && npx tsc --noEmit
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/auth/BrandPanel.tsx
git commit -m "feat: 添加登录页品牌展示区组件"
```

---

### Task 4: TabSwitcher 组件

**Files:**
- Create: `frontend/src/components/auth/TabSwitcher.tsx`

- [ ] **Step 1: 创建 TabSwitcher 组件**

```tsx
type LoginTab = 'password' | 'code'

interface TabSwitcherProps {
  activeTab: LoginTab
  onTabChange: (tab: LoginTab) => void
}

/**
 * 登录方式切换标签
 * 支持密码登录和验证码登录两种模式
 */
export default function TabSwitcher({ activeTab, onTabChange }: TabSwitcherProps) {
  const tabs: { key: LoginTab; label: string }[] = [
    { key: 'password', label: '密码登录' },
    { key: 'code', label: '验证码登录' },
  ]

  return (
    <div className="flex gap-2 mb-6">
      {tabs.map((tab) => (
        <button
          key={tab.key}
          onClick={() => onTabChange(tab.key)}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors ${
            activeTab === tab.key
              ? 'bg-emerald-600 text-white'
              : 'bg-stone-100 text-stone-500 hover:text-stone-700'
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  )
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/components/auth/TabSwitcher.tsx
git commit -m "feat: 添加登录方式切换标签组件"
```

---

### Task 5: PasswordForm 组件

**Files:**
- Create: `frontend/src/components/auth/PasswordForm.tsx`

- [ ] **Step 1: 创建 PasswordForm 组件**

```tsx
import { useState, type FormEvent } from 'react'
import { Loader2 } from 'lucide-react'

interface PasswordFormProps {
  onSubmit: (username: string, password: string) => Promise<void>
  isLoading: boolean
  error: string
}

/**
 * 密码登录表单
 */
export default function PasswordForm({ onSubmit, isLoading, error }: PasswordFormProps) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')

  const canSubmit = username.trim() && password.trim() && !isLoading

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (canSubmit) onSubmit(username.trim(), password)
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-stone-700 mb-1.5">
          邮箱地址
        </label>
        <input
          type="email"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="请输入邮箱"
          className="w-full px-4 py-2.5 border border-stone-200 rounded-lg text-sm
                     focus:ring-2 focus:ring-emerald-500 focus:border-transparent
                     outline-none transition"
          autoFocus
        />
      </div>

      <div>
        <div className="flex items-center justify-between mb-1.5">
          <label className="block text-sm font-medium text-stone-700">密码</label>
          <button type="button" className="text-xs text-emerald-600 hover:underline">
            忘记密码？
          </button>
        </div>
        <input
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          placeholder="请输入密码"
          className="w-full px-4 py-2.5 border border-stone-200 rounded-lg text-sm
                     focus:ring-2 focus:ring-emerald-500 focus:border-transparent
                     outline-none transition"
        />
      </div>

      {error && (
        <div className="text-red-600 text-sm bg-red-50 rounded-lg px-4 py-2.5">
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={!canSubmit}
        className="w-full py-2.5 bg-emerald-600 text-white rounded-lg text-sm font-medium
                   hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed
                   transition flex items-center justify-center gap-2"
      >
        {isLoading && <Loader2 className="w-4 h-4 animate-spin" />}
        {isLoading ? '登录中...' : '登录'}
      </button>
    </form>
  )
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/components/auth/PasswordForm.tsx
git commit -m "feat: 添加密码登录表单组件"
```

---

### Task 6: CodeForm 组件

**Files:**
- Create: `frontend/src/components/auth/CodeForm.tsx`

- [ ] **Step 1: 创建 CodeForm 组件**

```tsx
import { useState, useEffect, type FormEvent } from 'react'
import { Loader2 } from 'lucide-react'
import { authService } from '../../services/auth'

interface CodeFormProps {
  onSubmit: (email: string, code: string) => Promise<void>
  isLoading: boolean
  error: string
}

/**
 * 验证码登录表单
 */
export default function CodeForm({ onSubmit, isLoading, error }: CodeFormProps) {
  const [email, setEmail] = useState('')
  const [code, setCode] = useState('')
  const [countdown, setCountdown] = useState(0)
  const [sendLoading, setSendLoading] = useState(false)
  const [sendError, setSendError] = useState('')

  const canSubmit = email.trim() && code.trim() && !isLoading
  const canSendCode = email.trim() && countdown === 0 && !sendLoading

  useEffect(() => {
    if (countdown <= 0) return
    const timer = setTimeout(() => setCountdown(countdown - 1), 1000)
    return () => clearTimeout(timer)
  }, [countdown])

  const handleSendCode = async () => {
    if (!canSendCode) return
    setSendLoading(true)
    setSendError('')
    try {
      await authService.sendCode({ email: email.trim() })
      setCountdown(60)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : '发送失败'
      setSendError(msg)
    } finally {
      setSendLoading(false)
    }
  }

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault()
    if (canSubmit) onSubmit(email.trim(), code.trim())
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-sm font-medium text-stone-700 mb-1.5">
          邮箱地址
        </label>
        <input
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="请输入邮箱"
          className="w-full px-4 py-2.5 border border-stone-200 rounded-lg text-sm
                     focus:ring-2 focus:ring-emerald-500 focus:border-transparent
                     outline-none transition"
          autoFocus
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-stone-700 mb-1.5">
          验证码
        </label>
        <div className="flex gap-2">
          <input
            type="text"
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder="请输入 6 位验证码"
            maxLength={6}
            className="flex-1 px-4 py-2.5 border border-stone-200 rounded-lg text-sm
                       focus:ring-2 focus:ring-emerald-500 focus:border-transparent
                       outline-none transition"
          />
          <button
            type="button"
            onClick={handleSendCode}
            disabled={!canSendCode}
            className="px-4 py-2.5 bg-emerald-600 text-white rounded-lg text-sm font-medium
                       hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed
                       transition whitespace-nowrap"
          >
            {sendLoading ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : countdown > 0 ? (
              `${countdown}s`
            ) : (
              '发送验证码'
            )}
          </button>
        </div>
        {sendError && (
          <p className="text-red-500 text-xs mt-1">{sendError}</p>
        )}
      </div>

      {error && (
        <div className="text-red-600 text-sm bg-red-50 rounded-lg px-4 py-2.5">
          {error}
        </div>
      )}

      <button
        type="submit"
        disabled={!canSubmit}
        className="w-full py-2.5 bg-emerald-600 text-white rounded-lg text-sm font-medium
                   hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed
                   transition flex items-center justify-center gap-2"
      >
        {isLoading && <Loader2 className="w-4 h-4 animate-spin" />}
        {isLoading ? '登录中...' : '登录'}
      </button>
    </form>
  )
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/components/auth/CodeForm.tsx
git commit -m "feat: 添加验证码登录表单组件"
```

---

### Task 7: ThirdPartyLogin 组件

**Files:**
- Create: `frontend/src/components/auth/ThirdPartyLogin.tsx`

- [ ] **Step 1: 创建 ThirdPartyLogin 组件**

```tsx
/**
 * 第三方登录按钮组
 * 当前支持微信登录
 */
export default function ThirdPartyLogin() {
  const handleWechatLogin = () => {
    // TODO: 实现微信 OAuth 跳转
    window.location.href = '/api/auth/wechat'
  }

  return (
    <div className="mt-6">
      <div className="relative">
        <div className="absolute inset-0 flex items-center">
          <div className="w-full border-t border-stone-200" />
        </div>
        <div className="relative flex justify-center text-xs">
          <span className="bg-white px-3 text-stone-400">或使用以下方式登录</span>
        </div>
      </div>

      <div className="flex justify-center mt-4">
        <button
          onClick={handleWechatLogin}
          className="flex flex-col items-center gap-1.5 group"
          title="微信登录"
        >
          <div className="w-11 h-11 bg-[#07c160] rounded-xl flex items-center justify-center
                          text-white text-sm font-medium group-hover:opacity-90 transition">
            微
          </div>
          <span className="text-[11px] text-stone-400">微信</span>
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/components/auth/ThirdPartyLogin.tsx
git commit -m "feat: 添加第三方登录按钮组组件"
```

---

### Task 8: LoginForm 组件（整合）

**Files:**
- Create: `frontend/src/components/auth/LoginForm.tsx`

- [ ] **Step 1: 创建 LoginForm 组件**

```tsx
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAppStore } from '../../stores/appStore'
import TabSwitcher from './TabSwitcher'
import PasswordForm from './PasswordForm'
import CodeForm from './CodeForm'
import ThirdPartyLogin from './ThirdPartyLogin'

type LoginTab = 'password' | 'code'

/**
 * 登录表单区域
 * 整合密码登录、验证码登录、第三方登录
 */
export default function LoginForm() {
  const navigate = useNavigate()
  const login = useAppStore((s) => s.login)

  const [activeTab, setActiveTab] = useState<LoginTab>('password')
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState('')

  const handlePasswordLogin = async (username: string, password: string) => {
    setIsLoading(true)
    setError('')
    const ok = await login(username, password)
    setIsLoading(false)
    if (ok) {
      navigate('/gallery')
    } else {
      setError('登录失败，请检查邮箱和密码')
    }
  }

  const handleCodeLogin = async (email: string, code: string) => {
    setIsLoading(true)
    setError('')
    try {
      const { authService } = await import('../../services/auth')
      const res = await authService.loginWithCode({ email, code })
      localStorage.setItem('token', res.access_token)
      // 刷新用户信息后跳转
      window.location.href = '/gallery'
    } catch {
      setError('验证码无效或已过期')
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="flex flex-col justify-center px-8 sm:px-12 lg:px-16 py-12">
      <div className="w-full max-w-sm mx-auto">
        <h2 className="text-2xl font-semibold text-stone-900 mb-1">欢迎回来</h2>
        <p className="text-sm text-stone-500 mb-8">登录以继续使用 OpenGIS</p>

        <TabSwitcher activeTab={activeTab} onTabChange={setActiveTab} />

        {activeTab === 'password' ? (
          <PasswordForm
            onSubmit={handlePasswordLogin}
            isLoading={isLoading}
            error={error}
          />
        ) : (
          <CodeForm
            onSubmit={handleCodeLogin}
            isLoading={isLoading}
            error={error}
          />
        )}

        <ThirdPartyLogin />

        <p className="text-center text-sm text-stone-500 mt-8">
          还没有账号？{' '}
          <Link
            to="/register"
            className="text-emerald-600 hover:underline font-medium"
          >
            立即注册
          </Link>
        </p>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: 提交**

```bash
git add frontend/src/components/auth/LoginForm.tsx
git commit -m "feat: 添加登录表单整合组件"
```

---

### Task 9: 重构 Login 页面

**Files:**
- Modify: `frontend/src/pages/Login.tsx`

- [ ] **Step 1: 重写 Login 页面**

```tsx
import BrandPanel from '../components/auth/BrandPanel'
import LoginForm from '../components/auth/LoginForm'

/**
 * 登录页面
 * 左右分栏布局：左侧品牌展示 + 右侧登录表单
 */
export default function Login() {
  return (
    <div className="min-h-screen bg-stone-50 flex">
      {/* 左侧品牌区 */}
      <BrandPanel />

      {/* 右侧表单区 */}
      <div className="flex-1 flex items-center justify-center p-6">
        <LoginForm />
      </div>
    </div>
  )
}
```

- [ ] **Step 2: 添加路由到 App.tsx**

在 `frontend/src/App.tsx` 中添加登录和注册路由（在 Layout 路由之外）：

```tsx
import Login from './pages/Login'
import Register from './pages/Register'

export default function App() {
  return (
    <Routes>
      {/* 登录/注册页面 - 独立布局 */}
      <Route path="/login" element={<Login />} />
      <Route path="/register" element={<Register />} />

      {/* 主应用 - Layout 布局 */}
      <Route path="/" element={<Layout />}>
        {/* ... 现有路由保持不变 ... */}
      </Route>
    </Routes>
  )
}
```

- [ ] **Step 3: 验证页面渲染**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 无类型错误

- [ ] **Step 4: 提交**

```bash
git add frontend/src/pages/Login.tsx frontend/src/App.tsx
git commit -m "feat: 重构登录页面为左右分栏布局并添加路由"
```

---

### Task 10: 响应式适配和动画

**Files:**
- Modify: `frontend/src/components/auth/BrandPanel.tsx`
- Modify: `frontend/src/components/auth/LoginForm.tsx`
- Modify: `frontend/src/pages/Login.tsx`

- [ ] **Step 1: 移动端品牌区简化**

更新 `BrandPanel.tsx`，添加移动端顶部横幅：

```tsx
/**
 * 登录页品牌展示区
 * 桌面端：左侧完整展示
 * 移动端：顶部简化横幅
 */
export default function BrandPanel() {
  const features = [
    '智能温度反演与热岛分析',
    '多时相变化检测',
    '自然语言交互式分析',
  ]

  return (
    <>
      {/* 移动端顶部横幅 */}
      <div className="lg:hidden bg-gradient-to-r from-emerald-600 to-emerald-500 text-white py-6 px-6 text-center">
        <h1 className="text-xl font-bold">OpenGIS</h1>
        <p className="text-xs text-emerald-100 mt-1">AI 遥感分析平台</p>
      </div>

      {/* 桌面端左侧完整展示 */}
      <div className="hidden lg:flex flex-col justify-center px-12 py-16 bg-gradient-to-br from-emerald-600 to-emerald-500 text-white relative overflow-hidden">
        <div className="absolute top-0 right-0 w-64 h-64 bg-white/10 rounded-full -translate-y-1/3 translate-x-1/3" />
        <div className="absolute bottom-0 left-0 w-48 h-48 bg-white/5 rounded-full translate-y-1/3 -translate-x-1/4" />

        <div className="relative z-10">
          <h1 className="text-3xl font-bold mb-4">OpenGIS</h1>
          <p className="text-lg text-emerald-100 mb-10 leading-relaxed">
            从卫星影像到决策洞察
            <br />
            只需一句自然语言
          </p>

          <div className="space-y-4">
            {features.map((feature) => (
              <div key={feature} className="flex items-center gap-3">
                <div className="w-6 h-6 bg-white/20 rounded-full flex items-center justify-center text-xs">
                  ✓
                </div>
                <span className="text-sm text-emerald-50">{feature}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </>
  )
}
```

- [ ] **Step 2: 添加页面加载动画**

更新 `Login.tsx`，添加淡入动画：

```tsx
import BrandPanel from '../components/auth/BrandPanel'
import LoginForm from '../components/auth/LoginForm'

export default function Login() {
  return (
    <div className="min-h-screen bg-stone-50 flex flex-col lg:flex-row animate-in fade-in duration-300">
      <BrandPanel />
      <div className="flex-1 flex items-center justify-center p-6">
        <LoginForm />
      </div>
    </div>
  )
}
```

- [ ] **Step 3: 验证响应式布局**

在浏览器中测试：
- 桌面端 (>1024px)：左右分栏
- 移动端 (<768px)：上下布局

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components/auth/BrandPanel.tsx frontend/src/pages/Login.tsx
git commit -m "feat: 添加响应式适配和页面动画效果"
```

---

### Task 11: 清理旧代码和最终验证

**Files:**
- Delete: `frontend/src/components/auth/` 目录下不需要的文件（如有）
- Verify: 所有文件类型检查通过

- [ ] **Step 1: 清理旧的 Login 组件残留**

检查是否有旧的登录相关组件需要清理。当前 `Login.tsx` 已完全重写，无需额外清理。

- [ ] **Step 2: 全量类型检查**

```bash
cd frontend && npx tsc --noEmit
```

Expected: 无类型错误

- [ ] **Step 3: 启动开发服务器验证**

```bash
cd frontend && npm run dev
```

在浏览器中访问 `http://localhost:5173/login`，验证：
- 左右分栏布局正确
- 密码/验证码切换正常
- 表单验证和错误提示正常
- 响应式布局适配正确
- 微信登录按钮显示正确

- [ ] **Step 4: 最终提交**

```bash
git add -A
git commit -m "feat: 完成登录页面重构，支持密码/验证码/微信登录"
```
