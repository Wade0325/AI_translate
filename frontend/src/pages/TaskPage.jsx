import { useState, useEffect, useCallback, useRef } from "react"
import { Card, Button, Typography, Tag, Space, message, Empty, Spin, Popconfirm, Dropdown } from "antd"
import {
    Package,
    Clock,
    Download,
    ChevronDown,
    ChevronUp,
    CheckCircle2,
    Loader2,
    AlertCircle,
    RefreshCw,
    Archive,
    FileAudio,
} from "lucide-react"
import { ReloadOutlined, LoadingOutlined } from "@ant-design/icons"
import { useModelManager } from "@/components/ModelManager"

const { Text, Title } = Typography

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1"

const downloadFormats = [
    { key: "lrc", label: "LRC" },
    { key: "srt", label: "SRT" },
    { key: "vtt", label: "VTT" },
    { key: "txt", label: "TXT" },
]

const statusConfig = {
    POLLING: { icon: Loader2, color: "#d4a72d", label: "Gemini 處理中", spin: true },
    UPLOADING: { icon: Loader2, color: "#47b8d4", label: "上傳中", spin: true },
    UPLOADING_DEAD: { icon: AlertCircle, color: "#e05252", label: "上傳中斷", spin: false },
    RECOVERING: { icon: Loader2, color: "#d4a72d", label: "恢復中", spin: true },
    COMPLETED: { icon: CheckCircle2, color: "#2dd4a8", label: "已完成", spin: false },
    RETRIEVED: { icon: CheckCircle2, color: "#2dd4a8", label: "已取回", spin: false },
}

function formatElapsed(seconds) {
    if (!seconds || seconds < 0) return ""
    const m = Math.floor(seconds / 60)
    if (m < 1) return "剛剛"
    if (m < 60) return `${m} 分鐘前`
    const h = Math.floor(m / 60)
    if (h < 24) return `${h} 小時前`
    return `${Math.floor(h / 24)} 天前`
}

function formatDateTime(dateStr) {
    if (!dateStr) return ""
    try {
        return new Date(dateStr).toLocaleString("zh-TW", {
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
        })
    } catch {
        return dateStr
    }
}

