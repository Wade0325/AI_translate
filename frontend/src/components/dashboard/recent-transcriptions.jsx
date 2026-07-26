import { Card, Tag, Button, Typography, Empty } from "antd"
import { FileAudio } from "lucide-react"
import { Link } from "react-router-dom"
import { STATUS_META } from "@/constants/taskStatus"
import { formatDuration, formatDateTime } from "@/utils/formatters"

const { Text } = Typography

export function RecentTranscriptions({ items = [] }) {
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
            {items.length === 0 ? (
                <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description={<Text style={{ color: '#8888a8' }}>尚無轉錄紀錄</Text>}
                />
            ) : (
                <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                    {items.map((item) => {
                        const meta = STATUS_META[item.status] || { color: 'default', label: item.status }
                        return (
                            <div
                                key={item.task_uuid}
                                style={{
                                    display: 'flex',
                                    alignItems: 'center',
                                    gap: 16,
                                    borderRadius: 8,
                                    border: '1px solid #3a3a5c',
                                    background: 'rgba(42, 42, 72, 0.3)',
                                    padding: 12,
                                }}
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
                                            {item.original_filename || "(未命名)"}
                                        </Text>
                                        <Tag color={meta.color} style={{ fontSize: 11, marginRight: 0 }}>
                                            {meta.label}
                                        </Tag>
                                    </div>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#8888a8', flexWrap: 'wrap' }}>
                                        <span>{item.model_used || "—"}</span>
                                        {item.source_language && (
                                            <>
                                                <span>/</span>
                                                <span>{item.source_language}</span>
                                            </>
                                        )}
                                        {item.audio_duration_seconds > 0 && (
                                            <>
                                                <span>/</span>
                                                <span>{formatDuration(item.audio_duration_seconds)}</span>
                                            </>
                                        )}
                                        {item.request_timestamp && (
                                            <>
                                                <span>/</span>
                                                <span>{formatDateTime(item.request_timestamp)}</span>
                                            </>
                                        )}
                                    </div>
                                </div>
                                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
                                    <Text style={{ fontSize: 13, fontWeight: 500, color: '#e8e8e8' }}>
                                        {item.cost != null ? `$${item.cost.toFixed(4)}` : "—"}
                                    </Text>
                                    <Text style={{ fontSize: 12, color: '#8888a8' }}>
                                        {item.total_tokens != null ? `${item.total_tokens.toLocaleString()} tokens` : "—"}
                                    </Text>
                                </div>
                            </div>
                        )
                    })}
                </div>
            )}
        </Card>
    )
}
