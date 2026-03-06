import { Card, Tag, Button, Typography } from "antd"
import { FileAudio, ExternalLink } from "lucide-react"
import { Link } from "react-router-dom"

const { Text } = Typography

const recentItems = []

const statusColor = {
    completed: "green",
    processing: "blue",
    failed: "red",
}

const statusLabel = {
    completed: "Completed",
    processing: "Processing",
    failed: "Failed",
}

export function RecentTranscriptions() {
    return (
        <Card
            title={<span style={{ color: '#e8e8e8' }}>Recent Transcriptions</span>}
            extra={
                <Link to="/history">
                    <Button type="link" style={{ color: '#2dd4a8', padding: 0 }}>View all</Button>
                </Link>
            }
            style={{ border: '1px solid #3a3a5c' }}
        >
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {recentItems.map((item) => (
                    <div
                        key={item.id}
                        style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: 16,
                            borderRadius: 8,
                            border: '1px solid #3a3a5c',
                            background: 'rgba(42, 42, 72, 0.3)',
                            padding: 12,
                            transition: 'background 0.2s',
                        }}
                        onMouseEnter={(e) => { e.currentTarget.style.background = 'rgba(42, 42, 72, 0.6)' }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = 'rgba(42, 42, 72, 0.3)' }}
                    >
                        <div style={{
                            width: 40,
                            height: 40,
                            flexShrink: 0,
                            borderRadius: 8,
                            background: 'rgba(45, 212, 168, 0.1)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                        }}>
                            <FileAudio size={20} color="#2dd4a8" />
                        </div>
                        <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 4 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                <Text
                                    ellipsis
                                    style={{ fontSize: 13, fontWeight: 500, color: '#e8e8e8' }}
                                >
                                    {item.name}
                                </Text>
                                <Tag color={statusColor[item.status]} style={{ fontSize: 11, marginRight: 0 }}>
                                    {statusLabel[item.status]}
                                </Tag>
                            </div>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#8888a8' }}>
                                <span>{item.language}</span>
                                <span>/</span>
                                <span>{item.speakers > 1 ? `${item.speakers} speakers` : "Single speaker"}</span>
                                <span>/</span>
                                <span>{item.duration}</span>
                            </div>
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
                            <Text style={{ fontSize: 13, fontWeight: 500, color: '#e8e8e8' }}>{item.cost}</Text>
                            <Text style={{ fontSize: 12, color: '#8888a8' }}>
                                {item.tokens.toLocaleString()} tokens
                            </Text>
                        </div>
                        <Link to="/result">
                            <Button
                                type="text"
                                size="small"
                                icon={<ExternalLink size={16} />}
                                style={{ color: '#8888a8' }}
                            />
                        </Link>
                    </div>
                ))}
            </div>
        </Card>
    )
}
