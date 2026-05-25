import { Card, Spin, Tag, Typography } from "antd"
import { LoadingOutlined } from "@ant-design/icons"
import { AlertCircle, CheckCircle2, FileAudio, Loader2 } from "lucide-react"
import { formatDateTime } from "@/utils/formatters"

const { Text } = Typography

const STATUS_STYLE = {
    PROCESSING: { icon: Loader2, color: "#d4a72d", label: "處理中", spin: true },
    COMPLETED: { icon: CheckCircle2, color: "#2dd4a8", label: "已完成", spin: false },
    FAILED: { icon: AlertCircle, color: "#e05252", label: "失敗", spin: false },
}

export default function SingleTaskRow({ task }) {
    const sc = STATUS_STYLE[task.status] || STATUS_STYLE.PROCESSING
    const StatusIcon = sc.icon
    const timestamp = task.completed_at || task.request_timestamp

    return (
        <Card
            size="small"
            style={{
                border: `1px solid ${sc.color}4d`,
                background: "#1e1e3a",
            }}
            styles={{ body: { padding: "10px 14px" } }}
        >
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                <div
                    style={{
                        width: 30,
                        height: 30,
                        borderRadius: 8,
                        background: `${sc.color}1a`,
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        flexShrink: 0,
                    }}
                >
                    {sc.spin ? (
                        <Spin indicator={<LoadingOutlined style={{ fontSize: 14, color: sc.color }} spin />} />
                    ) : (
                        <StatusIcon size={14} color={sc.color} />
                    )}
                </div>

                <FileAudio size={14} color="#8888a8" style={{ flexShrink: 0 }} />

                <div style={{ flex: 1, minWidth: 0 }}>
                    <Text
                        ellipsis={{ tooltip: task.original_filename }}
                        style={{ color: "#e8e8e8", fontSize: 13, display: "block" }}
                    >
                        {task.original_filename || "(未命名)"}
                    </Text>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap", marginTop: 2 }}>
                        <Tag
                            style={{
                                fontSize: 11,
                                margin: 0,
                                border: `1px solid ${sc.color}40`,
                                color: sc.color,
                                background: `${sc.color}10`,
                            }}
                        >
                            {sc.label}
                        </Tag>
                        {task.model_used && (
                            <Text style={{ fontSize: 11, color: "#8888a8" }}>
                                {task.model_used}
                            </Text>
                        )}
                        {timestamp && (
                            <Text style={{ fontSize: 11, color: "#8888a8" }}>
                                · {formatDateTime(timestamp)}
                            </Text>
                        )}
                        {task.status === "COMPLETED" && task.total_tokens != null && (
                            <Text style={{ fontSize: 11, color: "#8888a8" }}>
                                · {task.total_tokens.toLocaleString()} tokens
                            </Text>
                        )}
                        {task.status === "COMPLETED" && task.cost != null && (
                            <Text style={{ fontSize: 11, color: "#8888a8" }}>
                                · ${task.cost.toFixed(4)}
                            </Text>
                        )}
                        {task.status === "FAILED" && task.error_message && (
                            <Text
                                ellipsis={{ tooltip: task.error_message }}
                                style={{ fontSize: 11, color: "#e05252", maxWidth: 360 }}
                            >
                                · {task.error_message}
                            </Text>
                        )}
                    </div>
                </div>
            </div>
        </Card>
    )
}
