# 智能画布 — 输出文件专用查看器

## 目标

根据用户选中的输出文件类型，画布自动切换对应的专用查看器，替代当前单一的图片显示。

## 组件设计

### 1. GifPlayer — GIF 动画播放器
- **触发条件**: 文件扩展名 `.gif`
- **功能**:
  - 播放/暂停按钮
  - 速率控制: 0.5x / 1x / 2x / 4x
  - 逐帧前进/后退（左右箭头键）
  - 帧指示器: "第 3/12 帧"
  - 支持拖拽上传的本地 GIF（未来）
- **实现**: 通过 `<img>` 的 src 切换实现帧控制，速率通过定时器间隔控制

### 2. TimeSeriesChart — 时序图表查看器
- **触发条件**: 文件扩展名 `.csv` 且内容可解析为时间序列
- **功能**:
  - 使用 recharts 渲染折线图/柱状图
  - 自动检测时间列和数值列
  - 多列数据可切换显示
  - 鼠标悬浮显示数值
  - 导出为 PNG
- **实现**: fetch CSV → 解析 → recharts 渲染，CSV 过大时采样

### 3. HtmlPreview — HTML 内嵌预览
- **触发条件**: 文件扩展名 `.html`
- **功能**:
  - iframe 沙箱内嵌预览
  - 工具栏: 新窗口打开、刷新 iframe
  - 安全: sandbox="allow-scripts allow-same-origin"
- **实现**: 通过 `/api/downloads/{taskId}/{filename}` 获取 HTML，blob URL 加载到 iframe

### 4. CompareSlider — 对比滑块
- **触发条件**: 用户点击"对比上次结果"且两张都是图片
- **功能**:
  - 两张图重叠，中间可拖拽分割线
  - 替代当前左右并排布局
  - 更适合遥感影像前后对比
- **实现**: CSS clip-path + 拖拽手柄

### 5. 智能查看器路由
- `ViewerRouter` 组件根据文件类型自动选择查看器
- 未知类型回退到 ImageViewer

## 数据流

```
用户点击文件 → setPreviewFile(file)
  → ViewerRouter 检测 file.name 扩展名
    → .gif  → GifPlayer
    → .csv  → TimeSeriesChart
    → .html → HtmlPreview
    → .png/.jpg → ImageViewer (已有)
    → 其他  → 文件信息 + 下载按钮
```

所有组件接收 `{ src: string, filename: string }` 统一接口。

## 不涉及

- 后端改动
- 路由变化
- 新的依赖（除 recharts 用于图表）
