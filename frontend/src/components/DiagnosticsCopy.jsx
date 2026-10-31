import { useState } from "react"
import { Button, Input, Typography, message } from "antd"
import { ClipboardCopy } from "lucide-react"
import { api } from "../services/api"
import { copyText } from "../utils/clipboard"

const { Text } = Typography

const noteStyle = { color: "#8888a8", fontSize: 12 }

/**
 * 設定頁 About 卡片的「複製診斷資訊」（#24）：回報問題時貼進 GitHub Issue。
 *
 * 按下時才問後端（它會查顯卡、nvidia-smi 與 ffmpeg），放進剪貼簿，並把複製的內容顯示出來，使用者
 * 貼出去之前看得到裡面有什麼。內容不含檔名、金鑰、路徑與轉錄內容（app/services/diagnostics.py）；
 * app 自己不會送出它（ADR-0005）。瀏覽器不給剪貼簿時，改請使用者選取下面的文字自己複製。
 */
export function DiagnosticsCopy() {
    const [text, setText] = useState(/** @type {string | null} */ (null))
    const [copied, setCopied] = useState(false)
    const [loading, setLoading] = useState(false)

    const handleCopy = async () => {
        setLoading(true)
        try {
            const result = await api.diagnostics()
            const ok = await copyText(result.text)
            setText(result.text)
            setCopied(ok)
            if (ok) message.success("已複製診斷資訊，可以貼進 GitHub Issue")
            else message.warning("瀏覽器不允許自動複製，請選取下面的文字自己複製")
        } catch (err) {
            message.error(`讀不到診斷資訊：${err.message}`)
        } finally {
            setLoading(false)
        }
    }

    return (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div>
                <Button icon={<ClipboardCopy size={14} />} loading={loading} onClick={handleCopy}>
                    複製診斷資訊
                </Button>
            </div>
            <Text style={noteStyle}>
                回報問題時貼進 GitHub Issue。內容是版本、執行模式、作業系統、顯卡與模型權重的狀態，不含檔名、金鑰、路徑與轉錄內容；按下後會顯示複製了什麼。
            </Text>
            {text !== null && (
                <>
                    <Text style={noteStyle}>{copied ? "已複製以下內容：" : "請選取以下內容自己複製："}</Text>
                    <Input.TextArea
                        readOnly
                        value={text}
                        autoSize
                        aria-label="診斷資訊"
                        onFocus={(e) => e.target.select()}
                        style={{ fontFamily: "monospace", fontSize: 12 }}
                    />
                </>
            )}
        </div>
    )
}
