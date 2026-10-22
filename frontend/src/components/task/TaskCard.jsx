import { Button, Card, Dropdown, Popconfirm, Space, Spin, Tag, Typography } from "antd"
import { LoadingOutlined } from "@ant-design/icons"
import {
    AlertCircle,
    CheckCircle2,
    ChevronDown,
    ChevronUp,
    Download,
    FileAudio,
    Loader2,
} from "lucide-react"
import { downloadFormats } from "@/constants/downloadFormats"
import { TASK_STATUS } from "@/constants/taskStatus"
import { formatDateTime, formatElapsed } from "@/utils/formatters"
import { isBatchFailed, isBatchInterrupted, isBatchProcessing } from "@/utils/taskSessions"

const { Text } = Typography

// 批次紀錄本身的狀態，屬於批次的狀態機（backend/app/core/batch_state.py），和任務狀態清單是兩回事（COMPLETED 只是同名）；
// 取回後逐檔結果的 status 才是任務狀態，用 TASK_STATUS 比對。UPLOADING_DEAD 與 INTERRUPTED 是停住的批次
// （看著它的任務不在了）只在畫面上用的名稱
const statusConfig = {
    POLLING: { icon: Loader2, color: "#d4a72d", label: "Gemini 處理中", spin: true },
    UPLOADING: { icon: Loader2, color: "#47b8d4", label: "上傳中", spin: true },
    UPLOADING_DEAD: { icon: AlertCircle, color: "#e05252", label: "上傳中斷", spin: false },
    INTERRUPTED: { icon: AlertCircle, color: "#d4a72d", label: "已中斷", spin: false },
    RECOVERING: { icon: Loader2, color: "#d4a72d", label: "恢復中", spin: true },
    COMPLETED: { icon: CheckCircle2, color: "#2dd4a8", label: "已完成", spin: false },
    RETRIEVED: { icon: CheckCircle2, color: "#2dd4a8", label: "已取回", spin: false },
    FAILED: { icon: AlertCircle, color: "#e05252", label: "失敗", spin: false },
}

// 停住或失敗的批次在狀態旁邊的說明；能不能恢復由後端決定（GET /batch/tasks 的 recoverable）
function stoppedNotice(displayStatus, recoverable) {
    switch (displayStatus) {
        case "UPLOADING_DEAD":
            return "Worker 已停止，任務無法完成"
        case "INTERRUPTED":
            return recoverable ? "沒有在等 Gemini 的結果，按「恢復」接著等" : "沒有在等 Gemini 的結果"
        case "FAILED":
            return recoverable ? "已送出給 Gemini，按「恢復」再查一次結果" : "原因見 History"
        default:
            return null
    }
}

