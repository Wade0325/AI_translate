import { Card, Typography } from "antd"
import {
    BarChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
} from "recharts"

const { Title, Text } = Typography

const data = [
    { day: "Mon", tokens: 0, cost: 0 },
    { day: "Tue", tokens: 0, cost: 0 },
    { day: "Wed", tokens: 0, cost: 0 },
    { day: "Thu", tokens: 0, cost: 0 },
    { day: "Fri", tokens: 0, cost: 0 },
    { day: "Sat", tokens: 0, cost: 0 },
    { day: "Sun", tokens: 0, cost: 0 },
]

function CustomTooltip({ active, payload, label }) {
    if (active && payload && payload.length) {
        return (
            <div style={{
                borderRadius: 8,
                border: '1px solid #3a3a5c',
                background: '#1e1e3a',
                padding: 12,
                boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
            }}>
                <div style={{ fontSize: 13, fontWeight: 500, color: '#e8e8e8' }}>{label}</div>
                <div style={{ fontSize: 12, color: '#8888a8' }}>
                    Tokens: {payload[0].value.toLocaleString()}
                </div>
                <div style={{ fontSize: 12, color: '#2dd4a8' }}>
                    Cost: ${(payload[0].value * 0.000015).toFixed(2)}
                </div>
            </div>
        )
    }
    return null
}

export function UsageChart() {
    return (
        <Card
            title={<span style={{ color: '#e8e8e8' }}>Weekly Token Usage</span>}
            style={{ border: '1px solid #3a3a5c', height: '100%' }}
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
