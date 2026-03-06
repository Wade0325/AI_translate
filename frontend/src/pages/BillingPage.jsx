
import { Card, Typography, Tabs, Table, Tag, Button, Row, Col } from "antd"
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
    Clock,
    CreditCard,
    ArrowUpRight,
    Zap,
} from "lucide-react"

const { Title, Text } = Typography

// Monthly usage data
const monthlyData = [
    { month: "Oct", tokens: 0, cost: 0, files: 0 },
    { month: "Nov", tokens: 0, cost: 0, files: 0 },
    { month: "Dec", tokens: 0, cost: 0, files: 0 },
    { month: "Jan", tokens: 0, cost: 0, files: 0 },
    { month: "Feb", tokens: 0, cost: 0, files: 0 },
    { month: "Mar", tokens: 0, cost: 0, files: 0 },
]

// Daily data for current month
const dailyData = []

// Recent invoices
const invoices = []

// Token breakdown by model
const modelBreakdown = [
    { model: "Gemini 3 Pro", inputTokens: 0, outputTokens: 0, cost: "$0.00", percentage: 0 },
    { model: "Gemini 3 Flash", inputTokens: 0, outputTokens: 0, cost: "$0.00", percentage: 0 },
    { model: "Gemini 3 Pro (Vision)", inputTokens: 0, outputTokens: 0, cost: "$0.00", percentage: 0 },
]

function CustomTooltip({ active, payload, label }) {
    if (active && payload && payload.length) {
        return (
            <div style={{ borderRadius: 8, border: '1px solid #3a3a5c', background: '#1e1e3a', padding: 12, boxShadow: '0 4px 12px rgba(0,0,0,0.3)' }}>
                <div style={{ fontSize: 13, fontWeight: 500, color: '#e8e8e8' }}>{label}</div>
                {payload.map((p, i) => (
                    <div key={i} style={{ fontSize: 12, color: '#8888a8' }}>
                        {p.dataKey === "tokens" && `Tokens: ${p.value.toLocaleString()}`}
                        {p.dataKey === "cost" && `Cost: $${p.value.toFixed(2)}`}
                        {p.dataKey === "files" && `Files: ${p.value}`}
                    </div>
                ))}
            </div>
        )
    }
    return null
}

