import { Link } from 'react-router-dom'
import { Map, Satellite, Thermometer, BarChart3 } from 'lucide-react'

const features = [
  {
    icon: Satellite,
    title: '遥感数据下载',
    description: '自动下载 Landsat、Sentinel 等卫星数据',
  },
  {
    icon: Thermometer,
    title: '地表温度反演',
    description: '基于单通道算法的 LST 反演',
  },
  {
    icon: BarChart3,
    title: '数据分析统计',
    description: '分类、统计、时间序列分析',
  },
  {
    icon: Map,
    title: '专题制图',
    description: '出版级质量的专题地图生成',
  },
]

export default function Home() {
  return (
    <div className="space-y-16">
      <section className="text-center py-20">
        <h1 className="text-4xl font-bold text-gray-900 mb-6">
          AI 驱动的 GIS 遥感分析平台
        </h1>
        <p className="text-xl text-gray-600 mb-8 max-w-2xl mx-auto">
          使用自然语言描述你的需求，AI 自动规划并执行 GIS 工作流
        </p>
        <Link
          to="/gallery"
          className="inline-flex items-center space-x-2 bg-primary-600 text-white px-8 py-4 rounded-lg text-lg font-medium hover:bg-primary-700 transition-colors"
        >
          <span>开始使用</span>
        </Link>
      </section>

      <section className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-8">
        {features.map((feature, index) => {
          const Icon = feature.icon
          return (
            <div
              key={index}
              className="bg-white p-6 rounded-xl shadow-sm border hover:shadow-md transition-shadow"
            >
              <div className="w-12 h-12 bg-primary-100 rounded-lg flex items-center justify-center mb-4">
                <Icon className="h-6 w-6 text-primary-600" />
              </div>
              <h3 className="text-lg font-semibold text-gray-900 mb-2">{feature.title}</h3>
              <p className="text-gray-600">{feature.description}</p>
            </div>
          )
        })}
      </section>

      <section className="bg-white rounded-xl p-8 border">
        <h2 className="text-2xl font-bold text-gray-900 mb-4">使用示例</h2>
        <div className="space-y-3">
          {[
            '找到 Beijing 的 TIF 文件，做温度反演并制图',
            '下载上海地区 2023 年 Landsat 数据并生成 NDVI 图',
            '生成北京地区 2020-2024 年 LST 时间序列动画',
          ].map((example, index) => (
            <div
              key={index}
              className="flex items-center space-x-3 p-3 bg-gray-50 rounded-lg"
            >
              <span className="text-primary-600 font-mono">→</span>
              <span className="text-gray-700">{example}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
