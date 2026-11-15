// @ts-nocheck
import { useState, useEffect, useCallback } from "react"
import { Card, Table, Button, Input, Select, Tag, Typography, Row, Col, Popconfirm, message, Space, Tooltip } from "antd"
import {
    SearchOutlined,
    DeleteOutlined,
    ReloadOutlined,
    FileTextOutlined,
    DownloadOutlined,
    EditOutlined,
} from "@ant-design/icons"
import { Link } from "react-router-dom"
import { FileAudio, Coins, Clock, TrendingUp } from "lucide-react"
import { api } from "../services/api"
import { StatCard } from "../components/StatCard"
import { STATUS_META, TASK_STATUS } from "../constants/taskStatus"
import { FailureSummary } from "../components/FailureNotice"
import { TailLossSummary } from "../components/TailLossNotice"
import { failureOf } from "../utils/failure"
import { correctionPath } from "../utils/correction"
import { TranscriptDownloadMenu } from "../components/transcript-download-menu"

const { Text } = Typography

/** 寫在檔名下面的一行（失敗的原因、可能掉尾）：和檔名的文字對齊。 */
const UNDER_FILENAME = { display: "block", maxWidth: 250, marginLeft: 22, fontSize: 12 }

export default function HistoryPage() {
    const [historyData, setHistoryData] = useState([])
    const [loading, setLoading] = useState(false)
    const [pagination, setPagination] = useState({ current: 1, pageSize: 10, total: 0 })
    const [searchKeyword, setSearchKeyword] = useState("")
    const [statusFilter, setStatusFilter] = useState(null)
    const [modeFilter, setModeFilter] = useState(null)
    const [stats, setStats] = useState({ total_tasks: 0, completed_tasks: 0, failed_tasks: 0, success_rate: 0, total_cost: 0, total_tokens: 0 })

    const fetchHistory = useCallback(async (page = 1, pageSize = 10, overrides = {}) => {
        setLoading(true)
        const keyword = "keyword" in overrides ? overrides.keyword : searchKeyword
        const status = "status" in overrides ? overrides.status : statusFilter
        const mode = "mode" in overrides ? overrides.mode : modeFilter
        try {
            const data = await api.history.list({
                page,
                pageSize,
                keyword: keyword || undefined,
                status: status || undefined,
                mode: mode || undefined,
            })
            setHistoryData(data.items || [])
            setPagination({ current: page, pageSize, total: data.total || 0 })
        } catch (error) {
            console.error("Error fetching history:", error)
            setHistoryData([])
        } finally {
            setLoading(false)
        }
    }, [searchKeyword, statusFilter, modeFilter])

    const fetchStats = useCallback(async () => {
        try {
            const data = await api.history.stats()
            setStats(data)
        } catch (error) {
            console.error("Error fetching stats:", error)
        }
    }, [])

    useEffect(() => {
        fetchStats()
    }, [fetchStats])

    // 下拉篩選改變時自動查詢；關鍵字只在按下搜尋 / Enter 時查詢，避免逐字打 API
    useEffect(() => {
        fetchHistory(1, pagination.pageSize)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [statusFilter, modeFilter])

    const handleDelete = async (taskUuid) => {
        try {
            await api.history.delete(taskUuid)
            message.success("紀錄已刪除")
            fetchHistory(pagination.current, pagination.pageSize)
            fetchStats()
        } catch (error) {
            console.error("刪除時發生錯誤:", error)
            message.error("刪除失敗")
        }
    }

    const handleTableChange = (pag) => {
        fetchHistory(pag.current, pag.pageSize)
    }

    const handleSearch = () => {
        fetchHistory(1, pagination.pageSize)
    }

    const columns = [
        {
            title: "檔案名稱",
            dataIndex: "original_filename",
            key: "original_filename",
            ellipsis: true,
            render: (v, record) => (
                <>
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <FileTextOutlined style={{ color: "#2dd4a8" }} />
                        <Text ellipsis style={{ color: "#e8e8e8", maxWidth: 250 }}>{v || "—"}</Text>
                        {/* 有校正紀錄的任務（改回原樣的也算）：找得到哪些已經校過（#348） */}
                        {record.has_corrections && (
                            <Tag color="gold" style={{ marginInlineEnd: 0, fontSize: 11, lineHeight: "18px" }}>有校正</Tag>
                        )}
                    </div>
                    {/* 失敗的原因寫在檔名下面，滑過去看下一步、錯誤碼與細節 */}
                    {record.status === TASK_STATUS.FAILED && (record.error_code || record.error_message) && (
                        <FailureSummary
                            failure={failureOf(record)}
                            style={UNDER_FILENAME}
                        />
                    )}
                    {/* 完成了，轉錄結果卻可能少了一段（#257）：滑過去看下一步 */}
                    {record.status === TASK_STATUS.COMPLETED && (
                        <TailLossSummary
                            seconds={record.tail_loss_from_seconds}
                            style={UNDER_FILENAME}
                        />
                    )}
                </>
            ),
        },
        {
            title: "狀態",
            dataIndex: "status",
            key: "status",
            width: 100,
            render: (v) => (
                <Tag color={STATUS_META[v]?.color || "default"}>
                    {STATUS_META[v]?.label || v || "—"}
                </Tag>
            ),
        },
        {
            title: "模式",
            key: "processing_mode",
            width: 90,
            render: (_, record) => {
                if (record.is_batch) {
                    return <Tag style={{ fontSize: 11 }}>批次</Tag>
                }
                if (record.service_tier_used === "flex") {
                    return (
                        <Tag style={{ fontSize: 11, color: "#47b8d4", borderColor: "#47b8d480" }}>
                            Flex
                        </Tag>
                    )
                }
                return <Tag style={{ fontSize: 11 }}>標準</Tag>
            },
        },
        {
            title: "模型",
            dataIndex: "model_used",
            key: "model_used",
            width: 160,
            render: (v) => <Text style={{ color: "#8888a8", fontSize: 12 }}>{v || "—"}</Text>,
        },
        {
            title: "語言",
            dataIndex: "source_language",
            key: "source_language",
            width: 80,
            render: (v) => <Text style={{ color: "#8888a8", fontSize: 12 }}>{v || "—"}</Text>,
        },
        {
            title: "Tokens",
            dataIndex: "total_tokens",
            key: "total_tokens",
            width: 100,
            render: (v) => (
                <Text style={{ color: "#e8e8e8", fontFamily: "monospace", fontSize: 12 }}>
                    {v ? v.toLocaleString() : "—"}
                </Text>
            ),
        },
        {
            title: "費用",
            dataIndex: "cost",
            key: "cost",
            width: 90,
            render: (v) => (
                <Text style={{ color: "#2dd4a8", fontWeight: 500, fontSize: 12 }}>
                    {v != null ? `$${v.toFixed(4)}` : "—"}
                </Text>
            ),
        },
        {
            title: "時間",
            dataIndex: "request_timestamp",
            key: "request_timestamp",
            width: 150,
            render: (v) => (
                <Text style={{ color: "#8888a8", fontSize: 12 }}>
                    {v ? new Date(v).toLocaleString("zh-TW") : "—"}
                </Text>
            ),
        },
        {
            title: "",
            key: "actions",
            width: 100,
            fixed: "right",
            render: (_, record) => (
                <Space size={0}>
                    {/* 能校正的任務才有入口：已完成、有片段、不是轉錄並翻譯的任務，由後端判斷（#347）。和旁邊一樣只放圖示，
                        這一欄不變寬：視窗窄的時候檔名那一欄已經只剩幾個字 */}
                    {record.correctable && (
                        <Tooltip title="校正">
                            <Link
                                to={correctionPath(record.task_uuid)}
                                aria-label="校正"
                                style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", width: 24, height: 24, color: "#2dd4a8" }}
                            >
                                <EditOutlined />
                            </Link>
                        </Tooltip>
                    )}
                    {/* 有校正的任務多一組「原始轉錄」；沒有校正的任務和以前一樣只有四種輸出格式（#346） */}
                    {record.status === TASK_STATUS.COMPLETED && (
                        <TranscriptDownloadMenu
                            taskUuid={record.task_uuid}
                            fileName={record.original_filename}
                            withOriginal={record.has_corrections}
                        >
                            <Tooltip title="下載轉錄結果">
                                <Button
                                    type="text"
                                    size="small"
                                    icon={<DownloadOutlined />}
                                    style={{ color: "#2dd4a8" }}
                                />
                            </Tooltip>
                        </TranscriptDownloadMenu>
                    )}
                    {/* 校正紀錄跟著任務一起刪（#25 故事 81），有校正的任務先說清楚（#348） */}
                    <Popconfirm
                        title="確定刪除此紀錄？"
                        description={record.has_corrections ? "這個任務的校正會一起刪掉" : undefined}
                        onConfirm={() => handleDelete(record.task_uuid)}
                        okText="確定"
                        cancelText="取消"
                    >
                        <Button type="text" size="small" icon={<DeleteOutlined />} danger style={{ color: "#8888a8" }} />
                    </Popconfirm>
                </Space>
            ),
        },
    ]

    // 成功率照後端算：完成 /（完成＋失敗），處理中與已取消的不算（#18）
    const successRate = stats.success_rate.toFixed(1)

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 24, padding: 24 }}>
            <Row gutter={[16, 16]}>
                <Col xs={24} sm={12} lg={6}>
                    <StatCard
                        title="總任務數"
                        value={stats.total_tasks}
                        icon={FileAudio}
                        iconColor="#2dd4a8"
                        bgColor="rgba(45, 212, 168, 0.1)"
                    />
                </Col>
                <Col xs={24} sm={12} lg={6}>
                    <StatCard
                        title="成功率"
                        value={`${successRate}%`}
                        subtitle={`${stats.completed_tasks} 完成 / ${stats.failed_tasks} 失敗`}
                        icon={TrendingUp}
                        iconColor="#47b8d4"
                        bgColor="rgba(71, 184, 212, 0.1)"
                    />
                </Col>
                <Col xs={24} sm={12} lg={6}>
                    <StatCard
                        title="總 Tokens"
                        value={(stats.total_tokens || 0).toLocaleString()}
                        icon={Clock}
                        iconColor="#d4a72d"
                        bgColor="rgba(212, 167, 45, 0.1)"
                    />
                </Col>
                <Col xs={24} sm={12} lg={6}>
                    <StatCard
                        title="總費用"
                        value={`$${(stats.total_cost || 0).toFixed(4)}`}
                        valueColor="#2dd4a8"
                        icon={Coins}
                        iconColor="#8b5cf6"
                        bgColor="rgba(139, 92, 246, 0.1)"
                    />
                </Col>
            </Row>

            <Card size="small" style={{ border: "1px solid #3a3a5c" }} styles={{ body: { padding: "12px 16px" } }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                    <Input
                        placeholder="搜尋檔案名稱..."
                        prefix={<SearchOutlined style={{ color: "#8888a8" }} />}
                        value={searchKeyword}
                        onChange={(e) => {
                            const value = e.target.value
                            setSearchKeyword(value)
                            // 按 allowClear 的 × 或刪到空字串時立即還原列表（輸入中不逐字查詢）
                            if (value === "" && searchKeyword !== "") {
                                fetchHistory(1, pagination.pageSize, { keyword: "" })
                            }
                        }}
                        onPressEnter={handleSearch}
                        style={{ flex: 1, minWidth: 200 }}
                        allowClear
                    />
                    <Select
                        placeholder="狀態"
                        value={statusFilter}
                        onChange={setStatusFilter}
                        style={{ width: 120 }}
                        allowClear
                        options={Object.entries(STATUS_META).map(([value, { label }]) => ({ value, label }))}
                    />
                    <Select
                        placeholder="模式"
                        value={modeFilter}
                        onChange={setModeFilter}
                        style={{ width: 120 }}
                        allowClear
                        options={[
                            { value: "regular", label: "標準" },
                            { value: "batch", label: "批次" },
                        ]}
                    />
                    <Button icon={<SearchOutlined />} onClick={handleSearch}>
                        搜尋
                    </Button>
                    <Button
                        icon={<ReloadOutlined />}
                        onClick={() => {
                            // 篩選有值時，setState 會觸發 [statusFilter, modeFilter] effect 重新查詢；
                            // 只有兩者皆空（effect 不會觸發）才需要自己補一次查詢，避免重複請求競態
                            const filtersActive = statusFilter !== null || modeFilter !== null
                            setSearchKeyword("")
                            setStatusFilter(null)
                            setModeFilter(null)
                            if (!filtersActive) {
                                fetchHistory(1, pagination.pageSize, { keyword: "" })
                            }
                            fetchStats()
                        }}
                    >
                        重置
                    </Button>
                </div>
            </Card>

            <Card style={{ border: "1px solid #3a3a5c" }} styles={{ body: { padding: 0 } }}>
                <Table
                    columns={columns}
                    dataSource={historyData}
                    rowKey={(record) => record.task_uuid || record.id}
                    loading={loading}
                    pagination={{
                        current: pagination.current,
                        pageSize: pagination.pageSize,
                        total: pagination.total,
                        showSizeChanger: true,
                        showTotal: (total) => `共 ${total} 筆`,
                    }}
                    onChange={handleTableChange}
                    size="small"
                    scroll={{ x: 900 }}
                />
            </Card>
        </div>
    )
}
