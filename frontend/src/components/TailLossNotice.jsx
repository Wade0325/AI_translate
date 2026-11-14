import { Tooltip, Typography } from "antd"
import { CardNotice } from "@/components/CardNotice"
import { describeTailLoss } from "@/utils/tailLoss"

const { Text } = Typography

/**
 * 轉錄結果可能掉尾（#257）的完整說明（轉錄頁的檔案卡、結果頁用）：從哪裡起可能沒有轉錄到，以及下一步。
 * seconds 是可能掉尾的起點（原音檔的秒數，utils/tailLoss.js）；沒有掉尾時不畫任何東西。任務是完成的，
 * 轉錄結果照樣可以下載。paddingLeft 讓文字和卡片上的檔名對齊（見 CardNotice）。
 */
export function TailLossNotice({ seconds, paddingLeft }) {
    const shown = describeTailLoss(seconds)
    if (!shown) return null
    return (
        <CardNotice
            testId="tail-loss-notice"
            paddingLeft={paddingLeft}
            style={{ display: "flex", flexDirection: "column", gap: 4 }}
        >
            <Text style={{ fontSize: 12, fontWeight: 500, color: "#e0b84a" }}>{shown.reason}</Text>
            <Text style={{ fontSize: 12, color: "#c8c8d8" }}>{shown.nextStep}</Text>
        </CardNotice>
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
