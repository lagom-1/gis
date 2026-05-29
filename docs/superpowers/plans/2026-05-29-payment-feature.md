# 收费功能实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 OpenGIS 实现下载收费功能，支持分享免费下载（每周 3 次）和微信扫码付费下载

**Architecture:** 后端新增分享记录表和支付记录表，前端新增 PaymentModal 组件，通过 API 接口控制下载权限

**Tech Stack:** React, TypeScript, TailwindCSS, Zustand, FastAPI, SQLAlchemy, SQLite

---

## 文件结构

### 后端文件

| 文件 | 职责 |
|------|------|
| `api/models.py` | 添加 ShareRecord、PaymentRecord 模型 |
| `api/routers/downloads.py` | 添加检查权限、记录分享、创建支付端点 |
| `api/services/payment_service.py` | 添加价格计算逻辑 |

### 前端文件

| 文件 | 职责 |
|------|------|
| `frontend/src/components/PaymentModal.tsx` | 收费弹窗组件 |
| `frontend/src/components/DownloadButton.tsx` | 修改下载按钮，触发收费弹窗 |
| `frontend/public/qrcode.jpg` | 微信收款码图片 |

---

### Task 1: 数据库模型

**Files:**
- Modify: `api/models.py`

- [ ] **Step 1: 添加分享记录模型**

在 `api/models.py` 的 `Download` 类之后添加：

```python
class ShareRecord(Base):
    """分享记录表"""
    __tablename__ = "share_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    shared_at = Column(DateTime, server_default=func.now(), nullable=False)
    week_number = Column(Integer, nullable=False, comment="ISO 周数")
    year = Column(Integer, nullable=False, comment="年份")

    # 关系
    user = relationship("User")
    task = relationship("Task")


class PaymentRecord(Base):
    """支付记录表"""
    __tablename__ = "payment_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    task_id = Column(Integer, ForeignKey("tasks.id"), nullable=False, index=True)
    amount_yuan = Column(Float, nullable=False, comment="金额（元）")
    status = Column(String(20), default="pending", nullable=False, comment="pending/paid/cancelled")
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    paid_at = Column(DateTime, nullable=True, comment="支付时间")
    confirmed_at = Column(DateTime, nullable=True, comment="确认时间")

    # 关系
    user = relationship("User")
    task = relationship("Task")
```

- [ ] **Step 2: 添加 Pydantic 模型**

在 `api/models.py` 的 Pydantic 模型部分添加：

```python
class ShareRecordResponse(BaseModel):
    """分享记录响应"""
    id: int
    user_id: int
    task_id: int
    shared_at: datetime
    week_number: int
    year: int

    model_config = {"from_attributes": True}


class PaymentRecordResponse(BaseModel):
    """支付记录响应"""
    id: int
    user_id: int
    task_id: int
    amount_yuan: float
    status: str
    created_at: datetime
    paid_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class DownloadPermissionResponse(BaseModel):
    """下载权限响应"""
    can_download: bool
    download_type: Optional[str] = None  # share/payment
    share_remaining: int
    price_yuan: float
    payment_status: Optional[str] = None


class ShareRequest(BaseModel):
    """分享请求"""
    task_id: int


class PaymentCreateRequest(BaseModel):
    """创建支付请求"""
    task_id: int


class PaymentConfirmRequest(BaseModel):
    """确认支付请求"""
    payment_id: int
```

- [ ] **Step 3: 验证模型导入**

```bash
conda run -n gdal_env python -c "from api.models import ShareRecord, PaymentRecord; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: 提交**

```bash
git add api/models.py
git commit -m "feat: 添加分享记录和支付记录数据模型"
```

---

### Task 2: 价格计算服务

**Files:**
- Modify: `api/services/payment_service.py`

- [ ] **Step 1: 添加价格计算函数**

在 `api/services/payment_service.py` 末尾添加：

```python
def calculate_price(task: Task) -> float:
    """
    根据任务的 API token 消耗计算价格

    公式：token 费用 × 2 倍
    最低 1 元，最高 100 元
    """
    # 估算 token 消耗（基于输入文本长度）
    input_tokens = len(task.input_text) * 2  # 粗略估算
    output_tokens = 1000  # 假设输出约 1000 tokens

    # DeepSeek 价格：约 0.001 元/1000 tokens
    token_cost = (input_tokens + output_tokens) / 1000 * 0.001

    # 应用倍数
    price = token_cost * 2

    # 限制范围
    price = max(1.0, min(100.0, price))

    # 保留两位小数
    return round(price, 2)