export default function TaskPage() {
    const [tasks, setTasks] = useState([])
    const [loading, setLoading] = useState(true)
    const [retrievingIds, setRetrievingIds] = useState(new Set())
    const [expandedIds, setExpandedIds] = useState(new Set())
    const [taskResults, setTaskResults] = useState({})
    const pollIntervalRef = useRef(null)
    const { getProviderConfig } = useModelManager()

    const fetchTasks = useCallback(async () => {
        try {
            const resp = await fetch(`${API_BASE_URL}/batch/tasks`)
            if (resp.ok) {
                const data = await resp.json()
                setTasks(data)
            }
        } catch (err) {
            console.error("取得任務列表失敗:", err)
        } finally {
            setLoading(false)
        }
    }, [])

    const retrieveResults = async (batchId) => {
        setRetrievingIds(prev => new Set(prev).add(batchId))
        try {
            let resp = await fetch(`${API_BASE_URL}/batch/${batchId}/recover`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({}),
            })

            if (resp.status === 400) {
                const config = await getProviderConfig("Google")
                const apiKey = config?.apiKeys?.[0]
                if (!apiKey) {
                    message.error("請先在 Settings 中設定 Google API 金鑰")
                    return
                }
                resp = await fetch(`${API_BASE_URL}/batch/${batchId}/recover`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ api_keys: apiKey }),
                })
            }

            if (!resp.ok) {
                const errData = await resp.json().catch(() => ({}))
                throw new Error(errData.detail || `取回失敗 (${resp.status})`)
            }
            const result = await resp.json()

            if (result.files && result.files.length > 0) {
                setTaskResults(prev => ({ ...prev, [batchId]: result }))
                setExpandedIds(prev => new Set(prev).add(batchId))
                setTasks(prev => prev.map(t =>
                    t.batch_id === batchId ? { ...t, status: "RETRIEVED" } : t
                ))
                const completed = result.files.filter(f => f.status === "COMPLETED").length
                message.success(`已取回 ${completed} / ${result.files.length} 個檔案的結果`)
            } else {
                message.info("此批次仍在處理中，請稍後再試")
            }
        } catch (err) {
            message.error(`取回失敗: ${err.message}`)
        } finally {
            setRetrievingIds(prev => {
                const next = new Set(prev)
                next.delete(batchId)
                return next
            })
        }
    }

    const retrieveAllCompleted = async () => {
        const completedTasks = tasks.filter(t => t.status === "COMPLETED")
        if (completedTasks.length === 0) {
            message.info("沒有已完成的任務需要取回")
            return
        }
        await Promise.allSettled(
            completedTasks.map(t => retrieveResults(t.batch_id))
        )
    }

    const dismissTask = async (batchId) => {
        try {
            const resp = await fetch(`${API_BASE_URL}/batch/${batchId}/dismiss`, { method: "POST" })
            if (resp.ok) {
                setTasks(prev => prev.filter(t => t.batch_id !== batchId))
                setTaskResults(prev => {
                    const next = { ...prev }
                    delete next[batchId]
                    return next
                })
                message.success("已歸檔此任務")
            }
        } catch {
            message.error("歸檔失敗")
        }
    }

    const dismissAllTasks = async () => {
        const ids = tasks.map(t => t.batch_id)
        if (ids.length === 0) return
        const results = await Promise.allSettled(
            ids.map(id => fetch(`${API_BASE_URL}/batch/${id}/dismiss`, { method: "POST" }))
        )
        const successCount = results.filter(r => r.status === "fulfilled" && r.value.ok).length
        setTasks([])
        setTaskResults({})
        message.success(`已歸檔 ${successCount} 個任務`)
    }

    const downloadResult = (fileResult, format) => {
        const content = fileResult.result?.transcripts?.[format]
                     || fileResult.result?.[format]
        if (!content) {
            message.warning("此格式無可用內容")
            return
        }
        const blob = new Blob([content], { type: "text/plain;charset=utf-8" })
        const url = URL.createObjectURL(blob)
        const a = document.createElement("a")
        a.href = url
        a.download = `${fileResult.original_filename.replace(/\.[^.]+$/, "")}.${format}`
        document.body.appendChild(a)
        a.click()
        document.body.removeChild(a)
        URL.revokeObjectURL(url)
    }

    const toggleExpand = (batchId) => {
        setExpandedIds(prev => {
            const next = new Set(prev)
            next.has(batchId) ? next.delete(batchId) : next.add(batchId)
            return next
        })
    }

    useEffect(() => {
        fetchTasks()
    }, [fetchTasks])

    useEffect(() => {
        const hasPolling = tasks.some(t => t.status === "POLLING" || t.status === "UPLOADING" || t.status === "RECOVERING")
        if (hasPolling) {
            pollIntervalRef.current = setInterval(fetchTasks, 30000)
        } else {
            clearInterval(pollIntervalRef.current)
        }
        return () => clearInterval(pollIntervalRef.current)
    }, [tasks, fetchTasks])

    const processingTasks = tasks.filter(t => ["POLLING", "UPLOADING", "RECOVERING"].includes(t.status))
    const completedTasks = tasks.filter(t => ["COMPLETED", "RETRIEVED"].includes(t.status))

    if (loading) {
        return (
            <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 300 }}>
                <Spin indicator={<LoadingOutlined style={{ fontSize: 32, color: "#2dd4a8" }} spin />} />
            </div>
        )
    }

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 20, padding: 24 }}>
            {/* Top action bar */}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
                <Button
                    icon={<ReloadOutlined />}
                    onClick={() => { setLoading(true); fetchTasks() }}
                    style={{ color: "#8888a8", borderColor: "#3a3a5c" }}
                >
                    重新整理
                </Button>
                {completedTasks.some(t => t.status === "COMPLETED") && (
                    <Button
                        type="primary"
                        ghost
                        onClick={retrieveAllCompleted}
                        loading={retrievingIds.size > 0}
                        style={{ borderColor: "#2dd4a8", color: "#2dd4a8" }}
                    >
                        全部取回已完成
                    </Button>
                )}
                {tasks.length > 0 && (
                    <Popconfirm
                        title="確定要歸檔所有任務？"
                        description="歸檔後可在 History 頁面查看紀錄"
                        onConfirm={dismissAllTasks}
                        okText="確定"
                        cancelText="取消"
                        placement="bottomRight"
                    >
                        <Button
                            danger
                            ghost
                            icon={<Archive size={14} />}
                            style={{ display: "flex", alignItems: "center", gap: 4 }}
                        >
                            全部歸檔
                        </Button>
                    </Popconfirm>
                )}
            </div>

            {tasks.length === 0 && (
                <Card style={{ border: "1px solid #3a3a5c", background: "#1e1e3a" }}>
                    <Empty
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                        description={<Text style={{ color: "#8888a8" }}>目前沒有進行中或待取回的任務</Text>}
                    />
                </Card>
            )}

            {/* Processing section */}
            {processingTasks.length > 0 && (
                <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                        <Spin indicator={<LoadingOutlined style={{ fontSize: 14, color: "#d4a72d" }} spin />} />
                        <Text style={{ color: "#d4a72d", fontSize: 14, fontWeight: 600 }}>
                            處理中 ({processingTasks.length})
                        </Text>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                        {processingTasks.map(task => (
                            <TaskCard
                                key={task.batch_id}
                                task={task}
                                expanded={expandedIds.has(task.batch_id)}
                                retrieving={retrievingIds.has(task.batch_id)}
                                taskResult={taskResults[task.batch_id]}
                                onToggleExpand={() => toggleExpand(task.batch_id)}
                                onRetrieve={() => retrieveResults(task.batch_id)}
                                onDismiss={() => dismissTask(task.batch_id)}
                                onDownload={downloadResult}
                            />
                        ))}
                    </div>
                </div>
            )}

            {/* Completed section */}
            {completedTasks.length > 0 && (
                <div>
                    <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
                        <CheckCircle2 size={14} color="#2dd4a8" />
                        <Text style={{ color: "#2dd4a8", fontSize: 14, fontWeight: 600 }}>
                            已完成 ({completedTasks.length})
                        </Text>
                    </div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                        {completedTasks.map(task => (
                            <TaskCard
                                key={task.batch_id}
                                task={task}
                                expanded={expandedIds.has(task.batch_id)}
                                retrieving={retrievingIds.has(task.batch_id)}
                                taskResult={taskResults[task.batch_id]}
                                onToggleExpand={() => toggleExpand(task.batch_id)}
                                onRetrieve={() => retrieveResults(task.batch_id)}
                                onDismiss={() => dismissTask(task.batch_id)}
                                onDownload={downloadResult}
                            />
                        ))}
                    </div>
                </div>
            )}
        </div>
    )
}


