import { useState, useEffect } from 'react'
import { BarChart3, AlertCircle } from 'lucide-react'
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts'

interface TimeSeriesChartProps {
  src: string
  filename: string
}

interface DataPoint {
  [key: string]: string | number
}

export default function TimeSeriesChart({ src }: TimeSeriesChartProps) {
  const [data, setData] = useState<DataPoint[]>([])
  const [valueCols, setValueCols] = useState<string[]>([])
  const [timeCol, setTimeCol] = useState<string>('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  const COLORS = ['#2563eb', '#dc2626', '#16a34a', '#ca8a04', '#9333ea', '#0891b2']

  useEffect(() => {
    fetch(src)
      .then(r => r.text())
      .then(csv => {
        const lines = csv.trim().split('\n')
        if (lines.length < 2) {
          setError('CSV 数据不足')
          setLoading(false)
          return
        }

        const headers = lines[0].split(',').map(h => h.trim().replace(/^"|"$/g, ''))
        const rows: DataPoint[] = []
        const numericCols = new Set<string>()

        for (let i = 1; i < Math.min(lines.length, 2000); i++) {
          const cells = lines[i].split(',').map(c => c.trim().replace(/^"|"$/g, ''))
          const row: DataPoint = {}
          headers.forEach((h, j) => {
            const val = cells[j] || ''
            const num = parseFloat(val)
            if (!isNaN(num) && val !== '') {
              row[h] = num
              numericCols.add(h)
            } else {
              row[h] = val
            }
          })
          rows.push(row)
        }

        // 找时间列（优先包含 year/date/time 的列）
        const timeCandidate = headers.find(h =>
          /year|date|time|month|年份|日期|时间|月份/i.test(h)
        ) || headers[0]

        const vals = Array.from(numericCols).filter(c => c !== timeCandidate)
        // 采样避免点太多
        const sampled = rows.length > 500
          ? rows.filter((_, i) => i % Math.ceil(rows.length / 500) === 0)
          : rows

        setTimeCol(timeCandidate)
        setValueCols(vals.slice(0, 6)) // 最多 6 条线
        setData(sampled)
        setLoading(false)
      })
      .catch(() => {
        setError('无法加载 CSV 文件')
        setLoading(false)
      })
  }, [src])

  if (loading) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center text-gray-400">
          <BarChart3 className="h-12 w-12 mx-auto mb-3 animate-pulse opacity-40" />
          <p className="text-sm">正在解析数据...</p>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="text-center text-gray-400">
          <AlertCircle className="h-12 w-12 mx-auto mb-3 opacity-40" />
          <p className="text-sm">{error}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center space-x-2">
          <BarChart3 className="h-4 w-4 text-blue-600" />
          <span className="text-sm font-medium text-gray-700">时序图</span>
          <span className="text-xs text-gray-400">({data.length} 个数据点)</span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {valueCols.map((col, i) => (
            <span
              key={col}
              className="text-[10px] px-1.5 py-0.5 rounded-full border"
              style={{ borderColor: COLORS[i % COLORS.length], color: COLORS[i % COLORS.length] }}
            >
              {col}
            </span>
          ))}
        </div>
      </div>
      <div className="flex-1 min-h-0 bg-white rounded-lg border">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
            <XAxis
              dataKey={timeCol}
              tick={{ fontSize: 11 }}
              tickFormatter={(v) => typeof v === 'number' ? Math.round(v).toString() : String(v)}
            />
            <YAxis tick={{ fontSize: 11 }} />
            <Tooltip
              contentStyle={{ fontSize: 12, borderRadius: 8 }}
              labelFormatter={(v) => `${timeCol}: ${v}`}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {valueCols.map((col, i) => (
              <Line
                key={col}
                type="monotone"
                dataKey={col}
                stroke={COLORS[i % COLORS.length]}
                strokeWidth={1.5}
                dot={false}
                activeDot={{ r: 3 }}
                connectNulls
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
