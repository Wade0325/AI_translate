import { useRef, useState } from "react"
import { Input, Modal } from "antd"
import { speakerNameProblem } from "@/utils/speakers"

/**
 * 替說話者取名字的對話框（#359）：從片段列的說話者選單打開。按 Enter 或「存檔」存成一次校正，這位說話者的所有片段
 * 一起換成新名稱；清空再存就回到顯示說話者編號。
 *
 * 不合規則的名稱（太長、方括號、寫成 S 加數字）邊打邊寫出原因，不送出；後端擋下的（例如另一位說話者已經用了這個
 * 名稱）存的時候寫出後端給的原因，對話框留著讓使用者改。名稱沒變時直接關掉，不送請求。
 *
 * @param {{
 *   speaker: string,
 *   name: string | null,
 *   onSave: (speaker: string, name: string) => Promise<string | null>,
 *   onClose: () => void,
 * }} props onSave 回 null 表示存好了，否則是沒存的原因
 */
export function SpeakerNameDialog({ speaker, name, onSave, onClose }) {
    const [draft, setDraft] = useState(name ?? "")
    const [refused, setRefused] = useState(/** @type {string | null} */ (null))
    const [saving, setSaving] = useState(false)
    const inputRef = useRef(/** @type {import("antd").InputRef | null} */ (null))
    const problem = speakerNameProblem(draft)
    const shown = problem ?? refused

    const save = async () => {
        if (problem || saving) return
        if (draft.trim() === (name ?? "")) {
            onClose()
            return
        }
        setSaving(true)
        const reason = await onSave(speaker, draft)
        setSaving(false)
        if (reason) setRefused(reason)
        else onClose()
    }

    return (
        <Modal
            open
            title={name ? `改 ${speaker} 的名字` : `替 ${speaker} 取名字`}
            okText="存檔"
            cancelText="取消"
            okButtonProps={{ disabled: Boolean(problem) }}
            confirmLoading={saving}
            onOk={save}
            onCancel={onClose}
            afterOpenChange={(open) => open && inputRef.current?.focus()}
            width={400}
        >
            <Input
                ref={inputRef}
                aria-label="說話者名稱"
                placeholder="例如：王小明"
                value={draft}
                status={shown ? "error" : undefined}
                onChange={(event) => {
                    setDraft(event.target.value)
                    setRefused(null)
                }}
                onKeyDown={(event) => {
                    // 輸入法選字時按的 Enter 不算存檔（Safari 選完字那一下的 keyCode 是 229）
                    if (event.key !== "Enter" || event.nativeEvent.isComposing || event.keyCode === 229) return
                    event.preventDefault()
                    save()
                }}
            />
            <div role={shown ? "alert" : undefined} style={{ marginTop: 8, fontSize: 12, color: shown ? "#ff7875" : "#8888a8" }}>
                {shown ?? `名稱只用在這個任務，下載的校正後版本寫名稱。清空再存就回到顯示 ${speaker}。`}
            </div>
        </Modal>
    )
}
