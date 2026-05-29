/**
 * 登录页左侧品牌展示区
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
