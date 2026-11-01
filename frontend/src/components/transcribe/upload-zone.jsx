import { useState, useCallback, useRef } from "react"
import { Upload, Button, Alert } from "antd"
import { InboxOutlined, PlusOutlined } from "@ant-design/icons"
import { AlertCircle } from "lucide-react"
import { useUploadLimits } from "@/hooks/useUploadLimits"
import { acceptAttribute, formatLabels, maxSizeLabel, rejectionOf } from "@/utils/uploadLimits"

const { Dragger } = Upload

// 收哪些格式、最大多大由伺服器決定（GET /upload/limits）。還沒讀到、讀不到時檔案選擇器列出所有音訊
// 與影片，加入時不先擋，交給伺服器上傳時檢查
const FALLBACK_ACCEPT = "audio/*,video/*"

export function UploadZone({ hasFiles, onFilesAdded }) {
    const [error, setError] = useState(null)
    const inputRef = useRef(null)
    const limits = useUploadLimits()
    const accept = limits ? acceptAttribute(limits) : FALLBACK_ACCEPT

    const handleFiles = useCallback(
        (fileList) => {
            setError(null)
            const valid = []
            const files = Array.from(fileList)

            for (const file of files) {
                const rejection = limits && rejectionOf(file, limits)
                if (rejection) {
                    setError(rejection)
                    continue
                }
                valid.push(file)
            }
            if (valid.length > 0) onFilesAdded(valid)
        },
        [onFilesAdded, limits]
    )

    // 已有檔案時縮成單顆按鈕，避免佔版面
    if (hasFiles) {
        return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <Button
                    icon={<PlusOutlined />}
                    onClick={() => inputRef.current?.click()}
                    style={{ borderStyle: 'dashed' }}
                >
                    Add More Files
                </Button>
                <input
                    ref={inputRef}
                    type="file"
                    accept={accept}
                    multiple
                    onChange={(e) => {
                        if (e.target.files) handleFiles(e.target.files)
                        e.target.value = ""
                    }}
                    style={{ display: 'none' }}
                />
                {error && (
                    <Alert
                        message={error}
                        type="error"
                        showIcon
                        icon={<AlertCircle size={14} />}
                        style={{ fontSize: 12 }}
                    />
                )}
            </div>
        )
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <Dragger
                multiple
                // 拖進來的檔案不照 accept 先濾掉（antd 預設會默默丟掉）：交給 handleFiles，不收的說明原因
                accept={{ format: accept, filter: "native" }}
                showUploadList={false}
                beforeUpload={(file, fileList) => {
                    // antd 對每個檔案都呼叫一次 beforeUpload，只在最後一個檔案時處理整批
                    if (file === fileList[fileList.length - 1]) {
                        handleFiles(fileList)
                    }
                    return false // 阻止 antd 自動上傳
                }}
                style={{
                    background: 'transparent',
                    border: '2px dashed #3a3a5c',
                    borderRadius: 12,
                    padding: '32px 24px',
                }}
            >
                <p className="ant-upload-drag-icon">
                    <InboxOutlined style={{ color: '#2dd4a8', fontSize: 40 }} />
                </p>
                <p style={{ color: '#e8e8e8', fontSize: 14, fontWeight: 500, marginBottom: 4 }}>
                    Drag audio or video files here or click to browse
                </p>
                {limits && (<>
                    <p style={{ color: '#8888a8', fontSize: 12, margin: 0 }}>
                        音檔 {formatLabels(limits, "audio")}，影片 {formatLabels(limits, "video")}
                        （上限 {maxSizeLabel(limits)}）
                    </p>
                    <p style={{ color: '#8888a8', fontSize: 12, margin: '2px 0 0' }}>
                        影片會先在這台電腦抽出聲音，只轉錄聲音，畫面不會送出
                    </p>
                </>)}
            </Dragger>
            {error && (
                <Alert
                    message={error}
                    type="error"
                    showIcon
                    style={{ fontSize: 12 }}
                />
            )}
        </div>
    )
}
