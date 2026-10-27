import { useCallback, useEffect, useState } from "react"
import { Button, Card, Col, Popconfirm, Typography, message } from "antd"
import { HardDrive, Trash2 } from "lucide-react"
import { api } from "../services/api"
import { formatFileSize } from "../utils/formatters"
import { deletedMessage, retentionNote } from "../utils/localData"

const { Text } = Typography

const noteStyle = { color: "#8888a8", fontSize: 12 }
/** @type {import("react").CSSProperties} */
const pathStyle = { color: "#e8e8e8", fontSize: 12, fontFamily: "monospace", wordBreak: "break-all" }

/** 免安裝版 data 資料夾裡的項目：哪些是個人資料，哪些只是模型權重。 */
const DATA_ITEMS = [
    ["app.db", "任務紀錄、轉錄結果與 API 金鑰"],
    ["audio_store", "保留音檔"],
    ["temp_uploads", "上傳後還沒轉錄完的音檔"],
    ["vad_artifacts", "去靜音與切點預覽留下的音檔（開發者工具）"],
    ["logs", "日誌檔，回報問題時附上；不含原檔名、提示詞與轉錄內容，留最近 7 天"],
    ["models", "本機模型的權重"],
]

/**
 * 設定頁「資料與隱私」（#231 Q1、Q7）：保留音檔留在哪、留多久、目前留了多少，可以一次刪掉；
 * 免安裝版另外說明 data 資料夾裡哪些是個人資料。app 裡的「清除所有資料」與匯出延後（Q7）。
 */
export function LocalDataCard() {
    const [data, setData] = useState(null)
    const [failed, setFailed] = useState(false)
    const [deleting, setDeleting] = useState(false)

    const refresh = useCallback(() => api.localData.get()
        .then((result) => {
            setData(result)
            setFailed(false)
        })
        .catch(() => setFailed(true)), [])

    useEffect(() => { refresh() }, [refresh])

    const handleDelete = async () => {
        setDeleting(true)
        try {
            const result = await api.localData.deleteRetainedAudio()
            const notify = result.failed > 0 ? message.warning : message.success
            notify(deletedMessage(result))
        } catch (err) {
            message.error(`刪除保留音檔失敗：${err.message}`)
        } finally {
            setDeleting(false)
            refresh()
        }
    }

    const retained = data?.retained_audio

    return (
        <Col xs={24} lg={12}>
            <Card
                title={
                    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <HardDrive size={16} color="#2dd4a8" />
                        <span style={{ color: "#e8e8e8" }}>資料與隱私</span>
                    </div>
                }
                style={{ border: "1px solid #3a3a5c", height: "100%" }}
            >
                {failed && <Text style={noteStyle}>讀不到保留音檔與資料的位置</Text>}
                {retained && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                        <Text style={{ color: "#e8e8e8", fontSize: 13 }}>保留音檔</Text>
                        <Text style={noteStyle}>{retentionNote(retained)}</Text>
                        <Text style={pathStyle}>{retained.folder}</Text>
                        <Text style={{ color: "#e8e8e8", fontSize: 13 }}>
                            目前保留 {retained.file_count} 個音檔，共 {formatFileSize(retained.total_bytes)}
                        </Text>
                        <div>
                            <Popconfirm
                                title="刪除全部保留音檔？"
                                description="刪除後無法復原，日後校正時也不能重聽這些音檔；轉錄結果與紀錄不受影響。"
                                onConfirm={handleDelete}
                                okText="刪除"
                                okButtonProps={{ danger: true }}
                                cancelText="取消"
                            >
                                <Button danger icon={<Trash2 size={14} />} loading={deleting}
                                    disabled={retained.file_count === 0}>
                                    立即刪除全部保留音檔
                                </Button>
                            </Popconfirm>
                        </div>
                        {/* JSX 的換行會變成空格，中文句子不換行 */}
                        <Text style={noteStyle}>
                            要改天數或關掉保留，在 .env 加一行 <code>AUDIO_RETENTION_DAYS=天數</code>（0 是不自動刪除）或 <code>RETAIN_AUDIO=false</code>，再重新開啟 app；免安裝版的 .env 放在 data 資料夾裡。
                        </Text>
                    </div>
                )}
                {data?.data_folder && (
                    <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 16 }}>
                        <Text style={{ color: "#e8e8e8", fontSize: 13 }}>資料放在哪</Text>
                        <Text style={noteStyle}>app 的所有資料都存在這個資料夾：</Text>
                        <Text style={pathStyle}>{data.data_folder}</Text>
                        <ul style={{ ...noteStyle, margin: 0, paddingLeft: 20 }}>
                            {DATA_ITEMS.map(([name, what]) => (
                                <li key={name}><code>{name}</code>：{what}</li>
                            ))}
                        </ul>
                        <Text style={noteStyle}>
                            要清掉個人資料，先關掉 app，再刪掉 models 以外的項目；刪掉 models 就要重新下載權重。換電腦時把整個 data 資料夾複製過去。
                        </Text>
                    </div>
                )}
            </Card>
        </Col>
    )
}