def get_share_count(db: Session, user_id: int) -> int:
    """获取用户本周的分享次数"""
    from datetime import datetime
    now = datetime.now()
    week_number = now.isocalendar()[1]
    year = now.year

    count = db.query(ShareRecord).filter(
        ShareRecord.user_id == user_id,
        ShareRecord.week_number == week_number,
        ShareRecord.year == year,
    ).count()

    return count


def check_download_permission(db: Session, user_id: int, task_id: int) -> dict:
    """
    检查用户是否有下载权限

    返回：
    - can_download: 是否可以下载
    - download_type: 下载类型（share/payment/None）
    - share_remaining: 剩余分享次数
    - price_yuan: 价格
    - payment_status: 支付状态
    """
    from datetime import datetime

    # 检查是否已有付费记录
    payment = db.query(PaymentRecord).filter(
        PaymentRecord.user_id == user_id,
        PaymentRecord.task_id == task_id,
        PaymentRecord.status == "paid",
    ).first()

    if payment:
        return {
            "can_download": True,
            "download_type": "payment",
            "share_remaining": 3 - get_share_count(db, user_id),
            "price_yuan": payment.amount_yuan,
            "payment_status": "paid",
        }

    # 检查分享次数
    share_count = get_share_count(db, user_id)
    share_remaining = max(0, 3 - share_count)

    # 计算价格
    task = db.query(Task).filter(Task.id == task_id).first()
    price = calculate_price(task) if task else 1.0

    return {
        "can_download": share_remaining > 0,
        "download_type": "share" if share_remaining > 0 else "payment",
        "share_remaining": share_remaining,
        "price_yuan": price,
        "payment_status": None,
    }
```

- [ ] **Step 2: 添加 ShareRecord 导入**

在文件顶部的导入部分添加：

```python
from api.models import Order, OrderStatus, PaymentRecord, ShareRecord, Task, TaskStatus, User
```

- [ ] **Step 3: 验证函数**

```bash
conda run -n gdal_env python -c "from api.services.payment_service import calculate_price, check_download_permission; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: 提交**

```bash
git add api/services/payment_service.py
git commit -m "feat: 添加价格计算和下载权限检查服务"
```

---

### Task 3: 下载权限 API

**Files:**
- Modify: `api/routers/downloads.py`

- [ ] **Step 1: 添加检查权限端点**

在 `api/routers/downloads.py` 中添加：

```python
@router.get("/{task_id}/check-permission", summary="检查下载权限")
async def check_permission(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """检查用户是否有下载权限"""
    # 验证任务属于当前用户
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.user_id == current_user.id,
    ).first()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    from api.services.payment_service import check_download_permission
    result = check_download_permission(db, current_user.id, task_id)
    return result


@router.post("/{task_id}/share", summary="记录分享")
async def record_share(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录用户分享并返回下载链接"""
    from datetime import datetime
    from api.services.payment_service import get_share_count, check_download_permission

    # 验证任务属于当前用户
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.user_id == current_user.id,
    ).first()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 检查分享次数
    permission = check_download_permission(db, current_user.id, task_id)
    if not permission["can_download"] or permission["download_type"] != "share":
        raise HTTPException(status_code=403, detail="本周免费下载次数已用完")

    # 记录分享
    now = datetime.now()
    share_record = ShareRecord(
        user_id=current_user.id,
        task_id=task_id,
        week_number=now.isocalendar()[1],
        year=now.year,
    )
    db.add(share_record)
    db.commit()

    return {
        "success": True,
        "message": "分享成功，开始下载",
        "share_remaining": permission["share_remaining"] - 1,
    }


@router.post("/{task_id}/payment", summary="创建支付记录")
async def create_payment(
    task_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建支付记录"""
    from api.services.payment_service import calculate_price

    # 验证任务属于当前用户
    task = db.query(Task).filter(
        Task.id == task_id,
        Task.user_id == current_user.id,
    ).first()
    if task is None:
        raise HTTPException(status_code=404, detail="任务不存在")

    # 检查是否已有待支付记录
    existing = db.query(PaymentRecord).filter(
        PaymentRecord.user_id == current_user.id,
        PaymentRecord.task_id == task_id,
        PaymentRecord.status == "pending",
    ).first()

    if existing:
        return {
            "success": True,
            "payment_id": existing.id,
            "amount_yuan": existing.amount_yuan,
            "message": "请扫码支付后点击「我已支付」",
        }

    # 创建新记录
    price = calculate_price(task)
    payment = PaymentRecord(
        user_id=current_user.id,
        task_id=task_id,
        amount_yuan=price,
        status="pending",
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    return {
        "success": True,
        "payment_id": payment.id,
        "amount_yuan": price,
        "message": "请扫码支付后点击「我已支付」",
    }


@router.post("/confirm-payment", summary="确认支付（管理员）")
async def confirm_payment(
    request: PaymentConfirmRequest,
    db: Session = Depends(get_db),
):
    """管理员确认支付"""
    payment = db.query(PaymentRecord).filter(
        PaymentRecord.id == request.payment_id,
    ).first()

    if payment is None:
        raise HTTPException(status_code=404, detail="支付记录不存在")

    if payment.status != "pending":
        raise HTTPException(status_code=400, detail="支付状态异常")

    from datetime import datetime
    payment.status = "paid"
    payment.paid_at = datetime.now()
    payment.confirmed_at = datetime.now()
    db.commit()

    return {
        "success": True,
        "message": "支付已确认，可以下载",
    }
```

