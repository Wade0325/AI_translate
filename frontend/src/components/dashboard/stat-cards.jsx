import { Card, Statistic, Row, Col } from "antd"
import {
    FileAudio,
    Clock,
    Coins,
    TrendingUp,
} from "lucide-react"

const stats = [
    {
        title: "Total Transcriptions",
        value: "0",
        change: "No activity yet",
        icon: FileAudio,
        iconColor: "#2dd4a8",
        bgColor: "rgba(45, 212, 168, 0.1)",
    },
    {
        title: "Total Duration",
        value: "0 hrs",
        change: "No activity yet",
        icon: Clock,
        iconColor: "#47b8d4",
        bgColor: "rgba(71, 184, 212, 0.1)",
    },
    {
        title: "Tokens Used",
        value: "0",
        change: "0% of monthly quota",
        icon: Coins,
        iconColor: "#d4a72d",
        bgColor: "rgba(212, 167, 45, 0.1)",
    },
    {
        title: "Total Cost",
        value: "$0.00",
        change: "$0.00 this week",
        icon: TrendingUp,
        iconColor: "#8b5cf6",
        bgColor: "rgba(139, 92, 246, 0.1)",
    },
]

export function StatCards() {
    return (
        <Row gutter={[16, 16]}>
            {stats.map((stat) => (
                <Col key={stat.title} xs={24} sm={12} lg={6}>
                    <Card
                        size="small"
                        style={{ border: '1px solid #3a3a5c' }}
                        styles={{ body: { padding: '20px' } }}
                    >
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                            <div>
                                <div style={{ color: '#8888a8', fontSize: 13, marginBottom: 8 }}>{stat.title}</div>
                                <div style={{ fontSize: 24, fontWeight: 700, color: '#e8e8e8' }}>{stat.value}</div>
                                <div style={{ color: '#8888a8', fontSize: 12, marginTop: 4 }}>{stat.change}</div>
                            </div>
                            <div style={{
                                width: 36,
                                height: 36,
                                borderRadius: 8,
                                background: stat.bgColor,
                                display: 'flex',
                                alignItems: 'center',
                                justifyContent: 'center',
                            }}>
                                <stat.icon size={16} color={stat.iconColor} />
                            </div>
                        </div>
                    </Card>
                </Col>
            ))}
        </Row>
    )
}