export default function TaskCard({
    task,
    expanded,
    retrieving,
    resuming,
    taskResult,
    onToggleExpand,
    onRetrieve,
    onResume,
    onDismiss,
    onDownload,
}) {
    const interrupted = isBatchInterrupted(task)
    const stopped = interrupted || isBatchFailed(task)
    const displayStatus = interrupted
        ? (task.status === "UPLOADING" ? "UPLOADING_DEAD" : "INTERRUPTED")
        : task.status
    const sc = statusConfig[displayStatus] || statusConfig.POLLING
    const StatusIcon = sc.icon
    const notice = stoppedNotice(displayStatus, task.recoverable)
    const isProcessing = isBatchProcessing(task)
    const isCompleted = task.status === "COMPLETED"
    const hasResult = !!taskResult

    return (
        <Card
            size="small"
            style={{
                border: stopped
                    ? `1px solid ${sc.color}4d`
                    : isProcessing
                        ? "1px solid rgba(212, 167, 45, 0.3)"
                        : "1px solid rgba(45, 212, 168, 0.3)",
                background: "#1e1e3a",
            }}
            styles={{ body: { padding: 0 } }}
        >
            <div
                style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 12,
                    padding: "12px 16px",
                    cursor: hasResult ? "pointer" : "default",
                }}
                onClick={hasResult ? onToggleExpand : undefined}
            >
                <div style={{
                    width: 36,
                    height: 36,
                    borderRadius: 8,
                    background: `${sc.color}1a`,
                    display: "flex",
                    alignItems: "center",
                    justifyContent: "center",
                    flexShrink: 0,
                }}>
                    {sc.spin ? (
                        <Spin indicator={<LoadingOutlined style={{ fontSize: 16, color: sc.color }} spin />} />
                    ) : (
                        <StatusIcon size={16} color={sc.color} />
                    )}
                </div>

                <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                        <Text strong style={{ color: "#e8e8e8", fontSize: 13 }}>
                            {task.file_count} 個檔案
                        </Text>
                        <Tag
                            style={{
                                fontSize: 11,
                                border: `1px solid ${sc.color}40`,
                                color: sc.color,
                                background: `${sc.color}10`,
                            }}
                        >
                            {sc.label}
                        </Tag>
                        {task.created_at && (
                            <Text style={{ fontSize: 11, color: "#8888a8" }}>
                                建立於 {formatDateTime(task.created_at)}
                            </Text>
                        )}
                        {isProcessing && task.elapsed_seconds && (
                            <Text style={{ fontSize: 11, color: "#d4a72d" }}>
                                · 已等待 {formatElapsed(task.elapsed_seconds)}
                            </Text>
                        )}
                        {notice && (
                            <Text style={{ fontSize: 11, color: sc.color }}>
                                · {notice}
                            </Text>
                        )}
                    </div>
                    <Text style={{ fontSize: 11, color: "#686888" }} ellipsis>
                        ID: {task.batch_id.slice(0, 20)}...
                    </Text>
                </div>

                <Space size={4}>
                    {task.recoverable && (
                        <Button
                            size="small"
                            loading={resuming}
                            onClick={(e) => { e.stopPropagation(); onResume() }}
                            style={{ color: "#d4a72d", borderColor: "#d4a72d", fontSize: 12 }}
                        >
                            恢復
                        </Button>
                    )}
                    {isCompleted && (
                        <Button
                            type="primary"
                            size="small"
                            loading={retrieving}
                            onClick={(e) => { e.stopPropagation(); onRetrieve() }}
                            style={{ background: "#2dd4a8", borderColor: "#2dd4a8", fontSize: 12 }}
                        >
                            取回結果
                        </Button>
                    )}
                    {hasResult && (
                        <Button
                            type="text"
                            size="small"
                            onClick={(e) => { e.stopPropagation(); onToggleExpand() }}
                            style={{ color: "#8888a8" }}
                        >
                            {expanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                        </Button>
                    )}
                    <Popconfirm
                        title="確定要歸檔此任務？"
                        description="歸檔後可在 History 頁面查看紀錄"
                        onConfirm={(e) => { e?.stopPropagation(); onDismiss() }}
                        onCancel={(e) => e?.stopPropagation()}
                        okText="確定"
                        cancelText="取消"
                        placement="topRight"
                    >
                        <Button
                            size="small"
                            onClick={(e) => e.stopPropagation()}
                            style={{ fontSize: 12, color: "#8888a8", borderColor: "#3a3a5c" }}
                        >
                            歸檔
                        </Button>
                    </Popconfirm>
                </Space>
            </div>

            {expanded && hasResult && (
                <div style={{
                    borderTop: "1px solid #2a2a48",
                    padding: "8px 16px 12px",
                }}>
                    {taskResult.files.map((file, idx) => (
                        <div
                            key={file.file_uid || idx}
                            style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 10,
                                padding: "6px 0",
                                borderBottom: idx < taskResult.files.length - 1 ? "1px solid #2a2a4820" : "none",
                            }}
                        >
                            <FileAudio size={14} color={file.status === TASK_STATUS.COMPLETED ? "#2dd4a8" : "#e05252"} />
                            <Text ellipsis style={{ flex: 1, fontSize: 12, color: "#e8e8e8" }}>
                                {file.original_filename}
                            </Text>
                            <Tag
                                color={file.status === TASK_STATUS.COMPLETED ? "green" : "red"}
                                style={{ fontSize: 11, margin: 0 }}
                            >
                                {file.status === TASK_STATUS.COMPLETED ? "完成" : "失敗"}
                            </Tag>
                            {file.status === TASK_STATUS.COMPLETED && (
                                <Dropdown
                                    menu={{
                                        items: downloadFormats.map(f => ({
                                            key: f.key,
                                            label: f.label,
                                            onClick: () => onDownload(file, f.key),
                                        })),
                                    }}
                                    trigger={["click"]}
                                >
                                    <Button
                                        type="text"
                                        size="small"
                                        onClick={(e) => e.stopPropagation()}
                                        style={{ color: "#2dd4a8", fontSize: 11, display: "flex", alignItems: "center", gap: 4 }}
                                    >
                                        <Download size={12} /> 下載
                                    </Button>
                                </Dropdown>
                            )}
                        </div>
                    ))}
                </div>
            )}

            {expanded && !hasResult && task.files && task.files.length > 0 && (
                <div style={{
                    borderTop: "1px solid #2a2a48",
                    padding: "8px 16px 12px",
                }}>
                    {task.files.map((file, idx) => (
                        <div
                            key={file.file_uid || idx}
                            style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 10,
                                padding: "6px 0",
                                borderBottom: idx < task.files.length - 1 ? "1px solid #2a2a4820" : "none",
                            }}
                        >
                            <FileAudio size={14} color="#8888a8" />
                            <Text ellipsis style={{ flex: 1, fontSize: 12, color: "#bbb" }}>
                                {file.original_filename}
                            </Text>
                            {isProcessing && (
                                <Spin indicator={<LoadingOutlined style={{ fontSize: 12, color: "#d4a72d" }} spin />} />
                            )}
                        </div>
                    ))}
                </div>
            )}
        </Card>
    )
}
