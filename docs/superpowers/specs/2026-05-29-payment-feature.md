# 收费功能设计规范

## 概述

为 OpenGIS 项目添加下载收费功能，支持两种下载方式：
1. **分享免费下载** — 分享 GitHub 项目链接后免费下载（每周 3 次）
2. **付费下载** — 扫描微信收款码支付后下载

## 设计目标

- 简单易用的收费弹窗
- 支持分享推广和付费两种模式
- 基于 API token 费用的动态定价
- 微信扫码支付（手动确认）

## 功能设计

### 1. 收费弹窗

#### 触发方式
- 用户点击下载按钮时弹出
- 显示模态对话框，遮罩层覆盖背景

#### 布局
- **左右分栏**：左侧分享免费，右侧付费下载
- **头部**：标题「下载文件」+ 关闭按钮
- **左侧区域**：
  - 图标：🔗
  - 标题：分享免费下载
  - 说明：分享 OpenGIS 项目到 GitHub，即可免费下载 1 次
  - GitHub 链接输入框（只读）+ 复制按钮
  - 「我已分享，下载文件」按钮
  - 剩余次数显示：本周剩余 2/3 次免费下载
- **右侧区域**：
  - 图标：💰
  - 标题：付费下载
  - 说明：扫码支付后即可下载，支持微信支付
  - 价格显示（基于 API token 费用 × 2 倍）
  - 微信收款码图片
  - 「我已支付，下载文件」按钮
  - 提示：支付后请稍等片刻，系统将自动确认

### 2. 分享免费下载

#### GitHub 链接
```
https://github.com/lagom-1/gis/tree/master
```

#### 流程
1. 用户点击下载按钮 → 弹出收费弹窗
2. 点击「复制」按钮 → 复制 GitHub 链接到剪贴板
3. 用户打开 GitHub 页面（可选）
4. 返回页面，点击「我已分享，下载文件」
5. 系统验证分享次数限制
6. 开始下载文件

#### 限制
- 每个用户每周最多 3 次免费下载
- 每周一 00:00 重置计数
- 基于用户 ID 和周数记录

### 3. 付费下载

#### 价格计算
- 基于任务实际消耗的 API token 费用
- 加价系数：2 倍
- 最低价格：1 元
- 最高价格：100 元
- 价格显示格式：¥X.XX

#### 微信收款码
- 静态图片文件：`D:\推文\收费.jpg`
- 部署时复制到 `frontend/public/qrcode.jpg`
- 前端通过 `/qrcode.jpg` 访问

#### 流程
1. 用户点击下载按钮 → 弹出收费弹窗
2. 查看价格和收款码
3. 使用微信扫码支付
4. 点击「我已支付，下载文件」
5. 系统创建支付记录（状态：pending）
6. 管理员手动确认支付
7. 系统更新支付状态为 paid
8. 用户刷新页面后可下载

### 4. 数据模型

#### 分享记录表 (share_records)
```sql
CREATE TABLE share_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    task_id INTEGER NOT NULL,
    shared_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    week_number INTEGER NOT NULL,  -- ISO 周数
    year INTEGER NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
```

#### 支付记录表 (payment_records)
```sql
CREATE TABLE payment_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    task_id INTEGER NOT NULL,
    amount_yuan REAL NOT NULL,  -- 金额（元）
    status VARCHAR(20) DEFAULT 'pending',  -- pending/paid/cancelled
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    paid_at DATETIME,
    confirmed_at DATETIME,
    FOREIGN KEY (user_id) REFERENCES users(id),
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);
```

### 5. API 接口

#### 检查下载权限
```
GET /api/downloads/{task_id}/check-permission
```
返回：
```json
{
  "can_download": true,
  "download_type": "share",  // share/payment
  "share_remaining": 2,
  "price_yuan": 3.50,
  "payment_status": null
}
```

#### 记录分享
```
POST /api/downloads/{task_id}/share
```
返回：
```json
{
  "success": true,
  "message": "分享成功，开始下载",
  "download_url": "/api/downloads/serve/{task_id}/{filename}?token=xxx"
}
```

#### 创建支付记录
```
POST /api/downloads/{task_id}/payment
```
返回：
```json
{
  "success": true,
  "payment_id": 123,
  "amount_yuan": 3.50,
  "message": "请扫码支付后点击「我已支付」"
}
```

#### 确认支付（管理员）
```
POST /api/payments/{payment_id}/confirm
```
返回：
```json
{
  "success": true,
  "message": "支付已确认，可以下载"
}
```

### 6. 前端组件

#### PaymentModal 组件
- 位置：`frontend/src/components/PaymentModal.tsx`
- Props：
  - `isOpen: boolean` — 是否显示
  - `onClose: () => void` — 关闭回调
  - `taskId: number` — 任务 ID
  - `files: OutputFile[]` — 文件列表

#### 状态管理
- `copied: boolean` — 是否已复制链接
- `shareRemaining: number` — 剩余分享次数
- `priceYuan: number` — 价格
- `paymentStatus: string` — 支付状态
- `isProcessing: boolean` — 处理中状态

### 7. 错误处理

#### 分享次数耗尽
- 显示提示：「本周免费下载次数已用完，请付费下载」
- 禁用「我已分享」按钮
- 高亮右侧付费区域

#### 支付未确认
- 显示提示：「支付确认中，请稍候...」
- 禁用两个下载按钮
- 显示加载动画

#### 网络错误
- 显示错误提示
- 提供重试按钮

### 8. 样式设计

#### 颜色系统
- 主色调：emerald-600 (#059669) — 分享按钮
- 强调色：amber-500 (#d97706) — 价格和支付按钮
- 背景：white + stone-50
- 文字：stone-900, stone-500

#### 响应式设计
- 桌面端：左右分栏
- 移动端：上下堆叠

### 9. 部署配置

#### 静态文件
- 将 `D:\推文\收费.jpg` 复制到 `frontend/public/qrcode.jpg`
- 前端通过 `/qrcode.jpg` 访问

#### 环境变量
- `PAYMENT_MULTIPLIER` — 价格倍数（默认 2）
- `SHARE_WEEKLY_LIMIT` — 每周分享次数限制（默认 3）
- `MIN_PRICE_YUAN` — 最低价格（默认 1）
- `MAX_PRICE_YUAN` — 最高价格（默认 100）

## 验证标准

### 功能验证
- [ ] 分享免费下载正常工作
- [ ] 分享次数限制正确（每周 3 次）
- [ ] 价格计算正确（token 费用 × 2）
- [ ] 微信收款码正确显示
- [ ] 支付记录正确创建
- [ ] 管理员确认后可下载

### 视觉验证
- [ ] 弹窗布局正确
- [ ] 响应式适配正确
- [ ] 颜色和间距正确
- [ ] 图标和按钮正确

### 安全验证
- [ ] 分享次数不能绕过
- [ ] 支付状态不能伪造
- [ ] 文件下载需要验证