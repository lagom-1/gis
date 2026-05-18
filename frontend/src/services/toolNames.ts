/**
 * 工具名称中文映射 + 步骤描述生成
 */

const TOOL_NAME_MAP: Record<string, string> = {
  // 行政区
  resolve_admin_region: '解析行政区边界',

  // GEE 初始化与数据下载
  gee_init: '连接 Google Earth Engine',
  gee_download_landsat_sca: '下载 Landsat 卫星数据',
  gee_download_monthly_lst: '下载月度地表温度数据',
  gee_download_yearly_lst: '下载年度地表温度数据',
  gee_download_multi_year_lst: '下载多年地表温度数据',

  // LST 反演
  run_lst: '执行地表温度反演',
  gee_compute_lst: '计算地表温度',

  // 时间序列与动画
  gee_lst_timelapse: '生成温度变化动画',
  gee_lst_timelapse_local: '生成温度变化动画',
  gee_lst_split_panel: '生成温度分屏对比图',
  gee_lst_trend_chart: '生成温度趋势图',
  generate_timeslider_map: '生成时间滑块地图',
  timeseries_extract: '提取时间序列数据',
  timeseries_inspector: '检查时间序列数据',

  // 制图与可视化
  make_thematic_map: '生成专题地图',
  generate_web_map: '生成交互式网页地图',
  classify_map: '执行地图分类',
  set_map_style: '设置地图样式',
  classify: '执行栅格分类',

  // 图像处理
  enhance: '图像增强处理',
  threshold: '阈值高亮处理',
  compare: '图像对比分析',
  profile: '剖面线分析',
  view3d: '生成 3D 可视化',

  // 统计与分析
  statistics: '计算统计信息',
  zonal_stats: '计算分区统计',

  // 文件操作
  search_local_files: '搜索本地文件',
  inspect: '检查文件元数据',
  export: '导出文件',
  transform: '图像变换处理',

  // 土地覆盖
  dynamic_world: '获取土地覆盖数据',
  ee_classification: '执行遥感分类',

  // 报告
  report: '生成实验报告',
  cartographic_map: '生成制图',

  // GEE 图表
  gee_charts: '生成 GEE 图表',
}

/**
 * 获取工具的中文名称
 */
export function getToolDisplayName(toolName: string): string {
  return TOOL_NAME_MAP[toolName] || toolName
}

/**
 * 生成步骤的中文描述（用于状态栏显示）
 * @param step 当前步骤号
 * @param maxSteps 最大步骤数
 * @param toolName 工具名
 * @param reason LLM 给出的原因
 */
export function getStepDescription(
  step: number,
  maxSteps: number,
  toolName?: string,
  reason?: string
): string {
  const parts: string[] = []

  if (step && maxSteps) {
    parts.push(`步骤 ${step}/${maxSteps}`)
  }

  if (reason) {
    // reason 通常是 LLM 生成的中文描述，直接使用
    parts.push(reason)
  } else if (toolName) {
    parts.push(getToolDisplayName(toolName))
  }

  return parts.join('：') || '执行中'
}
