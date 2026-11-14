import { useEffect, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { Result, Spin } from "antd"
import { api } from "@/services/api"
import { unavailableMessage } from "@/utils/correction"
import { CorrectionView } from "@/components/correction/correction-view"

/**
 * 校正頁（#347）：網址帶任務 id，從 History 或 Result 頁的「校正」進來，重新整理或之後再回來都開得到。
 * 直接開不能校正的任務的網址時（任務不存在、還沒完成、沒有片段、翻譯的任務），寫一句說明，不出錯。
 */
export default function CorrectionPage() {
    const { taskUuid } = useParams()
    const [state, setState] = useState(/** @type {{ uuid: string | null, transcript: any, error: unknown }} */ (
        { uuid: null, transcript: null, error: null }
    ))

    useEffect(() => {
        let current = true
        api.transcripts.get(taskUuid)
            .then((transcript) => current && setState({ uuid: taskUuid, transcript, error: null }))
            .catch((error) => current && setState({ uuid: taskUuid, transcript: null, error }))
        return () => {
            current = false
        }
    }, [taskUuid])

    // 換到另一個任務的網址時，上一個任務的內容不留在畫面上
    if (state.uuid !== taskUuid) {
        return <Spin style={{ marginTop: 64 }} />
    }
    if (state.error || !state.transcript.correctable) {
        return (
            <Result
                status="info"
                title={<span style={{ fontSize: 16 }}>{unavailableMessage({
                    error: state.error, reason: state.transcript?.uncorrectable_reason,
                })}</span>}
                extra={<Link to="/history">回到 History</Link>}
            />
        )
    }
    return <CorrectionView key={taskUuid} transcript={state.transcript} />
}
