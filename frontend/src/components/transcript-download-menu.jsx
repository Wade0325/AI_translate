import { Dropdown, message } from "antd"
import { api } from "@/services/api"
import { downloadBlob } from "@/utils/download"
import { ORIGINAL, downloadMenuItems, downloadTarget, transcriptFileName } from "@/utils/transcriptVersions"

/**
 * 下載一個任務的轉錄結果的選單（#346）：History 的每一列與校正頁（#348）共用。內容向下載端點拿，選的版本與
 * 輸出格式帶在選單項目的 key 裡（utils/transcriptVersions.js）。
 *
 * withOriginal 時分成「校正後版本」（預設）與「原始轉錄」兩組，原始轉錄的檔名多一段 .original；沒有時只列
 * 四種輸出格式，下載的是校正後版本（沒有校正時就是原始轉錄）。
 *
 * @param {{
 *   taskUuid: string,
 *   fileName: string | null | undefined,
 *   withOriginal: boolean,
 *   trigger?: ("hover" | "click")[],
 *   children: import("react").ReactNode,
 * }} props
 */
export function TranscriptDownloadMenu({ taskUuid, fileName, withOriginal, trigger, children }) {
    const onClick = async ({ key }) => {
        const { version, format } = downloadTarget(key)
        try {
            const content = await api.history.downloadTranscript(taskUuid, format, { version })
            downloadBlob(content, transcriptFileName(fileName || "transcript", format, version))
            const label = format.toUpperCase()
            message.success(version === ORIGINAL ? `已下載原始轉錄的 ${label} 檔` : `已下載 ${label} 檔`)
        } catch (error) {
            console.error("下載轉錄結果失敗:", error)
            message.error(error?.message || "下載失敗")
        }
    }

    // downloadMenuItems 的項目型別比 antd 的寬鬆（群組的 type 不是字面型別），內容就是 antd Menu 的項目
    const items = /** @type {import("antd").MenuProps["items"]} */ (/** @type {unknown} */ (downloadMenuItems(withOriginal)))
    return (
        <Dropdown trigger={trigger} menu={{ items, onClick }}>
            {children}
        </Dropdown>
    )
}
