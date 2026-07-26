import { useEffect, useState } from "react"
import { Card, Typography, Tabs, Table, Row, Col } from "antd"
import {
    BarChart,
    Bar,
    XAxis,
    YAxis,
    CartesianGrid,
    Tooltip,
    ResponsiveContainer,
    LineChart,
    Line,
    AreaChart,
    Area,
} from "recharts"
import {
    Coins,
    TrendingUp,
    FileAudio,
    CreditCard,
} from "lucide-react"
import RechartsTooltipBox from "@/components/charts/RechartsTooltipBox"
import { StatCard } from "@/components/StatCard"
import { api } from "@/services/api"

const { Text } = Typography

// 後端 daily 的 date 為 UTC 日期字串，月份切齊也用 UTC
const currentMonthKey = () => new Date().toISOString().slice(0, 7)

function sumUsage(rows) {
    return rows.reduce(
        (acc, r) => ({
            tokens: acc.tokens + r.tokens,
            cost: acc.cost + r.cost,
            files: acc.files + r.files,
        }),
        { tokens: 0, cost: 0, files: 0 }
    )
}

/** 當月 1 日～今日逐日補 0，讓圖表 x 軸連續 */
function buildDailyChartData(daily, monthKey) {
    const byDate = new Map(daily.map((d) => [d.date, d]))
    const today = new Date().getUTCDate()
    return Array.from({ length: today }, (_, i) => {
        const key = `${monthKey}-${String(i + 1).padStart(2, "0")}`
        const row = byDate.get(key)
        return {
            day: String(i + 1),
            tokens: row?.tokens || 0,
            cost: row?.cost || 0,
            files: row?.files || 0,
        }
    })
}

/** 最近 6 個月（含當月）逐月彙總，無資料的月份補 0 */
function buildMonthlyChartData(daily) {
    const now = new Date()
    const months = []
    for (let i = 5; i >= 0; i--) {
        const d = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - i, 1))
        months.push({
            key: d.toISOString().slice(0, 7),
            label: d.toLocaleString("en", { month: "short", timeZone: "UTC" }),
        })
    }
    return months.map((m) => {
        const totals = sumUsage(daily.filter((d) => d.date.startsWith(m.key)))
        return { month: m.label, ...totals }
    })
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

const pricingColumns = [
    { title: 'Model', dataIndex: 'model', key: 'model', render: (v) => <Text strong style={{ color: '#e8e8e8' }}>{v}</Text> },
    { title: 'Input Text (per 1M)', dataIndex: 'input_text', key: 'input_text', render: (v) => <Text code style={{ color: '#8888a8' }}>${v.toFixed(2)}</Text> },
    { title: 'Input Audio (per 1M)', dataIndex: 'input_audio', key: 'input_audio', render: (v) => <Text code style={{ color: '#8888a8' }}>${v.toFixed(2)}</Text> },
    { title: 'Output (per 1M)', dataIndex: 'output_text', key: 'output_text', render: (v) => <Text code style={{ color: '#8888a8' }}>${v.toFixed(2)}</Text> },
]

