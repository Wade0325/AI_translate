import { Card } from "antd"
import {
    BarChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
} from "recharts"
import { UsageTooltip } from "@/components/charts/RechartsTooltipBox"
import { localDateKey, formatTokensTick } from "@/utils/formatters"

// 後端 daily 的 date 是伺服器本地日期字串，以本地日期產生 key 對齊（見 localDateKey 說明）
function lastSevenDays(daily) {
    const byDate = new Map(daily.map((d) => [d.date, d]))
    const result = []
    for (let i = 6; i >= 0; i--) {
        const d = new Date()
        d.setDate(d.getDate() - i)
        const key = localDateKey(d)
        const row = byDate.get(key)
        result.push({
            day: key.slice(5),
            tokens: row?.tokens || 0,
            cost: row?.cost || 0,
            files: row?.files || 0,
        })
    }
    return result
}

export function UsageChart({ daily = [] }) {
    const data = lastSevenDays(daily)

    return (
        <Card
            title={<span style={{ color: '#e8e8e8' }}>Weekly Token Usage</span>}
            style={{ border: '1px solid #3a3a5c' }}
        >
            <div style={{ height: 256 }}>
                <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={data} barSize={32}>
                        <CartesianGrid
                            strokeDasharray="3 3"
                            stroke="#2a2a48"
                            vertical={false}
                        />
                        <XAxis
                            dataKey="day"
                            stroke="#8888a8"
                            fontSize={12}
                            tickLine={false}
                            axisLine={false}
                        />
                        <YAxis
                            stroke="#8888a8"
                            fontSize={12}
                            tickLine={false}
                            axisLine={false}
                            tickFormatter={formatTokensTick}
                        />
                        <Tooltip content={<UsageTooltip />} cursor={{ fill: "rgba(42, 42, 72, 0.5)" }} />
                        <Bar
                            dataKey="tokens"
                            fill="#2dd4a8"
                            radius={[4, 4, 0, 0]}
                        />
                    </BarChart>
                </ResponsiveContainer>
            </div>
        </Card>
    )
}
