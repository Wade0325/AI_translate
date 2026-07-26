import { Row, Col } from "antd"
import {
    FileAudio,
    Clock,
    Coins,
    TrendingUp,
} from "lucide-react"
import { StatCard } from "@/components/StatCard"

export function StatCards({ stats }) {
    const s = stats || {
        total_tasks: 0,
        completed_tasks: 0,
        failed_tasks: 0,
        success_rate: 0,
        total_tokens: 0,
        total_cost: 0,
        total_audio_duration_seconds: 0,
        avg_processing_time_seconds: 0,
    }

    const cards = [
        {
            title: "Total Transcriptions",
            value: s.total_tasks.toLocaleString(),
            subtitle: `${s.completed_tasks} completed · ${s.failed_tasks} failed`,
            icon: FileAudio,
            iconColor: "#2dd4a8",
            bgColor: "rgba(45, 212, 168, 0.1)",
        },
        {
            title: "Total Audio Duration",
            value: `${(s.total_audio_duration_seconds / 3600).toFixed(1)} hrs`,
            subtitle: `avg processing ${s.avg_processing_time_seconds.toFixed(0)}s / file`,
            icon: Clock,
            iconColor: "#47b8d4",
            bgColor: "rgba(71, 184, 212, 0.1)",
        },
        {
            title: "Tokens Used",
            value: s.total_tokens.toLocaleString(),
            icon: Coins,
            iconColor: "#d4a72d",
            bgColor: "rgba(212, 167, 45, 0.1)",
        },
        {
            title: "Total Cost",
            value: `$${s.total_cost.toFixed(4)}`,
            subtitle: `success rate ${s.success_rate}%`,
            icon: TrendingUp,
            iconColor: "#8b5cf6",
            bgColor: "rgba(139, 92, 246, 0.1)",
        },
    ]

    return (
        <Row gutter={[16, 16]}>
            {cards.map((card) => (
                <Col key={card.title} xs={24} sm={12} lg={6}>
                    <StatCard {...card} />
                </Col>
            ))}
        </Row>
    )
}