export default function BillingPage() {
    const [usage, setUsage] = useState({ daily: [], by_model: [], pricing: [] })

    useEffect(() => {
        api.history.usage({ days: 183 })
            .then(setUsage)
            .catch((err) => console.error("載入用量資料失敗:", err))
    }, [])

    const monthKey = currentMonthKey()
    const monthLabel = new Date().toLocaleString("en", { month: "long", year: "numeric", timeZone: "UTC" })
    const month = sumUsage(usage.daily.filter((d) => d.date.startsWith(monthKey)))
    const avgCostPerFile = month.files > 0 ? month.cost / month.files : 0

    const dailyData = buildDailyChartData(usage.daily, monthKey)
    const monthlyData = buildMonthlyChartData(usage.daily)

    const totalModelTokens = usage.by_model.reduce((sum, m) => sum + m.tokens, 0)

    const tabItems = [
        {
            key: 'daily',
            label: 'Daily Usage',
            children: (
                <Card title={<span style={{ color: '#e8e8e8' }}>Daily Token Usage - {monthLabel}</span>} style={{ border: '1px solid #3a3a5c' }}>
                    <div style={{ height: 288 }}>
                        <ResponsiveContainer width="100%" height="100%">
                            <AreaChart data={dailyData}>
                                <defs>
                                    <linearGradient id="tokenGradient" x1="0" y1="0" x2="0" y2="1">
                                        <stop offset="5%" stopColor="#2dd4a8" stopOpacity={0.3} />
                                        <stop offset="95%" stopColor="#2dd4a8" stopOpacity={0} />
                                    </linearGradient>
                                </defs>
                                <CartesianGrid strokeDasharray="3 3" stroke="#2a2a48" vertical={false} />
                                <XAxis dataKey="day" stroke="#8888a8" fontSize={12} tickLine={false} axisLine={false} />
                                <YAxis stroke="#8888a8" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`} />
                                <Tooltip content={<CustomTooltip />} />
                                <Area type="monotone" dataKey="tokens" stroke="#2dd4a8" fill="url(#tokenGradient)" strokeWidth={2} />
                            </AreaChart>
                        </ResponsiveContainer>
                    </div>
                </Card>
            ),
        },
        {
            key: 'monthly',
            label: 'Monthly Trend',
            children: (
                <Card title={<span style={{ color: '#e8e8e8' }}>Monthly Token Usage (6 Months)</span>} style={{ border: '1px solid #3a3a5c' }}>
                    <div style={{ height: 288 }}>
                        <ResponsiveContainer width="100%" height="100%">
                            <BarChart data={monthlyData} barSize={40}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#2a2a48" vertical={false} />
                                <XAxis dataKey="month" stroke="#8888a8" fontSize={12} tickLine={false} axisLine={false} />
                                <YAxis stroke="#8888a8" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(v) => v >= 1000000 ? `${(v / 1000000).toFixed(1)}M` : `${(v / 1000).toFixed(0)}k`} />
                                <Tooltip content={<CustomTooltip />} />
                                <Bar dataKey="tokens" fill="#2dd4a8" radius={[4, 4, 0, 0]} />
                            </BarChart>
                        </ResponsiveContainer>
                    </div>
                </Card>
            ),
        },
        {
            key: 'cost',
            label: 'Cost Trend',
            children: (
                <Card title={<span style={{ color: '#e8e8e8' }}>Monthly Cost Trend</span>} style={{ border: '1px solid #3a3a5c' }}>
                    <div style={{ height: 288 }}>
                        <ResponsiveContainer width="100%" height="100%">
                            <LineChart data={monthlyData}>
                                <CartesianGrid strokeDasharray="3 3" stroke="#2a2a48" vertical={false} />
                                <XAxis dataKey="month" stroke="#8888a8" fontSize={12} tickLine={false} axisLine={false} />
                                <YAxis stroke="#8888a8" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(v) => `$${v}`} />
                                <Tooltip content={<CustomTooltip />} />
                                <Line type="monotone" dataKey="cost" stroke="#2dd4a8" strokeWidth={2} dot={{ fill: "#2dd4a8", r: 4 }} />
                            </LineChart>
                        </ResponsiveContainer>
                    </div>
                </Card>
            ),
        },
    ]

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24, padding: 24 }}>
            <Row gutter={[16, 16]}>
                <Col xs={24} sm={12} lg={6}>
                    <StatCard
                        title="Current Month Cost"
                        value={`$${month.cost.toFixed(4)}`}
                        subtitle={monthLabel}
                        icon={CreditCard}
                        iconColor="#2dd4a8"
                        bgColor="rgba(45, 212, 168, 0.1)"
                    />
                </Col>
                <Col xs={24} sm={12} lg={6}>
                    <StatCard
                        title="Tokens This Month"
                        value={month.tokens.toLocaleString()}
                        icon={Coins}
                        iconColor="#d4a72d"
                        bgColor="rgba(212, 167, 45, 0.1)"
                    />
                </Col>
                <Col xs={24} sm={12} lg={6}>
                    <StatCard
                        title="Files Processed"
                        value={month.files.toLocaleString()}
                        subtitle="this month"
                        icon={FileAudio}
                        iconColor="#47b8d4"
                        bgColor="rgba(71, 184, 212, 0.1)"
                    />
                </Col>
                <Col xs={24} sm={12} lg={6}>
                    <StatCard
                        title="Avg. Cost / File"
                        value={`$${avgCostPerFile.toFixed(4)}`}
                        subtitle="based on this month"
                        icon={TrendingUp}
                        iconColor="#8b5cf6"
                        bgColor="rgba(139, 92, 246, 0.1)"
                    />
                </Col>
            </Row>

            <Tabs items={tabItems} />

            <Card title={<span style={{ color: '#e8e8e8' }}>Token Usage by Model (6 Months)</span>} style={{ border: '1px solid #3a3a5c' }}>
                {usage.by_model.length === 0 ? (
                    <Text style={{ color: '#8888a8', fontSize: 13 }}>尚無已完成的轉錄紀錄</Text>
                ) : (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                        {usage.by_model.map((m) => {
                            const percentage = totalModelTokens > 0 ? (m.tokens / totalModelTokens) * 100 : 0
                            return (
                                <div key={m.model} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                        <Text strong style={{ fontSize: 13, color: '#e8e8e8' }}>{m.model}</Text>
                                        <Text style={{ fontSize: 13, color: '#2dd4a8', fontWeight: 500 }}>${m.cost.toFixed(4)}</Text>
                                    </div>
                                    <div style={{ display: 'flex', gap: 12, fontSize: 12, color: '#8888a8' }}>
                                        <span>{m.tokens.toLocaleString()} tokens</span>
                                        <span>{m.files} files</span>
                                        <span>{percentage.toFixed(1)}%</span>
                                    </div>
                                    <div style={{ height: 8, width: '100%', borderRadius: 4, background: '#2a2a48', overflow: 'hidden' }}>
                                        <div
                                            style={{ height: '100%', borderRadius: 4, background: '#2dd4a8', transition: 'width 0.3s', width: `${percentage}%` }}
                                        />
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                )}
            </Card>

            <Card title={<span style={{ color: '#e8e8e8' }}>Gemini API Pricing Reference</span>} style={{ border: '1px solid #3a3a5c' }}>
                <Table
                    dataSource={usage.pricing.map((p) => ({ ...p, key: p.model }))}
                    columns={pricingColumns}
                    pagination={false}
                    size="small"
                />
                <Text style={{ display: 'block', marginTop: 12, fontSize: 12, color: '#8888a8' }}>
                    批次（Batch）與 Flex 模式為上表價格的 50%。未列出的模型套用預設價格。
                </Text>
            </Card>
        </div>
    )
}
