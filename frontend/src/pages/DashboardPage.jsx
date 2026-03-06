import { StatCards } from "@/components/dashboard/stat-cards"
import { RecentTranscriptions } from "@/components/dashboard/recent-transcriptions"
import { UsageChart } from "@/components/dashboard/usage-chart"
import { Card, Progress, Typography, Row, Col } from "antd"

const { Title, Text } = Typography

export default function DashboardPage() {
    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 24, padding: 24 }}>
            <StatCards />
            <Row gutter={24}>
                <Col xs={24} lg={15}>
                    <UsageChart />
                </Col>
                <Col xs={24} lg={9}>
                    <QuotaCard />
                </Col>
            </Row>
            <RecentTranscriptions />
        </div>
    )
}

function QuotaCard() {
    return (
        <Card
            title={<span style={{ color: '#e8e8e8' }}>Monthly Quota</span>}
            style={{ border: '1px solid #3a3a5c', height: '100%' }}
            styles={{ body: { display: 'flex', flexDirection: 'column', height: 'calc(100% - 57px)' } }}
        >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 16, flex: 1 }}>
                <QuotaItem label="Tokens" used={0} total={1500000} unit="tokens" />
                <QuotaItem label="Audio Duration" used={0} total={60} unit="hrs" />
                <QuotaItem label="API Calls" used={0} total={200} unit="calls" />
            </div>
            <div style={{
                marginTop: 'auto',
                borderRadius: 8,
                background: 'rgba(45, 212, 168, 0.05)',
                border: '1px solid rgba(45, 212, 168, 0.2)',
                padding: 12,
            }}>
                <Text style={{ fontSize: 12, color: '#8888a8' }}>
                    Current Plan: <Text style={{ fontWeight: 500, color: '#2dd4a8' }}>Pro</Text>
                </Text>
                <br />
                <Text style={{ fontSize: 12, color: '#8888a8' }}>
                    Resets on April 1, 2026
                </Text>
            </div>
        </Card>
    )
}

function QuotaItem({
    label,
    used,
    total,
    unit,
}) {
    const percentage = Math.round((used / total) * 100)
    const isHigh = percentage > 80

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13 }}>
                <Text style={{ color: '#8888a8' }}>{label}</Text>
                <Text style={{ color: '#e8e8e8', fontWeight: 500 }}>
                    {typeof used === "number" && used > 10000
                        ? `${(used / 1000000).toFixed(2)}M`
                        : used}{" "}
                    / {typeof total === "number" && total > 10000
                        ? `${(total / 1000000).toFixed(1)}M`
                        : total}{" "}
                    {unit}
                </Text>
            </div>
            <Progress
                percent={percentage}
                showInfo={false}
                strokeColor={isHigh ? '#d4a72d' : '#2dd4a8'}
                trailColor="#2a2a48"
                size="small"
            />
            <Text style={{ fontSize: 12, color: isHigh ? '#d4a72d' : '#8888a8' }}>
                {percentage}% used
            </Text>
        </div>
    )
}
