import { Typography } from "antd"

const { Text } = Typography

/**
 * 選了會把音檔送出本機的供應商（例如 Gemini）時的告知（#231 Q6）：音檔會送到哪裡、對方怎麼
 * 使用，並連到條款原文。notice 來自 utils/providerList.js 的 uploadNotice，是 null 時不顯示。
 */
export function UploadNotice({ notice }) {
    if (!notice) return null
    return (
        <Text style={{ fontSize: 12, color: "#d4a72d" }}>
            {notice.text}{" "}
            <a href={notice.termsUrl} target="_blank" rel="noopener noreferrer">條款原文</a>
        </Text>
    )
}
