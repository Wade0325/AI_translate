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
import RechartsTooltipBox from "@/components/charts/RechartsTooltipBox"

// 後端 daily 的 date 為 UTC 日期字串（func.date on UTC timestamp），這裡同樣以 UTC 取日期對齊
function lastSevenDays(daily) {
    const byDate = new Map(daily.map((d) => [d.date, d]))
    const result = []
    for (let i = 6; i >= 0; i--) {
        const d = new Date()
        d.setUTCDate(d.getUTCDate() - i)
        const key = d.toISOString().slice(0, 10)
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

function CustomTooltip({ active, payload, label }) {
    if (!active || !payload?.length) return null
    const row = payload[0].payload
    return (
        <RechartsTooltipBox label={label}>
            <div style={{ fontSize: 12, color: '#8888a8' }}>
                Tokens: {row.tokens.toLocaleString()} · Files: {row.files}
            </div>
            <div style={{ fontSize: 12, color: '#2dd4a8' }}>
                Cost: ${row.cost.toFixed(4)}
            </div>
        </RechartsTooltipBox>
    )
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
                            tickFormatter={(value) => `${(value / 1000).toFixed(0)}k`}
                        />
                        <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(42, 42, 72, 0.5)" }} />
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