- [ ] **Step 2: 添加导入**

在文件顶部添加：

```python
from api.models import Download, Order, OrderStatus, PaymentRecord, ShareRecord, Task, TaskStatus, User
```

同时添加请求模型：

```python
class PaymentConfirmRequest(BaseModel):
    """确认支付请求"""
    payment_id: int
```

- [ ] **Step 3: 验证端点**

```bash
conda run -n gdal_env python -c "from api.routers.downloads import router; print('OK')"
```

Expected: `OK`

- [ ] **Step 4: 提交**

```bash
git add api/routers/downloads.py
git commit -m "feat: 添加下载权限检查、分享记录和支付确认端点"
```

---

### Task 4: 微信收款码图片

**Files:**
- Copy: `D:\推文\收费.jpg` → `frontend/public/qrcode.jpg`

- [ ] **Step 1: 复制收款码图片**

```bash
cp "D:\推文\收费.jpg" "D:\opengis\frontend\public\qrcode.jpg"
```

- [ ] **Step 2: 验证文件存在**

```bash
ls -la "D:\opengis\frontend\public\qrcode.jpg"
```

Expected: 文件存在，大小约 149KB

- [ ] **Step 3: 提交**

```bash
git add frontend/public/qrcode.jpg
git commit -m "feat: 添加微信收款码图片"
```

---

### Task 5: PaymentModal 组件

**Files:**
- Create: `frontend/src/components/PaymentModal.tsx`

- [ ] **Step 1: 创建 PaymentModal 组件**

