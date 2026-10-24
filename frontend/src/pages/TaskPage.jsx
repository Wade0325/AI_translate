// @ts-nocheck
import { useState, useEffect, useCallback, useRef, useMemo } from "react"
import { Card, Button, Typography, message, Empty, Spin, Popconfirm } from "antd"
import { Archive } from "lucide-react"
import { ReloadOutlined, LoadingOutlined } from "@ant-design/icons"
import { api } from "../services/api"
import { downloadBlob, renameExtension } from "../utils/download"
import TaskCard from "@/components/task/TaskCard"
import SingleTaskRow from "@/components/task/SingleTaskRow"
import TaskSessionDivider from "@/components/task/TaskSessionDivider"
import { TASK_STATUS } from "@/constants/taskStatus"
import {
    buildTaskSessions,
    isBatchProcessing,
    isBatchInterrupted,
    isBatchCompleted,
    isBatchFailed,
    isSingleProcessing,
    isSingleCompleted,
    sessionHasProcessing,
} from "@/utils/taskSessions"

const { Text } = Typography

// 請求還沒回來的批次 id 記在 setIds 管的集合裡（卡片的按鈕顯示載入中），請求結束就拿掉
async function whilePending(setIds, batchId, request) {
    setIds(prev => new Set(prev).add(batchId))
    try {
        await request()
    } finally {
        setIds(prev => {
            const next = new Set(prev)
            next.delete(batchId)
            return next
        })
    }
}

export default function TaskPage() {
    const [tasks, setTasks] = useState([])
    const [singleTasks, setSingleTasks] = useState([])
    const [loading, setLoading] = useState(true)
    const [retrievingIds, setRetrievingIds] = useState(new Set())
    const [recoveringIds, setRecoveringIds] = useState(new Set())
    const [expandedIds, setExpandedIds] = useState(new Set())
    const [taskResults, setTaskResults] = useState({})
    const pollIntervalRef = useRef(null)

    const fetchTasks = useCallback(async () => {
        try {
            const [batchData, singleData] = await Promise.all([
                api.batch.tasks(),
                api.history.activeSingle({ hours: 24 }),
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

    // 取回結果與恢復都呼叫復原端點（POST /batch/{id}/recover）：完成的批次回結果，沒有任務看著的批次
    // 由復原入口接手。金鑰由後端從資料庫取用；尚未設定時後端回 400 並提示先到 Settings 設定
    const retrieveResults = (batchId) => whilePending(setRetrievingIds, batchId, async () => {
        try {
            const result = await api.batch.recover(batchId, {})

            if (result.files && result.files.length > 0) {
                setTaskResults(prev => ({ ...prev, [batchId]: result }))
                setExpandedIds(prev => new Set(prev).add(batchId))
                setTasks(prev => prev.map(t =>
                    t.batch_id === batchId ? { ...t, status: "RETRIEVED" } : t
                ))
                const completed = result.files.filter(f => f.status === TASK_STATUS.COMPLETED).length
                message.success(`已取回 ${completed} / ${result.files.length} 個檔案的結果`)
            } else {
                message.info("此批次仍在處理中，請稍後再試")
            }
        } catch (err) {
            message.error(`取回失敗: ${err.message}`)
        }
    })

    // 停住或失敗的批次：接著等到批次結束，之後再取回結果
    const recoverBatch = (batchId) => whilePending(setRecoveringIds, batchId, async () => {
        try {
            await api.batch.recover(batchId, {})
            message.success("已開始恢復，批次結束後就能取回結果")
            await fetchTasks()
        } catch (err) {
            message.error(`恢復失敗: ${err.message}`)
        }
    })

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
        downloadBlob(content, renameExtension(fileResult.original_filename, format))
    }

    const toggleExpand = (batchId) => {
        setExpandedIds(prev => {
            const next = new Set(prev)
            if (next.has(batchId)) {
                next.delete(batchId)
            } else {
                next.add(batchId)
            }
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
            const showBatch = isBatchProcessing(task) || isBatchInterrupted(task)
                || isBatchCompleted(task) || isBatchFailed(task)
            if (!showBatch) return null
            return (
                <TaskCard
                    key={task.batch_id}
                    task={task}
                    expanded={expandedIds.has(task.batch_id)}
                    retrieving={retrievingIds.has(task.batch_id)}
                    recovering={recoveringIds.has(task.batch_id)}
                    taskResult={taskResults[task.batch_id]}
                    onToggleExpand={() => toggleExpand(task.batch_id)}
                    onRetrieve={() => retrieveResults(task.batch_id)}
                    onRecover={() => recoverBatch(task.batch_id)}
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
