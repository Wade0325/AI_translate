import { useState, useEffect, useCallback } from "react"
import { Card, Table, Button, Input, Select, Tag, Typography, Row, Col, Statistic, Popconfirm, message, Space, Tooltip } from "antd"
import {
    SearchOutlined,
    DeleteOutlined,
    ReloadOutlined,
    CheckCircleOutlined,
    CloseCircleOutlined,
    ClockCircleOutlined,
    FileTextOutlined,
} from "@ant-design/icons"
import { FileAudio, Coins, Clock, TrendingUp } from "lucide-react"

const { Text } = Typography

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "/api/v1"

export default function HistoryPage() {
    const [historyData, setHistoryData] = useState([])
    const [loading, setLoading] = useState(false)
    const [pagination, setPagination] = useState({ current: 1, pageSize: 10, total: 0 })
    const [searchKeyword, setSearchKeyword] = useState("")
    const [statusFilter, setStatusFilter] = useState(null)
    const [modeFilter, setModeFilter] = useState(null)
    const [stats, setStats] = useState({ total: 0, completed: 0, failed: 0, total_cost: 0, total_tokens: 0 })

    // Fetch history data
    const fetchHistory = useCallback(async (page = 1, pageSize = 10) => {
        setLoading(true)
        try {
            const params = new URLSearchParams({
                page: String(page),
                page_size: String(pageSize),
            })
            if (searchKeyword) params.append("keyword", searchKeyword)
            if (statusFilter) params.append("status", statusFilter)
            if (modeFilter) params.append("mode", modeFilter)

            const response = await fetch(`${API_BASE_URL}/history?${params}`)
            if (response.ok) {
                const data = await response.json()
                setHistoryData(data.items || data.data || data || [])
                setPagination({
                    current: page,
                    pageSize,
                    total: data.total || data.items?.length || 0,
                })
            } else {
                console.error("Failed to fetch history:", response.status)
                setHistoryData([])
            }
        } catch (error) {
            console.error("Error fetching history:", error)
            setHistoryData([])
        } finally {
            setLoading(false)
        }
    }, [searchKeyword, statusFilter, modeFilter])

    // Fetch stats
    const fetchStats = useCallback(async () => {
        try {
            const response = await fetch(`${API_BASE_URL}/history/stats`)
            if (response.ok) {
                const data = await response.json()
                setStats(data)
            }
        } catch (error) {
            console.error("Error fetching stats:", error)
        }
    }, [])

    useEffect(() => {
        fetchHistory(1, pagination.pageSize)
        fetchStats()
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    // Delete a record
    const handleDelete = async (taskUuid) => {
        try {
            const response = await fetch(`${API_BASE_URL}/history/${taskUuid}`, {
                method: "DELETE",
            })
            if (response.ok) {
                message.success("紀錄已刪除")
                fetchHistory(pagination.current, pagination.pageSize)
                fetchStats()
            } else {
                message.error("刪除失敗")
            }
        } catch (error) {
            message.error("刪除時發生錯誤")
        }
    }

    // Handle table change
    const handleTableChange = (pag) => {
        fetchHistory(pag.current, pag.pageSize)
    }

    // Handle search
    const handleSearch = () => {
        fetchHistory(1, pagination.pageSize)
    }

    const statusColors = {
        COMPLETED: "green",
        FAILED: "red",
        PROCESSING: "blue",
        PENDING: "default",
    }

    const statusLabels = {
        COMPLETED: "完成",
        FAILED: "失敗",
        PROCESSING: "處理中",
        PENDING: "等待中",
    }

    const columns = [
        {
            title: "檔案名稱",
            dataIndex: "original_filename",
            key: "original_filename",
            ellipsis: true,
            render: (v) => (
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <FileTextOutlined style={{ color: "#2dd4a8" }} />
                    <Text ellipsis style={{ color: "#e8e8e8", maxWidth: 250 }}>{v || "—"}</Text>
                </div>
            ),
        },
        {
            title: "狀態",
            dataIndex: "status",
            key: "status",
            width: 100,
            render: (v) => (
                <Tag color={statusColors[v] || "default"}>
                    {statusLabels[v] || v || "—"}
                </Tag>
            ),
        },
        {
            title: "模式",
            dataIndex: "mode",
            key: "mode",
            width: 80,
            render: (v) => (
                <Tag style={{ fontSize: 11 }}>
                    {v === "batch" ? "批次" : "一般"}
                </Tag>
            ),
        },
        {
            title: "模型",
            dataIndex: "model",
            key: "model",
            width: 160,
            render: (v) => <Text style={{ color: "#8888a8", fontSize: 12 }}>{v || "—"}</Text>,
        },
        {
            title: "語言",
            dataIndex: "source_lang",
            key: "source_lang",
            width: 80,
            render: (v) => <Text style={{ color: "#8888a8", fontSize: 12 }}>{v || "—"}</Text>,
        },
        {
            title: "Tokens",
            dataIndex: "tokens_used",
            key: "tokens_used",
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
            dataIndex: "created_at",
            key: "created_at",
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
            width: 50,
            render: (_, record) => (
                <Popconfirm
                    title="確定刪除此紀錄？"
                    onConfirm={() => handleDelete(record.task_uuid)}
                    okText="確定"
                    cancelText="取消"
                >
                    <Button type="text" size="small" icon={<DeleteOutlined />} danger style={{ color: "#8888a8" }} />
                </Popconfirm>
            ),
        },
    ]

    const successRate = stats.total > 0 ? ((stats.completed / stats.total) * 100).toFixed(1) : 0

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 24, padding: 24 }}>
            {/* Stats Cards */}
            <Row gutter={[16, 16]}>
                <Col xs={24} sm={12} lg={6}>
                    <Card size="small" style={{ border: "1px solid #3a3a5c" }} styles={{ body: { padding: 20 } }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                            <div>
                                <div style={{ color: "#8888a8", fontSize: 13, marginBottom: 8 }}>總任務數</div>
                                <div style={{ fontSize: 24, fontWeight: 700, color: "#e8e8e8" }}>{stats.total}</div>
                            </div>
                            <div style={{ width: 36, height: 36, borderRadius: 8, background: "rgba(45, 212, 168, 0.1)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                                <FileAudio size={16} color="#2dd4a8" />
                            </div>
                        </div>
                    </Card>
                </Col>
                <Col xs={24} sm={12} lg={6}>
                    <Card size="small" style={{ border: "1px solid #3a3a5c" }} styles={{ body: { padding: 20 } }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                            <div>
                                <div style={{ color: "#8888a8", fontSize: 13, marginBottom: 8 }}>成功率</div>
                                <div style={{ fontSize: 24, fontWeight: 700, color: "#e8e8e8" }}>{successRate}%</div>
                                <div style={{ color: "#8888a8", fontSize: 12, marginTop: 4 }}>{stats.completed} 完成 / {stats.failed} 失敗</div>
                            </div>
                            <div style={{ width: 36, height: 36, borderRadius: 8, background: "rgba(71, 184, 212, 0.1)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                                <TrendingUp size={16} color="#47b8d4" />
                            </div>
                        </div>
                    </Card>
                </Col>
                <Col xs={24} sm={12} lg={6}>
                    <Card size="small" style={{ border: "1px solid #3a3a5c" }} styles={{ body: { padding: 20 } }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                            <div>
                                <div style={{ color: "#8888a8", fontSize: 13, marginBottom: 8 }}>總 Tokens</div>
                                <div style={{ fontSize: 24, fontWeight: 700, color: "#e8e8e8" }}>{(stats.total_tokens || 0).toLocaleString()}</div>
                            </div>
                            <div style={{ width: 36, height: 36, borderRadius: 8, background: "rgba(212, 167, 45, 0.1)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                                <Clock size={16} color="#d4a72d" />
                            </div>
                        </div>
                    </Card>
                </Col>
                <Col xs={24} sm={12} lg={6}>
                    <Card size="small" style={{ border: "1px solid #3a3a5c" }} styles={{ body: { padding: 20 } }}>
                        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                            <div>
                                <div style={{ color: "#8888a8", fontSize: 13, marginBottom: 8 }}>總費用</div>
                                <div style={{ fontSize: 24, fontWeight: 700, color: "#2dd4a8" }}>${(stats.total_cost || 0).toFixed(4)}</div>
                            </div>
                            <div style={{ width: 36, height: 36, borderRadius: 8, background: "rgba(139, 92, 246, 0.1)", display: "flex", alignItems: "center", justifyContent: "center" }}>
                                <Coins size={16} color="#8b5cf6" />
                            </div>
                        </div>
                    </Card>
                </Col>
            </Row>

            {/* Search & Filters */}
            <Card size="small" style={{ border: "1px solid #3a3a5c" }} styles={{ body: { padding: "12px 16px" } }}>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 12 }}>
                    <Input
                        placeholder="搜尋檔案名稱..."
                        prefix={<SearchOutlined style={{ color: "#8888a8" }} />}
                        value={searchKeyword}
                        onChange={(e) => setSearchKeyword(e.target.value)}
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
                        options={[
                            { value: "COMPLETED", label: "完成" },
                            { value: "FAILED", label: "失敗" },
                            { value: "PROCESSING", label: "處理中" },
                        ]}
                    />
                    <Select
                        placeholder="模式"
                        value={modeFilter}
                        onChange={setModeFilter}
                        style={{ width: 120 }}
                        allowClear
                        options={[
                            { value: "regular", label: "一般" },
                            { value: "batch", label: "批次" },
                        ]}
                    />
                    <Button icon={<SearchOutlined />} onClick={handleSearch}>
                        搜尋
                    </Button>
                    <Button
                        icon={<ReloadOutlined />}
                        onClick={() => {
                            setSearchKeyword("")
                            setStatusFilter(null)
                            setModeFilter(null)
                            fetchHistory(1, pagination.pageSize)
                            fetchStats()
                        }}
                    >
                        重置
                    </Button>
                </div>
            </Card>

            {/* History Table */}
            <Card style={{ border: "1px solid #3a3a5c" }} styles={{ body: { padding: 0 } }}>
                <Table
                    columns={columns}
                    dataSource={historyData}
                    rowKey={(record) => record.task_uuid || record.id || Math.random()}
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
