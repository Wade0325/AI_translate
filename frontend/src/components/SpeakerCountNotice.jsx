import { Typography } from "antd"
import { CardNotice } from "@/components/CardNotice"
import { speakerCountMismatch } from "@/utils/speakerCount"

const { Text } = Typography

/**
 * 選了 2 到 8 人、結果裡的說話者數目卻不同時的一行提醒（#351 第 4 點，結果頁的檔案卡與校正頁上方用），例如「選了 2 人，
 * 結果有 3 位說話者」。selected 是任務記下的人數，actual 是這份輸出（校正頁是校正後版本）裡有幾位說話者；不必
 * 提醒時不畫任何東西。
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