```tsx
import { useState, useEffect } from 'react'
import { X, Copy, Check, Loader2 } from 'lucide-react'
import api from '../services/api'

interface PaymentModalProps {
  isOpen: boolean
  onClose: () => void
  taskId: number
  onDownload: () => void
}

interface PermissionData {
  can_download: boolean
  download_type: string | null
  share_remaining: number
  price_yuan: number
  payment_status: string | null
}

export default function PaymentModal({ isOpen, onClose, taskId, onDownload }: PaymentModalProps) {
  const [permission, setPermission] = useState<PermissionData | null>(null)
  const [copied, setCopied] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)
  const [error, setError] = useState('')
  const [paymentId, setPaymentId] = useState<number | null>(null)

  const githubUrl = 'https://github.com/lagom-1/gis/tree/master'

  useEffect(() => {
    if (isOpen) {
      checkPermission()
    }
  }, [isOpen, taskId])

  const checkPermission = async () => {
    try {
      const res = await api.get(`/downloads/${taskId}/check-permission`)
      setPermission(res.data)
    } catch {
      setError('检查权限失败')
    }
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(githubUrl)
      setCopied(true)
    } catch {
      //  fallback
      const input = document.createElement('input')
      input.value = githubUrl
      document.body.appendChild(input)
      input.select()
      document.execCommand('copy')
      document.body.removeChild(input)
      setCopied(true)
    }
  }

  const handleShare = async () => {
    setIsProcessing(true)
    setError('')
    try {
      await api.post(`/downloads/${taskId}/share`)
      onDownload()
      onClose()
    } catch (err: any) {
      setError(err.response?.data?.detail || '分享失败')
    } finally {
      setIsProcessing(false)
    }
  }

  const handleCreatePayment = async () => {
    setIsProcessing(true)
    setError('')
    try {
      const res = await api.post(`/downloads/${taskId}/payment`)
      setPaymentId(res.data.payment_id)
    } catch (err: any) {
      setError(err.response?.data?.detail || '创建支付失败')
    } finally {
      setIsProcessing(false)
    }
  }

  const handleConfirmPayment = async () => {
    if (!paymentId) return
    setIsProcessing(true)
    setError('')
    try {
      await api.post('/downloads/confirm-payment', { payment_id: paymentId })
      onDownload()
      onClose()
    } catch (err: any) {
      setError(err.response?.data?.detail || '确认失败，请稍后再试')
    } finally {
      setIsProcessing(false)
    }
  }

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-xl shadow-xl max-w-2xl w-full mx-4 overflow-hidden">
        {/* 头部 */}
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h3 className="text-lg font-semibold text-stone-900">下载文件</h3>
          <button onClick={onClose} className="text-stone-400 hover:text-stone-600">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* 内容区 */}
        <div className="flex flex-col md:flex-row">
          {/* 左侧：分享免费下载 */}
          <div className="flex-1 p-6 border-r border-stone-200">
            <div className="text-center">
              <div className="w-12 h-12 bg-emerald-50 rounded-full flex items-center justify-center mx-auto mb-4">
                <span className="text-2xl">🔗</span>
              </div>
              <h4 className="font-semibold text-stone-900 mb-2">分享免费下载</h4>
              <p className="text-sm text-stone-500 mb-6">
                分享 OpenGIS 项目到 GitHub<br />
                即可免费下载 1 次
              </p>

              {/* GitHub 链接 */}
              <div className="bg-stone-50 rounded-lg p-3 mb-4">
                <div className="text-xs text-stone-400 mb-2">项目链接</div>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={githubUrl}
                    readOnly
                    className="flex-1 px-3 py-2 border border-stone-200 rounded-md text-xs bg-white"
                  />
                  <button
                    onClick={handleCopy}
                    className="px-3 py-2 bg-emerald-600 text-white rounded-md text-xs hover:bg-emerald-700 transition"
                  >
                    {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                  </button>
                </div>
              </div>

              {/* 我已分享按钮 */}
              <button
                onClick={handleShare}
                disabled={!copied || isProcessing || permission?.download_type !== 'share'}
                className="w-full py-2.5 bg-emerald-600 text-white rounded-lg font-medium hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed transition flex items-center justify-center gap-2"
              >
                {isProcessing ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                {isProcessing ? '处理中...' : '✓ 我已分享，下载文件'}
              </button>

              <div className="text-xs text-stone-400 mt-3">
                本周剩余 {permission?.share_remaining ?? 3}/3 次免费下载
              </div>
            </div>
          </div>

          {/* 右侧：付费下载 */}
          <div className="flex-1 p-6">
            <div className="text-center">
              <div className="w-12 h-12 bg-amber-50 rounded-full flex items-center justify-center mx-auto mb-4">
                <span className="text-2xl">💰</span>
              </div>
              <h4 className="font-semibold text-stone-900 mb-2">付费下载</h4>
              <p className="text-sm text-stone-500 mb-6">
                扫码支付后即可下载<br />
                支持微信支付
              </p>

              {/* 价格显示 */}
              <div className="bg-amber-50 rounded-lg p-4 mb-4">
                <div className="text-xs text-amber-700 mb-1">本次下载费用</div>
                <div className="text-3xl font-bold text-amber-600">
                  ¥{permission?.price_yuan?.toFixed(2) ?? '1.00'}
                </div>
              </div>

              {/* 微信收款码 */}
              <div className="bg-stone-50 rounded-lg p-4 mb-4">
                <div className="text-xs text-stone-400 mb-3">微信扫码支付</div>
                <div className="w-32 h-32 bg-white border border-stone-200 rounded-lg mx-auto overflow-hidden">
                  <img
                    src="/qrcode.jpg"
                    alt="微信收款码"
                    className="w-full h-full object-contain"
                  />
                </div>
              </div>

              {/* 按钮区域 */}
              {!paymentId ? (
                <button
                  onClick={handleCreatePayment}
                  disabled={isProcessing}
                  className="w-full py-2.5 bg-amber-500 text-white rounded-lg font-medium hover:bg-amber-600 disabled:opacity-50 disabled:cursor-not-allowed transition flex items-center justify-center gap-2"
                >
                  {isProcessing ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                  {isProcessing ? '处理中...' : '我已支付，下载文件'}
                </button>
              ) : (
                <button
                  onClick={handleConfirmPayment}
                  disabled={isProcessing}
                  className="w-full py-2.5 bg-amber-500 text-white rounded-lg font-medium hover:bg-amber-600 disabled:opacity-50 disabled:cursor-not-allowed transition flex items-center justify-center gap-2"
                >
                  {isProcessing ? <Loader2 className="w-4 h-4 animate-spin" /> : null}
                  {isProcessing ? '确认中...' : '✓ 我已支付，确认下载'}
                </button>
              )}

              <div className="text-xs text-stone-400 mt-3">
                支付后请稍等片刻，系统将自动确认
              </div>
            </div>
          </div>
        </div>

        {/* 错误提示 */}
        {error && (
          <div className="px-6 py-3 bg-red-50 border-t border-red-100">
            <p className="text-sm text-red-600 text-center">{error}</p>
          </div>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: 验证组件无类型错误**

```bash
cd frontend && npx tsc --noEmit 2>&1 | grep -i PaymentModal
```

Expected: 无错误

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/PaymentModal.tsx
git commit -m "feat: 添加收费弹窗组件"
```