export default function BillingPage() {
    const invoiceColumns = [
        { title: 'Invoice', dataIndex: 'id', key: 'id', render: (v) => <Text style={{ fontFamily: 'monospace', fontSize: 12, color: '#e8e8e8' }}>{v}</Text> },
        { title: 'Period', dataIndex: 'period', key: 'period', render: (v) => <Text style={{ color: '#8888a8' }}>{v}</Text> },
        { title: 'Amount', dataIndex: 'amount', key: 'amount', render: (v) => <Text strong style={{ color: '#e8e8e8' }}>{v}</Text> },
        {
            title: 'Status', dataIndex: 'status', key: 'status',
            render: (v) => <Tag color={v === 'paid' ? 'default' : 'green'}>{v === 'paid' ? 'Paid' : 'Current'}</Tag>,
        },
    ]

    const pricingColumns = [
        { title: 'Model', dataIndex: 'model', key: 'model', render: (v) => <Text strong style={{ color: '#e8e8e8' }}>{v}</Text> },
        { title: 'Input (per 1M tokens)', dataIndex: 'input', key: 'input', render: (v) => <Text code style={{ color: '#8888a8' }}>{v}</Text> },
        { title: 'Output (per 1M tokens)', dataIndex: 'output', key: 'output', render: (v) => <Text code style={{ color: '#8888a8' }}>{v}</Text> },
        { title: 'Context Window', dataIndex: 'context', key: 'context', render: (v) => <Text style={{ color: '#8888a8' }}>{v}</Text> },
    ]

    const pricingData = [
        { key: '1', model: 'Gemini 3 Pro', input: '$1.25', output: '$5.00', context: '2M tokens' },
        { key: '2', model: 'Gemini 3 Flash', input: '$0.075', output: '$0.30', context: '1M tokens' },
        { key: '3', model: 'Gemini 3 Pro (Vision)', input: '$1.25', output: '$5.00', context: '2M tokens' },
    ]

    const tabItems = [
        {
            key: 'daily',
            label: 'Daily Usage',
            children: (
                <Card title={<span style={{ color: '#e8e8e8' }}>Daily Token Usage - March 2026</span>} style={{ border: '1px solid #3a3a5c' }}>
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
                                <YAxis stroke="#8888a8" fontSize={12} tickLine={false} axisLine={false} tickFormatter={(v) => `${(v / 1000000).toFixed(1)}M`} />
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
            label: 'Cost Breakdown',
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

            {/* Summary Cards */}
            <Row gutter={[16, 16]}>
                <Col xs={24} sm={12} lg={6}>
                    <SummaryCard
                        title="Current Month Cost"
                        value="$0.00"
                        subtitle="March 2026"
                        icon={CreditCard}
                        iconColor="#2dd4a8"
                        bgColor="rgba(45, 212, 168, 0.1)"
                    />
                </Col>
                <Col xs={24} sm={12} lg={6}>
                    <SummaryCard
                        title="Tokens This Month"
                        value="0"
                        subtitle="0% of 1.5M quota"
                        icon={Coins}
                        iconColor="#d4a72d"
                        bgColor="rgba(212, 167, 45, 0.1)"
                    />
                </Col>
                <Col xs={24} sm={12} lg={6}>
                    <SummaryCard
                        title="Files Processed"
                        value="0"
                        subtitle="0 this month"
                        icon={FileAudio}
                        iconColor="#47b8d4"
                        bgColor="rgba(71, 184, 212, 0.1)"
                    />
                </Col>
                <Col xs={24} sm={12} lg={6}>
                    <SummaryCard
                        title="Avg. Cost / File"
                        value="$0.00"
                        subtitle="Based on this month"
                        icon={TrendingUp}
                        iconColor="#8b5cf6"
                        bgColor="rgba(139, 92, 246, 0.1)"
                    />
                </Col>
            </Row>

            {/* Charts */}
            <Tabs items={tabItems} />

            {/* Model Breakdown + Invoices */}
            <Row gutter={24}>
                <Col xs={24} lg={12}>
                    <Card title={<span style={{ color: '#e8e8e8' }}>Token Usage by Model</span>} style={{ border: '1px solid #3a3a5c' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
                            {modelBreakdown.map((m) => (
                                <div key={m.model} style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                        <Text strong style={{ fontSize: 13, color: '#e8e8e8' }}>{m.model}</Text>
                                        <Text style={{ fontSize: 13, color: '#2dd4a8', fontWeight: 500 }}>{m.cost}</Text>
                                    </div>
                                    <div style={{ display: 'flex', gap: 12, fontSize: 12, color: '#8888a8' }}>
                                        <span>Input: {(m.inputTokens / 1000).toFixed(0)}k</span>
                                        <span>Output: {(m.outputTokens / 1000).toFixed(0)}k</span>
                                    </div>
                                    <div style={{ height: 8, width: '100%', borderRadius: 4, background: '#2a2a48', overflow: 'hidden' }}>
                                        <div
                                            style={{ height: '100%', borderRadius: 4, background: '#2dd4a8', transition: 'width 0.3s', width: `${m.percentage}%` }}
                                        />
                                    </div>
                                </div>
                            ))}
                        </div>
                    </Card>
                </Col>
                <Col xs={24} lg={12}>
                    <Card
                        title={<span style={{ color: '#e8e8e8' }}>Invoices</span>}
                        extra={<Button type="link" style={{ color: '#2dd4a8', padding: 0 }}>View All</Button>}
                        style={{ border: '1px solid #3a3a5c' }}
                    >
                        <Table
                            dataSource={invoices.map((inv) => ({ ...inv, key: inv.id }))}
                            columns={invoiceColumns}
                            pagination={false}
                            size="small"
                        />
                    </Card>
                </Col>
            </Row>

            {/* API Pricing Reference */}
            <Card title={<span style={{ color: '#e8e8e8' }}>Gemini API Pricing Reference</span>} style={{ border: '1px solid #3a3a5c' }}>
                <Table
                    dataSource={pricingData}
                    columns={pricingColumns}
                    pagination={false}
                    size="small"
                />
            </Card>
        </div>
    )
}

function SummaryCard({
    title,
    value,
    subtitle,
    icon: Icon,
    iconColor,
    bgColor,
    trend,
    trendUp,
}) {
    return (
        <Card size="small" style={{ border: '1px solid #3a3a5c' }} styles={{ body: { padding: 20 } }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ flex: 1 }}>
                    <div style={{ color: '#8888a8', fontSize: 13, marginBottom: 8 }}>{title}</div>
                    <div style={{ fontSize: 24, fontWeight: 700, color: '#e8e8e8' }}>{value}</div>
                    <div style={{ color: '#8888a8', fontSize: 12, marginTop: 4 }}>{subtitle}</div>
                    {trend && (
                        <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: trendUp ? '#2dd480' : '#2dd4a8' }}>
                            <ArrowUpRight size={12} style={{ transform: !trendUp ? 'rotate(90deg)' : undefined }} />
                            {trend}
                        </div>
                    )}
                </div>
                <div style={{
                    width: 36,
                    height: 36,
                    borderRadius: 8,
                    background: bgColor,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                }}>
                    <Icon size={16} color={iconColor} />
                </div>
            </div>
        </Card>
    )
}
