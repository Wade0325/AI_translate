import { useState, useEffect, useCallback, useRef, useMemo } from "react"
import { Card, Button, Typography, message, Empty, Spin, Popconfirm } from "antd"
import { Archive } from "lucide-react"
import { ReloadOutlined, LoadingOutlined } from "@ant-design/icons"
import { useModelManager } from "@/components/ModelManager"
import { api, ApiError } from "../services/api"
import TaskCard from "@/components/task/TaskCard"
import SingleTaskRow from "@/components/task/SingleTaskRow"
import TaskSessionDivider from "@/components/task/TaskSessionDivider"
import {
    buildTaskSessions,
    isBatchProcessing,
    isBatchCompleted,
    isSingleProcessing,
    isSingleCompleted,
    sessionHasProcessing,
} from "@/utils/taskSessions"

const { Text } = Typography

export default function TaskPage() {
    const [tasks, setTasks] = useState([])
    const [singleTasks, setSingleTasks] = useState([])
    const [loading, setLoading] = useState(true)
    const [retrievingIds, setRetrievingIds] = useState(new Set())
    const [expandedIds, setExpandedIds] = useState(new Set())
    const [taskResults, setTaskResults] = useState({})
    const pollIntervalRef = useRef(null)
    const { getProviderConfig } = useModelManager()

    const fetchTasks = useCallback(async () => {
        try {
            const [batchData, singleData] = await Promise.all([
                api.batch.tasks(),
                api.history.activeSingle({ hours: 6 }),
            ])
            setTasks(batchData)
            setSingleTasks(singleData)
        } catch (err) {
            console.error("取得任務列表失敗:", err)
        } finally {
            setLoading(false)
        }
    }, [])

    const sessions = useMemo(
        () => buildTaskSessions(tasks, singleTasks),
        [tasks, singleTasks]
    )

    const retrieveResults = async (batchId) => {
        setRetrievingIds(prev => new Set(prev).add(batchId))
        try {
            let result
            try {
                result = await api.batch.recover(batchId, {})
            } catch (err) {
                if (err instanceof ApiError && err.status === 400) {
                    const config = await getProviderConfig("Google")
                    const apiKey = config?.apiKeys?.[0]
                    if (!apiKey) {
                        message.error("請先在 Settings 中設定 Google API 金鑰")
                        return
                    }
                    result = await api.batch.recover(batchId, { api_keys: apiKey })
                } else {
                    throw err
                }
            }

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
            await api.batch.dismiss(batchId)
            setTasks(prev => prev.filter(t => t.batch_id !== batchId))
            setTaskResults(prev => {
                const next = { ...prev }
                delete next[batchId]
                return next
            })
            message.success("已歸檔此任務")
        } catch {
            message.error("歸檔失敗")
        }
    }

    const dismissAllTasks = async () => {
        const ids = tasks.map(t => t.batch_id)
        if (ids.length === 0) return
        const results = await Promise.allSettled(
            ids.map(id => api.batch.dismiss(id))
        )
        const successCount = results.filter(r => r.status === "fulfilled").length
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
        const hasBatchPolling = tasks.some(t => isBatchProcessing(t))
        const hasSinglePolling = singleTasks.some(t => isSingleProcessing(t))
        if (hasBatchPolling || hasSinglePolling) {
            pollIntervalRef.current = setInterval(fetchTasks, hasSinglePolling ? 5000 : 30000)
        } else {
            clearInterval(pollIntervalRef.current)
        }
        return () => clearInterval(pollIntervalRef.current)
    }, [tasks, singleTasks, fetchTasks])

    const hasAny = sessions.length > 0
    const hasAnyProcessing = sessions.some(sessionHasProcessing)
    const completedBatchCount = tasks.filter(t => t.status === "COMPLETED").length

    const renderSessionItem = (item) => {
        if (item.kind === "batch") {
            const task = item.task
            const showBatch =
                isBatchProcessing(task) || isBatchCompleted(task)
            if (!showBatch) return null
            return (
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
            )
        }
        const task = item.task
        if (!isSingleProcessing(task) && !isSingleCompleted(task)) return null
        return <SingleTaskRow key={task.task_uuid} task={task} />
    }

    if (loading) {
        return (
            <div style={{ display: "flex", justifyContent: "center", alignItems: "center", height: 300 }}>
                <Spin indicator={<LoadingOutlined style={{ fontSize: 32, color: "#2dd4a8" }} spin />} />
            </div>
        )
    }

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 20, padding: 24 }}>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
                <Button
                    icon={<ReloadOutlined />}
                    onClick={() => { setLoading(true); fetchTasks() }}
                    style={{ color: "#8888a8", borderColor: "#3a3a5c" }}
                >
                    重新整理
                </Button>
                {completedBatchCount > 0 && (
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

            {!hasAny && (
                <Card style={{ border: "1px solid #3a3a5c", background: "#1e1e3a" }}>
                    <Empty
                        image={Empty.PRESENTED_IMAGE_SIMPLE}
                        description={<Text style={{ color: "#8888a8" }}>目前沒有進行中或最近完成的任務</Text>}
                    />
                </Card>
            )}

            {hasAnyProcessing && (
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <Spin indicator={<LoadingOutlined style={{ fontSize: 14, color: "#d4a72d" }} spin />} />
                    <Text style={{ color: "#d4a72d", fontSize: 13 }}>有任務處理中，將自動更新</Text>
                </div>
            )}

            {sessions.map((session, idx) => (
                <div key={session.sessionId}>
                    <TaskSessionDivider
                        showTopMargin={idx > 0}
                        startedAt={session.startedAt}
                        fileCount={session.fileCount}
                    />
                    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                        {session.items.map((item) => renderSessionItem(item))}
                    </div>
                </div>
            ))}
        </div>
    )
}