function TaskCard({ task, expanded, retrieving, taskResult, onToggleExpand, onRetrieve, onDismiss, onDownload }) {
    const isDead = task.status === "UPLOADING" && task.is_alive === false
    const displayStatus = isDead ? "UPLOADING_DEAD" : task.status
    const sc = statusConfig[displayStatus] || statusConfig.POLLING
    const StatusIcon = sc.icon
    const isProcessing = ["POLLING", "UPLOADING", "RECOVERING"].includes(task.status) && !isDead
    const isCompleted = task.status === "COMPLETED"
    const isRetrieved = task.status === "RETRIEVED"
    const hasResult = !!taskResult

    return (
        <Card
            size="small"
            style={{
                border: isDead
                    ? "1px solid rgba(224, 82, 82, 0.3)"
                    : isProcessing
                        ? "1px solid rgba(212, 167, 45, 0.3)"
                        : "1px solid rgba(45, 212, 168, 0.3)",
                background: "#1e1e3a",
            }}
            styles={{ body: { padding: 0 } }}
        >
            {/* Header row */}
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
                {/* Status icon */}
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

                {/* Info */}
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
                        {isDead && (
                            <Text style={{ fontSize: 11, color: "#e05252" }}>
                                · Worker 已停止，任務無法完成
                            </Text>
                        )}
                    </div>
                    <Text style={{ fontSize: 11, color: "#6868888" }} ellipsis>
                        ID: {task.batch_id.slice(0, 20)}...
                    </Text>
                </div>

                {/* Actions */}
                <Space size={4}>
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

            {/* Expanded file list */}
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
                            <FileAudio size={14} color={file.status === "COMPLETED" ? "#2dd4a8" : "#e05252"} />
                            <Text ellipsis style={{ flex: 1, fontSize: 12, color: "#e8e8e8" }}>
                                {file.original_filename}
                            </Text>
                            <Tag
                                color={file.status === "COMPLETED" ? "green" : "red"}
                                style={{ fontSize: 11, margin: 0 }}
                            >
                                {file.status === "COMPLETED" ? "完成" : "失敗"}
                            </Tag>
                            {file.status === "COMPLETED" && (
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

            {/* Expanded file list for tasks without results (show file names) */}
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
