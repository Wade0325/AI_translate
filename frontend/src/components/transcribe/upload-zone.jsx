import { useState, useCallback, useRef } from "react"
import { Upload, Button, Alert } from "antd"
import { InboxOutlined, PlusOutlined } from "@ant-design/icons"
import { AlertCircle } from "lucide-react"

const { Dragger } = Upload

// 都要在伺服器收的格式裡（backend/app/api/upload.py 的 SUPPORTED_MIME_TYPES）：伺服器不收 OGG，
// 這裡收了也只會在上傳時失敗
const ACCEPTED_TYPES = [
    "audio/mpeg",
    "audio/wav",
    "audio/mp4",
    "audio/x-m4a",
    "audio/flac",
    "audio/webm",
]

const ACCEPTED_LABEL = "MP3、WAV、M4A、FLAC、WebM"

const MAX_FILE_SIZE = 1000 * 1024 * 1024

export function UploadZone({ hasFiles, onFilesAdded }) {
    const [error, setError] = useState(null)
    const inputRef = useRef(null)

    const handleFiles = useCallback(
        (fileList) => {
            setError(null)
            const valid = []
            const files = Array.from(fileList)

            for (const file of files) {
                if (!ACCEPTED_TYPES.includes(file.type)) {
                    setError(`不支援這種格式：${file.name}（可以用 ${ACCEPTED_LABEL}）`)
                    continue
                }
                if (file.size > MAX_FILE_SIZE) {
                    setError(`檔案太大：${file.name}（上限 1000 MB）`)
                    continue
                }
                valid.push(file)
            }
            if (valid.length > 0) onFilesAdded(valid)
        },
        [onFilesAdded]
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
                    accept="audio/*"
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
                accept="audio/*"
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
                    Drag audio files here or click to browse
                </p>
                <p style={{ color: '#8888a8', fontSize: 12, margin: 0 }}>
                    MP3, WAV, M4A, FLAC, WebM (max 1000MB)
                </p>
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