---

### Task 6: 修改下载按钮

**Files:**
- Modify: `frontend/src/components/DownloadButton.tsx`

- [ ] **Step 1: 读取现有 DownloadButton**

```bash
cat frontend/src/components/DownloadButton.tsx
```

- [ ] **Step 2: 修改 DownloadButton 集成 PaymentModal**

```tsx
import { useState } from 'react'
import { Download } from 'lucide-react'
import PaymentModal from './PaymentModal'

interface DownloadButtonProps {
  taskId: number
  filename?: string
  className?: string
}

export default function DownloadButton({ taskId, filename, className }: DownloadButtonProps) {
  const [showModal, setShowModal] = useState(false)

  const handleDownload = () => {
    // 触发下载逻辑
    if (filename) {
      const url = `/api/downloads/serve/${taskId}/${encodeURIComponent(filename)}?token=${localStorage.getItem('token')}`
      window.open(url, '_blank')
    }
  }

  return (
    <>
      <button
        onClick={() => setShowModal(true)}
        className={className || 'px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition flex items-center gap-2'}
      >
        <Download className="w-4 h-4" />
        下载
      </button>

      <PaymentModal
        isOpen={showModal}
        onClose={() => setShowModal(false)}
        taskId={taskId}
        onDownload={handleDownload}
      />
    </>
  )
}
```

- [ ] **Step 3: 提交**

```bash
git add frontend/src/components/DownloadButton.tsx
git commit -m "feat: 修改下载按钮集成收费弹窗"
```

---

### Task 7: 集成测试

**Files:**
- Test: 手动测试

- [ ] **Step 1: 重启后端**

```bash
taskkill //F //IM uvicorn.exe 2>/dev/null; sleep 2
conda run -n gdal_env uvicorn api.app:app --reload --host 0.0.0.0 --port 8000
```

- [ ] **Step 2: 测试检查权限 API**

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login -H "Content-Type: application/json" -d '{"username":"gis","password":"123456"}' | grep -o '"access_token":"[^"]*"' | cut -d'"' -f4)
curl -s "http://localhost:8000/api/downloads/4/check-permission" -H "Authorization: Bearer $TOKEN"
```

Expected: 返回权限信息

- [ ] **Step 3: 测试分享 API**

```bash
curl -s -X POST "http://localhost:8000/api/downloads/4/share" -H "Authorization: Bearer $TOKEN"
```

Expected: 返回成功信息

- [ ] **Step 4: 测试创建支付 API**

```bash
curl -s -X POST "http://localhost:8000/api/downloads/4/payment" -H "Authorization: Bearer $TOKEN"
```

Expected: 返回支付 ID 和金额

- [ ] **Step 5: 前端测试**

访问 http://localhost:3000，点击下载按钮，验证：
- 弹窗正确显示
- 复制链接功能正常
- 分享下载功能正常
- 付费流程正常

- [ ] **Step 6: 最终提交**

```bash
git add -A
git commit -m "feat: 完成收费功能实现"
```
