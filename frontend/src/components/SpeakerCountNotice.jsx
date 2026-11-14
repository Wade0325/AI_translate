import { Typography } from "antd"
import { CardNotice } from "@/components/CardNotice"
import { speakerCountMismatch } from "@/utils/speakerCount"

const { Text } = Typography

/**
 * 選了 2 到 8 人、結果裡的說話者數目卻不同時的一行提醒（#351 第 4 點，結果頁的檔案卡用），例如「選了 2 人，
 * 結果有 3 位說話者」。selected 與 actual 是完成時的結果帶的所選人數與這份輸出裡有幾位說話者；不必提醒時
 * 不畫任何東西。
 */
export function SpeakerCountNotice({ selected, actual, paddingLeft }) {
    const text = speakerCountMismatch(selected, actual)
    if (!text) return null
    return (
        <CardNotice testId="speaker-count-notice" paddingLeft={paddingLeft}>
            <Text style={{ fontSize: 12, color: "#e0b84a" }}>{text}</Text>
        </CardNotice>
    )
}
