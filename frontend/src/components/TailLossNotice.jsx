import { Tooltip, Typography } from "antd"
import { describeTailLoss } from "@/utils/tailLoss"

const { Text } = Typography

/**
 * 轉錄結果可能掉尾（#257）的完整說明（轉錄頁的檔案卡、結果頁用）：從哪裡起可能沒有轉錄到，以及下一步。
 * seconds 是可能掉尾的起點（原音檔的秒數，utils/tailLoss.js）；沒有掉尾時不畫任何東西。任務是完成的，
 * 轉錄結果照樣可以下載，所以用提醒的顏色，不用失敗的紅色。paddingLeft 讓文字和卡片上的檔名對齊。
 */
export function TailLossNotice({ seconds, paddingLeft = 56 }) {
    const shown = describeTailLoss(seconds)
    if (!shown) return null
    return (
        <div
            data-testid="tail-loss-notice"
            style={{
                borderTop: "1px solid rgba(212, 167, 45, 0.2)",
                background: "rgba(212, 167, 45, 0.06)",
                padding: `8px 12px 10px ${paddingLeft}px`,
                display: "flex",
                flexDirection: "column",
                gap: 4,
            }}
        >
            <Text style={{ fontSize: 12, fontWeight: 500, color: "#e0b84a" }}>{shown.reason}</Text>
            <Text style={{ fontSize: 12, color: "#c8c8d8" }}>{shown.nextStep}</Text>
        </div>
    )
}

/**
 * 一行的提醒（History 用）：從哪裡起可能沒有轉錄到，滑過去看下一步。沒有掉尾時不畫任何東西。
 */
export function TailLossSummary({ seconds, style }) {
    const shown = describeTailLoss(seconds)
    if (!shown) return null
    return (
        <Tooltip title={shown.nextStep}>
            <Text ellipsis style={{ fontSize: 11, color: "#e0b84a", ...style }}>
                {shown.reason}
            </Text>
        </Tooltip>
    )
}
